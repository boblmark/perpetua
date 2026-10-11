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
    _TERMINAL = {"uploaded", "rejected", "review_failed"}
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


def review_pending(max_wait_minutes=30, instant_timeout_minutes=5):
    from prompt_review import (
        submit_prompt_review_instant, wait_for_review_answer,
        parse_review_score, find_best_review_answer)
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("status") != "selected" or item.get("urgent"):
            continue
        topic = item["topic"]
        print(f"[review] 送审: {topic} ...", flush=True)
        try:
            qid, answer = submit_prompt_review_instant(
                item["prompt"], item["title"], item["description"],
                topic=topic, instant_timeout_minutes=instant_timeout_minutes)
            if not answer and max_wait_minutes > 0:
                answer = wait_for_review_answer(qid, max_wait_minutes, 60)
            if not answer:
                # 2026-10-10 修：--wait 0 表示只提交不等待，此时不标 timeout，
                # 保持 selected 让下一轮继续捡答案；只有真正等过才标超时。
                item["review_qid"] = qid
                # 2026-10-10 补：记录送审时间，供 dead_state_watchdog 识别"等评审中"（非卡死）
                # 2026-10-11 修：删函数内重复 import（模块 22 行已有；函数内 import 会使
                # datetime 成为全函数局部变量，answer 分支引用时 UnboundLocalError）
                item["review_triggered_at"] = datetime.now(timezone.utc).isoformat()
                if max_wait_minutes > 0:
                    item["status"] = "review_timeout"
                    pipeline_log("select", "error", f"终审超时: {topic}", 0)
                else:
                    pipeline_log("select", "ok", f"已送审待答案: {topic}", 0)
                changed = True
                continue
            fb = find_best_review_answer(qid)
            best_score = fb[1] if fb else None
            score = best_score if best_score is not None else parse_review_score(answer)
            item["review_score"] = score
            item["review_qid"] = qid
            if score is not None and score >= REVIEW_THRESHOLD:
                item["status"] = "review_passed"
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
            # 2026-10-10 主后端：dispatcher → muse-main 内置视频管线。
            # 不走 mcp_jobs/pending（旧 processor 已无可用供应商）；在途状态记在队列项上，
            # collect_results() 开头的 collect_musemain_results() 负责轮询取回。
            try:
                import gen_video_musemain as _gvm
                muse_jid = _gvm.submit(item["prompt"], jid)
            except Exception as e:
                pipeline_log("submit", "error",
                             f"muse-main 提交失败 {item.get('topic')}: {e}", 0)
                item["status"] = "generate_failed"
                item["generate_error"] = f"musemain submit: {e}"[:200]
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
        try:
            state, info = gvm.check(muse_jid)
        except Exception as e:
            pipeline_log("generate", "error",
                         f"muse-main 轮询异常 {item.get('topic')}: {e}", 0)
            continue  # transient，下轮重试
        if state == "done":
            sys.path.insert(0, "/home/hatch/data/perpetua")
            from atomic_json import atomic_write as _aw2
            _aw2(rp, {"status": "done", "file": info, "backend": "musemain",
                      "muse_job_id": muse_jid, "topic": item.get("topic")})
            pipeline_log("generate", "ok",
                         f"muse-main 取回 {item.get('topic')} → {os.path.basename(info)}", 1)
            changed = True
        elif state == "failed":
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

        try:
            qc = run_qc(final, title=item["title"],
                        prompt_meta={"expected_duration": item.get("duration", 8)},
                        regen_fn=_qc_regen)
        except Exception as e:
            item["status"] = "qc_error"
            item["qc_error"] = str(e)[:200]
            pipeline_log("qc", "error", f"QC 异常 {item['topic']}: {e}", 0)
            changed = True
            continue
        item["qc_report"] = {"passed": qc.get("passed"),
                             "warnings": len(qc.get("warnings", [])),
                             "rejects": qc.get("rejects", []),
                             "regen_used": qc.get("regen_used", 0)}
        if not qc.get("passed"):
            # QC 失败处理：needs_regen 说明自动修不好，需要重生成
            if qc.get("needs_regen"):
                retry = item.get("qc_retry", 0)
                if retry < 2:
                    item["qc_retry"] = retry + 1
                    item["status"] = "selected"  # 打回重选，重新生成
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
    from datetime import timezone
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
