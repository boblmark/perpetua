#!/usr/bin/env python3
"""死状态看门狗：扫描管线中卡死、超时、状态不一致的条目。
每 30 分钟运行，告警 + 自动修复（review_timeout 自动重送评审）。
2026-10-08 补完 P1-3/4：非终态超时检查 + ask_studio pending 超时。
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

def check_qc_orphans():
    """2026-10-09 新增：QC 通过但未进入任何队列的 veo_inbox 成品。

    背景：批量路（agent-browser 手动/脚本生成）绕过 MCP submit_job，
    collect_results() 只收编 job_submitted 项，导致 QC 97 分的成品
    （2026-10-09 drive-thru）在 inbox 里躺 8 小时无人认领。
    只告警不自动修复：送上传需要标题决策，留给用户/主 agent。
    同一文件 12 小时内只告警一次。
    """
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
        if not vf.startswith(VEO_INBOX + "/"):
            continue
        if bn in referenced:
            continue
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
                 "qc_failed", "qc_error", "selected", "generating"}
    issues = []
    auto_fixed = []
    q = queue_db.pipeline_load()  # D20261011-001 P1: pipeline_queue 已迁 SQLite
    items = q if isinstance(q, list) else q.get("items", [])
    changed = False
    for it in items:
        if not isinstance(it, dict):
            continue
        st = it.get("status", "")
        if st not in TRANSIENT:
            continue
        # 找最后更新时间
        ts = (it.get("updated_at") or it.get("reviewed_at") or
              it.get("selected_at") or it.get("created_at", ""))
        updated = parse_time(ts)
        if not updated:
            continue
        age_h = (now() - updated).total_seconds() / 3600
        if age_h < 2:
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
            it["status"] = "selected"
            it.pop("review_timeout_at", None)
            it["updated_at"] = now().isoformat()
            it["auto_resubmitted"] = it.get("auto_resubmitted", 0) + 1
            changed = True
            auto_fixed.append(f"{topic}（review_timeout {age_h:.1f}h → 已自动重送评审）")
        else:
            issues.append(f"pipeline_queue 卡死：{topic} status={st} 已 {age_h:.1f}h")
    if changed:
        queue_db.pipeline_save(q)  # D20261011-001 P1: pipeline_queue 已迁 SQLite
    return issues, auto_fixed

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
        # 只处理待人工的（approved/rejected/uploaded 不动）
        if st in ("approved", "rejected", "uploaded"):
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

    print("=== 扫描完成 ===")
    return len(stuck) + len(p_issues) + len(a_issues) + len(d_issues) + len(e_issues) + len(r_issues) + len(o_issues)

if __name__ == "__main__":
    with run_lock("dead_state_watchdog"):
        sys.exit(main())
