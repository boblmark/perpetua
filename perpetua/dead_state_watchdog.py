#!/usr/bin/env python3
"""死状态看门狗：扫描管线中卡死、超时、状态不一致的条目。
每 30 分钟运行，告警 + 自动修复（review_timeout 自动重送评审）。
2026-10-08 补完 P1-3/4：非终态超时检查 + ask_studio pending 超时。
2026-10-28 新增 check_arena_manual（空转审计 G2）：arena_manual 只告警不改状态。
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_json import atomic_write, tolerant_read
from json_safe import run_lock  # P0修复5（2026-10-09）：单飞锁
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；其他 JSON 文件不动。
# K3 对冲：本模块不碰任何 auth/登录逻辑，只换状态持久层。
import queue_db

DATA = "/home/hatch/data"
APPROVAL_PATH = f"{DATA}/perpetua/awaiting_approval.json"
QUEUE_PATH = f"{DATA}/perpetua/pipeline_queue.json"
ASK_QUEUE_PATH = f"{DATA}/ask_studio/queue.json"
INBOX_PATH = f"{DATA}/collab/inbox.json"
QC_LOG_PATH = f"{DATA}/perpetua/pre_upload_qc.log"
VEO_INBOX = f"{DATA}/veo_inbox"
ORPHAN_STATE_PATH = f"{DATA}/perpetua/qc_orphan_alerted.json"
ALERT_DEDUP_PATH = f"{DATA}/perpetua/dead_state_alert_dedup.json"
ALERT_DEDUP_HOURS = 12  # 2026-10-09：同一告警 12h 内只发一次（防 30min 轮询刷屏）

def now():
    return datetime.now(timezone.utc)

def parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except:
        return None

def load(p, default):
    return tolerant_read(p, default)


def save(p, data):
    atomic_write(p, data)

def _dedup_key(msg):
    # 2026-10-10 修：告警文本含年龄（"已 2.7h"），每轮 key 都不同导致 12h 去重失效、
    # 30 分钟轮询重复刷屏。去重按稳定 key（剥离末尾年龄），显示文本保持不变。
    key = re.sub(r" 已 \d+(\.\d+)?h$", "", msg)
    # 2026-10-12 修：orphan 告警年龄是中文 "X.X 小时" 且在消息中间（"…84）91.3 小时未进任何队列"），
    # 上条正则剥不掉 → 12h 去重对 orphan 告警从未生效。同样剥离易变字段。
    key = re.sub(r"\d+(\.\d+)?\s*小时", "", key)
    # 2026-10-15 修：dead-man 告警年龄是消息中间的 "距上次上传已 24.7h"，两条正则都剥不掉 →
    # 同一死状态每 30 分钟重新告警（10-15 00:01 与 23:32 各告一次）。剥离该中间年龄。
    key = re.sub(r"距上次上传已 \d+(\.\d+)?h", "距上次上传已", key)
    # 2026-10-15 修2：review_passed 卡死告警的年龄同样在消息中间（"已 131.7h，submit 门禁…"），
    # 与 10-10/10-12 的规律同类——通用规则剥离所有 "已 X.Xh" 中间年龄（dead-man 的也一并兜底）。
    key = re.sub(r"已 \d+(\.\d+)?h", "已", key)
    return key

def alert(msg):
    """写入 inbox 告警（messages + notices，控制台事件流可见）。
    2026-10-09：同一消息 12h 内只告警一次（防 30min 轮询重复刷屏）。"""
    try:
        dedup = load(ALERT_DEDUP_PATH, {})
        key = _dedup_key(msg)
        last = parse_time(dedup.get(key, ""))
        if last and (now() - last) < timedelta(hours=ALERT_DEDUP_HOURS):
            print(f"  (去重跳过：{msg[:40]}…)")
            return
        dedup[key] = now().isoformat()
        # 只保留 200 条，防止无限增长
        if len(dedup) > 200:
            for k in sorted(dedup, key=lambda k: dedup[k])[:len(dedup) - 200]:
                del dedup[k]
        save(ALERT_DEDUP_PATH, dedup)
    except Exception as ex:
        print(f"  WARN: 告警去重失败（继续告警）: {ex}")
    # inbox 双写（messages + notices），经统一网关（原子写，容忍损坏）
    sys.path.insert(0, "/home/hatch/data/perpetua")
    import inbox as inbox_gw
    ib = inbox_gw.load()
    msgs = ib.get("messages", [])
    notices = ib.get("notices", [])
    entry = {
        "type": "dead_state_alert",
        "title": msg,
        "message": msg,
        "created": now().isoformat(),
        "created_at": now().isoformat(),
        "for": "user",
    }
    msgs.append(entry)
    notices.append(entry)
    ib["messages"] = msgs[-100:]
    ib["notices"] = notices[-100:]
    inbox_gw.save(ib)
    print(f"ALERT: {msg}")

def check_stuck_uploads():
    """检查 approved 但未上传的视频"""
    aa = load(APPROVAL_PATH, [])
    issues = []
    for it in aa:
        if not isinstance(it, dict):
            continue
        if it.get("status") == "approved" and it.get("video_file"):
            approved_at = parse_time(it.get("approved_at", ""))
            slot = it.get("scheduled_slot")
            # 检查是否超过 scheduled_slot 30 分钟
            if slot:
                try:
                    slot_dt = datetime.fromisoformat(slot).replace(tzinfo=timezone.utc)
                    # slot 是本地时间，转 UTC (CST = UTC+8)
                    slot_utc = slot_dt - timedelta(hours=8)
                    if now() > slot_utc + timedelta(minutes=30):
                        issues.append((it, f"错过排期 {slot} 超过 30 分钟"))
                except:
                    pass
            # 检查是否 approved 超过 2 小时未上传（无 slot 的）
            elif approved_at and now() - approved_at > timedelta(hours=2):
                issues.append((it, f"approved 超过 2 小时未上传"))
    return issues

def check_status_mismatch():
    """检查状态机不一致"""
    issues = []
    # upload_approved 只认 awaiting，但人工批准设 approved
    # 这里检查是否有这种不匹配导致的卡死
    return issues

def _load_reject_calib_samples():
    """读 aesthetic_calibration.json 的 reject 负样本名集合（容错：读失败返回空集）。"""
    try:
        d = load(f"{DATA}/perpetua/aesthetic_calibration.json", [])
        items = d if isinstance(d, list) else d.get("samples", [])
        out = set()
        for it in items:
            if isinstance(it, dict) and it.get("label") == "reject" and it.get("file"):
                out.add(os.path.basename(str(it["file"])))
        return out
    except Exception:
        return set()


def check_qc_orphans():
    """2026-10-09 新增：QC 通过但未进入任何队列的 veo_inbox 成品。

    背景：批量路（agent-browser 手动/脚本生成）绕过 MCP submit_job，
    collect_results() 只收编 job_submitted 项，导致 QC 97 分的成品
    （2026-10-09 drive-thru）在 inbox 里躺 8 小时无人认领。
    只告警不自动修复：送上传需要标题决策，留给用户/主 agent。
    同一文件 12 小时内只告警一次。
    2026-10-17 补：排除 aesthetic_calibration.json 中 label=reject 的样片
    （如 h3_20261008_160708_seed28311100.mp4，画面烧录乱码字幕+监控时间码，
    为美学口径校准的负样本，绝不可送排期），避免每 12h 误报一次。
    """
    reject_samples = _load_reject_calib_samples()
    latest = {}
    try:
        with open(QC_LOG_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                vf = d.get("video") or ""
                if vf:
                    latest[vf] = d
    except FileNotFoundError:
        return []
    referenced = set()
    # 2026-10-12 修：pipeline_queue 已迁 SQLite（D20261011-001 P1），JSON 是死镜像（最后写入 10-10）。
    # 此前只读 JSON 导致已在 SQLite 队列的成品被误判 orphan，每 12h 重复误报。真相源走 queue_db。
    for p in (QUEUE_PATH, APPROVAL_PATH):
        items = load(p, [])
        items = items if isinstance(items, list) else items.get("items", [])
        for it in items:
            if isinstance(it, dict) and it.get("video_file"):
                referenced.add(os.path.basename(str(it["video_file"])))
    try:
        _q = queue_db.pipeline_load()
        _qitems = _q if isinstance(_q, list) else _q.get("items", [])
        for it in _qitems:
            if isinstance(it, dict) and it.get("video_file"):
                referenced.add(os.path.basename(str(it["video_file"])))
    except Exception as ex:
        print(f"  WARN: 读 SQLite 队列失败（orphan 检查降级用 JSON）: {ex}")
    # 2026-10-18 修：已发布的 item 只留 video_id 不回填 video_file
    # （如 kiosk geminigen-browser-20261017-v3 发布为 5gcdjQ0SdrU），
    # 其本地同宗文件会被误判 orphan 每 12h 误报一次。建立"已发布 lineage"
    # 集合：item 有 video_id 且其 (job 日期 token + device/backend token)
    # 均命中文件名 stem 时，视为已出片 lineage，跳过告警。
    published_lineage = []
    try:
        for it in (_qitems if "_qitems" in dir() else []):
            if not isinstance(it, dict):
                continue
            up = it.get("upload_result")
            up_vid = up.get("video_id") if isinstance(up, dict) else None
            vid = (it.get("youtube_video_id") or up_vid
                   or it.get("teaser_video_id")
                   or it.get("video_id"))
            if not vid or str(vid).lower() in ("none", ""):
                continue
            job = str(it.get("job_id") or "")
            m = re.search(r"(\d{8})", job)
            date_tok = m.group(1) if m else None
            dev_toks = {t for t in re.split(r"[^a-z0-9]+", str(it.get("device") or "").lower()) if len(t) > 2}
            be_tok = re.split(r"[^a-z0-9]+", str(it.get("gen_backend") or "").lower())[0]
            published_lineage.append((date_tok, dev_toks, be_tok))
    except Exception as ex:
        print(f"  WARN: lineage 集合构建失败（跳过此项）: {ex}")
    def _lineage_published(bn: str) -> bool:
        stem = bn.lower()
        for date_tok, dev_toks, be_tok in published_lineage:
            date_hit = bool(date_tok and date_tok in stem)
            dev_hit = any(t in stem for t in dev_toks)
            be_hit = bool(be_tok and len(be_tok) > 2 and be_tok in stem)
            if date_hit and (dev_hit or be_hit):
                return True
        return False
    now_t = now()
    state = load(ORPHAN_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    issues = []
    for vf, d in latest.items():
        if not d.get("passed"):
            continue
        bn = os.path.basename(vf)
        if "test" in bn.lower():
            continue
        if bn in reject_samples:
            continue  # 2026-10-17：美学校准负样本（测试样片），永不送排期建议
        if not vf.startswith(VEO_INBOX + "/"):
            continue
        if bn in referenced:
            continue
        if _lineage_published(bn):
            continue  # 2026-10-18：同宗已发布（只留 video_id），非孤儿
        if not os.path.exists(vf):
            continue
        age_h = (now_t.timestamp() - os.path.getmtime(vf)) / 3600
        if age_h < 2:
            continue
        last_alert = parse_time(state.get(bn, ""))
        if last_alert and (now_t - last_alert) < timedelta(hours=12):
            continue
        score = d.get("experience_score")
        issues.append((bn, f"QC 通过（体验分 {score}）{age_h:.1f} 小时未进任何队列"))
        state[bn] = now_t.isoformat()
    if issues:
        save(ORPHAN_STATE_PATH, state)
    return issues

def check_pipeline_stuck():
    """P1-3: 检查 pipeline_queue 非终态卡死。返回 (issues, auto_fixed)。"""
    # 终态：uploaded, rejected（永久结束）
    # transient 失败：review_timeout, review_error, generate_failed, qc_failed, qc_error
    #   → 超 2 小时未动 → review_timeout 自动重送，其他告警
    TRANSIENT = {"review_timeout", "review_error", "generate_failed",
                 "qc_failed", "qc_error", "selected", "job_submitted"}
    # 注："generating" 已移除——全库无任何写入点（2026-10-16 P1-3），列入 TRANSIENT
    # 只是死条目；"job_submitted" 新增——dispatcher 在途任务无看门狗覆盖。
    issues = []
    auto_fixed = []
    q = queue_db.pipeline_load()  # D20261011-001 P1: pipeline_queue 已迁 SQLite
    items = q if isinstance(q, list) else q.get("items", [])
    changed = False
    for it in items:
        if not isinstance(it, dict):
            continue
        st = it.get("status", "")
        # 2026-10-15 新增：review_passed 但分数 <85 且非对照组 = 死状态
        # （D20261010-007 前的老数据，未路由到 teaser_validation；submit 门禁拦住，无执行者）
        if st == "review_passed":
            rs = it.get("review_score")
            cg = it.get("control_group")
            if isinstance(rs, (int, float)) and rs < 85 and not cg:
                ts = it.get("updated_at") or it.get("reviewed_at") or ""
                updated = parse_time(ts)
                if updated:
                    age_h = (now() - updated).total_seconds() / 3600
                    if age_h >= 2:
                        topic = it.get("topic", "?")
                        issues.append(
                            f"{topic} review_passed {rs}分（<85非对照组）"
                            f"已 {age_h:.1f}h，submit 门禁拦住，无执行者。"
                            f"应按 D20261010-007 路由到 teaser_validation"
                        )
            continue
        # Q9（2026-10-28，按审计结论落地）：ready_to_upload 被关卡
        # 持有超 24h → inbox 升级（只告警，不自动改状态、不放行；
        # alert() 自带 12h 去重，30 分钟轮询不会刷屏）。
        if st == "ready_to_upload" and it.get("upload_gate_held"):
            _hts = it.get("upload_gate_held_at") or it.get("updated_at") or ""
            _hup = parse_time(_hts)
            if _hup:
                _hage = (now() - _hup).total_seconds() / 3600
                if _hage >= 24:
                    issues.append(
                        f"pipeline_queue 升级：{it.get('topic', '?')} "
                        f"ready_to_upload 被上传关卡持有已 {_hage:.1f}h，"
                        "待人工目视放行")
            continue
        if st not in TRANSIENT:
            continue
        # X1（2026-10-28）：job_submitted 不再用 updated_at 判龄——collect 每
        # 20 分钟 _gen_poll_tick 经 pipeline_save 刷新 updated_at，job_submitted
        # 的 updated_at 永远 <6h，本分支永不触发。改用 submitted_at；无
        # submitted_at 的老条目用 gen_poll_count × 20 分钟估算；两者皆无才
        # 回落旧 updated_at 链。其他 TRANSIENT 状态不受影响。
        _age_note = ""  # X1：job_submitted 判龄口径备注，非该状态恒为空
        if st == "job_submitted":
            _sub = parse_time(it.get("submitted_at", ""))
            if _sub:
                age_h = (now() - _sub).total_seconds() / 3600
            elif it.get("gen_poll_count") is not None:
                try:
                    _ticks = int(it.get("gen_poll_count") or 0)
                except Exception:
                    _ticks = 0
                age_h = _ticks * 20 / 60
                _age_note = "（按 gen_poll_count×20分钟估算）"
            else:
                _ts = (it.get("updated_at") or it.get("reviewed_at") or
                       it.get("selected_at") or it.get("created_at", ""))
                _upd = parse_time(_ts)
                if not _upd:
                    continue
                age_h = (now() - _upd).total_seconds() / 3600
        else:
            # 找最后更新时间
            ts = (it.get("updated_at") or it.get("reviewed_at") or
                  it.get("selected_at") or it.get("created_at", ""))
            updated = parse_time(ts)
            if not updated:
                continue
            age_h = (now() - updated).total_seconds() / 3600
        # 2026-10-16 P1-3：job_submitted 用 6h 门限（dispatcher 任务正常数分钟~数小时；
        # 2h 对它太激进），其他 TRANSIENT 保持 2h
        _min_age = 6 if st == "job_submitted" else 2
        if age_h < _min_age:
            continue
        topic = it.get("topic", "?")
        # 2026-10-09：selected + 6h 内触发过评审 = 等评审结果中，不是卡死，跳过
        # （之前 AI car wash 在排期等待时被 30min 轮询重复误报）
        if st == "selected":
            rt = parse_time(it.get("review_triggered_at", ""))
            if rt and (now() - rt) < timedelta(hours=6):
                continue
        if st == "review_timeout":
            # 自动重送：重置为 selected，清除超时标记，下一轮 review 会重新处理
            # 2026-10-16 P2-2 修（四脑议会 anti-idle）：auto_resubmitted 上限 3，
            # 超限转归档 + issues 告警（经调用方进 inbox），不再无限重送
            _resub = int(it.get("auto_resubmitted", 0) or 0)
            if _resub >= 3:
                it["status"] = "archived"
                it["archive_reason"] = "review_resubmit_cap:3次自动重送仍无评审答案"
                it["updated_at"] = now().isoformat()
                issues.append(
                    f"pipeline_queue 归档：{topic} 评审自动重送已达 3 次上限仍无答案，转人工")
                changed = True
                continue
            it["status"] = "selected"
            it.pop("review_timeout_at", None)
            it["updated_at"] = now().isoformat()
            it["auto_resubmitted"] = _resub + 1
            changed = True
            auto_fixed.append(f"{topic}（review_timeout {age_h:.1f}h → 已自动重送评审）")
        elif st == "qc_error":
            # Q6（2026-10-28 用户批准，按审计结论落地，与 G14 同一根治）：
            # qc_error>6h 自动回 job_submitted，上限 3 次（专用计数
            # qc_error_back_count，不与 review_timeout 的 auto_resubmitted
            # 混用）。Q8：回流耗尽后且 age>24h → archived，不无限回流。
            _back = int(it.get("qc_error_back_count", 0) or 0)
            if age_h >= 6 and _back < 3:
                it["status"] = "job_submitted"
                it["qc_error_back_count"] = _back + 1
                it["updated_at"] = now().isoformat()
                changed = True
                auto_fixed.append(
                    f"{topic}（qc_error {age_h:.1f}h → 已自动回 job_submitted "
                    f"重跑 QC，第 {_back + 1} 次）")
            elif age_h >= 24:
                it["status"] = "archived"
                it["archive_reason"] = "qc_error 24h未恢复自动归档（Q8）"
                it["updated_at"] = now().isoformat()
                issues.append(
                    f"pipeline_queue 归档：{topic} qc_error 已 {age_h:.1f}h，"
                    f"回流上限已耗尽或超时，转人工")
                changed = True
            else:
                issues.append(f"pipeline_queue 卡死：{topic} status={st} 已 {age_h:.1f}h")
        elif st == "qc_failed":
            # Q8（2026-10-28 用户批准，二选一落定方案①看门狗归档）：
            # qc_failed 且 age>24h → archived（archived 在 select_topics
            # 的 _TERMINAL 内，话题坑位随之释放）；24h 内仍只告警，
            # 不直接进 _TERMINAL，避免与 P0-3 的永久失败口径混写。
            if age_h >= 24:
                it["status"] = "archived"
                it["archive_reason"] = "qc_failed 24h未恢复自动归档（Q8）"
                it["updated_at"] = now().isoformat()
                issues.append(
                    f"pipeline_queue 归档：{topic} qc_failed 已 {age_h:.1f}h，转人工")
                changed = True
            else:
                issues.append(f"pipeline_queue 卡死：{topic} status={st} 已 {age_h:.1f}h")
        else:
            issues.append(f"pipeline_queue 卡死：{topic} status={st} 已 {age_h:.1f}h{_age_note}")
    if changed:
        queue_db.pipeline_save(q)  # D20261011-001 P1: pipeline_queue 已迁 SQLite
    return issues, auto_fixed

def check_selected_timeout():
    """D20261017-00X KILL#12/#13：selected 状态超时告警 + 7 天自动归档。

    - selected 超 24h 未出评审结果 → 告警（Rule 15：状态必须有超时告警）。
    - selected 超 7 天（168h）仍无评审答案 → 自动归档（附原因），不永久锁定。
    有 review_score 的条目不归档（那是路由 bug，不是无评审，交其他检查处理）。
    6h 内触发过评审的视为"等答案中"，跳过（与 check_pipeline_stuck 同口径）。
    返回 (issues, auto_archived)。
    """
    issues = []
    auto_archived = []
    q = queue_db.pipeline_load()
    items = q if isinstance(q, list) else q.get("items", [])
    changed = False
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "selected":
            continue
        ts = (it.get("selected_at") or it.get("review_triggered_at")
              or it.get("updated_at") or it.get("created_at", ""))
        base = parse_time(ts)
        if not base:
            continue
        age_h = (now() - base).total_seconds() / 3600
        topic = it.get("topic", "?")
        # 6h 内触发过评审 = 等答案中，跳过
        rt = parse_time(it.get("review_triggered_at", ""))
        if rt and (now() - rt) < timedelta(hours=6):
            continue
        if age_h >= 168 and not it.get("review_score"):
            it["status"] = "archived"
            it["archive_reason"] = "selected_timeout_7d:7天无评审答案自动归档"
            it["updated_at"] = now().isoformat()
            auto_archived.append(f"{topic}（selected {age_h:.1f}h 无评审→已自动归档）")
            changed = True
        elif age_h >= 24:
            issues.append(
                f"selected 超时：{topic} 已 {age_h:.1f}h 未出评审结果 "
                f"（review_qid={it.get('review_qid', '无')}）")
    if changed:
        queue_db.pipeline_save(q)
    return issues, auto_archived


def check_boundary_hold():
    """D20261017-00X KILL#3：boundary-hold 消费者（Rule 15：状态必须有执行者）。

    boundary_hold 超 24h（自 boundary_hold_at）仍无独立复核确认 >=79
    → 自动归档。复核已回但晋档待人工（rescore_pending_confirm）的不动。
    """
    issues = []
    q = queue_db.pipeline_load()
    items = q if isinstance(q, list) else q.get("items", [])
    changed = False
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "boundary_hold":
            continue
        base = parse_time(it.get("boundary_hold_at", ""))
        if not base:
            continue
        age_h = (now() - base).total_seconds() / 3600
        if age_h >= 24:
            topic = it.get("topic", "?")
            it["status"] = "archived"
            it["archive_reason"] = ("boundary_hold_expired:24h无独立复核确认>=79"
                                    "(D20261010-007:78<79复核线)")
            it["updated_at"] = now().isoformat()
            issues.append(f"boundary-hold 到期归档：{topic}（{age_h:.1f}h 无复核）")
            changed = True
    if changed:
        queue_db.pipeline_save(q)
    return issues


def check_rescore_pending():
    """D20261017-00X KILL#6：rescore_pending_confirm 消费者。

    24h 无人工确认 → 告警；7 天无人工确认 → 自动归档（按原分档位无晋档）。
    """
    issues = []
    q = queue_db.pipeline_load()
    items = q if isinstance(q, list) else q.get("items", [])
    changed = False
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "rescore_pending_confirm":
            continue
        base = parse_time(it.get("rescore_pending_at", ""))
        if not base:
            continue
        age_h = (now() - base).total_seconds() / 3600
        topic = it.get("topic", "?")
        if age_h >= 168:
            it["status"] = "archived"
            it["archive_reason"] = (
                "rescore_pending_confirm_timeout:7天无人工确认晋档，"
                f"原分{it.get('review_score')}未晋档")
            it["updated_at"] = now().isoformat()
            issues.append(f"rescore 待确认超时归档：{topic}（{age_h:.1f}h 无人工确认）")
            changed = True
        elif age_h >= 24:
            issues.append(
                f"rescore 待人工确认：{topic} 重审 {it.get('review_score')}→"
                f"{it.get('rescore_pending_score')} 已 {age_h:.1f}h 无人确认")
    if changed:
        queue_db.pipeline_save(q)
    return issues


def check_ask_studio_pending():
    """P1-4: 检查 ask_studio queue pending 超时（>2h 告警）。"""
    issues = []
    q = load(ASK_QUEUE_PATH, {})
    items = q.get("queue", []) if isinstance(q, dict) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("status") != "pending":
            continue
        ts = it.get("created_at", "") or it.get("asked_at", "")
        created = parse_time(ts)
        if not created:
            continue
        age_h = (now() - created).total_seconds() / 3600
        if age_h >= 2:
            qid = it.get("id", "?")[:20]
            topic = it.get("topic", "?")[:30]
            issues.append(f"ask_studio pending 超时：{topic}（{qid}）已 {age_h:.1f}h")
    return issues

def check_approval_ttl():
    """AI Studio 规格 #3：awaiting_approval 超 TTL 自动处理。
    人工 24h 未终审 → 自动标记为 expired，释放给管线重新处理。

    冲突决议（approval TTL lease 暂停）：有效年龄 = 挂钟年龄 - 累计暂停时长；
    单次暂停超 12h 的先按过期处理并告警（防无限冻结 TTL）。
    """
    # 先执行防滥用：超限暂停按过期处理
    try:
        from approval_lease import enforce_pause_limits, effective_age_hours
        for it in enforce_pause_limits():
            print(f"  LEASE-EXPIRED: {it.get('topic','?')} 单次暂停超限，已按过期释放")
    except Exception as e:
        print(f"WARN: lease 超限检查失败: {e}")
        def effective_age_hours(item, now=None):  # fallback：挂钟年龄
            ts = item.get("created_at", "") or item.get("qc_passed_at", "")
            created = parse_time(ts)
            if not created:
                return 0.0
            return (now() - created).total_seconds() / 3600
    issues = []
    aa = load(APPROVAL_PATH, [])
    changed = False
    for it in aa:
        if not isinstance(it, dict):
            continue
        st = it.get("status", "")
        # 只处理待人工的（approved/rejected/uploaded/applied 不动）
        if st in ("approved", "rejected", "uploaded", "applied"):
            continue
        # P3（2026-10-28）：auto_retitle 条目无 video_file，旧逻辑
        # `if not video_file: continue` 使其永不过期；改按 created_at
        # 计 7 天 TTL（换标题审批比生成终审宽松），到期转 expired。
        if it.get("type") == "auto_retitle":
            if it.get("lease_paused"):
                continue
            _cts = it.get("created_at") or it.get("created", "")
            _created = parse_time(_cts)
            if _created:
                _age_h = (now() - _created).total_seconds() / 3600
                if _age_h > 7 * 24:
                    topic = it.get("topic") or it.get("old_title", "?")
                    it["status"] = "expired"
                    it["expired_at"] = now().isoformat()
                    it["expired_reason"] = (
                        f"换标题 7 天未审批（年龄 {_age_h:.1f}h），自动过期释放")
                    changed = True
                    issues.append(
                        f"换标题过期自动释放：{topic}（年龄 {_age_h:.1f}h 无人处理）")
            continue
        if not it.get("video_file"):
            continue
        # 暂停中的条目不计 TTL（lease 冻结）
        if it.get("lease_paused"):
            continue
        age_h = effective_age_hours(it)
        if age_h > 24:
            topic = it.get("topic", "?")
            it["status"] = "expired"
            it["expired_at"] = now().isoformat()
            it["expired_reason"] = f"人工 24h 未终审（有效年龄 {age_h:.1f}h），自动过期释放"
            changed = True
            issues.append(f"终审过期自动释放：{topic}（有效年龄 {age_h:.1f}h 无人处理）")
    if changed:
        save(APPROVAL_PATH, aa)
    return issues

def check_dead_mans_switch():
    """AI Studio 规格 #12：2 倍发布周期内零 uploaded → 告警。
    这是唯一能抓到"全线静默卡死"（D1 拒绝循环、QC 拒绝风暴、评审超时堆积）的方式。
    期望节奏：2 条/天 → 24h 内零上传即异常。"""
    issues = []
    try:
        import subprocess
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt.py", "recent", "5"],
            capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout) if r.stdout.strip() else []
        if not items:
            return ["dead-man's-switch：YouTube 近期无任何视频（API 可能异常）"]
        latest = None
        for it in items:
            if not isinstance(it, dict):
                continue
            pub = parse_time(str(it.get("published", "")))
            if pub and (latest is None or pub > latest):
                latest = pub
        if latest:
            age_h = (now() - latest).total_seconds() / 3600
            # 2 条/天 → 24h 无上传即异常（2 倍周期）
            if age_h > 24:
                issues.append(
                    f"dead-man's-switch：距上次上传已 {age_h:.1f}h（>24h），"
                    f"管线可能全线静默卡死")
    except Exception as e:
        issues.append(f"dead-man's-switch 检查异常：{e}")
    return issues

def check_reject_storm():
    """AI Studio 规格 #14：D1 网关拒绝 + QC 拒绝聚合告警。
    warn-only 不得等于 watch-never；拒绝风暴（1h 内 ≥3 次）说明管线系统性出问题。"""
    issues = []
    try:
        from collections import Counter
        cutoff = now() - timedelta(hours=1)
        # D1 拒绝
        d1_count = 0
        try:
            with open("/home/hatch/data/perpetua/upload_gateway_rejects.jsonl",
                      encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if parse_time(e.get("ts", "")) and parse_time(e["ts"]) > cutoff:
                            d1_count += 1
                    except Exception:
                        continue
        except FileNotFoundError:
            pass
        # QC regen 耗尽
        qc_count = 0
        try:
            with open("/home/hatch/data/perpetua/qc_regen_exhausted.jsonl",
                      encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if parse_time(e.get("ts", "")) and parse_time(e["ts"]) > cutoff:
                            qc_count += 1
                    except Exception:
                        continue
        except FileNotFoundError:
            pass
        if d1_count >= 3:
            issues.append(f"拒绝风暴：1h 内 D1 网关拒绝 {d1_count} 次，管线可能系统性阻塞")
        if qc_count >= 3:
            issues.append(f"拒绝风暴：1h 内 QC 重生成耗尽 {qc_count} 次，生成质量可能系统性下滑")
    except Exception as e:
        pass
    return issues

ARENA_MANUAL_DIR = f"{DATA}/perpetua/arena_manual"


def _arena_manual_age_hours(it):
    """arena_manual 滞留年龄：优先兜底文件 mtime（进入该状态时写），
    无文件时退 created_at；updated_at 每轮 collect 保存都会刷新，不可用作判龄。"""
    jid = it.get("job_id") or ""
    if jid:
        p = os.path.join(ARENA_MANUAL_DIR, jid + ".md")
        try:
            return (now().timestamp() - os.path.getmtime(p)) / 3600
        except OSError:
            pass
    base = parse_time(it.get("created_at", ""))
    if base:
        return (now() - base).total_seconds() / 3600
    return 0.0


def check_arena_manual():
    """2026-10-28 新增（空转审计 G2）：arena_manual 超时只告警，不改状态。

    - 已有 youtube_video_id 的项跳过（已上传/已排期，如烤箱 3575），免永久误报。
    - 滞留 >= 24h → 告警；>= 168h → 升级措辞告警（仍不自动归档、不打回，
      有 video_file 的可接手项归档即丢片，须人工定去留）。
    - 有 video_file 标注“可接手”，无 video_file 标注“无成片待人工”。
    返回 issues 列表（调用方进 inbox，与其他检查同口径）。
    """
    issues = []
    try:
        q = queue_db.pipeline_load()
    except Exception as ex:
        print(f"  WARN: 读 SQLite 队列失败（arena_manual 检查跳过）: {ex}")
        return issues
    items = q if isinstance(q, list) else q.get("items", [])
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "arena_manual":
            continue
        if it.get("youtube_video_id"):
            continue
        topic = it.get("topic", "?")
        age_h = _arena_manual_age_hours(it)
        has_file = bool(it.get("video_file"))
        state = "有成片可接手" if has_file else "无成片待人工"
        if age_h >= 168:
            issues.append(
                f"arena_manual 7天未接手：{topic} 已 {age_h:.1f}h（{state}），"
                f"需人工定去留（不自动归档、不打回）")
        elif age_h >= 24:
            issues.append(
                f"arena_manual 超时：{topic} 已 {age_h:.1f}h 未接手（{state}）")
    return issues


def check_privateq_stuck():
    """U11（2026-10-28，按审计结论落地）：看门狗此前只扫 pipeline
    队列与 awaiting 文件，privateq 无 30 分钟覆盖。新增：
    - waiting 且 scheduled_at 已过 2h 仍未翻 → inbox 告警
    - flip_blocked → inbox 告警（救援口见 private_flip.emergency_flip，
      已放宽到 waiting+flip_blocked，U10）
    只告警不改状态；alert() 自带 12h 去重。scheduled_at 解析
    失败的不在此判（属 U9 坏 scheduled_at，另案处理）。"""
    issues = []
    try:
        pq = queue_db.privateq_load()
        items = pq if isinstance(pq, list) else pq.get("items", [])
    except Exception as e:
        return [f"privateq 读取异常：{e}"]
    for it in items:
        if not isinstance(it, dict):
            continue
        st = it.get("status", "")
        vid = it.get("video_id", "?")
        title = it.get("title", "")[:30]
        if st == "flip_blocked":
            issues.append(
                f"privateq flip_blocked：{title}（{vid}，"
                f"原因 {it.get('flip_block_reason', '?')}），"
                "可用 emergency_flip 救援")
        elif st == "waiting":
            sched = parse_time(it.get("scheduled_at", ""))
            if sched and (now() - sched).total_seconds() / 3600 > 2:
                issues.append(
                    f"privateq waiting 过期：{title}（{vid}）"
                    f"排期已过 {(now() - sched).total_seconds() / 3600:.1f}h 仍未翻")
    return issues


def main():
    print(f"=== 死状态扫描 {now().isoformat()[:19]} ===")
    stuck = check_stuck_uploads()
    if stuck:
        for it, reason in stuck:
            topic = it.get("topic", "?")
            msg = f"死状态：视频 {topic} {reason}，video_file 存在但未上传"
            print(f"  DEAD: {topic} | {reason}")
            alert(msg)
    else:
        print("  无卡死上传")

    # P1-3: pipeline 非终态卡死
    p_issues, p_fixed = check_pipeline_stuck()
    for msg in p_fixed:
        print(f"  AUTO-FIX: {msg}")
    for msg in p_issues:
        print(f"  STUCK: {msg}")
        alert(f"死状态：{msg}")

    # D20261017-00X KILL#12/#13：selected 24h 超时告警 + 7 天自动归档
    s_issues, s_archived = check_selected_timeout()
    for msg in s_archived:
        print(f"  AUTO-ARCHIVE: {msg}")
        alert(f"死状态：{msg}")
    for msg in s_issues:
        print(f"  SELECTED-TIMEOUT: {msg}")
        alert(f"死状态：{msg}")

    # D20261017-00X KILL#3：boundary-hold 24h 到期自动归档
    b_issues = check_boundary_hold()
    for msg in b_issues:
        print(f"  BOUNDARY-HOLD: {msg}")
        alert(f"死状态：{msg}")

    # D20261017-00X KILL#6：rescore 待人工确认超时
    r2_issues = check_rescore_pending()
    for msg in r2_issues:
        print(f"  RESCORE-PENDING: {msg}")
        alert(f"死状态：{msg}")

    # P1-4: ask_studio pending 超时
    a_issues = check_ask_studio_pending()
    for msg in a_issues:
        print(f"  ASK-STUCK: {msg}")
        alert(f"死状态：{msg}")

    # AI Studio #12: dead-man's-switch
    d_issues = check_dead_mans_switch()
    for msg in d_issues:
        print(f"  DEADMAN: {msg}")
        alert(f"死状态：{msg}")

    # AI Studio #3: 终审超 TTL 自动释放
    e_issues = check_approval_ttl()
    for msg in e_issues:
        print(f"  EXPIRED: {msg}")
        alert(f"死状态：{msg}")

    # P3（2026-10-28）：已批准 auto_retitle 条目的应用动作（消费者）。
    # best-effort：异常绝不拖垮看门狗；失败留 approved 下轮重试，
    # alert() 自带 12h 去重，失败告警不刷屏。
    try:
        from apply_retitle import apply_approved
        _applied, _failed, _stale = apply_approved()
        for _a in _applied:
            print(f"  RETITLE-APPLIED: {_a.get('video_id')} → "
                  f"{_a.get('applied_title', '')[:40]}")
        for _f in _failed:
            _msg = (f"换标题应用失败：{_f.get('video_id')} "
                    f"（{_f.get('apply_last_error', '')[:80]}），"
                    f"已保留 approved 下轮重试")
            print(f"  RETITLE-FAILED: {_msg}")
            alert(f"死状态：{_msg}")
        for _s in _stale:
            print(f"  RETITLE-STALE: {_s.get('video_id')} 批准后标题已被改过，"
                  f"未覆盖，待人工看")
    except Exception as _re:
        print(f"  WARN: apply_retitle 调用失败（不阻塞看门狗）: {_re}")

    # AI Studio #14: 拒绝风暴聚合告警
    r_issues = check_reject_storm()
    for msg in r_issues:
        print(f"  STORM: {msg}")
        alert(f"死状态：{msg}")

    # 2026-10-09 新增：QC 通过但未进队列的孤儿成品
    o_issues = check_qc_orphans()
    for bn, reason in o_issues:
        msg = f"死状态：成品 {bn} {reason}，如已发布可忽略，否则考虑送今晚排期"
        print(f"  ORPHAN: {bn} | {reason}")
        alert(msg)

    # 2026-10-28 新增（空转审计 G2）：arena_manual 超时只告警
    am_issues = check_arena_manual()
    for msg in am_issues:
        print(f"  ARENA-MANUAL: {msg}")
        alert(f"死状态：{msg}")

    # U11：privateq 卡死扫描（只告警不改状态）
    pq_issues = check_privateq_stuck()
    for msg in pq_issues:
        print(f"  PRIVATEQ: {msg}")
        alert(f"死状态：{msg}")

    print("=== 扫描完成 ===")
    return (len(stuck) + len(p_issues) + len(a_issues) + len(d_issues)
            + len(e_issues) + len(r_issues) + len(o_issues)
            + len(s_issues) + len(s_archived) + len(b_issues) + len(r2_issues)
            + len(am_issues) + len(pq_issues))

if __name__ == "__main__":
    with run_lock("dead_state_watchdog"):
        sys.exit(main())
