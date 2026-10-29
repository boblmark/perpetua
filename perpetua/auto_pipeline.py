#!/usr/bin/env python3
"""Perpetua 独立自动管线（不依赖 Marvis）。

链路（2026-10-09 质量战略：prompt=规格书，后期=修机械门，QC=验证，内容门=重生成）：
  topic_select（趋势→打分→去重→prompt；prompt 必须覆盖 viral_factor_checklist.md 全要素）
  → Ask Studio 终审（>=85，URGENT 豁免）
  → generate（写 mcp_jobs/pending，processor 每10min 生成）
  → postprocess（qc_repair 修机械门：R1黑帧/R2人脸起始帧/R3循环点 → loop_check → 字幕 → 音频包络）
  → collect（done → pre_upload_qc 跑在最终交付文件上 → 自动上传 private → private_queue 排期）
  → private_flip 到点翻 public（经跃迁门；2026-10-09 起取消人工终审）

失败分流：机械门修不好/内容门不达标 → 自动重生成（≤2次）；供应商拒单 → 换供应商不重试。
每步写 pipeline_log（pipeline_runs.json）。状态文件：pipeline_queue.json。
全要素清单：perpetua/viral_factor_checklist.md。
"""
import atexit
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import graded_assertions as ga
except Exception:
    ga = None


def _queue_verb_expansion(reason):
    """动词池耗尽触发：往 Ask Studio 队列塞扩充问题。"""
    import json as _json
    import uuid as _uuid
    qpath = "/home/hatch/data/ask_studio/queue.json"
    try:
        q = _json.load(open(qpath, encoding="utf-8"))
    except Exception:
        return False
    # 避免重复排队：已有 pending 的 verb 扩充问题就跳过
    for x in q.get("pending", []):
        if x.get("batch_key") in ("verb_pool_expansion", "verb_pool_dedup"):
            return False
    qid = f"q_verbauto_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    question = (
        "For my scripted comedy Shorts channel @karenvsai: the 'Karen' is a fictional, "
        "exaggerated comedy character (played by an actor) in family-friendly slapstick sketches. "
        "Recurring gag: she argues with everyday AI devices, device wins with harmless cartoon-level "
        "physical comedy payoff in under 2 seconds. "
        f"TRIGGER: my dedup system just reported '{reason}' - all candidate topics were blocked, "
        "the karma verb pool is exhausted. I need 10 FRESH slapstick payoff verbs that are: "
        "1) visually sudden and physical, safe, cartoon-level, "
        "2) doable by everyday AI devices (self-checkout, doorbell, vacuum, parking meter, speaker), "
        "3) NOT synonyms of: spray, soak, lock, trap, tow, slam, eject, blast, drench, shock, print, "
        "balloon, flap, reverse, stamp, vibrate, jolt, mute, spotlight, bop, unroll, yank, slurp, "
        "whistle, dangle, snap, dive. "
        "For each: verb, one example line, best device types. Rank by visual impact."
    )
    q["pending"].append({
        "id": qid,
        "question": question,
        "asked_by": "dash-auto",
        "priority": "high",
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "batch_key": "verb_pool_expansion",
    })
    sys.path.insert(0, "/home/hatch/data/perpetua")
    from atomic_json import atomic_write as _atomic_write
    _atomic_write(qpath, q)
    return True

BASE = "/home/hatch/data/perpetua"
QUEUE_PATH = f"{BASE}/pipeline_queue.json"
SCENARIO_POOL = f"{BASE}/scenario_pool.json"
TRENDS_PATH = "/home/hatch/data/trends/daily.json"
MCP_PENDING = "/home/hatch/data/mcp_jobs/pending"
MCP_DONE = "/home/hatch/data/mcp_jobs/done"
APPROVAL_PATH = f"{BASE}/awaiting_approval.json"
INBOX_PATH = "/home/hatch/data/collab/inbox.json"
VENV_PY = "/home/hatch/data/mcp_server/venv/bin/python"

sys.path.insert(0, BASE)
sys.path.insert(0, "/home/hatch/data")
# D20261011-001 P1: 热队列改走 SQLite（queue_db），JSON 只留备份。
# K3 对冲：本模块不碰任何 auth/登录逻辑，只换状态持久层。
import queue_db
REVIEW_THRESHOLD = 85
# D20261010-007 三级放行：>=85 直进正片；78-84 进 teaser 验证；<78 归档。
TEASER_THRESHOLD = 78
# D20261017-00X KILL#5：归档原因必须显式引用三级放行规则，承认阈值本身即规则
# （77 vs 78 的一分悬崖不虚构质的差异）。
BAND_RULE_REF = "D20261010-007"
# D20261017-00X KILL#3：78.0-78.9 为边界档——不进标准 teaser，标记 boundary-hold；
# 24h 内无独立复核确认 >=79 则自动归档（见 dead_state_watchdog.check_boundary_hold）。
BOUNDARY_HOLD_MIN = 78.0
BOUNDARY_HOLD_MAX = 79.0  # [78.0, 79.0)
BOUNDARY_HOLD_CONFIRM = 79  # 独立复核确认线
# D20261017-00X KILL#6：7 天内重审的记分窗口（留 log；晋档需人工确认）。
RESCORE_WINDOW_DAYS = 7
# D20261011-002 B-稳：对照组配额。Ask Studio 2026-10-11 实测：库里全是 >=85，
# 无 <85 对照组，>=85 与真实播放的相关性数学上算不出（r≈0 只是"无数据"）。
# 20% 配额放行 70-84 分走完全生产链（标记 control_group=True），60 天样本冲刺用。
# 选择是确定性的（topic 哈希），避免每轮随机漂移。
CONTROL_GROUP_MIN = 70
CONTROL_GROUP_RATIO_NUM = 2   # 分子：每 10 个里 2 个
CONTROL_GROUP_RATIO_DEN = 10  # 分母
# 2026-10-10：生成后端切换。musemain = 主 Muse 内置视频管线（经 VPS dispatcher），
# 已 2026-10-10 00:30 实测打通（7 分钟产出 720x1280 9:16 h264+aac mp4）。
# legacy = 旧链路（GeminiGen/GMI/Vids，经 mcp_jobs/pending + processor），仅保留做 fallback。
GEN_BACKEND = "musemain"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(p, obj):
    # v2.0.0 KILL3: 原子写
    sys.path.insert(0, "/home/hatch/data/perpetua")
    from atomic_json import atomic_write
    atomic_write(p, obj)


# A12（2026-10-28）：collect 轮次 qc 探针异常计数（模块级，单进程单轮次）。
_QC_PROBE_TRACKING = [False]
_QC_PROBE_ERRORS = [0]


def pipeline_log(stage, status="ok", detail="", count=0):
    # A12（2026-10-28）：collect 轮次探针异常计数。collect_results 开始时
    # 置位，轮次内所有 qc error 心跳（引擎导入失败、自愈失败、QC 异常等）
    # 均计数；轮末由 _write_qc_round_summary 写区分心跳。非 collect 上下文
    # （review/submit 等单次调用）不计数，避免跨轮次污染。
    global _QC_PROBE_ERRORS
    if _QC_PROBE_TRACKING[0] and stage == "qc" and status == "error":
        _QC_PROBE_ERRORS[0] += 1
    # A11（2026-10-28）：查子进程返回码——此前不查，pipeline.py 对非法阶段
    # 的抛错（及一切非零退出）都被静默吞掉，心跳丢失不可见。非零时把 stderr
    # 写进当日日志（~/memory/YYYY-MM-DD.md，运维日志惯例），best-effort。
    try:
        r = subprocess.run(
            ["python3", f"{BASE}/pipeline.py", "default", stage, status,
             detail[:200], str(count)],
            capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            try:
                import os as _os
                _logdir = _os.environ.get(
                    "PIPELINE_LOG_ERROR_DIR",
                    _os.path.expanduser("~/memory"))
                _os.makedirs(_logdir, exist_ok=True)
                _day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
                with open(_os.path.join(_logdir, f"{_day}.md"),
                          "a", encoding="utf-8") as _f:
                    _f.write(
                        f"[pipeline_log] stage={stage} status={status} "
                        f"rc={r.returncode} "
                        f"stderr={(r.stderr or '')[-300:]}\n")
            except Exception:
                pass
    except Exception:
        pass


def _write_qc_round_summary():
    """A12：collect 轮末 qc 探针区分心跳。仅当轮次内有 qc error 心跳时写
    error 心跳（detail 含 probes_failed=K，供 dispatch_health 读取）；0 异常
    时不额外写（任务体步骤 2 的“收集 N 个任务”ok 心跳即为真空闲证明）。
    调用后清计数与置位（无论是否写心跳）。"""
    global _QC_PROBE_ERRORS
    k = _QC_PROBE_ERRORS[0]
    # 先清置位，避免小结心跳本身被计入计数；再写心跳；最后清计数。
    _QC_PROBE_TRACKING[0] = False
    try:
        if k:
            pipeline_log("qc", "error",
                         f"probes_failed={k} collect 轮次探针异常"
                         "（本轮 qc error 心跳数；0 收集不代表健康）", 0)
    finally:
        _QC_PROBE_ERRORS[0] = 0


def load_queue():
    return queue_db.pipeline_load()


def save_queue(q):
    queue_db.pipeline_save(q)


def notify_inbox(msg_type, message, extra=None):
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        import inbox as inbox_gw
        inbox_gw.append_message({
            "type": msg_type, "message": message, "from": "auto-pipeline",
            "created_at": now_iso(), **(extra or {}),
        })
    except Exception:
        pass


def _trend_heat_map():
    data = _load(TRENDS_PATH, {})
    heat_map = {"high": 3, "medium": 2, "low": 1}
    out = []
    for t in data.get("trends", []):
        text = f"{t.get('title','')} {t.get('summary','')} {t.get('angle','')}"
        words = set(re.findall(r"[a-zA-Z]{3,}", text.lower()))
        out.append((words, heat_map.get(t.get("heat", "medium"), 2)))
    # 观众评论选题（2026-10-07）：合并 comment_topics.json，不破坏原格式
    try:
        cdata = _load("/home/hatch/data/trends/comment_topics.json", {})
        for t in cdata.get("candidates", []):
            text = f"{t.get('title','')} {t.get('summary','')} {t.get('angle','')}"
            words = set(re.findall(r"[a-zA-Z]{3,}", text.lower()))
            out.append((words, heat_map.get(t.get("heat", "medium"), 2)))
    except Exception:
        pass
    return out


def select_topics(n=2, slot="12:30"):
    # B' 节流（2026-10-10 议会决议 D20261010-003）：独立 Karen 模板短剧停止自动量产。
    # Shorts 只允许从《AI UNHINGED》正片剪 teaser（走独立 teaser 流程，不走本函数）。
    # 本函数直接返回空，不再从 scenario_pool 生成独立短剧选题。
    # D20261011-002 B-稳：样本冲刺延至 YPP 截止日（2027-01-31，D20261028 YPP 自行决策）期间 short 冻结解除，
    # 以 2-3 条/天跑量；到期自动恢复冻结（与 submit_jobs 的解冻期一致）。
    # 2026-10-11 补：此前解冻只加在 submit_jobs，select 漏加导致冲刺 0 选题，本次补齐。
    try:
        from datetime import date as _date
        _bsteaday = _date.today().isoformat() <= "2027-01-31"
    except Exception:
        _bsteaday = False
    try:
        from bprime_throttle import standalone_frozen
        if standalone_frozen() and not _bsteaday:
            pipeline_log("select", "ok",
                         "B' 冻结：独立短剧停止自动量产（D20261010-003），本轮选题 0 条", 0)
            return []
    except Exception as e:
        pipeline_log("select", "error", f"B' 门读取失败，fail-closed: {e}", 0)
        return []
    from virality_score import score as vscore
    from dedup_check import check_duplicate
    from viral_prompt import build_viral_prompt
    from datetime import datetime

    # P1-9 周五档：周五 12:30 时段优先选 preferred_day=Friday 的品牌系列
    weekday = datetime.now().strftime("%A")  # Monday..Sunday
    is_friday_slot = (weekday == "Friday" and slot == "12:30")

    pool = _load(SCENARIO_POOL, [])
    if not pool:
        print("scenario_pool.json 为空", file=sys.stderr)
        pipeline_log("select", "error", "scenario_pool.json 为空", 0)
        return []
    trends = _trend_heat_map()
    queue = load_queue()
    # P1-6 修复（2026-10-08）：transient 失败状态不再永久占坑。
    # 之前只有 uploaded/rejected/review_failed 被排除，review_timeout 等 transient
    # 失败永久留在 used 里，一个 topic 超时一次就永不复选。
    # D20261015-009：review_failed 去 TERMINAL 化（重审闭环入口）；archived 为新终点
    _TERMINAL = {"uploaded", "rejected", "archived",
                 "upload_permanently_failed"}  # 2026-10-28 P0-3：永久失败立即释放话题坑位
    _TRANSIENT_FAIL = {"review_timeout", "review_error", "generate_failed",
                       "qc_failed", "qc_error"}
    used = set()
    for i in queue:
        st = i.get("status", "")
        if st in _TERMINAL:
            continue
        if st in _TRANSIENT_FAIL:
            # transient 失败：如果死状态看门狗已自动重送（auto_resubmitted>0）
            # 或失败超过 24h，释放坑位允许重选
            ts = i.get("updated_at", "") or i.get("created_at", "")
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            except Exception:
                age_h = 0
            if i.get("auto_resubmitted", 0) > 0 or age_h > 24:
                continue
        used.add(i["topic"])
    # 剧集系列亲和（2026-10-07）：新选题优先填已有系列宇宙
    try:
        _series_cfg = json.load(open(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "series.json"),
            encoding="utf-8"))
        _series_list = _series_cfg.get("series", [])
        _affinity_boost = _series_cfg.get("affinity_boost", 15)
    except Exception:
        _series_list, _affinity_boost = [], 0

    def _series_match(sc):
        import re as _re
        text = f"{sc.get('topic','')} {sc.get('tags','')} {sc.get('hook','')}".lower()
        best, best_score = None, 0
        for s in _series_list:
            if s.get("status") not in ("active", "seed"):
                continue
            score = 0
            for kw in s.get("device_keywords", []):
                # 词边界匹配，防 "car" 命中 "cart"
                if _re.search(r"(?<![a-z])" + _re.escape(kw.lower()) + r"(?![a-z])", text):
                    score += len(kw)  # 长关键词权重更高
            if score > best_score:
                best, best_score = s, score
        return best

    scored = []
    for sc in pool:
        topic = sc["topic"]
        if topic in used:
            continue
        hook = sc["hook"]
        try:
            vs = vscore({"title": f"Karen vs {topic}", "hook": hook,
                         "topic_heat": "medium", "duration": 10})
            base = vs.get("score", 50) if isinstance(vs, dict) else 50  # 2026-10-19 修复：virality_score 返回键为 score，非 total
        except Exception:
            base = 50
        sc_words = set(re.findall(r"[a-zA-Z]{3,}",
                                  f"{topic} {hook} {sc.get('tags','')}".lower()))
        boost = 0
        for tw, th in trends:
            if sc_words & tw:
                boost = max(boost, th * 3)
        # P1-9: 周五档品牌系列加权
        if is_friday_slot and sc.get("preferred_day") == "Friday":
            boost += 30
            pipeline_log("select", "ok",
                         f"周五档加权: {topic} (+30)", 0)
        # 剧集亲和加权：命中现有系列宇宙的场景优先
        _ms = _series_match(sc)
        if _ms:
            boost += _affinity_boost
            sc["_series_id"] = _ms["id"]
            sc["_series_name"] = _ms["name"]
            pipeline_log("select", "ok",
                         f"剧集亲和加权: {topic} -> {_ms['name']} (+{_affinity_boost})", 0)
        scored.append((base + boost, sc))
    scored.sort(key=lambda x: -x[0])
    selected = []
    for total, sc in scored:
        if len(selected) >= n:
            break
        topic, hook = sc["topic"], sc["hook"]
        try:
            is_dup, matched, ov = check_duplicate(f"Karen {topic}", f"{topic} {hook}")
        except Exception as e:
            # P2-9 修复（2026-10-08）：去重异常不再静默放行，记 loud 日志
            pipeline_log("select", "error", f"去重检查异常 fail-open: {topic} ({e})", 0)
            is_dup, matched, ov = False, None, 0
        if is_dup:
            pipeline_log("select", "ok", f"去重拦截: {topic} (重叠{ov})", 0)
            continue
        # 公式级去重（2026-10-07）：防"系列公式"滑向"套模板"。
        # 先比 device + hook（不需要 prompt），prompt 建好后再比 karma 动词。
        try:
            from formula_dedup import check_formula, fingerprint
            f_dup, f_reason, f_detail = check_formula(
                topic, hook, "", ab_group=sc.get("ab_group"))
            if f_dup and f_reason in ("device_collision", "hook_collision"):
                pipeline_log("select", "ok",
                             f"公式去重拦截: {topic} ({f_reason}: {f_detail.get('matched')})", 0)
                continue
        except Exception as e:
            # P2-9: 公式去重异常也记 loud 日志（之前只记 error 无告警）
            pipeline_log("select", "error", f"公式去重异常 fail-open: {topic} ({e})", 0)
        try:
            pkg = build_viral_prompt(topic, hook,
                                     emoji_pair=tuple(sc.get("emoji_pair", ["🤖", "😂"])))
        except ValueError as e:
            pipeline_log("select", "error", f"prompt 纯度拒绝 {topic}: {e}", 0)
            continue
        # prompt 建好后：检查 karma 动词 30 天内是否用过，撞了就换动词重建
        try:
            from formula_dedup import check_formula as _cf2, KARMA_VERBS as _KV
            _fd, _fr, _fdet = _cf2(topic, hook, pkg["prompt"],
                                   ab_group=sc.get("ab_group"))
            if _fd and _fr == "karma_verb_reuse":
                rebuilt = False
                used_verb = _fdet.get("verb")
                from formula_dedup import KARMA_VERBS as _FULL_KV
                _base_verbs = sorted(set(
                    re.sub(r"(s|ed)$", "", v) for v in _FULL_KV
                ))
                for _v in _base_verbs:
                    if _v == used_verb:
                        continue
                    _payoff = (f"sudden slapstick mishap in under 2 seconds — a comedic "
                               f"{_v} gag erupts from the {topic} (tangible physical comedy). "
                               f"She freezes mid-gesture in comic disbelief, caught on camera")
                    try:
                        pkg = build_viral_prompt(topic, hook,
                                                 emoji_pair=tuple(sc.get("emoji_pair", ["🤖", "😂"])),
                                                 karma_payoff=_payoff)
                        _fd2, _fr2, _ = _cf2(topic, hook, pkg["prompt"])
                        if not (_fd2 and _fr2 == "karma_verb_reuse"):
                            rebuilt = True
                            pipeline_log("select", "ok",
                                         f"karma 动词撞车已换词重建: {topic} ({used_verb}->{_v})", 0)
                            break
                    except ValueError:
                        continue
                if not rebuilt:
                    pipeline_log("select", "ok",
                                 f"公式去重拦截: {topic} (karma_verb_reuse 无可用动词)", 0)
                    continue
        except Exception as e:
            pipeline_log("select", "error", f"karma 动词检查异常跳过: {e}", 0)
        title = pkg["title"]
        # v5.3 (2026-10-10 三脑会诊)：标题双门（禁剧透+语法）+ 报应轮换
        try:
            from v53_gates import check_v53_package
            _v53_ok, _v53_reason, _v53_detail = check_v53_package(
                title, pkg["prompt"])
            if not _v53_ok:
                pipeline_log("select", "ok",
                             f"v5.3 门禁拦截: {topic} ({_v53_reason})", 0)
                continue
            _payback_cat = _v53_detail.get("category")
        except Exception as e:
            pipeline_log("select", "error", f"v5.3 门禁异常 fail-open: {e}", 0)
            _payback_cat = None
        # P1-9: 品牌系列标题加前缀（如【AI Satire】）
        brand = sc.get("brand_prefix", "")
        if brand and not title.startswith(brand):
            title = f"{brand}{title}"
        selected.append({
            "topic": topic, "hook": hook,
            "title": title, "prompt": pkg["prompt"],
            "payback_category": _payback_cat,
            "description": pkg.get("description", ""),
            "tags": "Karen,InstantKarma,Shorts,AICustomerService,Comedy",
            "virality_score": round(total, 1),
            "series": sc.get("series", ""),
            "series_id": sc.get("_series_id", ""),
            "series_name": sc.get("_series_name", ""),
            "status": "selected", "slot": slot,
            "urgent": False, "created_at": now_iso(),
        })
    queue.extend(selected)
    save_queue(queue)
    pipeline_log("select", "ok",
                 f"选中 {len(selected)} 个选题({slot}): "
                 + " / ".join(s["topic"] for s in selected), len(selected))
    # 动词池耗尽触发：空窗口时自动向 Ask Studio 求新词
    if len(selected) == 0:
        if _queue_verb_expansion(f"slot {slot} 空窗口，所有候选被去重拦截"):
            pipeline_log("select", "ok",
                         "动词池耗尽，已自动向 Ask Studio 队列追加扩充问题", 0)
    return selected


def _in_control_group(item):
    """D20261011-002 B-稳对照组：topic 哈希确定性 20% 选中。
    2026-10-17：被用户指令豁免的（control_group_overridden）永不进对照组。"""
    if item.get("control_group_overridden"):
        return False
    import hashlib
    key = str(item.get("topic") or item.get("id") or "")
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    return (h % CONTROL_GROUP_RATIO_DEN) < CONTROL_GROUP_RATIO_NUM


def _pipeline_delay_waiver(qid, trig_dt, ans_dt):
    """方案 3（2026-10-27）：管线延迟豁免判定。

    仅当三条同时成立才豁免：① prompt_reviewed 里该 qid 的真提交时间早于答案
    （答案确属本次提交）；② 当前 trig 晚于答案（管线在答案到达后刷新了触发
    时间——10-22 事件的指纹，延迟是管线造成的，不是版本错配）。满足时答案
    可采信且跳过 TTL（TTL 防的是跨提交套用，qid 绑定已防住）；不满足一律不豁免。
    """
    try:
        reviewed = json.load(open(
            "/home/hatch/data/perpetua/prompt_reviewed.json", encoding="utf-8"))
        for _v in reviewed.values():
            if isinstance(_v, dict) and _v.get("qid") == qid:
                true_sub = _parse_iso_ts(_v.get("submitted_at"))
                if (true_sub is not None and true_sub < ans_dt
                        and trig_dt > ans_dt):
                    return True
                return False
    except Exception:
        pass
    return False


def _fresh_review_answer(qid, submitted_at):
    """分级断言 M5/M7/M8/N7：只接受「本次提交qid + answered_at晚于提交时间 + TTL内」的答案。
    返回 (answer_text, answered_at, verdict)。stale/qid失配 → SUSPECT。"""
    if ga is None:
        return None, None, "NO_GA"
    try:
        q = json.load(open("/home/hatch/data/ask_studio/queue.json", encoding="utf-8"))
    except Exception:
        return None, None, "NO_QUEUE"
    item = None
    for it in q.get("answered", []):
        if it.get("id") == qid:
            item = it
            break
    if not item or not (item.get("answer") or item.get("answer_summary") or "").strip():
        return None, None, ga.OK  # 无答案：还在等
    ans_at = item.get("answered_at") or ""
    # qid 必须对应本次提交：答案时间不得早于提交时间
    try:
        sub_dt = datetime.fromisoformat(str(submitted_at))
        ans_dt = datetime.fromisoformat(str(ans_at))
        if sub_dt.tzinfo is None:
            sub_dt = sub_dt.replace(tzinfo=timezone.utc)
        if ans_dt.tzinfo is None:
            ans_dt = ans_dt.replace(tzinfo=timezone.utc)
        if ans_dt < sub_dt:
            # 方案 3 豁免：trig 在答案后被刷新（管线延迟指纹）→ 答案确属本次
            # 提交，采信并跳过 TTL；否则仍按旧提交答案判 SUSPECT
            if _pipeline_delay_waiver(qid, sub_dt, ans_dt):
                pipeline_log("select", "ok",
                             f"评审答案管线延迟豁免（qid={qid}，答案确属本次提交）", 0)
                ans = item.get("answer") or item.get("answer_summary")
                if isinstance(ans, dict):
                    ans = ans.get("section") or ans.get("full") or ""
                return str(ans).strip(), ans_at, ga.CONFIRMED
            return None, ans_at, ga.SUSPECT  # 旧提交的答案：版本选择 bug
    except Exception:
        return None, ans_at, ga.SUSPECT
    # TTL：评审答案 60min
    if not ga.evidence_fresh(ans_at, ga.TTL["review_answer"]):
        return None, ans_at, ga.SUSPECT
    ans = item.get("answer") or item.get("answer_summary")  # 2026-10-16: 兼容只写summary的条目
    if isinstance(ans, dict):
        ans = ans.get("section") or ans.get("full") or ""
    return str(ans).strip(), ans_at, ga.CONFIRMED


def _suspect_review(topic, qid, reason, detail):
    """评审 SUSPECT：写 ledger + 升级，保持 selected 不跃迁（M2/N4）。"""
    if ga is None:
        return
    rec = ga.make_verdict(ga.SUSPECT, detail, ga.utcnow(), "review_answer",
                          checker="auto_pipeline.review_pending",
                          subject=f"review:{topic}",
                          checker_health={"probe_ok": True, "last_error": reason})
    ga.ledger_append(rec)
    ga.escalate("auto_pipeline.review_pending", f"review:{topic}", reason,
                severity="P2", detail=detail, evidence_ts=ga.utcnow(),
                ttl_key="review_answer", checker_health={"probe_ok": True})


def _maybe_auto_clear_stale_qid(item, topic):
    """2026-10-16 P1-1（四脑议会 anti-idle）：stale qid 自动清理。

    qid 触发超过 STALE_QID_CLEAR_AFTER_H（3h）仍无任何答案 → 把 review_qid 备份到
    review_qid_stale 后清空，本条目下个预算周期重新送审（仍须过 Ask Studio≥85 门）。
    同一条目最多自动清理 2 次，第 3 次转 _suspect_review 升级。
    返回 True=本轮已处理（调用方应 continue）。
    """
    STALE_QID_CLEAR_AFTER_H = 3
    STALE_QID_MAX_CLEARS = 2
    trig = item.get("review_triggered_at")
    try:
        trig_dt = datetime.fromisoformat(str(trig))
        if trig_dt.tzinfo is None:
            trig_dt = trig_dt.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - trig_dt).total_seconds() / 3600
    except Exception:
        return False
    if age_h < STALE_QID_CLEAR_AFTER_H:
        return False
    clears = int(item.get("review_qid_auto_clears", 0) or 0)
    qid = item.get("review_qid")
    if clears >= STALE_QID_MAX_CLEARS:
        _suspect_review(topic, qid, "stale_qid_cap",
                        f"qid {qid} {age_h:.1f}h 无答案，已达 {STALE_QID_MAX_CLEARS} 次自动清理上限，转人工")
        pipeline_log("select", "error",
                     f"qid {age_h:.1f}h 无答案达清理上限，转人工: {topic}", 0)
        return True
    item["review_qid_stale"] = qid
    item["review_qid"] = None
    item["review_qid_auto_clears"] = clears + 1
    item["review_auto_cleared"] = True
    pipeline_log("select", "ok",
                 f"qid {age_h:.1f}h 无答案，自动清理第{clears + 1}次备重审: {topic}", 0)
    return True


def _guard_stale_qid_rewrite_boundary(item, topic):
    """Batch B（2026-10-29）：rewrite/boundary 项 stale-qid 的守卫变体。

    为什么不能直接复用 _maybe_auto_clear_stale_qid（已证伪，见实施记录）：
    - rewrite_round1/2 的 qid 由重审循环以 force=True 新建，父 qid/父分
      记在 review_parent_qid/review_parent_score，旧分已清零；清掉该 qid
      后下一轮不走重审循环，而走 review_pending 送审分支，且 stale-force
      仅限 selected（force=False），topic 幂等可能返回同一旧 qid，SUSPECT
      循环不破，还丢了“该 qid 属第 N 轮重审”这一不变式，回归检查
      （新分 < 父分 → 归档）会被套到非重审提交上。
    - boundary_hold 的 qid 是首审（78-78.9 分）的提交；独立复核只在
      review_qid 为空时才打 second_review=True，且看门狗
      check_boundary_hold 的 24h 钟从 boundary_hold_at 起算；清 qid
      会让两口钟错位，且一次普通送审可能被 second_review 计分路径
      （<79 → 归档）误杀。
    因此本函数绝不碰 qid/status/review_triggered_at/review_parent_* /
    rewrite_rounds/boundary_hold_at，只在首次命中时写两个守卫标记并
    走一次 _suspect_review 升级（ga 为空时该函数自行返回，只记 log），
    之后各轮因标记已在而返回 False，落回原 SUSPECT 升级，不重复刷屏。
    返回 True=本轮已守卫处理（调用方应 continue）；False=不适用，
    调用方走原 SUSPECT 路径。
    """
    if item.get("status") not in ("rewrite_round1", "rewrite_round2",
                                  "boundary_hold"):
        return False
    if not item.get("review_qid"):
        return False
    if item.get("review_stale_qid_guarded_at"):
        return False
    trig = item.get("review_triggered_at")
    try:
        trig_dt = datetime.fromisoformat(str(trig))
        if trig_dt.tzinfo is None:
            trig_dt = trig_dt.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - trig_dt).total_seconds() / 3600
    except Exception:
        return False
    if age_h < 3:
        return False
    clears = int(item.get("review_qid_auto_clears", 0) or 0)
    if clears >= 2:
        return False
    qid = item.get("review_qid")
    item["review_stale_qid_guarded_at"] = now_iso()
    item["review_stale_qid_guarded_reason"] = \
        "stale_qid_rewrite_boundary_withheld"
    try:
        _suspect_review(topic, qid, "stale_qid_rewrite_boundary_guarded",
                        f"rewrite/boundary 项 qid {qid} 已 {age_h:.1f}h 无新鲜答案，"
                        f"直接清 qid 不安全（重审父子不变式/边界复核钟），"
                        f"本次只标记守卫、不清 qid、不改状态，待 force 路径另案处理")
    except Exception:
        pass
    pipeline_log("select", "ok",
                 f"rewrite/boundary stale-qid 已守卫标记（不清 qid）: {topic}", 0)
    return True


def _gen_poll_tick(item, backend):
    """2026-10-16 P1-3（四脑议会 anti-idle）：生成轮询计数。

    每轮 collect 对在途任务调用一次；超 72 轮（约 24h @20min 频率，红队 WATCH-4：
    若轮询频率变更，此阈值需同步调整）→ 升级一次并标记，不再重复升级。
    返回 True=本轮已达上限（调用方可继续等待，升级已记）。
    """
    pc = int(item.get("gen_poll_count", 0) or 0) + 1
    item["gen_poll_count"] = pc
    if pc > 72 and not item.get("gen_poll_escalated"):
        item["gen_poll_escalated"] = True
        detail = f"{backend} 在途任务 {pc} 轮（约 24h）仍未完成，dispatcher/thread 可能 hung"
        try:
            if ga is not None:
                ga.escalate("auto_pipeline.generate",
                            str(item.get("topic", ""))[:40],
                            "stuck_generation", severity="P2", detail=detail,
                            evidence_ts=ga.utcnow(), ttl_key="gen_poll")
        except Exception:
            pass
        pipeline_log("generate", "error",
                     f"生成 hung 升级: {item.get('topic')} {detail}", 0)
        return True
    return False


def _gen_poll_reset(item):
    """任务终结（done/failed）时清轮询计数。"""
    item.pop("gen_poll_count", None)
    item.pop("gen_poll_escalated", None)


# ---------------- 方案 1（2026-10-27）：认领超时清道夫 + 容量快照 ----------------
# 背景：muse-main claimed-but-unconsumed 致生成静默断流；旧逻辑只在 24h 轮询后升级，
# 无超时处理。清道夫每轮 collect 扫 job_submitted：超 GEN_CLAIM_TIMEOUT_MIN 无结果
# → 直接转 arena 手工兜底（2026-10-28 起 nano 路由已下掉，不再换后端重派）；
# attempts 达 GEN_MAX_ATTEMPTS → generate_failed + 升级。arena 只能主 agent 经浏览器
# 派发（reCAPTCHA 拦 CDP），故超时后落手工兜底文件，不谎称自动。
# 超时取 60 分钟（不用 30）：健康生成约 7 分钟，但主 Muse 排队起步有延迟，60 分钟
# 既防误杀慢启动，又远小于当前以天计的卡死。
GEN_CLAIM_TIMEOUT_MIN = 60
GEN_MAX_ATTEMPTS = 2
ARENA_MANUAL_DIR = "/home/hatch/data/perpetua/arena_manual"
GEN_CAPACITY_PATH = "/home/hatch/data/perpetua/gen_capacity.json"


def _parse_iso_ts(s):
    try:
        if not s or not isinstance(s, str):
            return None
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _write_arena_manual_file(item, jid):
    """写 arena 手工兜底任务文件（供主 agent 经浏览器派发），返回路径或空串。"""
    try:
        os.makedirs(ARENA_MANUAL_DIR, exist_ok=True)
        path = os.path.join(ARENA_MANUAL_DIR, jid + ".md")
        content = (
            "# Arena 手工兜底任务（清道夫生成，主 agent 经浏览器派发）\n\n"
            f"- job_id：{jid}\n"
            f"- topic：{item.get('topic')}\n"
            f"- review_score：{item.get('review_score')}\n"
            f"- slot：{item.get('slot')}\n"
            f"- 原后端：{item.get('gen_rerouted_from')}\n\n"
            "## 操作\n\n"
            "Visit https://arena.ai/video，在 \"Describe your video…\" 输入以下 prompt，"
            "等两条视频生成完成，下载到 /home/hatch/data/veo_inbox/，两条都进 QC 取优者。\n\n"
            "## Prompt\n\n"
            f"{item.get('prompt', '')}\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except Exception as e:
        pipeline_log("generate", "error",
                     f"arena 手工兜底文件写失败 {item.get('topic')}: {e}", 0)
        return ""


def _vps_job_is_done(muse_job_id):
    """G9（2026-10-28）：SSH 直读 VPS done 目录，确认 muse 任务是否已完成。

    返回 True（done 目录有 .result.json 或 .json 结果）、False（明确无结果）、
    None（SSH/解析失败，结果未知，调用方按 fail-open 处理）。
    只读远端，不写任何状态。"""
    import re as _re
    if not muse_job_id or not _re.fullmatch(r"[\w-]+", str(muse_job_id)):
        return None
    try:
        from dispatcher_nano_bridge import DispatcherClient
        _c = DispatcherClient()
        _out = _c._ssh_run(
            f"[ -f /opt/mcp-b/data/mcp_jobs/done/{muse_job_id}.result.json ] "
            f"|| [ -f /opt/mcp-b/data/mcp_jobs/done/{muse_job_id}.json ]; "
            f"echo $?")
        return _out.strip().split()[-1] == "0"
    except Exception:
        return None


def _supersede_vps_job(muse_job_id):
    """G8（2026-10-28）：把 VPS pending/claimed 文件移入 pending/superseded/。

    换后端（现为转 arena_manual）时调用，防 muse-main 后到出片无人认领、
    也防 fallback/G16 把已转手工的任务当新任务重做。返回 True（已移走或
    本就无文件）、False（SSH 失败，调用方留 marker 下轮重试）。
    绝不抛异常。"""
    import re as _re
    if not muse_job_id or not _re.fullmatch(r"[\w-]+", str(muse_job_id)):
        return False
    try:
        from dispatcher_nano_bridge import DispatcherClient
        _c = DispatcherClient()
        _c._ssh_run(
            f"mkdir -p /opt/mcp-b/data/mcp_jobs/pending/superseded; "
            f"for f in /opt/mcp-b/data/mcp_jobs/pending/{muse_job_id}.json "
            f"/opt/mcp-b/data/mcp_jobs/pending/{muse_job_id}.*.json; do "
            f"[ -f \"$f\" ] && mv \"$f\" "
            f"/opt/mcp-b/data/mcp_jobs/pending/superseded/; done; echo OK")
        return True
    except Exception:
        return False


def _sweep_stale_submitted(queue, route_fn=None, now=None):
    """认领超时清道夫。返回 (changed, actions)。

    2026-10-28 起 nano 路由已下掉：超时项不再换后端，直接转 arena 手工兜底。
    route_fn 参数保留兼容，不再用于换后端。只动 job_submitted 且无 done 文件且
    超时的项；无时间戳的项仅在轮询满 72 轮时才视为过期（P0-2 补洞）。
    G9：翻转前若 VPS 已 done（本地取回失败），不翻转，改标
    vps_done_unfetched 等取回重试 + 看门狗 24h 升级，防已完成任务被重做。
    G8：转 arena_manual 时同步 supersede 原 VPS 认领并 pop muse_job_id，
    SSH 失败留 marker 由 collect 的 arena_manual 循环重试（上限 3 次）。
    """
    now = now or datetime.now(timezone.utc)
    changed = False
    actions = []
    for item in queue:
        if item.get("status") != "job_submitted" or not item.get("job_id"):
            continue
        jid = item["job_id"]
        if os.path.exists(os.path.join(MCP_DONE, jid + ".result.json")):
            continue
        submitted_at = _parse_iso_ts(item.get("submitted_at"))
        if submitted_at is None:
            # 2026-10-28 P0-2：无时间戳项此前永不被扫。轮询满 72 轮
            # （约 24h，与 _gen_poll_tick 升级阈值一致）才视为过期；
            # 未满 72 轮不动，防误杀慢启动。
            if int(item.get("gen_poll_count") or 0) < 72:
                continue
            age_min = 10 ** 9
        else:
            age_min = (now - submitted_at).total_seconds() / 60.0
        if age_min < GEN_CLAIM_TIMEOUT_MIN:
            continue
        attempts = int(item.get("gen_attempts") or 0)
        backend = item.get("gen_backend") or ""
        topic = item.get("topic")
        # G9：VPS 已 done 但本地取回失败 → 不是未完成，不翻转、不判死。
        # 只标旗：collect 每轮继续取回重试；看门狗对 24h 未取回升级。
        # SSH 查不到（None）按 fail-open 照常翻转（停摆期窗口内翻转与旧行为一致）。
        _mj = item.get("muse_job_id")
        if _mj and not item.get("vps_done_unfetched"):
            if _vps_job_is_done(_mj) is True:
                item["vps_done_unfetched"] = True
                item["vps_done_seen_at"] = now.isoformat()
                pipeline_log("generate", "error",
                             f"清道夫跳过 {topic}：VPS 已 done 但本地未取回，"
                             f"等取回重试不重做", 0)
                changed = True
                actions.append(("vps_done_unfetched", topic))
                continue
        if item.get("vps_done_unfetched"):
            # 已标旗的项：取回重试仍在 collect 侧跑，清道夫永不翻转它。
            continue
        if attempts >= GEN_MAX_ATTEMPTS:
            item["status"] = "generate_failed"
            item["generate_error"] = (
                f"认领超时清道夫：{backend} {attempts} 次换后端仍无结果，达上限")
            _gen_poll_reset(item)
            pipeline_log("generate", "error",
                         f"清道夫判死 {topic}：{backend} 超时 {attempts} 次", 0)
            try:
                if ga is not None:
                    ga.escalate("auto_pipeline.gen_timeout",
                                str(topic or "")[:40], "claim_timeout_exhausted",
                                severity="P1",
                                detail=f"{backend} {attempts} 次换后端仍无结果",
                                evidence_ts=ga.utcnow(), ttl_key="gen_timeout")
            except Exception:
                pass
            changed = True
            actions.append(("failed", topic))
            continue
        # nano 路由已下掉（2026-10-28）：超时项不再换后端，直接转 arena 手工兜底；
        # 历史 nano 项（gen_backend == "nano"）同样走此分支排空。
        # 自动后端已耗尽 → arena 手工兜底
        item["gen_attempts"] = attempts + 1
        item["status"] = "arena_manual"
        item["gen_rerouted_from"] = backend
        # G8：同步注销原 VPS 认领。成功则 pop muse_job_id（此后任何轮询
        # 都不再认领它，后到出片也不会复活本条）；SSH 失败留 marker，
        # 由 collect 的 arena_manual 循环重试，上限 3 次后升级不断重试。
        # 安全边界：清道夫只遍历本地 job_submitted 项；17:05 留置的 VPS-only
        # 认领积压无本地 job_submitted 项，永不进入本分支。
        _mj2 = item.get("muse_job_id")
        if _mj2:
            if _supersede_vps_job(_mj2):
                item.pop("muse_job_id", None)
                item["muse_job_superseded"] = _mj2
                item["muse_job_superseded_at"] = now.isoformat()
                item.pop("muse_claim_supersede_pending", None)
            else:
                item["muse_claim_supersede_pending"] = True
                item["muse_supersede_retries"] = \
                    int(item.get("muse_supersede_retries") or 0) + 1
        # 方案 1 收尾：兜底产物默认须人工目视放行（上传关卡拦截），防异构后端直发
        item["requires_fallback_approval"] = True
        item.pop("fallback_approved", None)
        path = _write_arena_manual_file(item, jid)
        pipeline_log("generate", "error",
                     f"清道夫转 arena 手工兜底 {topic}（文件 {path}）", 0)
        try:
            if ga is not None:
                ga.escalate("auto_pipeline.gen_timeout",
                            str(topic or "")[:40], "arena_manual_pending",
                            severity="P2",
                            detail=f"{backend} 超时（nano 路由已下掉），arena 手工兜底文件 {path}",
                            evidence_ts=ga.utcnow(), ttl_key="gen_timeout")
        except Exception:
            pass
        changed = True
        actions.append(("arena_manual", topic))
    return changed, actions


def _handle_done_error_exhausted(item, jid):
    """G5（2026-10-28）：done-error 重试耗尽后不再直写 generate_failed
    死胡同，改走 arena 手工兜底（与清道夫同款语义：兜底文件 + 须人工
    目视放行），下轮由 Stage 1 ingest / G2 看门狗接手，不静默丢弃。
    审计另一半“重提时强制换后端”已随 nano 路由下掉而作废：route()
    现按实时健康返 muse-main/qqbox/拒绝，重提即按当前健康路由，
    不再需要按 retry_count 钉死后端。"""
    backend = item.get("gen_backend") or ""
    item["status"] = "arena_manual"
    item["gen_rerouted_from"] = backend
    item["requires_fallback_approval"] = True
    item.pop("fallback_approved", None)
    path = _write_arena_manual_file(item, jid)
    pipeline_log("generate", "error",
                 f"生成失败(已重试2次)转 arena 手工兜底 {item.get('topic')}（文件 {path}）", 0)
    try:
        if ga is not None:
            ga.escalate("auto_pipeline.gen_timeout",
                        str(item.get("topic") or "")[:40], "arena_manual_pending",
                        severity="P2",
                        detail=f"{backend} done-error 耗尽，arena 手工兜底文件 {path}",
                        evidence_ts=ga.utcnow(), ttl_key="gen_timeout")
    except Exception:
        pass
    return path


def _write_gen_capacity(queue, now=None):
    """写生成容量快照（看板数据源）：在途任务按后端计数 + 最老在途年龄。"""
    try:
        now = now or datetime.now(timezone.utc)
        by_backend = {}
        oldest = None
        for item in queue:
            if item.get("status") != "job_submitted":
                continue
            b = item.get("gen_backend") or "unknown"
            by_backend[b] = by_backend.get(b, 0) + 1
            ts = _parse_iso_ts(item.get("submitted_at"))
            if ts is not None and (oldest is None or ts < oldest):
                oldest = ts
        # 方案 1 收尾：arena_manual 消费者——快照列出待手工兜底项，collect 每轮
        # 另行打日志（见 collect_results），该状态不再是无人认领的孤儿状态
        arena_pending = [{
            "topic": it.get("topic"), "job_id": it.get("job_id"),
            "file": os.path.join(ARENA_MANUAL_DIR, str(it.get("job_id")) + ".md"),
        } for it in queue if it.get("status") == "arena_manual"]
        snap = {
            "ts": now.isoformat(),
            "job_submitted_by_backend": by_backend,
            "job_submitted_total": sum(by_backend.values()),
            "arena_manual_pending": arena_pending,
            "oldest_job_submitted_age_min": (
                round((now - oldest).total_seconds() / 60.0, 1)
                if oldest is not None else None),
        }
        sys.path.insert(0, "/home/hatch/data/perpetua")
        from atomic_json import atomic_write as _awc
        _awc(GEN_CAPACITY_PATH, snap)
        return snap
    except Exception:
        return {}


# ---------------- 重审闭环（D20261015-009，四脑议会） ----------------
# 评审预算：动态（2026-10-15 用户要求：不固定，按实际需求浮动）
# 需求=待审条目数；预算=需求+25%余量；下限8（保底）、上限24（防失控）
DYNAMIC_BUDGET_FLOOR = 8
DYNAMIC_BUDGET_CEIL = 24


def dynamic_review_budget_cap():
    """按实际待审需求动态计算当日预算。"""
    try:
        queue = load_queue()
    except Exception:
        queue = []
    demand = sum(1 for i in queue
                 if i.get("status") in ("selected", "review_failed",
                                        "rewrite_round1", "rewrite_round2")
                 and not i.get("urgent"))
    return max(DYNAMIC_BUDGET_FLOOR, min(DYNAMIC_BUDGET_CEIL, int(demand * 1.25) + 2))


DAILY_REVIEW_BUDGET_CAP = 16  # 兼容旧引用，实际以 dynamic_review_budget_cap() 为准


def _review_budget_path():
    return "/home/hatch/data/perpetua/review_budget_%s.json" % datetime.now(
        timezone.utc).strftime("%Y-%m-%d")


def review_budget_remaining(cap=None):
    cap = cap if cap is not None else dynamic_review_budget_cap()
    try:
        b = json.load(open(_review_budget_path(), encoding="utf-8"))
        used = int(b.get("used", 0))
    except Exception:
        used = 0
    return max(0, cap - used)


def review_budget_consume(n=1, cap=None):
    """2026-10-28 解封：Ask Studio 免费，预算只计数、永不硬卡评审。
    旧 N7“预算耗尽不提交”已废：无论 used 是否超 cap，一律扣计数并返回 True，
    评审不得因预算空转。cap/dynamic 仅作观测口径保留。"""
    cap = cap if cap is not None else dynamic_review_budget_cap()
    p = _review_budget_path()
    try:
        b = json.load(open(p, encoding="utf-8"))
    except Exception:
        b = {"used": 0}
    used = int(b.get("used", 0))
    b["used"] = used + n
    b["cap"] = cap
    b["dynamic"] = True
    json.dump(b, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return True


def parse_reviewer_fixes(answer_text):
    """从评审答案提取 Fix 1-3 的 (OLD, NEW) 文本对。M1：verbatim 应用，不改写。"""
    import re as _re
    pat = _re.compile(r'Change:\s*"(.+?)"\s*(→|->)\s*"(.+?)"', _re.S)
    return [(o.strip(), n.strip()) for o, _, n in pat.findall(str(answer_text or ""))]


def apply_reviewer_fixes(prompt, fixes):
    """M1：reviewer 原文 fix 逐字替换。返回 (new_prompt, applied_count)。"""
    new_prompt = str(prompt or "")
    applied = 0
    for old, new in fixes:
        if old and old in new_prompt and new != old:
            new_prompt = new_prompt.replace(old, new, 1)
            applied += 1
    return new_prompt, applied


def _review_answer_text(qid):
    """取某 qid 的评审答案原文（用于提取 fixes / 判 overlap / 判 FLAG）。"""
    try:
        q = json.load(open("/home/hatch/data/ask_studio/queue.json", encoding="utf-8"))
    except Exception:
        return ""
    for it in q.get("answered", []):
        if it.get("id") == qid:
            ans = it.get("answer", "")
            if isinstance(ans, dict):
                ans = ans.get("section") or ans.get("full") or ""
            return str(ans)
    return ""


def rewrite_failed_loop(instant_timeout_minutes=0):
    """重审循环：review_failed → rewrite_roundN → review_passed/升级人工。
    T1-T12 状态机（AI Studio 规格 §2），红队修订 R1/R4 已并入。
    2026-10-17 修：instant_timeout_minutes 由调用方传入（默认 0 只提交不阻塞），
    此前硬编码 5 导致 review --wait 0 --instant-timeout 0 每轮空等最多 10 分钟。
    2026-10-17 用户铁律：取消 2 轮硬上限，没过 85 一直改；5 轮未过升级人工，不静默归档。"""
    from prompt_review import submit_prompt_review_instant
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("status") != "review_failed":
            continue
        topic = item.get("topic", "")
        rounds = int(item.get("rewrite_rounds", 0) or 0)
        # 2026-10-17 用户铁律：取消 2 轮硬上限——没过 85 就一直改，不静默归档；
        # 5 轮仍未过则升级人工判别（换题/继续），避免无限烧评审预算。
        if rounds >= 5:
            try:
                ga.escalate("auto_pipeline.rewrite", topic,
                            "rewrite_rounds_exhausted_5",
                            severity="P2",
                            detail=f"5轮重写仍未过85(父分{item.get('review_parent_score')})，请人工判断换题或继续")
            except Exception:
                pass
            item["status"] = "review_failed"
            item["needs_human_review"] = True
            item["human_reason"] = "5轮重写仍未过85，已升级人工"
            # G12（2026-10-28）：写死人工复核起止时间供看门狗消费——
            # 只写一次（后续轮次不再刷新），7 天无人处理看门狗即归档；
            # 归档时发 inbox，不是静默归档（2026-10-17“不静默归档”铁律）。
            if not item.get("human_review_at"):
                item["human_review_at"] = now_iso()
            if not item.get("human_review_deadline_at"):
                item["human_review_deadline_at"] = (
                    datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            pipeline_log("select", "error", f"重审5轮未过→升级人工: {topic}", 0)
            changed = True
            continue
        qid = item.get("review_qid")
        answer = _review_answer_text(qid)
        # N1：POLICY: FLAG 永不自动重写
        if "POLICY: FLAG" in answer.upper().replace("：", ":"):
            item["status"] = "archived"
            item["archive_reason"] = "policy_flag_human_review"
            pipeline_log("select", "error", f"POLICY FLAG→人工复核: {topic}", 0)
            changed = True
            continue
        # T4：<60 分结构性失败直接归档
        parent_score = item.get("review_score")
        if isinstance(parent_score, (int, float)) and parent_score < 60:
            item["status"] = "archived"
            item["archive_reason"] = "score_below_60_structural"
            pipeline_log("select", "ok", f"终审{parent_score}分结构性失败→归档: {topic}", 0)
            changed = True
            continue
        fixes = parse_reviewer_fixes(answer)
        if not fixes:
            item["status"] = "archived"
            item["archive_reason"] = "no_extractable_fixes"
            pipeline_log("select", "ok", f"无可提取fix→归档: {topic}", 0)
            changed = True
            continue
        # T2：原创性结构重叠 → 跳过 round1，直接 round2（消耗两轮）
        # 2026-10-17：取消轮数上限后不再因轮数不足归档
        overlap = "significant overlap" in answer.lower()
        consume = 2 if overlap else 1
        new_prompt, applied = apply_reviewer_fixes(item.get("prompt", ""), fixes)
        # N3/M8：必须与父 prompt 有差异
        if applied == 0 or new_prompt == item.get("prompt", ""):
            item["status"] = "archived"
            item["archive_reason"] = "fixes_not_applicable"
            pipeline_log("select", "ok", f"fix无法应用→归档: {topic}", 0)
            changed = True
            continue
        # N7：预算检查
        if not review_budget_consume(1):
            pipeline_log("select", "ok", f"评审预算耗尽，重审等待: {topic}", 0)
            continue
        # M3：fresh 提交拿新 qid（N4：绝不用父 qid）
        try:
            new_qid, _ = submit_prompt_review_instant(
                new_prompt, item.get("title", ""), item.get("description", ""),
                topic=topic, force=True,
                instant_timeout_minutes=instant_timeout_minutes)
        except Exception as e:
            item["status"] = "archived"
            item["archive_reason"] = f"resubmit_error:{str(e)[:80]}"
            changed = True
            continue
        new_rounds = rounds + consume
        item["prompt"] = new_prompt
        item["review_qid"] = new_qid
        item["review_parent_score"] = parent_score
        item["review_parent_qid"] = qid
        item["rewrite_rounds"] = new_rounds
        item["rewrite_applied_fixes"] = applied
        item["overlap_rewrite"] = overlap
        item["review_triggered_at"] = datetime.now(timezone.utc).isoformat()
        # 注意：答案尚未回来，保持 rewrite_roundN 等答案；下一轮 review_pending 捡答案
        item["status"] = "rewrite_round2" if new_rounds >= 2 else "rewrite_round1"
        item["review_score"] = None  # N4 精神：旧分清零，不带入新轮
        pipeline_log("select", "ok",
                     f"重审第{new_rounds}轮已送审({applied}处fix): {topic}", 0)
        changed = True
    if changed:
        save_queue(queue)
    return queue


def _score_tier(score):
    """D20261017-00X KILL#6：分数档位。None=-1；<78=0（归档档）；78-84=1（teaser档）；>=85=2（正片档）。"""
    if not isinstance(score, (int, float)):
        return -1
    if score >= REVIEW_THRESHOLD:
        return 2
    if score >= TEASER_THRESHOLD:
        return 1
    return 0


def _within_days(iso_s, days):
    try:
        dt = datetime.fromisoformat(str(iso_s))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() < days * 86400
    except Exception:
        return False


def _log_rescore(item, old_score, new_score, qid):
    """D20261017-00X KILL#6：7 天内重审必须留 log。返回 True=本次是窗口内重审。"""
    old_at = item.get("review_answered_at")
    if not (isinstance(old_score, (int, float)) and isinstance(new_score, (int, float))):
        return False
    if not (old_at and _within_days(old_at, RESCORE_WINDOW_DAYS)):
        return False
    log = item.setdefault("rescore_log", [])
    log.append({
        "at": datetime.now(timezone.utc).isoformat(),
        "old_score": old_score,
        "new_score": new_score,
        "qid": qid,
    })
    item["rescore_log"] = log[-10:]  # 只保留最近 10 条
    return True


def confirm_rescore_promotion(topic_substr):
    """D20261017-00X KILL#6：人工确认重审晋档（Dash 手工执行）。

    对 status=rescore_pending_confirm 的条目，按 rescore_pending_score
    的档位执行正常路由（review_passed/teaser_validation/review_failed）。
    返回 True=已确认并路由。
    """
    queue = load_queue()
    items = queue if isinstance(queue, list) else queue.get("items", [])
    hit = False
    for it in items:
        if it.get("status") != "rescore_pending_confirm":
            continue
        if topic_substr not in str(it.get("topic", "")):
            continue
        score = it.get("rescore_pending_score")
        it["review_score"] = score
        it["review_answered_at"] = it.get("rescore_pending_at")
        it.pop("rescore_pending_score", None)
        it.pop("rescore_pending_at", None)
        if score is not None and score >= REVIEW_THRESHOLD:
            it["status"] = "review_passed"
        elif score is not None and score >= TEASER_THRESHOLD:
            it["status"] = "teaser_validation"
            it["teaser_queued_at"] = datetime.now(timezone.utc).isoformat()
        else:
            it["status"] = "review_failed"
        it["rescore_confirmed_by"] = "human"
        it["rescore_confirmed_at"] = datetime.now(timezone.utc).isoformat()
        pipeline_log("select", "ok",
                     f"人工确认重审晋档 {score}分: {it.get('topic')}", 1)
        hit = True
    if hit:
        save_queue(queue)
    return hit


def request_archive_reentry(topic_substr):
    """D20261017-00X KILL#8：归档话题重入（Dash 手工执行，非自动）。

    条件：已归档超 24h（禁同一评审人 24h 内反复刷分）；重入后 status=selected
    等待新一轮独立评审，旧分保留在 rescore 守卫视野内（7 天内重审留 log）。
    返回 True=已重入。
    """
    queue = load_queue()
    items = queue if isinstance(queue, list) else queue.get("items", [])
    hit = False
    for it in items:
        if it.get("status") != "archived":
            continue
        if topic_substr not in str(it.get("topic", "")):
            continue
        arch_at = it.get("updated_at") or it.get("archived_at") or ""
        if arch_at and not _within_days(arch_at, 1):
            pass  # 超 24h，可重入
        elif arch_at:
            pipeline_log("select", "error",
                         f"重入被拒（归档未满24h，防刷分）: {it.get('topic')}", 0)
            continue
        it["status"] = "selected"
        it["selected_at"] = datetime.now(timezone.utc).isoformat()
        rlog = it.setdefault("reentry_log", [])
        rlog.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "from": "archived",
            "archive_reason": it.get("archive_reason", ""),
            "by": "human",
        })
        pipeline_log("select", "ok", f"归档重入→selected 待独立评审: {it.get('topic')}", 0)
        hit = True
    if hit:
        save_queue(queue)
    return hit


def review_pending(max_wait_minutes=30, instant_timeout_minutes=5):
    from prompt_review import (
        submit_prompt_review_instant, wait_for_review_answer,
        parse_review_score, find_best_review_answer)
    queue = load_queue()
    changed = False
    for item in queue:
        # D20261015-009：重审轮次的答案也在此捡起（rewrite_round1/2 等同 selected 流程）
        # D20261017-00X KILL#3：boundary_hold 同 selected 流程参与独立复核
        # （新 qid、新一轮评审），送审时打 second_review=True。
        _st = item.get("status")
        _is_rewrite = _st in ("rewrite_round1", "rewrite_round2")
        _is_boundary = _st == "boundary_hold"
        if (_st != "selected" and not _is_rewrite and not _is_boundary) or item.get("urgent"):
            continue
        if _is_boundary and not item.get("review_qid"):
            item["second_review"] = True
        topic = item["topic"]
        # 重审轮次：已送审（qid 已有），只捡答案不重复提交
        # 2026-10-16 修：普通 selected 项若已有 review_qid，同样只捡答案
        # （submit_prompt_review_instant 幂等，重调 ask_now 只是返回同一 iid）。
        # 不重复提交、不扣预算、不刷新 review_triggered_at。
        # 修复 selected 死状态：此前每轮"重提交"会刷新 submitted_at 并扣预算，
        # 导致答案永被判 SUSPECT（答案早于提交）且预算耗尽后 pickup 被跳过。
        _pickup_only = bool(item.get("review_qid"))
        print(f"[review] {'捡答案' if _pickup_only else '送审'}: {topic} ...", flush=True)
        try:
            if _pickup_only:
                # qid 已有，只捡答案（N7 预算已在首次送审时扣除）
                qid = item.get("review_qid")
                answer = None
                submitted_at = item.get("review_triggered_at")
            else:
                # N7：新提交先扣预算
                if not review_budget_consume(1):
                    pipeline_log("select", "ok", f"评审预算耗尽，送审等待: {topic}", 0)
                    continue
                # 2026-10-29 stale-force：刚被 stale-qid 清理过的条目（qid=None、
                # review_auto_cleared=True）重送时必须 force，否则 topic 幂等返回
                # 同一个旧 qid，旧答案已过 TTL → 每轮 SUSPECT 死循环（3594 实证）。
                # force 产生全新 iid，旧答案无法再被捡到；成功拿到新 qid 后清标记，
                # 避免之后每轮都 force；拿不到新 qid（与 stale 相同或为空）则保留
                # 标记，下轮继续 force。
                # 仅 selected 项走 force；rewrite/boundary 项沿用第十五批限定，
                # 其 qid 属重审轮次，不在此强制换 qid。
                _force_resubmit = bool(item.get("review_auto_cleared")) and _st == "selected"
                _stale_qid = item.get("review_qid_stale")
                qid, answer = submit_prompt_review_instant(
                    item["prompt"], item["title"], item["description"],
                    topic=topic, force=_force_resubmit,
                    instant_timeout_minutes=instant_timeout_minutes)
                if _force_resubmit and qid and qid != _stale_qid:
                    item.pop("review_auto_cleared", None)
                # 本次提交时间（用于 qid/版本绑定，M5/N7）
                submitted_at = None
                try:
                    reviewed = json.load(open(
                        "/home/hatch/data/perpetua/prompt_reviewed.json", encoding="utf-8"))
                    for _k, _v in reviewed.items():
                        if isinstance(_v, dict) and _v.get("qid") == qid:
                            submitted_at = _v.get("submitted_at")
                            break
                except Exception:
                    pass
                if not submitted_at:
                    submitted_at = item.get("review_triggered_at") or datetime.now(timezone.utc).isoformat()
                item["review_qid"] = qid
                item["review_triggered_at"] = datetime.now(timezone.utc).isoformat()
            # 分级断言：只接受本次提交qid + 新鲜TTL内的答案（M5/M7/M8/N7）
            fresh_answer, fresh_at, fverdict = _fresh_review_answer(qid, submitted_at)
            if fverdict == (ga.SUSPECT if ga else "SUSPECT"):
                # 2026-10-29 细化（review_timeout 兜底）：看门狗把 review_timeout
                # 重送回 selected 后，条目仍带旧 review_qid，collect 只捡答案；
                # 若答案已过 60min TTL，每轮都判 SUSPECT 且永不清 qid、永不重送
                # （3594 实证：22:24 答案→00:31 重送→00:32 起每轮 SUSPECT）。
                # 与无答案分支同款：触发超 3h 的 pickup_only selected 项先试
                # stale-qid 清理（备份→清空，2 次上限），下轮重新送审；未达
                # 清理条件（触发 <3h 或已达上限）时仍走原 SUSPECT 升级。
                # rewrite/boundary 项不在此清理（其 qid 属重审轮次，另案处理）。
                # Batch B（2026-10-29）：rewrite/boundary 项先走守卫变体，
                # 绝不直接清 qid（理由见 _guard_stale_qid_rewrite_boundary
                # 的 docstring；直接清已被证伪为不安全）。
                if (_pickup_only
                        and _st in ("rewrite_round1", "rewrite_round2",
                                    "boundary_hold")
                        and _guard_stale_qid_rewrite_boundary(item, topic)):
                    changed = True
                    continue
                if (_pickup_only and _st == "selected"
                        and _maybe_auto_clear_stale_qid(item, topic)):
                    changed = True
                    continue
                # stale/qid失配 → SUSPECT：不写分、不跃迁、保持 selected（M2/N4）
                _suspect_review(topic, qid, "stale_or_qid_mismatch",
                                f"评审答案非本次提交或已过期（qid={qid}），不写分不跃迁")
                pipeline_log("select", "ok", f"评审答案待定(SUSPECT): {topic}", 0)
                changed = True
                continue
            if not fresh_answer and max_wait_minutes > 0:
                waited = wait_for_review_answer(qid, max_wait_minutes, 60)
                if waited:
                    fresh_answer, fresh_at, fverdict = _fresh_review_answer(qid, submitted_at)
            if not fresh_answer:
                # M6：--wait 0 永不标 timeout；带等待的超时也不写任何旧分
                if max_wait_minutes > 0:
                    item["status"] = "review_timeout"
                    pipeline_log("select", "error", f"终审超时: {topic}", 0)
                else:
                    # 2026-10-16 P1-1 修（四脑议会 anti-idle）：_pickup_only 且 qid
                    # 触发超过 3h 仍无答案 → stale qid 自动清理（备份→清空），下个
                    # 预算周期重新送审。2 次上限后转升级。红队 WEAKEN 对冲：重审仍
                    # 须过 Ask Studio≥85 门，不存在"自批"；review_auto_cleared 留痕。
                    if _pickup_only and _maybe_auto_clear_stale_qid(item, topic):
                        changed = True
                        continue
                    pipeline_log("select", "ok", f"已送审待答案: {topic}", 0)
                changed = True
                continue
            answer = fresh_answer
            score = parse_review_score(answer)
            # D20261017-00X KILL#6：7 天内重审必须留 log；重审分晋档
            # （新档位高于旧档位）不得自动路由，转人工确认。
            # 注：rewrite 流程旧分已清零（review_score=None），天然豁免，
            # D20261015-009 重审机制不受影响。
            _old_score = item.get("review_score")
            if _log_rescore(item, _old_score, score, qid) \
                    and _score_tier(score) > _score_tier(_old_score):
                item["status"] = "rescore_pending_confirm"
                item["rescore_pending_score"] = score
                item["rescore_pending_at"] = datetime.now(timezone.utc).isoformat()
                pipeline_log("select", "ok",
                             f"重审晋档待人工确认({_old_score}→{score}): {topic}", 0)
                changed = True
                continue
            item["review_score"] = score
            item["review_answered_at"] = fresh_at
            # 边界复核完成：清标记（无论最终去向）
            if item.pop("second_review", None) is not None:
                item.pop("boundary_hold_at", None)
                item.pop("boundary_hold_reason", None)
            # R4 跨 qid 回归检查（T7/N6）：重审分低于父分 → 归档，不再试
            _parent = item.get("review_parent_score")
            if _is_rewrite and isinstance(score, (int, float)) \
                    and isinstance(_parent, (int, float)) and score < _parent:
                item["status"] = "archived"
                item["archive_reason"] = f"rewrite_regression:{_parent}->{score}"
                pipeline_log("select", "ok",
                             f"重审退化({_parent}→{score})→归档: {topic}", 0)
                changed = True
                continue
            if score is not None and score >= REVIEW_THRESHOLD:
                item["status"] = "review_passed"
                # R1 反刷门：经重审才过的包打标，48h 真实数据单独跟踪
                if _is_rewrite:
                    item["rewrite_pass"] = True
                pipeline_log("select", "ok", f"终审通过 {score}分: {topic}", 1)
            elif (score is not None and score >= CONTROL_GROUP_MIN
                    and _in_control_group(item)):
                # D20261011-002 B-稳对照组（先于 teaser 分支判定，保证 78-84 也有
                # 20% 走完全生产链）：70-84 分中 20% 标记 control_group=True，
                # 与 >=85 同待遇进生产，供 60 天后校准阈值用。
                item["status"] = "review_passed"
                item["control_group"] = True
                pipeline_log("select", "ok", f"终审 {score}分→对照组放行: {topic}", 1)
            elif (score is not None
                    and BOUNDARY_HOLD_MIN <= score < BOUNDARY_HOLD_MAX):
                if item.get("second_review"):
                    # 独立复核回来了，但仍 <79（未达确认线）→ 归档
                    item["status"] = "archived"
                    item["archive_reason"] = (
                        f"boundary_hold_failed:second_review_{score}<79"
                        f"({BAND_RULE_REF})")
                    pipeline_log("select", "ok",
                                 f"边界复核未达79({score})→归档: {topic}", 0)
                else:
                    # D20261017-00X KILL#3：78.0-78.9 边界分不进标准 teaser，
                    # 标记 boundary-hold；24h 内无独立复核确认 >=79 则自动归档
                    #（dead_state_watchdog.check_boundary_hold 消费）。
                    item["status"] = "boundary_hold"
                    item["boundary_hold_at"] = datetime.now(timezone.utc).isoformat()
                    item["boundary_hold_reason"] = "boundary:78.0-78.9→hold待独立复核>=79"
                    pipeline_log("select", "ok",
                                 f"终审 {score}分→boundary-hold(24h待复核): {topic}", 0)
            elif score is not None and score >= TEASER_THRESHOLD:
                # D20261010-007/008：78-84（非对照组）进观众验证环，不直接判死
                item["status"] = "teaser_validation"
                item["teaser_queued_at"] = datetime.now(timezone.utc).isoformat()
                pipeline_log("select", "ok", f"终审 {score}分→teaser验证: {topic}", 1)
            else:
                # T10（2026-10-17 修）：重审多轮仍 <85 → 回 review_failed 继续改，
                # 不再静默归档；5 轮上限在 rewrite_failed_loop 入口处升级人工。
                if item.get("status") in ("rewrite_round1", "rewrite_round2"):
                    item["status"] = "review_failed"
                    item["archive_reason"] = None
                    pipeline_log("select", "ok",
                                 f"重审{score}分未过→回review_failed继续改: {topic}", 0)
                else:
                    item["status"] = "review_failed"
                pipeline_log("select", "error", f"终审未达标 {score}分: {topic}", 0)
            changed = True
        except Exception as e:
            item["status"] = "review_error"
            item["review_error"] = str(e)[:200]
            pipeline_log("select", "error", f"终审异常 {topic}: {e}", 0)
            changed = True
    if changed:
        save_queue(queue)
    return queue


def submit_jobs():
    # B' 纵深防御（2026-10-10 D20261010-003）：独立短剧冻结期间，short 格式的
    # review_passed 不提交生成。D20261010-007/009：longform（teaser GREEN 转正）
    # 不受冻结影响；teaser 本体走 teaser_validate.py 独立流程，不走本函数。
    # D20261011-002 B-稳：样本冲刺延至 YPP 截止日（2027-01-31，D20261028 YPP 自行决策）期间 short 冻结解除，
    # 以 2-3 条/天跑量；到期自动恢复以 teaser_spec_bprime.json 为准。
    BSTEADY_UNFREEZE_UNTIL = "2027-01-31"
    try:
        from datetime import date as _date
        _bsteaday = _date.today().isoformat() <= BSTEADY_UNFREEZE_UNTIL
    except Exception:
        _bsteaday = False
    try:
        from bprime_throttle import standalone_frozen
        _bprime_frozen = standalone_frozen() and not _bsteaday
    except Exception:
        _bprime_frozen = True
    queue = load_queue()
    os.makedirs(MCP_PENDING, exist_ok=True)
    n = 0
    for item in queue:
        st = item.get("status")
        if st == "review_passed" or (item.get("urgent") and st == "selected"):
            pass
        else:
            continue
        # B' 冻结只拦 short；longform（YPP 主路径）放行
        if _bprime_frozen and item.get("format", "short") != "longform":
            continue
        # 硬防护 2026-10-08：review_passed 必须有 review_score >= 85，防止状态被误写
        # D20261011-002 B-稳：对照组（control_group=True，70-84 分）豁免此门禁
        rs = item.get("review_score")
        if st == "review_passed" and not item.get("control_group") and not (
                isinstance(rs, (int, float)) and rs >= 85):
            pipeline_log("submit", "error",
                         f"拦截未达标: {item.get('topic')} review_score={rs}", 0)
            continue
        jid = "pipe-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                               uuid.uuid4().hex[:6])
        if GEN_BACKEND == "musemain":
            # 2026-10-12 统一路由：muse_or_nano（2026-10-28 起 nano 路由已下掉；
            # D20261028-006 起主 Muse 不健康时路由返回 qqbox，不再拒绝空转）。
            # muse-main 路：在途状态记在队列项上，collect_musemain_results() 轮询取回。
            # qqbox 路：本函数只记 qqbox_pending（不带 muse_job_id，不可轮询），
            # daemon 的 qqbox_fallback.py 生成后翻回 job_submitted 走原有 QC 流程。
            # 历史 nano 项的排空仍由 collect_nano_results() 处理（只轮询已标记项，不再新派）。
            try:
                import muse_or_nano as _router
                routed = _router.route("generate_video", item["prompt"], 1)
                backend = routed.get("backend", "")
                if backend == "muse-main":
                    muse_jid = routed.get("job_id", "")
                elif backend == "qqbox":
                    item["job_id"] = jid
                    item["muse_job_id"] = ""
                    item["gen_backend"] = "qqbox"
                    item["gen_attempts"] = 0
                    item.pop("router_retry_count", None)  # G4：提交成功清重试计数
                    item["status"] = "qqbox_pending"
                    item["submitted_at"] = now_iso()
                    item["qqbox_route_reason"] = routed.get("reason", "")[:200]
                    pipeline_log("submit", "working",
                                 f"主 Muse 异常，自动切 QQ box 待生成: {item.get('topic')}", 0)
                    n += 1
                    continue
                else:
                    raise RuntimeError(f"路由拒绝: {routed.get('reason', '')}")
            except Exception as e:
                # G4（2026-10-28）：瞬时异常不直接判死，回 review_passed
                # 下轮重提；router_retry_count 满 2 次才判死。审计另一备选
                # “强制走 nano”已随 nano 路由下掉而作废，不实施。
                _err = str(e).lower()
                _transient = any(m in _err for m in (
                    "ssh", "timeout", "timed out", "connection", "thread",
                    "temporary", "temporarily", "socket", "ssl", "econn",
                    "502", "503", "504"))
                _rc = int(item.get("router_retry_count", 0) or 0)
                if _transient and _rc < 2:
                    item["router_retry_count"] = _rc + 1
                    item["status"] = "review_passed"
                    item["generate_error"] = f"router transient retry {_rc + 1}: {e}"[:200]
                    pipeline_log("submit", "error",
                                 f"统一路由提交瞬时失败，第 {_rc + 1} 次回 review_passed 重提 "
                                 f"{item.get('topic')}: {e}", 0)
                else:
                    pipeline_log("submit", "error",
                                 f"统一路由提交失败 {item.get('topic')}: {e}", 0)
                    item["status"] = "generate_failed"
                    item["generate_error"] = f"router submit: {e}"[:200]
                continue
            item["job_id"] = jid
            item["muse_job_id"] = muse_jid
            item["gen_backend"] = "musemain"
            item["gen_attempts"] = 0
            item.pop("router_retry_count", None)  # G4：提交成功清重试计数
            item["status"] = "job_submitted"
            item["submitted_at"] = now_iso()
            n += 1
            continue
        # ---- fallback：旧后端（GeminiGen/GMI/Vids，经 mcp_jobs/pending + processor）----
        # 2026-10-10 起停用：GeminiGen 拒收 Karen、GMI 402 billing 失败、Vids 额度耗尽至 11-01。
        # 保留代码不删除；GEN_BACKEND 切回 "legacy" 即可恢复。
        job = {
            "job_id": jid, "job_type": "generate_video",
            "payload": {
                "prompt": item["prompt"], "title": item["title"],
                "description": item["description"],
                "pipeline": True, "topic": item["topic"],
                "review_score": item.get("review_score"),
            },
            "status": "pending", "created_at": now_iso(),
            "from": "auto-pipeline",
            "idempotency_key": f"pipe-{item['topic']}-{item.get('slot','')}",
        }
        sys.path.insert(0, "/home/hatch/data/perpetua")
        from atomic_json import atomic_write as _aw1
        _aw1(os.path.join(MCP_PENDING, jid + ".json"), job)
        item["job_id"] = jid
        item["gen_backend"] = "legacy"
        item["gen_attempts"] = 0
        item["status"] = "job_submitted"
        item["submitted_at"] = now_iso()
        n += 1
    save_queue(queue)
    pipeline_log("generate", "working" if n else "ok",
                 f"提交 {n} 个生成任务（后端={GEN_BACKEND}"
                 + (", 经 mcp_jobs/pending" if GEN_BACKEND == "legacy" else ", 经 muse-main") + ")",
                 n)
    return n


def collect_musemain_results(queue):
    """muse-main 后端：在途 job 做单次非阻塞轮询。

    完成的 → 写标准 done 文件 mcp_jobs/done/<jid>.result.json（{"status":"done","file":本机路径}），
    后续 collect_results() 原有流程（QC→上传）无缝接管。
    失败的 → 写 {"status":"error",...}，走原有"重试2次→generate_failed"逻辑。
    pending → 不动，等下一轮 collect（每 20 分钟）。
    """
    import gen_video_musemain as gvm
    changed = False
    for item in queue:
        if item.get("status") != "job_submitted" or item.get("gen_backend") != "musemain":
            continue
        muse_jid = item.get("muse_job_id")
        jid = item.get("job_id")
        if not muse_jid or not jid:
            continue
        rp = os.path.join(MCP_DONE, jid + ".result.json")
        if os.path.exists(rp):
            # G9：本地 done 已到，旧的未取回旗即失效，清掉防看门狗误报。
            if item.pop("vps_done_unfetched", None) is not None:
                item.pop("vps_done_seen_at", None)
                changed = True
            continue
        # 2026-10-16 P1-3：轮询计数（超 72 轮约 24h → 升级）
        _gen_poll_tick(item, "musemain")
        changed = True
        try:
            state, info = gvm.check(muse_jid)
        except Exception as e:
            pipeline_log("generate", "error",
                         f"muse-main 轮询异常 {item.get('topic')}: {e}", 0)
            # G9：取回失败时先经 SSH 确认 VPS 是否已 done；已 done 则标旗，
            # 清道夫此后永不翻转它（取回重试每轮继续），未 done 则纯 transient。
            try:
                _st = gvm._check_via_ssh(muse_jid)
                if str(_st.get("status", "")).lower() in (
                        "done", "completed", "succeeded"):
                    if not item.get("vps_done_unfetched"):
                        item["vps_done_unfetched"] = True
                        item["vps_done_seen_at"] = \
                            datetime.now(timezone.utc).isoformat()
                        pipeline_log("generate", "error",
                                     f"muse-main 取回失败但 VPS 已 done "
                                     f"{item.get('topic')}：标未取回不重做", 0)
            except Exception:
                pass
            continue  # transient，下轮重试
        if state == "done":
            item.pop("vps_done_unfetched", None)
            item.pop("vps_done_seen_at", None)
            _gen_poll_reset(item)
            sys.path.insert(0, "/home/hatch/data/perpetua")
            from atomic_json import atomic_write as _aw2
            _aw2(rp, {"status": "done", "file": info, "backend": "musemain",
                      "muse_job_id": muse_jid, "topic": item.get("topic")})
            pipeline_log("generate", "ok",
                         f"muse-main 取回 {item.get('topic')} → {os.path.basename(info)}", 1)
            changed = True
        elif state == "failed":
            _gen_poll_reset(item)
            sys.path.insert(0, "/home/hatch/data/perpetua")
            from atomic_json import atomic_write as _aw3
            _aw3(rp, {"status": "error", "error": info, "backend": "musemain",
                      "muse_job_id": muse_jid, "topic": item.get("topic")})
            pipeline_log("generate", "error",
                         f"muse-main 生成失败 {item.get('topic')}: {info}", 0)
            changed = True
    if changed:
        save_queue(queue)
    return changed


def _write_nano_error_done(rp, payload, raw, jid):
    """S6（2026-10-29）：写 nano error done 文件时同时把 raw 全文落盘。
    审计原问题：error done 只留 file_or_summary[:100]，raw 丢失，后续重试
    无法复核 nano 当时到底返回了什么（若实际已出片但路径解析失败，成片
    即成孤儿）。本函数把 raw 全文写到与 done 文件同目录的
    nano_raw_<jid>.txt，并在 payload 附 nano_raw_path 供人工复核/找回。
    raw 写盘失败时 fail-open：仍写 error done 文件，不丢主错误。
    注意：本函数仅服务存量排空（2026-10-28 起不再新派 nano）；error done
    文件一旦存在，下轮 collect 即跳过，故此处只做证据保全，不新增自动
    重试消费者（自动重试须另案定消费者，见实施记录限定）。"""
    from atomic_json import atomic_write as _awr
    raw_path = None
    try:
        raw_path = os.path.join(os.path.dirname(rp), "nano_raw_%s.txt" % jid)
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw or "")
    except Exception as e:
        try:
            pipeline_log("generate", "error",
                         "nano raw 落盘失败 %s: %s" % (jid, e), 0)
        except Exception:
            pass
        raw_path = None
    if raw_path:
        payload["nano_raw_path"] = raw_path
    _awr(rp, payload)
    return raw_path


def collect_nano_results(queue):
    """历史 nano 项排空轮询：只轮询已标记 gen_backend=nano 的在途项。

    2026-10-28 起不再新派 nano；本函数仅为存量项排空保留，队列中现无
    job_submitted + nano 项时即为空操作。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dispatcher_nano_bridge", "/home/hatch/data/perpetua/dispatcher_nano_bridge.py")
    _bridge = importlib.util.module_from_spec(spec)
    sys.modules["dispatcher_nano_bridge"] = _bridge
    spec.loader.exec_module(_bridge)

    changed = False
    for item in queue:
        if item.get("status") != "job_submitted" or item.get("gen_backend") != "nano":
            continue
        thread_id = item.get("nano_thread_id")
        jid = item.get("job_id")
        if not thread_id or not jid:
            continue
        rp = os.path.join(MCP_DONE, jid + ".result.json")
        if os.path.exists(rp):
            continue
        # 2026-10-16 P1-3：轮询计数（超 72 轮约 24h → 升级）
        _gen_poll_tick(item, "nano")
        changed = True
        try:
            nano = _bridge.NanoMuseClient()
            # 桥接线程自动批准 pending 的 approval 卡，避免卡在人工确认
            nano.auto_approve_pending(thread_id)
            evts = nano.events(thread_id, limit=30)
            # 找最新 assistant/tool 事件
            last = {}
            for e in reversed(evts):
                if e.get("type") in ("assistant", "tool"):
                    last = e
                    break
            if not last:
                continue  # 还没输出，等下轮
            # 检查 thread 是否还在忙
            try:
                r = nano._request("GET", f"/api/threads/{thread_id}/events?limit=1")
                thread = r.get("thread", {})
                if thread.get("busy", False) or thread.get("queued", 0):
                    continue  # 还在跑，等下轮
            except Exception:
                continue  # 保守：等下轮
            success, file_or_summary, raw = _bridge.parse_nano_result(last)
        except Exception as e:
            pipeline_log("generate", "error",
                         f"nano 轮询异常 {item.get('topic')}: {e}", 0)
            continue  # transient，下轮重试

        sys.path.insert(0, "/home/hatch/data/perpetua")
        from atomic_json import atomic_write as _aw
        if success and item.get("job_id"):
            _gen_poll_reset(item)
            # generate_video 期望文件路径
            local_path = file_or_summary.strip()
            if not (local_path and os.path.exists(local_path)):
                import re as _re
                m = _re.search(r"(/[^\s]+\.mp4)", raw)
                local_path = m.group(1) if m else ""
            if local_path and os.path.exists(local_path):
                _aw(rp, {"status": "done", "file": local_path, "backend": "nano",
                         "nano_thread_id": thread_id, "topic": item.get("topic")})
                pipeline_log("generate", "ok",
                             f"nano 取回 {item.get('topic')} → {os.path.basename(local_path)}", 1)
            else:
                # S6：error done 同时落盘 raw 全文并记 nano_raw_path。
                _raw_path = _write_nano_error_done(
                    rp, {"status": "error",
                         "error": f"nano 未返回有效文件: {file_or_summary[:100]}",
                         "backend": "nano", "topic": item.get("topic")},
                    raw, item.get("job_id"))
                if _raw_path:
                    item["nano_raw_path"] = _raw_path
                pipeline_log("generate", "error",
                             f"nano 生成无有效文件 {item.get('topic')}", 0)
        else:
            _gen_poll_reset(item)
            # S6：error done 同时落盘 raw 全文并记 nano_raw_path。
            _raw_path = _write_nano_error_done(
                rp, {"status": "error", "error": file_or_summary[:300],
                     "backend": "nano", "topic": item.get("topic")},
                raw, item.get("job_id"))
            if _raw_path:
                item["nano_raw_path"] = _raw_path
            pipeline_log("generate", "error",
                         f"nano 生成失败 {item.get('topic')}: {file_or_summary[:100]}", 0)
        changed = True
    if changed:
        save_queue(queue)
    return changed


def _beat_watchdog(name, interval_min):
    """C20（2026-10-29）：best-effort 写元看门狗 heartbeat；失败静默。"""
    try:
        from watchdog_watchdog import write_heartbeat as _ww_beat
        _ww_beat(name, interval_min)
    except Exception:
        pass


# S7（2026-10-29，空转审计第 7 条：QC 挂起拖垮整轮 collect，且无锁）。
# 核验结论（见实施记录）：属实——auto_pipeline 全文件无 flock/lock；
# pre_upload_qc 各 subprocess 有 10–300s 分项超时，但无总上限，
# 分项超时叠加可超 20 分钟 collect 间隔，下一轮并发重入会同时改队列。
# 根治两件套（均 fail-open，绝不让保护机制本身拖垮 collect）：
# 1) collect_results 入口非阻塞文件锁：已持有则本轮跳过（不改状态）；
#    锁文件放持久目录（不用 /tmp；进程退出即自动释放 flock，
#    不存在 stale 锁文件问题）。
# 2) run_qc 单条总超时 600s（审计原文口径）：超时抛 TimeoutError，
#    由既有 Q6 except 计 qc_error（<2 回 job_submitted，满 2 次 qc_failed）。
#    信号超时仅主线程可用；非主线程/无 SIGALRM 时直调（fail-open）。
#    限定：超时只中断 QC 调用路径，不保证杀掉已在跑的 ffmpeg 子进程，
#    但各子进程自带 10–300s 上限，孤儿有界；整轮总时长（上传等）
#    不在本项内，_do_upload 自带 300s 超时。
_COLLECT_LOCK_PATH = "/home/hatch/data/perpetua/collect_results.lock"
_COLLECT_LOCK_FP = None
_QC_TOTAL_TIMEOUT_S = 600


def _acquire_collect_lock(lock_path=None):
    """S7 非阻塞 collect 单飞锁。返回 True=已持有（或 fail-open 放行），
    False=另一实例持有中，本轮应跳过。lock_path 仅隔离测试注入用。"""
    global _COLLECT_LOCK_FP
    if _COLLECT_LOCK_FP is not None:
        return True  # 同进程重入：本进程已持有，不重复加锁
    path = lock_path or _COLLECT_LOCK_PATH
    try:
        fp = open(path, "w")
    except Exception as e:
        pipeline_log("qc", "error", f"collect 单飞锁文件打不开（fail-open 放行）: {e}", 0)
        return True
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        try:
            fp.close()
        except Exception:
            pass
        pipeline_log("qc", "ok", "collect 单飞锁：另一实例正在运行，本轮跳过", 0)
        return False
    except Exception as e:
        try:
            fp.close()
        except Exception:
            pass
        pipeline_log("qc", "error", f"collect 单飞锁异常（fail-open 放行）: {e}", 0)
        return True
    _COLLECT_LOCK_FP = fp
    try:
        atexit.register(_release_collect_lock)
    except Exception:
        pass
    return True


def _release_collect_lock():
    """S7：释放 collect 单飞锁（进程退出时 flock 本就会自动释放，
    此函数仅作显式清理；异常静默）。"""
    global _COLLECT_LOCK_FP
    fp = _COLLECT_LOCK_FP
    _COLLECT_LOCK_FP = None
    if fp is None:
        return
    try:
        fcntl.flock(fp, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fp.close()
    except Exception:
        pass


def _run_qc_with_timeout(run_qc, timeout_s, *args, **kwargs):
    """S7：给单条 run_qc 加总超时。超时抛 TimeoutError（Q6 计 qc_error）。
    非主线程或无 SIGALRM 时直调并记 log（fail-open）。"""
    if (timeout_s is None or timeout_s <= 0
            or threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, "SIGALRM")):
        if threading.current_thread() is not threading.main_thread():
            pipeline_log("qc", "error",
                         "QC 总超时不可用（非主线程），直调 run_qc（fail-open）", 0)
        return run_qc(*args, **kwargs)

    def _handler(signum, frame):
        raise TimeoutError(f"QC 总超时（>{timeout_s}s），按 Q6 计 qc_error 重试")

    old_handler = signal.getsignal(signal.SIGALRM)
    try:
        signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        return run_qc(*args, **kwargs)
    finally:
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
        except Exception:
            pass
        try:
            signal.signal(signal.SIGALRM, old_handler)
        except Exception:
            pass


def _import_run_qc():
    """导入 pre_upload_qc.run_qc，缺 cv2 时尝试自愈安装。

    2026-10-09 自愈补丁：VM 重启会清空 /usr/bin/python3 的 ephemeral site-packages
    （cv2 只装在那里，mcp_server/venv 下的持久副本 collect 不用），pre_upload_qc
    导入失败会导致整个 collect_results 在第一行崩掉——连自扫提交和 ready_to_upload
    重试一起死。本轮先尝试 pip 装回 cv2（~7s），装不上则返回 None：调用方跳过
    QC 相关项（job_submitted 原样保留等下一轮），其余流程照常。
    fail-closed 不变：run_qc 为 None 时绝不进入 QC→上传路径。
    """
    try:
        from pre_upload_qc import run_qc
        return run_qc
    except ImportError as e:
        pipeline_log("qc", "error",
                     f"QC 引擎导入失败(疑似 VM 重启清掉了 cv2)，尝试自愈安装: {e}", 0)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages",
             "--ignore-installed", "--no-deps", "opencv-python-headless"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            pipeline_log("qc", "error",
                         f"cv2 自愈安装失败，本轮跳过生成收集: {r.stderr[-200:]}", 0)
            return None
        from pre_upload_qc import run_qc
        pipeline_log("qc", "ok", "cv2 自愈安装成功，QC 引擎恢复", 0)
        return run_qc
    except Exception as e:
        pipeline_log("qc", "error", f"cv2 自愈异常，本轮跳过生成收集: {e}", 0)
        return None


UPLOAD_FAILED_RETRY_MIN = 60
UPLOAD_FAILED_MAX_RETRIES = 3


def _retry_upload_failed(queue):
    """2026-10-28 P0-3（D20261028-004）：upload_failed 消费者。

    审计前 upload_failed 无任何消费者且话题永久占坑。本函数每轮 collect
    扫一次，只动主链路 private 上传失败项：
    - urgent 直发项不走 private 重试（见 U2 分支：走 public 重试，
      与 urgent_upload_ready 同隐私，不得改 private 重试）；
    - 无 video_file 的项无法重试，直接转永久失败；
    - 无 upload_failed_at 的遗留项先补时间戳、本轮不动（防误判为立即重试）；
    - 失败满 60 分钟且重试 <3 次：回 ready_to_upload（下一段 ready_to_upload
      循环会调 _auto_upload_private，间隔门若拦则保持 ready_to_upload，不回
      upload_failed；门放行才真正重传）；
    - 重试满 3 次：转 upload_permanently_failed（select_topics 的 _TERMINAL
      含此状态，话题坑位立即释放），并记 inbox 升级。
    返回 (changed, actions)。不抛异常到 collect（调用方已包 try）。
    """
    now = datetime.now(timezone.utc)
    changed = False
    actions = []
    for item in queue:
        if item.get("status") != "upload_failed":
            continue
        if item.get("urgent"):
            # U2（2026-10-28，按审计结论落地，二选一取 public 重试分支）：
            # 旧代码 `continue` 裸跳，urgent 的 upload_failed 无任何消费者
            #（urgent_upload_ready 只由人工 CLI 调用，collect 不调；
            # 看门狗 TRANSIENT 也不含 upload_failed）。新分支：60 分钟
            # 退避、重试 <3 次时直接走 public 重传（与原 urgent 路径同
            # 隐私），成功置 uploaded，失败计 urgent_upload_failed_retries
            # 并保留 upload_failed；满 3 次转永久失败 + inbox 升级。
            # 本轮不回 ready_to_upload（那会改走 private，改隐私）。
            topic = item.get("topic")
            if not item.get("video_file"):
                item["status"] = "upload_permanently_failed"
                item["upload_failed_reason"] = "no_video_file"
                pipeline_log("publish", "error",
                             f"U2 永久失败（urgent 无成片）: {topic}", 0)
                changed = True
                actions.append(("urgent_permanent_no_file", topic))
                continue
            failed_at = _parse_iso_ts(item.get("upload_failed_at"))
            if failed_at is None:
                item["upload_failed_at"] = now_iso()
                changed = True
                actions.append(("urgent_stamp_missing_ts", topic))
                continue
            age_min = (now - failed_at).total_seconds() / 60.0
            if age_min < UPLOAD_FAILED_RETRY_MIN:
                continue
            retries = int(item.get("urgent_upload_failed_retries", 0) or 0)
            if retries >= UPLOAD_FAILED_MAX_RETRIES:
                item["status"] = "upload_permanently_failed"
                item["upload_failed_reason"] = "retries_exhausted"
                pipeline_log("publish", "error",
                             f"U2 永久失败（urgent public 重试 {retries} 次耗尽）: {topic}", 0)
                try:
                    notify_inbox("auto_upload_permanently_failed",
                                 f"【自动发布永久失败】{item.get('title', '')[:80]}："
                                 f"urgent public 重试 3 次耗尽，话题已释放重选",
                                 {"topic": topic, "title": item.get("title", "")})
                except Exception:
                    pass
                changed = True
                actions.append(("urgent_permanent", topic))
                continue
            item["urgent_upload_failed_retries"] = retries + 1
            item["upload_failed_at"] = now_iso()
            res = _do_upload(item["video_file"], item["title"],
                             item.get("description", ""),
                             template={"topic": item.get("topic", ""),
                                       "hook": item.get("hook", ""),
                                       "prompt": item.get("prompt", "")},
                             privacy="public")
            if _is_upload_success(res):
                item["status"] = "uploaded"
                item["upload_result"] = res[:500]
                item["uploaded_at"] = now_iso()
                item.pop("urgent_upload_failed_retries", None)
                pipeline_log("publish", "ok",
                             f"U2 urgent public 重试成功: {topic}", 1)
                actions.append(("urgent_retry_success", topic))
            else:
                pipeline_log("publish", "error",
                             f"U2 urgent public 第 {retries + 1} 次重试仍失败 "
                             f"{topic}: {res[:120]}", 0)
                actions.append(("urgent_retry_failed", topic))
            changed = True
            continue
        topic = item.get("topic")
        if not item.get("video_file"):
            item["status"] = "upload_permanently_failed"
            item["upload_failed_reason"] = "no_video_file"
            pipeline_log("publish", "error",
                         f"P0-3 永久失败（无成片）: {topic}", 0)
            changed = True
            actions.append(("permanent_no_file", topic))
            continue
        failed_at = _parse_iso_ts(item.get("upload_failed_at"))
        if failed_at is None:
            item["upload_failed_at"] = now_iso()
            changed = True
            actions.append(("stamp_missing_ts", topic))
            continue
        age_min = (now - failed_at).total_seconds() / 60.0
        if age_min < UPLOAD_FAILED_RETRY_MIN:
            continue
        retries = int(item.get("upload_failed_retries", 0) or 0)
        if retries >= UPLOAD_FAILED_MAX_RETRIES:
            item["status"] = "upload_permanently_failed"
            item["upload_failed_reason"] = "retries_exhausted"
            pipeline_log("publish", "error",
                         f"P0-3 永久失败（重试 {retries} 次耗尽）: {topic}", 0)
            try:
                notify_inbox("auto_upload_permanently_failed",
                             f"【自动发布永久失败】{item.get('title', '')[:80]}："
                             f"上传失败重试 3 次耗尽，话题已释放重选",
                             {"topic": topic,
                              "title": item.get("title", "")})
            except Exception:
                pass
            changed = True
            actions.append(("permanent", topic))
            continue
        item["upload_failed_retries"] = retries + 1
        item["upload_failed_at"] = now_iso()
        item["status"] = "ready_to_upload"
        pipeline_log("publish", "ok",
                     f"P0-3 上传失败第 {retries + 1} 次重试: {topic}", 0)
        changed = True
        actions.append(("retry_ready", topic))
    return changed, actions


def _retry_awaiting_upload_failed():
    """U3（2026-10-28，按审计结论落地，二选一取 awaiting 扫描项）：
    upload_approved 失败时只写 awaiting 条目为 upload_failed，
    pipeline 侧写的是 status==awaiting_human 的条目（全库无写入点，
    实际永不命中），故 P0-3（只扫 pipeline）永远看不到它，
    最终只会被看门狗 TTL 在 24h 后改 expired，不是重试。
    新消费者：每轮 collect 扫 awaiting 文件，upload_failed 项
    60 分钟退避、<3 次时先把状态复位为 awaiting 并落盘，再调
    upload_approved(topic) 重传 public（原路径同隐私，成功判定
    已由 U4 修为 _is_upload_success）；满 3 次转
    upload_permanently_failed + inbox 升级；无成片直接永久失败；
    无时间戳先补戳本轮不动。每次重传前重读文件，避免
    upload_approved 自身落盘覆盖本轮计数。返回 actions 列表。
    不抛异常到 collect（调用方已包 try）。"""
    actions = []
    now = datetime.now(timezone.utc)
    try:
        awaiting = _load(APPROVAL_PATH, [])
    except Exception as e:
        pipeline_log("publish", "error", f"U3 awaiting 读取失败：{e}", 0)
        return actions
    # 先处理非重传项（永久/补戳/未到退避），一次落盘
    changed = False
    for a in awaiting:
        if not isinstance(a, dict) or a.get("status") != "upload_failed":
            continue
        topic = a.get("topic")
        if not a.get("video_file"):
            a["status"] = "upload_permanently_failed"
            a["upload_failed_reason"] = "no_video_file"
            pipeline_log("publish", "error", f"U3 永久失败（awaiting 无成片）: {topic}", 0)
            changed = True
            actions.append(("awaiting_permanent_no_file", topic))
            continue
        failed_at = _parse_iso_ts(a.get("upload_failed_at"))
        if failed_at is None:
            a["upload_failed_at"] = now_iso()
            changed = True
            actions.append(("awaiting_stamp_missing_ts", topic))
            continue
        age_min = (now - failed_at).total_seconds() / 60.0
        if age_min < UPLOAD_FAILED_RETRY_MIN:
            continue
        retries = int(a.get("awaiting_upload_failed_retries", 0) or 0)
        if retries >= UPLOAD_FAILED_MAX_RETRIES:
            a["status"] = "upload_permanently_failed"
            a["upload_failed_reason"] = "retries_exhausted"
            pipeline_log("publish", "error",
                         f"U3 永久失败（awaiting 重试 {retries} 次耗尽）: {topic}", 0)
            try:
                notify_inbox("auto_upload_permanently_failed",
                             f"【自动发布永久失败】{a.get('title', '')[:80]}："
                             f"审批路径重试 3 次耗尽",
                             {"topic": topic, "title": a.get("title", "")})
            except Exception:
                pass
            changed = True
            actions.append(("awaiting_permanent", topic))
    if changed:
        try:
            _save(APPROVAL_PATH, awaiting)
        except Exception as e:
            pipeline_log("publish", "error", f"U3 awaiting 落盘失败：{e}", 0)
            return actions
    # 再逐条重传：每次重读、计次、复位 awaiting、落盘、调 upload_approved
    try:
        awaiting = _load(APPROVAL_PATH, [])
    except Exception:
        return actions
    for a in list(awaiting):
        if not isinstance(a, dict) or a.get("status") != "upload_failed":
            continue
        if not a.get("video_file"):
            continue
        failed_at = _parse_iso_ts(a.get("upload_failed_at"))
        if failed_at is None:
            continue
        age_min = (now - failed_at).total_seconds() / 60.0
        if age_min < UPLOAD_FAILED_RETRY_MIN:
            continue
        retries = int(a.get("awaiting_upload_failed_retries", 0) or 0)
        if retries >= UPLOAD_FAILED_MAX_RETRIES:
            continue
        topic = a.get("topic")
        # 重读后定位该条，计次并复位为 awaiting，落盘后再重传
        fresh = _load(APPROVAL_PATH, [])
        target = None
        for f in fresh:
            if isinstance(f, dict) and f.get("topic") == topic and f.get("status") == "upload_failed":
                target = f
                break
        if target is None:
            continue
        target["awaiting_upload_failed_retries"] = retries + 1
        target["upload_failed_at"] = now_iso()
        target["status"] = "awaiting"
        try:
            _save(APPROVAL_PATH, fresh)
        except Exception as e:
            pipeline_log("publish", "error", f"U3 awaiting 复位落盘失败：{e}", 0)
            continue
        try:
            result = upload_approved(topic)
            if result.get("ok"):
                actions.append(("awaiting_retry_success", topic))
                pipeline_log("publish", "ok", f"U3 awaiting 第 {retries + 1} 次重传成功: {topic}", 1)
            else:
                actions.append(("awaiting_retry_failed", topic))
                pipeline_log("publish", "error",
                             f"U3 awaiting 第 {retries + 1} 次重传仍失败: {topic}", 0)
        except Exception as e:
            actions.append(("awaiting_retry_error", topic))
            pipeline_log("publish", "error", f"U3 awaiting 重传异常: {topic}: {e}", 0)
    return actions


def collect_results():
    # S7（2026-10-29）：入口非阻塞单飞锁；另一实例持有中则本轮跳过，
    # 不改任何队列状态（持有轮次完成时会写 collect beat）。
    if not _acquire_collect_lock():
        return None
    # A12：本轮 qc 探针异常计数置位（含 _import_run_qc 的引擎导入/自愈心跳）。
    _QC_PROBE_TRACKING[0] = True
    _QC_PROBE_ERRORS[0] = 0
    run_qc = _import_run_qc()
    queue = load_queue()
    changed = False
    # 方案 1（2026-10-27）：认领超时清道夫先行，防新提交重蹈 claimed-but-unconsumed
    try:
        _swept, _acts = _sweep_stale_submitted(queue)
        if _swept:
            changed = True
            pipeline_log("generate", "ok", f"清道夫动作：{_acts}", 0)
    except Exception as e:
        pipeline_log("generate", "error", f"清道夫异常（不阻塞 collect）：{e}", 0)
    try:
        _swept_up, _up_acts = _retry_upload_failed(queue)
        if _swept_up:
            changed = True
            pipeline_log("publish", "ok", f"P0-3 上传失败消费者动作：{_up_acts}", 0)
    except Exception as e:
        pipeline_log("publish", "error", f"P0-3 消费者异常（不阻塞 collect）：{e}", 0)
    try:
        _aw_acts = _retry_awaiting_upload_failed()
        if _aw_acts:
            pipeline_log("publish", "ok", f"U3 审批上传失败消费者动作：{_aw_acts}", 0)
    except Exception as e:
        pipeline_log("publish", "error", f"U3 消费者异常（不阻塞 collect）：{e}", 0)
    try:
        _write_gen_capacity(queue)
    except Exception:
        pass
    # 方案 1 收尾：arena_manual 每轮打日志（消费者），待手工兜底不静默
    for _am in queue:
        if _am.get("status") == "arena_manual":
            pipeline_log("generate", "error",
                         f"arena 手工兜底待派发：{_am.get('topic')}（文件 "
                         f"{ARENA_MANUAL_DIR}/{_am.get('job_id')}.md）", 0)
            # G8：清道夫转手工时 VPS 注销失败的重试（上限 3 次）。
            # 成功则 pop muse_job_id；耗尽则 P2 升级一次后停 retry，留人工。
            if _am.get("muse_claim_supersede_pending") and _am.get("muse_job_id"):
                _rt = int(_am.get("muse_supersede_retries") or 0)
                if _rt < 3:
                    if _supersede_vps_job(_am["muse_job_id"]):
                        _am["muse_job_superseded"] = _am.pop("muse_job_id")
                        _am["muse_job_superseded_at"] = \
                            datetime.now(timezone.utc).isoformat()
                        _am.pop("muse_claim_supersede_pending", None)
                        changed = True
                        pipeline_log("generate", "ok",
                                     f"arena 手工兜底 VPS 注销补成功 "
                                     f"{_am.get('topic')}", 0)
                    else:
                        _am["muse_supersede_retries"] = _rt + 1
                        changed = True
                elif not _am.get("muse_supersede_escalated"):
                    _am["muse_supersede_escalated"] = True
                    changed = True
                    try:
                        if ga is not None:
                            ga.escalate("auto_pipeline.gen_timeout",
                                        str(_am.get("topic") or "")[:40],
                                        "muse_claim_supersede_failed",
                                        severity="P2",
                                        detail="VPS 认领注销 3 次失败，"
                                               "muse-main 后到出片可能无人认领",
                                        evidence_ts=ga.utcnow(),
                                        ttl_key="gen_timeout")
                    except Exception:
                        pass
    # 2026-10-09 自治补漏：submit 原来只在 11:00/22:00 跟选题跑，中途 review_passed 的要等数小时。
    # 每 20 分钟 collect 时扫一遍，达标即提交生成（submit_jobs 自带 ≥85 硬门禁 + 已提交的不重复）。
    # 先修复坏状态：review_passed 但无 score（历史误写）→ 打回重审。
    for item in queue:
        if item.get("status") == "review_passed" and not isinstance(
                item.get("review_score"), (int, float)):
            item["status"] = "selected"
            item["retry_reason"] = "坏状态修复：review_passed 无 score，打回重审"
            pipeline_log("submit", "error",
                         f"坏状态修复 {item.get('topic')}：无 score，打回重审", 0)
            changed = True
    if changed:
        save_queue(queue)
    n_sub = submit_jobs()
    if n_sub:
        queue = load_queue()  # submit 改了队列状态，重读
        changed = True
    # 2026-10-10：muse-main 后端在途任务轮询（单次非阻塞；完成的写 done 文件，
    # 后续原有 done 扫描→QC→上传流程接管；失败的走原有重试逻辑）
    if collect_musemain_results(queue):
        queue = load_queue()
        changed = True
    # 2026-10-12：nano 降级后端在途任务轮询（同上，写标准 done 文件后原有流程接管）
    if collect_nano_results(queue):
        queue = load_queue()
        changed = True
    # U5 消费者（2026-10-28，按审计结论落地）：uploaded_no_queue
    # 是上传已成功、入 privateq 失败的中间态，每轮 collect 补入队，
    # 成功转 uploaded_private，失败保留 video_id 继续等下轮，
    # 绝不回 ready_to_upload 重传（无 video_id 重传是 U5 原 bug）。
    for item in queue:
        if item.get("status") == "uploaded_no_queue" and item.get("video_id"):
            try:
                entry = _enqueue_private_flip(item["video_id"], item["title"],
                                              review_score=item.get("review_score"),
                                              video_file=item.get("video_file"))
                if entry.get("status") == "throttle_deferred":
                    # P5：节流拦截 → 保持 uploaded_no_queue 下轮重试，
                    # 不误置 uploaded_private（旧代码无条件置位会谎报入队成功）。
                    item["throttle_deferred_at"] = now_iso()
                    item["throttle_defer_count"] = int(item.get("throttle_defer_count", 0) or 0) + 1
                    pipeline_log("publish", "error",
                                 f"B' 节流拦截补入队，保留待下轮重试 {item['topic']}: "
                                 f"{entry.get('throttle_reason', '')}", 0)
                else:
                    item["status"] = "uploaded_private"
                    item.pop("throttle_deferred_at", None)
                    item.pop("throttle_defer_count", None)
                    pipeline_log("publish", "ok",
                                 f"补入 privateq 成功: {item['topic']} → "
                                 f"{item['video_id']}，排期 {entry.get('slot', '?')}", 1)
            except Exception as _eqe:
                pipeline_log("publish", "error",
                             f"补入 privateq 仍失败，保留 video_id 下轮再试 "
                             f"{item['topic']}: {_eqe}", 0)
            changed = True
    # 2026-10-09 新政：上一轮被间隔门禁拦下的 ready_to_upload，本轮重试
    for item in queue:
        if item.get("status") == "ready_to_upload" and item.get("video_file"):
            ok, _ = _auto_upload_private(item)
            changed = True
    for item in queue:
        if item.get("status") != "job_submitted" or not item.get("job_id"):
            continue
        jid = item["job_id"]
        rp = os.path.join(MCP_DONE, jid + ".result.json")
        if not os.path.exists(rp):
            continue
        res = _load(rp, {})
        if res.get("status") != "done":
            # 失败重试机制：最多重试 2 次，换不同的 karma 动词
            retry = item.get("retry_count", 0)
            if retry < 2:
                item["retry_count"] = retry + 1
                # 2026-10-15 修（同 QC 路径）：已过终审的不重审，直接回
                # review_passed 走重提；无 score 的（如 urgent 直发）仍走
                # selected 原流程，避免坏状态修复误伤。
                if isinstance(item.get("review_score"), (int, float)):
                    item["status"] = "review_passed"  # 生成失败重提（已过终审，不重审）
                else:
                    item["status"] = "selected"  # 打回重选，换动词重试
                item["retry_reason"] = str(res.get("error", ""))[:200]
                pipeline_log("generate", "ok",
                             f"生成失败，第 {retry+1} 次重试 {item['topic']}", 0)
            else:
                item["generate_error"] = str(res.get("error", ""))[:200]
                _handle_done_error_exhausted(item, jid)
                # 告警：连续失败需要人工看
                _queue_verb_expansion(f"生成连续失败: {item['topic']}") \
                    if 'verb' in str(res.get('error','')).lower() else None
            changed = True
            continue
        if run_qc is None:
            # Q12（2026-10-28 用户批准，按审计结论落地）：QC 引擎不可用
            # 不再静默 continue。累计 qc_engine_unavailable_count，连续
            # 3 轮仍 None → 当轮 qc_error 化，走 Q6 的重试链（看门狗 6h
            # 回 job_submitted，上限 3 次；耗尽后 Q8 24h 归档）。fail-closed
            # 不变：绝不跳过 QC 直接上传。
            _cnt = int(item.get("qc_engine_unavailable_count", 0) or 0) + 1
            item["qc_engine_unavailable_count"] = _cnt
            pipeline_log("qc", "error",
                         f"QC 引擎不可用第 {_cnt} 轮 {item['topic']}", 0)
            if _cnt >= 3:
                item["status"] = "qc_error"
                item["qc_error"] = "qc_engine_unavailable_3_rounds"
                item["qc_engine_unavailable_count"] = 0
                pipeline_log("qc", "error",
                             f"QC 引擎连续 3 轮不可用，转 qc_error {item['topic']}", 0)
            changed = True
            continue
        video = res.get("file", "")
        pp = res.get("postprocess") or {}
        final = pp.get("final_video") or video
        item["video_file"] = final
        item["status"] = "generated"
        pipeline_log("generate", "ok",
                     f"生成完成: {item['topic']} → {os.path.basename(final)}", 1)
        # QC 重生成回调：loop 检查失败时触发重新生成
        def _qc_regen(attempt):
            pipeline_log("qc", "ok",
                         f"QC 触发重生成 (attempt {attempt}) {item['topic']}", 0)
            # 标记需要重新走生成流程
            return None  # 返回 None 让 QC 标记 needs_regen，由管线统一重试

        # 2026-10-16 MoviePy 修复层：loop 不达标先试接缝修复（1次），
        # 修好继续 QC，修不好才重生成。生成性缺陷（AI畸形等）不在此修。
        def _qc_repair(video_path, similarity):
            try:
                from qc_repair import repair_loop_seam
            except ImportError as e:
                pipeline_log("qc", "error", f"qc_repair 模块缺失: {e}", 0)
                return None
            pipeline_log("qc", "ok",
                         f"QC 接缝修复尝试 {item['topic']} "
                         f"(相似度 {similarity:.3f})", 0)
            return repair_loop_seam(video_path, similarity)

        # Q12 计数复位：引擎恢复且本轮真正跑 QC 时，清掉不可用累计，
        # 避免旧计数在恢复后仍把下一轮误判为连续不可用。
        if item.get("qc_engine_unavailable_count"):
            item["qc_engine_unavailable_count"] = 0
        # Q1/Q2（2026-10-28，按审计结论落地）：QC 前 ffprobe 事前分流。
        # run_qc 默认 MAX_DUR=11s，>11s 会静默裁到 11s（Rule 8 风险），
        # 且事后 duration_match 不是唯一防线（duration 字段本身可被
        # 误写为 11）。实测 >11.5s 的 Shorts 链路条目禁调 run_qc，
        # 伪造 qc 失败结果走下方统一 QC 失败处理（needs_regen=True，
        # qc_retry<2 回 review_passed 重生成，耗尽才 qc_failed，
        # 再由 Q8 看门狗 24h 归档），不裁剪、不上传、无孤儿状态。
        # ffprobe 失败时不拦，由 run_qc 自身 fail-closed。
        # Q3-B（2026-10-29，用户拍板 D20261029-003，选项 3B）：已批的
        # 15–25s 三拍试验开条目级例外——仅当条目带 trial_15_25s 标记时，
        # 上限放宽到 25s（试验规格上限；超 25s 仍拒绝，不静默裁剪），
        # 且 run_qc 传 max_duration=25、check_loop=False（三拍试验不是
        # 循环视频，loop 硬门不适用）。未标记项仍走 11.5s 上限。
        # 试验条目尚不存在，本批只装机制，不标记任何生产条目。
        _trial_15_25s = bool(item.get("trial_15_25s"))
        _trial_ceiling = 25.0 if _trial_15_25s else 11.5
        _pre_dur = None
        try:
            import subprocess as _sp_ff, json as _js_ff
            _pr = _sp_ff.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "json", final],
                             capture_output=True, text=True, timeout=30)
            _pre_dur = float(_js_ff.loads(_pr.stdout)["format"]["duration"])
        except Exception:
            _pre_dur = None
        if _pre_dur is not None and _pre_dur > _trial_ceiling:
            qc = {"passed": False, "needs_regen": True,
                  "rejects": [f"[longform] 实测时长 {_pre_dur:.1f}s > {_trial_ceiling}s，"
                              "禁走 Shorts QC，未裁剪，待重生成"],
                  "warnings": [], "regen_used": 0, "repair_used": 0,
                  "output_file": final, "experience_score": 0}
            # 跳过 run_qc，直接走下方 qc_report 赋值 + QC 失败处理
            item["qc_report"] = {"passed": qc.get("passed"),
                                 "warnings": len(qc.get("warnings", [])),
                                 "rejects": qc.get("rejects", []),
                                 "regen_used": qc.get("regen_used", 0),
                                 "repair_used": qc.get("repair_used", 0)}
            if qc.get("needs_regen"):
                retry = item.get("qc_retry", 0)
                if retry < 2:
                    item["qc_retry"] = retry + 1
                    item["status"] = "review_passed"
                    pipeline_log("qc", "ok",
                                 f"QC 事前分流：长视频第 {retry+1} 次重生成 "
                                 f"{item['topic']}: {qc.get('rejects', [])[:1]}", 0)
                else:
                    item["status"] = "qc_failed"
                    pipeline_log("qc", "error",
                                 f"QC 事前分流：长视频重生成耗尽 {item['topic']}", 0)
            changed = True
            continue
        try:
            # S7（2026-10-29）：单条 QC 总超时 600s，超时按 Q6 计 qc_error。
            qc = _run_qc_with_timeout(
                run_qc, _QC_TOTAL_TIMEOUT_S, final, title=item["title"],
                prompt_meta={"expected_duration": item.get("duration", 8)},
                # Q3-B：试验标记项传 max_duration=25、check_loop=False；
                # 未标记项传默认值（max_duration=None→11、check_loop=True），
                # 与改前行为一致。
                max_duration=(25 if _trial_15_25s else None),
                check_loop=(not _trial_15_25s),
                regen_fn=_qc_regen, repair_fn=_qc_repair)
        except Exception as e:
            # Q6（2026-10-28 用户批准，按审计结论落地）：QC 异常不再
            # 直接写 qc_error 死状态。计数重试：qc_error_count<2 回
            # job_submitted（done 结果文件仍在，下轮可重跑 QC），满 2 次
            # 才 qc_failed；qc_error 的看门狗回流见 dead_state_watchdog
            #（与 G14 同一根治，此处不双写看门狗逻辑）。
            _ecnt = int(item.get("qc_error_count", 0) or 0) + 1
            item["qc_error_count"] = _ecnt
            item["qc_error"] = str(e)[:200]
            if _ecnt < 2:
                item["status"] = "job_submitted"
                pipeline_log("qc", "error",
                             f"QC 异常第 {_ecnt} 次，回 job_submitted 重跑 "
                             f"{item['topic']}: {e}", 0)
            else:
                item["status"] = "qc_failed"
                pipeline_log("qc", "error",
                             f"QC 异常满 2 次，转 qc_failed {item['topic']}: {e}", 0)
            changed = True
            continue
        item["qc_report"] = {"passed": qc.get("passed"),
                             "warnings": len(qc.get("warnings", [])),
                             "rejects": qc.get("rejects", []),
                             "regen_used": qc.get("regen_used", 0),
                             "repair_used": qc.get("repair_used", 0)}
        # 2026-10-16：接缝修复成功 → video_file 指向修复后文件；
        # 打 qc_repaired 标记供 48h 单独追踪（同 rewrite_pass 逻辑，防修复刷门）
        if qc.get("repair_used"):
            item["video_file"] = qc.get("output_file", item.get("video_file"))
            item["qc_repaired"] = True
            pipeline_log("qc", "ok",
                         f"接缝修复已用，输出文件更新: {item['topic']}", 0)
        if not qc.get("passed"):
            # QC 失败处理：needs_regen 说明自动修不好，需要重生成
            if qc.get("needs_regen"):
                retry = item.get("qc_retry", 0)
                if retry < 2:
                    item["qc_retry"] = retry + 1
                    # 2026-10-15 修：QC 失败是生成质量问题，不是选题问题，
                    # 该条已过 Ask Studio 终审（review_score 在），打回 selected
                    # 会进重审死循环（幂等送审+--wait 0 永读不到已存在的答案，
                    # submit 只认 review_passed/urgent+selected）。直接回
                    # review_passed 走重生成；submit 门禁（≥85/对照组）与
                    # 无 score 坏状态修复照常兜底。
                    item["status"] = "review_passed"  # 打回重生成（已过终审，不重审）
                    pipeline_log("qc", "ok",
                                 f"QC 失败，第 {retry+1} 次重生成 {item['topic']}: "
                                 f"{qc.get('rejects', [])[:1]}", 0)
                else:
                    item["status"] = "qc_failed"
                    pipeline_log("qc", "error",
                                 f"QC 失败(已重生成2次，放弃) {item['topic']}", 0)
            else:
                # Q7（2026-10-28 用户批准，按审计结论落地）：非 needs_regen
                # 的失败不再零重试即 qc_failed。统一计数器，与 needs_regen
                # 分支同一逻辑：qc_retry<2 回 review_passed 重生成，耗尽
                # 才 qc_failed（耗尽后 Q8 看门狗 24h 归档）。
                _retry = int(item.get("qc_retry", 0) or 0)
                if _retry < 2:
                    item["qc_retry"] = _retry + 1
                    item["status"] = "review_passed"
                    pipeline_log("qc", "ok",
                                 f"QC 失败（非 needs_regen），第 {_retry + 1} 次重生成 "
                                 f"{item['topic']}: {qc.get('rejects', [])[:1]}", 0)
                else:
                    item["status"] = "qc_failed"
                    pipeline_log("qc", "error", f"QC 拒绝（重生成耗尽）{item['topic']}: "
                                 f"{qc.get('rejects', [])[:2]}", 0)
            changed = True
            continue
        qc_video = qc.get("output_file") or final
        item["video_file"] = qc_video
        item["status"] = "qc_passed"
        pipeline_log("qc", "ok", f"QC 通过: {item['topic']}", 1)
        # 2026-10-09 新政：取消人工终审，QC 通过 → 自动上传 private → 到点翻 public
        item["status"] = "ready_to_upload"
        _auto_upload_private(item)
        changed = True
    if changed:
        save_queue(queue)
    # A12：轮末写 qc 探针区分心跳（有异常才写 error，0 异常不额外写）。
    _write_qc_round_summary()
    # C20（2026-10-29）：整轮完成才写 beat；挂起的轮次无 beat，元检查能发现。
    _beat_watchdog("perpetua-pipeline-collect", 20)
    return queue


def _do_upload(video, title, description, template=None, privacy="private"):
    tmpl = "" if template is None else f", template={template!r}"
    code = (
        "import sys; sys.path.insert(0, '/home/hatch/data/mcp_server');"
        "import server, json;"
        f"r = server.youtube_upload({video!r}, {title!r}, {description!r}, "
        f"tags='Karen,InstantKarma,Shorts,Comedy,Viral', language='en', ai_disclosure=True{tmpl}, privacy={privacy!r});"
        "print(json.dumps({'result': r}, ensure_ascii=False))"
    )
    # Stage 2 U1 防护（2026-10-28 用户批准）：subprocess 超时不再炸整轮
    # collect，改走 transient 文本（_auto_upload_private 的 transient 重试
    # + 同标题查重接手）；幂等墙 [blocked] 若带 video_id=，按已上传恢复，
    # 其它 [blocked]（合规/原创度门禁，无 video_id）仍原样返回失败。
    try:
        r = subprocess.run([VENV_PY, "-c", code], capture_output=True,
                           text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "[error] timeout: upload subprocess timed out after 300s"
    except Exception as e:
        return f"[error] upload subprocess failed: {str(e)[:200]}"
    out = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "{}"
    try:
        result = json.loads(out).get("result", "")
    except Exception:
        return f"[error] {r.stderr[:200]}"
    if isinstance(result, str) and result.startswith("[blocked]"):
        m = re.search(r"video_id=([\w-]{11})", result)
        if m:
            return m.group(1)
    return result


def _is_upload_success(res):
    """U4（2026-10-28，按审计结论落地）：与主链路一致的成功判定。
    旧 urgent/审批路径用 '"youtube.com" in res or "youtu.be" in res'，
    服务端校验失败文本 '[error] 上传后验证失败：... https://youtu.be/<id>'
    也含链接，会被误判为 uploaded（且不入 privateq、不翻公开，
    uploaded 在看门狗眼中还是终态）。新判定：非空、不以 '[' 开头、
    且含 11 位 video_id（链接形式或裸 id）。服务端已在返回 [error]
    前做 privacyStatus 复核，故 [error] 文本本身即复核失败信号，
    不再另调 API 复核（省配额、少一处失败点）。"""
    if not res or not isinstance(res, str):
        return False
    if res.startswith("["):
        return False
    if re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", res):
        return True
    if re.match(r"^[\w-]{11}$", res.strip()):
        return True
    return False


def _enqueue_private_flip(video_id, title, slot=None, review_score=None,
                          video_file=None):
    """加入 private_queue.json，等待到点自动翻 public。

    2026-10-09 起：档位不再写死，从 publish_slots.json 动态取下一档
    （Ask Studio 协商：工作日 23:30/05:30+1，周末 22:30/04:00+1，北京时间）。
    scheduled_at 为下一个该档位的 UTC 时间。
    review_score 存入条目，供指标异常时队列重排用。
    video_file（2026-10-10）：本地原片路径，供 gemini-semantic-review 经网页版做语义评审。
    """
    import sys
    sys.path.insert(0, "/home/hatch/data/youtube")
    from slot_config import next_slot
    from datetime import timezone, timedelta
    slot_label, target_cst = next_slot()
    slot = slot_label
    target = target_cst
    pq_path = "/home/hatch/data/youtube/private_queue.json"  # 已迁 SQLite，路径仅留作注释
    try:
        pq = queue_db.privateq_load()
    except Exception:
        pq = []
    # 幂等：同一 video_id 已在等待就不重复入队
    for e in pq:
        if e.get("video_id") == video_id and e.get("status") == "waiting":
            return e
    # P5（2026-10-28）：入队前查 B' 节流门。此前主链路从不查节流，
    # bprime_throttle 的“7 天 ≤2 条、间隔 ≥72h”对主 Shorts 不生效。
    # 不通过 → 不入队，返回 throttle_deferred 标记；调用方
    # （_auto_upload_private 与 uploaded_no_queue 补入队）保持
    # uploaded_no_queue，下轮 collect 重试（重试时 next_slot() 重新取档，
    # 即“顺延一档”，不写假排期）。节流门本身异常同样 fail-closed
    # 按不通过处理（U5 循环会重试，不丢视频）；已在等待的条目走上
    # 面的幂等复用，不重复查节流。
    try:
        import sys as _sys
        if "/home/hatch/data/perpetua" not in _sys.path:
            _sys.path.insert(0, "/home/hatch/data/perpetua")
        from bprime_throttle import throttle_allows
        _allowed, _treason = throttle_allows()
    except Exception as _te:
        _allowed, _treason = False, f"节流门检查异常，fail-closed: {_te}"
    if not _allowed:
        pipeline_log("publish", "error",
                     f"B' 节流门拦截入队 {video_id}：{_treason}，保留待下轮重试", 0)
        return {"video_id": video_id, "title": title,
                "status": "throttle_deferred", "deferred": True,
                "throttle_reason": _treason}
    # D20261015-010 R4：禁背靠背批量发出（10-13 曾 23:08/23:20 连发两条）。
    # 新 target 若距任一 waiting 条目的 scheduled_at 不足 90 分钟，顺延一档。
    # 红队修订：不做 ±2min 硬卡，只保最小间隔。
    try:
        latest = None
        for e in pq:
            if e.get("status") != "waiting" or not e.get("scheduled_at"):
                continue
            try:
                t = datetime.fromisoformat(
                    e["scheduled_at"].replace("Z", "+00:00"))
                if latest is None or t > latest:
                    latest = t
            except Exception:
                continue
        target_utc = target.astimezone(timezone.utc)
        if latest and (target_utc - latest).total_seconds() < 90 * 60:
            target_utc = latest + timedelta(minutes=90)
            target = target_utc
            slot = slot + "+90m"
    except Exception:
        pass
    entry = {"video_id": video_id, "title": title,
             "scheduled_at": target.astimezone(timezone.utc).isoformat(),
             "slot": slot, "status": "waiting",
             "review_score": review_score,
             "video_file": video_file,
             "gemini_verdict": "",
             "queued_at": now_iso(),
             "note": "2026-10-09 起取消人工终审：QC 通过后自动 private 上传，到点自动翻 public"}
    pq.append(entry)
    queue_db.privateq_save(pq)
    return entry


def _is_recovered_vid_usable(vid, queue_items, privateq_items):
    """5xx 恢复防误认（2026-10-28）：频道最近上传里同标题命中的 video_id，
    只有在未被已占视频的条目拥有、且未已在 privateq 里时才可用。
    同标题多条目并存时，误认会把别人的 video_id 写进来并重复入队。
    任一来源异常时 fail-closed 返回 False（走正常重试链，不丢视频）。
    调用方传进来的 queue_items 应只含已占视频状态的条目判断——本函数内
    以 uploaded_private/uploaded_no_queue 为占位状态过滤，待上传的本条
    （ready_to_upload）不会误挡自己。"""
    if not vid:
        return False
    try:
        # 注意：不用 `or []`——空列表子类 falsy 时会跳过迭代、掩盖读取异常。
        for it in (queue_items if queue_items is not None else []):
            if (isinstance(it, dict)
                    and it.get("status") in ("uploaded_private", "uploaded_no_queue")
                    and it.get("video_id") == vid):
                return False
        for it in (privateq_items if privateq_items is not None else []):
            if isinstance(it, dict) and it.get("video_id") == vid:
                return False
    except Exception:
        return False
    return True


def _find_recent_upload_by_title(title):
    """2026-10-16 P2-6（红队 WEAKEN 对冲）：5xx/网络错误可能已在服务端提交，
    重试前先查频道最近 5 条是否有同标题已发布，防止盲重传导致重复发布。
    返回 video_id 或 ""。"""
    import subprocess as _sp
    try:
        r = _sp.run(["python3", "/home/hatch/data/youtube/yt.py", "recent", "5"],
                    capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout) if r.stdout.strip() else []
        norm = lambda s: "".join(str(s).lower().split())
        nt = norm(title)
        for it in items:
            if not isinstance(it, dict):
                continue
            if norm(it.get("title", "")) == nt and it.get("video_id"):
                return it["video_id"]
    except Exception:
        pass
    return ""


# 网络/API 5xx 类临时错误标记（2026-10-16 P2-6：此类最多重试 2 次再终态；
# 4xx/鉴权类仍立即终态）
_TRANSIENT_UPLOAD_MARKERS = (
    "[error]", "timeout", "timed out", "connection", "temporary",
    "500", "502", "503", "504", "socket", "ssl", "econnreset", "econnrefused",
)


def _upload_gate_ok(item):
    """方案 1 收尾·staging 上传关卡：兜底后端产物须人工目视放行后才可上传。

    拦截：status=arena_manual，或 requires_fallback_approval=True 且未
    fallback_approved。nano 等自动后端正常 QC 产物不受影响。
    """
    if item.get("status") == "arena_manual":
        return False
    if item.get("requires_fallback_approval") and not item.get("fallback_approved"):
        return False
    return True


def _auto_upload_private(item):
    """2026-10-09 新政：QC 通过后自动上传为 private，到点翻 public，无人工终审。
    返回 (ok, retryable)。interval 门禁拒绝 → retryable=True，下一轮 collect 重试。
    """
    if not _upload_gate_ok(item):
        # 关卡拦截不是失败：保持原状态等人工放行，首轮打日志、后续静默防刷屏
        # Q9（2026-10-28，按审计结论落地）：首轮同时写 upload_gate_held_at，
        # 供看门狗算 24h 超时升级；已写则不覆盖（年龄从首次被拦起算）。
        if not item.get("upload_gate_held"):
            item["upload_gate_held"] = True
            item["upload_gate_held_at"] = now_iso()
            pipeline_log("publish", "error",
                         f"上传关卡拦截（待人工目视放行）: {item.get('topic')}", 0)
        elif not item.get("upload_gate_held_at"):
            item["upload_gate_held_at"] = now_iso()
        return False, False
    item.pop("upload_gate_held", None)
    item.pop("upload_gate_held_at", None)
    res = _do_upload(item["video_file"], item["title"],
                     item.get("description", ""),
                     template={"topic": item.get("topic", ""),
                               "hook": item.get("hook", ""),
                               "prompt": item.get("prompt", "")},
                     privacy="private")
    # res 形如 video_id 或 watch 链接；失败时为 [error]/[gateway:...] 文本
    ok = False
    video_id = ""
    if res and not res.startswith("["):
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", res)
        if m:
            video_id = m.group(1)
            ok = True
        elif re.match(r"^[\w-]{11}$", res.strip()):
            video_id = res.strip()
            ok = True
    if ok:
        # U5（2026-10-28，按审计结论落地）：先落 video_id 再入队。
        # 旧代码先 _enqueue_private_flip 再写 video_id/status，入队
        # 若抛错则 collect 崩、队列未保存，DB 里仍是 ready_to_upload
        # 且无 video_id，下轮重传撞幂等墙。新顺序：先写 video_id/
        # upload_result/uploaded_at 并置 uploaded_no_queue，入队
        # 包 try，成功才转 uploaded_private；失败保留 video_id，
        # 由 collect 的 uploaded_no_queue 消费者补入队，禁止无
        # video_id 重传。collect 末尾 save_queue 会落盘本轮改动。
        item["video_id"] = video_id
        item["upload_result"] = res[:500]
        item["uploaded_at"] = now_iso()
        item["status"] = "uploaded_no_queue"
        item.pop("upload_retries", None)  # 2026-10-16 P2-6：成功后清重试计数
        item.pop("upload_failed_retries", None)  # 2026-10-28 P0-3：成功后清上传失败重试计数
        item.pop("upload_failed_at", None)
        try:
            # 2026-10-09 起：档位动态取自 publish_slots.json（Ask Studio 协商）
            entry = _enqueue_private_flip(video_id, item["title"],
                                          review_score=item.get("review_score"),
                                          video_file=item.get("video_file"))
        except Exception as _eqe:
            pipeline_log("publish", "error",
                         f"上传已成功但入 privateq 失败，保留 video_id 待补入队 "
                         f"{item['topic']}: {_eqe}", 0)
            return True, False
        if entry.get("status") == "throttle_deferred":
            # P5：节流拦截 → 保持 uploaded_no_queue（U5 消费者下轮重试入队），
            # 不置 uploaded_private、不记 INTENTIONAL_PRIVATE、不发成功通知。
            item["throttle_deferred_at"] = now_iso()
            item["throttle_defer_count"] = int(item.get("throttle_defer_count", 0) or 0) + 1
            pipeline_log("publish", "error",
                         f"B' 节流拦截，保留待下轮重试 {item['topic']}: "
                         f"{entry.get('throttle_reason', '')}", 0)
            return True, False
        slot = entry.get("slot", "?")
        item["status"] = "uploaded_private"
        item.pop("throttle_deferred_at", None)
        item.pop("throttle_defer_count", None)
        # 状态机记录：进入 INTENTIONAL_PRIVATE（经跃迁门）
        try:
            import pipeline_state as ps
            ps.transition(f"yt:{video_id}", None, "INTENTIONAL_PRIVATE",
                          "auto-pipeline", "qc_pass→auto private upload",
                          idempotency_key=f"auto-priv-{video_id}")
        except Exception as e:
            pipeline_log("publish", "error",
                         f"状态机记录失败 {item['topic']}: {e}", 0)
        pipeline_log("publish", "ok",
                     f"自动上传 private 成功: {item['topic']} → {video_id}，"
                     f"排期 {slot} 到点翻 public", 1)
        qc = item.get("qc_report", {})
        notify_inbox("auto_uploaded_private",
                     f"【自动发布·Private 预传成功】\n"
                     f"标题：{item['title']}\n"
                     f"链接：https://youtu.be/{video_id}（private，频道主可见）\n"
                     f"排期：{slot} 自动翻 public\n"
                     f"QC：{'通过' if qc.get('passed') else '未知'}"
                     f"（rejects={qc.get('rejects', [])[:2]}）\n"
                     f"Ask Studio 评分：{item.get('review_score')}\n"
                     f"状态：private 待排期",
                     {"topic": item["topic"], "title": item["title"],
                      "video_id": video_id, "slot": slot,
                      "link": f"https://youtu.be/{video_id}",
                      "qc_passed": qc.get("passed"),
                      "review_score": item.get("review_score")})
        return True, False
    retryable = ("gateway:spacing" in res or "[gate1:错峰]" in res)  # 2026-10-17 修：间隔门禁真实文本是 [gate1:错峰]，旧串从不命中导致可重试拒绝被判 upload_failed 终态
    # 2026-10-16 P2-6 修（四脑议会 anti-idle）：网络异常/API 5xx 判 transient，
    # 最多重试 2 次再终态（此前直接进 upload_failed 终态）
    _rl = str(res).lower()
    _is_transient = any(m in _rl for m in _TRANSIENT_UPLOAD_MARKERS)
    if _is_transient and not retryable:
        # 红队 WEAKEN 对冲：重试前先验重——5xx 可能已在服务端提交
        _dup_vid = _find_recent_upload_by_title(item["title"])
        if _dup_vid:
            # 2026-10-28 5xx 恢复缺口修复：旧代码直接置 uploaded_private，
            # 既不入 privateq（永无翻公开消费者）、也不记状态机/发通知，
            # 且同标题误认会把别人的 video_id 写进来。改后：先验重防误认，
            # 验过置 uploaded_no_queue，交 U5 消费者下轮补入队（节流/入队/
            # 转 uploaded_private 全走已有链路）；验不过落回正常重试链
            # （≤2 次后 upload_failed → P0-3），绝不谎报成功。
            _usable = False
            try:
                _usable = _is_recovered_vid_usable(
                    _dup_vid, queue_db.pipeline_load(),
                    queue_db.privateq_load())
            except Exception:
                _usable = False
            if _usable:
                pipeline_log("publish", "ok",
                             f"上传疑似已提交（频道已见同标题 {_dup_vid}），"
                             f"验重通过，转 uploaded_no_queue 待 U5 补入队: {item['topic']}", 1)
                item["status"] = "uploaded_no_queue"
                item["video_id"] = _dup_vid
                item["upload_result"] = f"recovered:{_dup_vid}"
                item["uploaded_at"] = now_iso()
                item["recovered_from_5xx"] = True
                item.pop("upload_retries", None)
                return True, False
            pipeline_log("publish", "error",
                         f"上传疑似已提交但验重未通过（{_dup_vid} 已被占用或队列读不到），"
                         f"不按成功恢复，走重试链: {item['topic']}", 0)
        _ur = int(item.get("upload_retries", 0) or 0)
        if _ur < 2:
            item["upload_retries"] = _ur + 1
            pipeline_log("publish", "ok",
                         f"自动上传遇临时错误，下轮第{_ur + 1}次重试: {item['topic']}: {res[:100]}", 0)
            return False, True
        pipeline_log("publish", "error",
                     f"自动上传临时错误重试 2 次仍失败，转终态: {item['topic']}", 0)
    if retryable:
        pipeline_log("publish", "ok",
                     f"自动上传被间隔门禁拦下，下一轮重试: {item['topic']}", 0)
    else:
        item["status"] = "upload_failed"
        item["upload_result"] = res[:500]
        item["upload_failed_at"] = now_iso()  # 2026-10-28 P0-3：失败时间戳，供重试消费者算退避
        pipeline_log("publish", "error",
                     f"自动上传失败: {item['topic']}: {res[:120]}", 0)
        notify_inbox("auto_upload_failed",
                     f"【自动发布失败】{item['title'][:80]}：{res[:120]}",
                     {"topic": item["topic"], "title": item["title"]})
    return False, retryable


def upload_approved(topic):
    awaiting = _load(APPROVAL_PATH, [])
    target = None
    for a in awaiting:
        if (a.get("topic") == topic and a.get("status") == "awaiting"
                and a.get("video_file")):
            target = a
            break
    if not target:
        return {"ok": False, "error": f"待审批队列中没有带视频的 {topic}"}
    res = _do_upload(target["video_file"], target["title"],
                     target.get("description", ""),
                     template={"topic": target.get("topic", ""),
                               "hook": target.get("hook", ""),
                               "prompt": target.get("prompt", "")},
                     privacy="public")
    ok = _is_upload_success(res)  # U4：与主链路一致，[error]+链接不再误判成功
    target["status"] = "uploaded" if ok else "upload_failed"
    target["upload_result"] = res[:500]
    if ok:
        target["uploaded_at"] = now_iso()
    _save(APPROVAL_PATH, awaiting)
    # S5（2026-10-29）：awaiting_human 已废弃——全库无任何代码把条目写成该状态
    # （生产 0 行），此处原有的 pipeline 同步分支已删除；upload_approved 只认
    # awaiting 文件，不再假装存在一个无人写入、无人消费的孤儿状态。
    pipeline_log("publish", "ok" if ok else "error",
                 f"{'上传成功' if ok else '上传失败'}: {topic}", 1 if ok else 0)
    return {"ok": ok, "result": res[:300]}


def urgent_submit(topic, hook):
    from viral_prompt import build_viral_prompt
    try:
        pkg = build_viral_prompt(topic, hook)
    except ValueError as e:
        pipeline_log("select", "error", f"URGENT 纯度拒绝: {e}", 0)
        return {"ok": False, "error": str(e)}
    queue = load_queue()
    item = {
        "topic": f"urgent_{topic}", "hook": hook,
        "title": pkg["title"], "prompt": pkg["prompt"],
        "description": pkg.get("description", ""),
        "tags": "Karen,InstantKarma,Shorts",
        "status": "selected", "slot": "urgent",
        "urgent": True, "created_at": now_iso(),
    }
    queue.append(item)
    save_queue(queue)
    pipeline_log("select", "ok", f"URGENT 选题: {topic}（豁免终审）", 1)
    return {"ok": True, "topic": item["topic"]}


def urgent_upload_ready():
    queue = load_queue()
    changed = False
    for item in queue:
        # Q9（2026-10-28，按审计结论落地）：可视化放宽，不放行。
        # QC 通过后 collect 会立即把 status 覆写为 ready_to_upload，
        # 故 urgent 项在 qc_passed 态几乎不存在，旧匹配视而不见
        # 已转 ready_to_upload 的 urgent 被拦项。此分支只打日志
        # 可视化，绝不调 _do_upload（不绕 private 排期直接 public）。
        if (item.get("urgent") and item.get("status") == "ready_to_upload"
                and item.get("upload_gate_held")):
            pipeline_log("publish", "error",
                         f"URGENT 可视化：ready_to_upload 被关卡持有 "
                         f"（待人工目视放行，未上传）: {item.get('topic')}", 0)
            continue
        if not (item.get("urgent") and item.get("status") == "qc_passed"):
            continue
        if not _upload_gate_ok(item):
            # 关卡拦截：不标记 upload_failed，保持 qc_passed 等人工放行
            if not item.get("upload_gate_held"):
                item["upload_gate_held"] = True
                item["upload_gate_held_at"] = now_iso()
                pipeline_log("publish", "error",
                             f"URGENT 上传关卡拦截（待人工目视放行）: "
                             f"{item.get('topic')}", 0)
            elif not item.get("upload_gate_held_at"):
                item["upload_gate_held_at"] = now_iso()
            continue
        item.pop("upload_gate_held", None)
        item.pop("upload_gate_held_at", None)
        res = _do_upload(item["video_file"], item["title"],
                         item.get("description", ""),
                         template={"topic": item.get("topic", ""),
                                   "hook": item.get("hook", ""),
                                   "prompt": item.get("prompt", "")},
                         privacy="public")
        ok = _is_upload_success(res)  # U4：与主链路一致，[error]+链接不再误判成功
        item["status"] = "uploaded" if ok else "upload_failed"
        item["upload_result"] = res[:500]
        pipeline_log("publish", "ok" if ok else "error",
                     f"URGENT {'上传成功' if ok else '上传失败'}: {item['topic']}",
                     1 if ok else 0)
        changed = True
    if changed:
        save_queue(queue)


def show_status():
    queue = load_queue()
    rows = []
    for i in queue[-20:]:
        rows.append({
            "topic": i["topic"], "status": i.get("status"),
            "slot": i.get("slot"), "score": i.get("review_score"),
            "video": os.path.basename(i["video_file"]) if i.get("video_file") else None,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("select")
    p.add_argument("--n", type=int, default=2)
    p.add_argument("--slot", default="12:30")
    p = sub.add_parser("review")
    p.add_argument("--wait", type=int, default=30)
    p.add_argument("--instant-timeout", type=int, default=5,
                   help="单条即时答案等待分钟数；collect 高频轮询用 0，只提交不阻塞")
    sub.add_parser("submit")
    sub.add_parser("collect")
    p = sub.add_parser("upload")
    p.add_argument("topic")
    p = sub.add_parser("urgent")
    p.add_argument("--topic", required=True)
    p.add_argument("--hook", required=True)
    sub.add_parser("urgent-upload")
    sub.add_parser("status")
    p = sub.add_parser("run-once")
    p.add_argument("--test-topic", required=True)
    p.add_argument("--test-hook", required=True)
    args = ap.parse_args()

    if args.cmd == "select":
        sel = select_topics(n=args.n, slot=args.slot)
        print(json.dumps([{"topic": s["topic"], "title": s["title"],
                           "score": s["virality_score"]} for s in sel],
                         ensure_ascii=False, indent=2))
    elif args.cmd == "review":
        review_pending(max_wait_minutes=args.wait,
                         instant_timeout_minutes=args.instant_timeout)
        rewrite_failed_loop(instant_timeout_minutes=args.instant_timeout)  # D20261015-009：重审闭环
        show_status()
    elif args.cmd == "submit":
        print(json.dumps({"submitted": submit_jobs()}, ensure_ascii=False))
    elif args.cmd == "collect":
        collect_results()
        urgent_upload_ready()
        show_status()
    elif args.cmd == "upload":
        print(json.dumps(upload_approved(args.topic), ensure_ascii=False, indent=2))
    elif args.cmd == "urgent":
        print(json.dumps(urgent_submit(args.topic, args.hook), ensure_ascii=False))
    elif args.cmd == "urgent-upload":
        urgent_upload_ready()
        show_status()
    elif args.cmd == "status":
        show_status()
    elif args.cmd == "run-once":
        from viral_prompt import build_viral_prompt
        from dedup_check import check_duplicate
        topic, hook = args.test_topic, args.test_hook
        dup, matched, ov = check_duplicate(topic, hook)
        if dup:
            print(json.dumps({"ok": False, "reason": f"去重拦截 (重叠{ov})"}))
            sys.exit(1)
        pkg = build_viral_prompt(topic, hook)
        queue = load_queue()
        item = {"topic": f"test_{topic}", "hook": hook, "title": pkg["title"],
                "prompt": pkg["prompt"], "description": pkg.get("description", ""),
                "tags": "Karen,InstantKarma,Shorts",
                "status": "review_passed", "review_score": 99,
                "review_note": "测试模式跳过 Ask Studio",
                "slot": "test", "urgent": False, "created_at": now_iso()}
        queue.append(item)
        save_queue(queue)
        pipeline_log("select", "ok", f"测试选题: {topic}", 1)
        n = submit_jobs()
        print(json.dumps(
            {"ok": True, "submitted": n, "topic": item["topic"],
             "note": "已提交生成，等待 mcp-media-job-processor 处理后跑 collect"},
            ensure_ascii=False, indent=2))
    else:
        ap.print_help()
