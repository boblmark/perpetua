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
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone

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


def pipeline_log(stage, status="ok", detail="", count=0):
    try:
        subprocess.run(
            ["python3", f"{BASE}/pipeline.py", "default", stage, status,
             detail[:200], str(count)],
            capture_output=True, timeout=10)
    except Exception:
        pass


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
    # D20261011-002 B-稳：60 天样本冲刺（至 2026-12-10）期间 short 冻结解除，
    # 以 2-3 条/天跑量；到期自动恢复冻结（与 submit_jobs 的解冻期一致）。
    # 2026-10-11 补：此前解冻只加在 submit_jobs，select 漏加导致冲刺 0 选题，本次补齐。
    try:
        from datetime import date as _date
        _bsteaday = _date.today().isoformat() <= "2026-12-10"
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
    _TERMINAL = {"uploaded", "rejected", "archived"}
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
            base = vs.get("total", 50) if isinstance(vs, dict) else 50
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
    """D20261011-002 B-稳对照组：topic 哈希确定性 20% 选中。"""
    import hashlib
    key = str(item.get("topic") or item.get("id") or "")
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    return (h % CONTROL_GROUP_RATIO_DEN) < CONTROL_GROUP_RATIO_NUM


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
    """N7：预算耗尽不提交。返回 True=成功扣减。"""
    cap = cap if cap is not None else dynamic_review_budget_cap()
    p = _review_budget_path()
    try:
        b = json.load(open(p, encoding="utf-8"))
    except Exception:
        b = {"used": 0}
    used = int(b.get("used", 0))
    if used + n > cap:
        return False
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


def rewrite_failed_loop():
    """重审循环：review_failed → rewrite_round1/2 → review_passed/archived。
    T1-T12 状态机（AI Studio 规格 §2），红队修订 R1/R4 已并入。"""
    from prompt_review import submit_prompt_review_instant
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("status") != "review_failed":
            continue
        topic = item.get("topic", "")
        rounds = int(item.get("rewrite_rounds", 0) or 0)
        if rounds >= 2:  # N2：最多 2 轮
            item["status"] = "archived"
            item["archive_reason"] = "rewrite_rounds_exhausted"
            pipeline_log("select", "ok", f"重审2轮未过→归档: {topic}", 0)
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
        overlap = "significant overlap" in answer.lower()
        consume = 2 if overlap else 1
        if rounds + consume > 2:
            item["status"] = "archived"
            item["archive_reason"] = "overlap_no_rounds_left"
            pipeline_log("select", "ok", f"原创重叠且轮数不足→归档: {topic}", 0)
            changed = True
            continue
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
                topic=topic, force=True, instant_timeout_minutes=5)
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


def review_pending(max_wait_minutes=30, instant_timeout_minutes=5):
    from prompt_review import (
        submit_prompt_review_instant, wait_for_review_answer,
        parse_review_score, find_best_review_answer)
    queue = load_queue()
    changed = False
    for item in queue:
        # D20261015-009：重审轮次的答案也在此捡起（rewrite_round1/2 等同 selected 流程）
        _st = item.get("status")
        _is_rewrite = _st in ("rewrite_round1", "rewrite_round2")
        if (_st != "selected" and not _is_rewrite) or item.get("urgent"):
            continue
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
                qid, answer = submit_prompt_review_instant(
                    item["prompt"], item["title"], item["description"],
                    topic=topic, instant_timeout_minutes=instant_timeout_minutes)
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
            item["review_score"] = score
            item["review_answered_at"] = fresh_at
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
            elif score is not None and score >= TEASER_THRESHOLD:
                # D20261010-007/008：78-84（非对照组）进观众验证环，不直接判死
                item["status"] = "teaser_validation"
                item["teaser_queued_at"] = datetime.now(timezone.utc).isoformat()
                pipeline_log("select", "ok", f"终审 {score}分→teaser验证: {topic}", 1)
            else:
                # T10：rewrite_round2 仍 <85 → 直接归档（轮数已用完，不回 review_failed）
                if item.get("status") == "rewrite_round2":
                    item["status"] = "archived"
                    item["archive_reason"] = f"round2_failed:{score}"
                    pipeline_log("select", "ok",
                                 f"重审第2轮 {score}分未过→归档: {topic}", 0)
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
    # D20261011-002 B-稳：60 天样本冲刺（至 2026-12-10）期间 short 冻结解除，
    # 以 2-3 条/天跑量；到期自动恢复以 teaser_spec_bprime.json 为准。
    BSTEADY_UNFREEZE_UNTIL = "2026-12-10"
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
            # 2026-10-12 统一路由：muse_or_nano 自动处理主 Muse 优先/异常降级/无 Muse 模式。
            # 不走 mcp_jobs/pending（旧 processor 已无可用供应商）；在途状态记在队列项上，
            # collect_results() 开头的 collect_musemain_results() 负责轮询取回。
            # nano 降级时：thread_id 记入 item，collect_nano_results() 轮询取回。
            try:
                import muse_or_nano as _router
                routed = _router.route("generate_video", item["prompt"], 1)
                backend = routed.get("backend", "")
                if backend == "nano":
                    item["job_id"] = jid
                    item["nano_thread_id"] = routed.get("thread_id", "")
                    item["nano_job_id"] = routed.get("job_id", "")
                    item["gen_backend"] = "nano"
                    item["gen_route_reason"] = routed.get("reason", "")[:200]
                    item["status"] = "job_submitted"
                    pipeline_log("submit", "ok",
                                 f"nano 降级提交 {item.get('topic')}: {item['gen_route_reason']}", 0)
                    continue
                elif backend == "muse-main":
                    muse_jid = routed.get("job_id", "")
                else:
                    raise RuntimeError(f"路由拒绝: {routed.get('reason', '')}")
            except Exception as e:
                pipeline_log("submit", "error",
                             f"统一路由提交失败 {item.get('topic')}: {e}", 0)
                item["status"] = "generate_failed"
                item["generate_error"] = f"router submit: {e}"[:200]
                continue
            item["job_id"] = jid
            item["muse_job_id"] = muse_jid
            item["gen_backend"] = "musemain"
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
            continue
        # 2026-10-16 P1-3：轮询计数（超 72 轮约 24h → 升级）
        _gen_poll_tick(item, "musemain")
        changed = True
        try:
            state, info = gvm.check(muse_jid)
        except Exception as e:
            pipeline_log("generate", "error",
                         f"muse-main 轮询异常 {item.get('topic')}: {e}", 0)
            continue  # transient，下轮重试
        if state == "done":
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


def collect_nano_results(queue):
    """nano 降级后端：在途 thread 做单次非阻塞轮询。

    完成的 → 写标准 done 文件 mcp_jobs/done/<jid>.result.json，
    后续 collect_results() 原有流程（QC→上传）无缝接管。
    失败的 → 写 {"status":"error",...}，走原有"重试2次→generate_failed"逻辑。
    pending → 不动，等下一轮 collect（每 20 分钟）。
    """
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
                _aw(rp, {"status": "error", "error": f"nano 未返回有效文件: {file_or_summary[:100]}",
                         "backend": "nano", "topic": item.get("topic")})
                pipeline_log("generate", "error",
                             f"nano 生成无有效文件 {item.get('topic')}", 0)
        else:
            _gen_poll_reset(item)
            _aw(rp, {"status": "error", "error": file_or_summary[:300],
                     "backend": "nano", "topic": item.get("topic")})
            pipeline_log("generate", "error",
                         f"nano 生成失败 {item.get('topic')}: {file_or_summary[:100]}", 0)
        changed = True
    if changed:
        save_queue(queue)
    return changed


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


def collect_results():
    run_qc = _import_run_qc()
    queue = load_queue()
    changed = False
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
                item["status"] = "generate_failed"
                item["generate_error"] = str(res.get("error", ""))[:200]
                pipeline_log("generate", "error",
                             f"生成失败(已重试2次，放弃) {item['topic']}", 0)
                # 告警：连续失败需要人工看
                _queue_verb_expansion(f"生成连续失败: {item['topic']}") \
                    if 'verb' in str(res.get('error','')).lower() else None
            changed = True
            continue
        if run_qc is None:
            # QC 引擎不可用（缺 cv2 且自愈失败）：本轮不碰生成完成项，
            # 保留 job_submitted 等下一轮；fail-closed，绝不跳过 QC 直接上传。
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

        try:
            qc = run_qc(final, title=item["title"],
                        prompt_meta={"expected_duration": item.get("duration", 8)},
                        regen_fn=_qc_regen, repair_fn=_qc_repair)
        except Exception as e:
            item["status"] = "qc_error"
            item["qc_error"] = str(e)[:200]
            pipeline_log("qc", "error", f"QC 异常 {item['topic']}: {e}", 0)
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
                # 非 needs_regen 的失败（如文件损坏）直接标记
                item["status"] = "qc_failed"
                pipeline_log("qc", "error", f"QC 拒绝 {item['topic']}: "
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
    r = subprocess.run([VENV_PY, "-c", code], capture_output=True,
                       text=True, timeout=300)
    out = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "{}"
    try:
        return json.loads(out).get("result", "")
    except Exception:
        return f"[error] {r.stderr[:200]}"


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


def _auto_upload_private(item):
    """2026-10-09 新政：QC 通过后自动上传为 private，到点翻 public，无人工终审。
    返回 (ok, retryable)。interval 门禁拒绝 → retryable=True，下一轮 collect 重试。
    """
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
        # 2026-10-09 起：档位动态取自 publish_slots.json（Ask Studio 协商）
        entry = _enqueue_private_flip(video_id, item["title"],
                                      review_score=item.get("review_score"),
                                      video_file=item.get("video_file"))
        slot = entry.get("slot", "?")
        item["status"] = "uploaded_private"
        item["video_id"] = video_id
        item["upload_result"] = res[:500]
        item["uploaded_at"] = now_iso()
        item.pop("upload_retries", None)  # 2026-10-16 P2-6：成功后清重试计数
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
    retryable = "gateway:spacing" in res  # 120 分钟间隔门禁 → 下一轮重试
    # 2026-10-16 P2-6 修（四脑议会 anti-idle）：网络异常/API 5xx 判 transient，
    # 最多重试 2 次再终态（此前直接进 upload_failed 终态）
    _rl = str(res).lower()
    _is_transient = any(m in _rl for m in _TRANSIENT_UPLOAD_MARKERS)
    if _is_transient and not retryable:
        # 红队 WEAKEN 对冲：重试前先验重——5xx 可能已在服务端提交
        _dup_vid = _find_recent_upload_by_title(item["title"])
        if _dup_vid:
            pipeline_log("publish", "ok",
                         f"上传疑似已提交（频道已见同标题 {_dup_vid}），按成功恢复: {item['topic']}", 1)
            item["status"] = "uploaded_private"
            item["video_id"] = _dup_vid
            item["upload_result"] = f"recovered:{_dup_vid}"
            item["uploaded_at"] = now_iso()
            item.pop("upload_retries", None)
            return True, False
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
    ok = "youtube.com" in res or "youtu.be" in res
    target["status"] = "uploaded" if ok else "upload_failed"
    target["upload_result"] = res[:500]
    if ok:
        target["uploaded_at"] = now_iso()
    _save(APPROVAL_PATH, awaiting)
    queue = load_queue()
    for item in queue:
        if item.get("topic") == topic and item.get("status") == "awaiting_human":
            item["status"] = "uploaded" if ok else "upload_failed"
            item["upload_result"] = res[:500]
    save_queue(queue)
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
        if not (item.get("urgent") and item.get("status") == "qc_passed"):
            continue
        res = _do_upload(item["video_file"], item["title"],
                         item.get("description", ""),
                         template={"topic": item.get("topic", ""),
                                   "hook": item.get("hook", ""),
                                   "prompt": item.get("prompt", "")},
                         privacy="public")
        ok = "youtube.com" in res or "youtu.be" in res
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
        rewrite_failed_loop()  # D20261015-009：重审闭环
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
