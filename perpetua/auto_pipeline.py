#!/usr/bin/env python3
"""Perpetua 独立自动管线（不依赖 Marvis）。

链路：
  topic_select（趋势→打分→去重→prompt）
  → Ask Studio 终审（>=85，URGENT 豁免）
  → generate（写 mcp_jobs/pending，processor 每10min 生成+后处理）
  → collect（done → pre_upload_qc → 待审批队列）
  → 人工批准 → upload（youtube_upload 全部硬门禁）

每步写 pipeline_log（pipeline_runs.json）。状态文件：pipeline_queue.json。
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
    _json.dump(q, open(qpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
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
REVIEW_THRESHOLD = 85


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def pipeline_log(stage, status="ok", detail="", count=0):
    try:
        subprocess.run(
            ["python3", f"{BASE}/pipeline.py", "default", stage, status,
             detail[:200], str(count)],
            capture_output=True, timeout=10)
    except Exception:
        pass


def load_queue():
    return _load(QUEUE_PATH, [])


def save_queue(q):
    _save(QUEUE_PATH, q)


def notify_inbox(msg_type, message, extra=None):
    try:
        d = _load(INBOX_PATH, {})
        d.setdefault("messages", []).append({
            "type": msg_type, "message": message, "from": "auto-pipeline",
            "created_at": now_iso(), **(extra or {}),
        })
        _save(INBOX_PATH, d)
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
    used = {i["topic"] for i in queue
            if i.get("status") not in ("uploaded", "rejected", "review_failed")}
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
        except Exception:
            is_dup, matched, ov = False, None, 0
        if is_dup:
            pipeline_log("select", "ok", f"去重拦截: {topic} (重叠{ov})", 0)
            continue
        # 公式级去重（2026-10-07）：防"系列公式"滑向"套模板"。
        # 先比 device + hook（不需要 prompt），prompt 建好后再比 karma 动词。
        try:
            from formula_dedup import check_formula, fingerprint
            f_dup, f_reason, f_detail = check_formula(topic, hook, "")
            if f_dup and f_reason in ("device_collision", "hook_collision"):
                pipeline_log("select", "ok",
                             f"公式去重拦截: {topic} ({f_reason}: {f_detail.get('matched')})", 0)
                continue
        except Exception as e:
            pipeline_log("select", "error", f"公式去重异常跳过: {e}", 0)
        try:
            pkg = build_viral_prompt(topic, hook,
                                     emoji_pair=tuple(sc.get("emoji_pair", ["🤖", "😂"])))
        except ValueError as e:
            pipeline_log("select", "error", f"prompt 纯度拒绝 {topic}: {e}", 0)
            continue
        # prompt 建好后：检查 karma 动词 30 天内是否用过，撞了就换动词重建
        try:
            from formula_dedup import check_formula as _cf2, KARMA_VERBS as _KV
            _fd, _fr, _fdet = _cf2(topic, hook, pkg["prompt"])
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
        # P1-9: 品牌系列标题加前缀（如【AI Satire】）
        brand = sc.get("brand_prefix", "")
        if brand and not title.startswith(brand):
            title = f"{brand}{title}"
        selected.append({
            "topic": topic, "hook": hook,
            "title": title, "prompt": pkg["prompt"],
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


def review_pending(max_wait_minutes=30):
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
                topic=topic, instant_timeout_minutes=5)
            if not answer:
                answer = wait_for_review_answer(qid, max_wait_minutes, 60)
            if not answer:
                item["status"] = "review_timeout"
                item["review_qid"] = qid
                pipeline_log("select", "error", f"终审超时: {topic}", 0)
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
    queue = load_queue()
    os.makedirs(MCP_PENDING, exist_ok=True)
    n = 0
    for item in queue:
        st = item.get("status")
        if st == "review_passed" or (item.get("urgent") and st == "selected"):
            pass
        else:
            continue
        jid = "pipe-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                               uuid.uuid4().hex[:6])
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
        with open(os.path.join(MCP_PENDING, jid + ".json"), "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
        item["job_id"] = jid
        item["status"] = "job_submitted"
        item["submitted_at"] = now_iso()
        n += 1
    save_queue(queue)
    pipeline_log("generate", "working" if n else "ok",
                 f"提交 {n} 个生成任务到 mcp_jobs/pending", n)
    return n


def collect_results():
    from pre_upload_qc import run_qc
    queue = load_queue()
    changed = False
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
            qc = run_qc(final, title=item["title"], regen_fn=_qc_regen)
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
        awaiting = _load(APPROVAL_PATH, [])
        entry = {
            "topic": item["topic"], "title": item["title"],
            "prompt": item["prompt"], "description": item["description"],
            "video_file": qc_video,
            "review_score": item.get("review_score"),
            "virality_score": item.get("virality_score"),
            "qc_passed": True, "stage": "video_ready",
            "submitted_at": now_iso(), "status": "awaiting",
            "human_approved": False, "from": "auto-pipeline",
        }
        awaiting = [a for a in awaiting
                    if not (a.get("topic") == entry["topic"]
                            and a.get("status") == "awaiting")]
        awaiting.append(entry)
        _save(APPROVAL_PATH, awaiting)
        item["status"] = "awaiting_human"
        pipeline_log("review", "ok",
                     f"待人工审批: {item['topic']}", 1)
        notify_inbox("approval_needed",
                     f"【人工终审】视频已生成并通过 QC，待批准上传：{item['title'][:80]}",
                     {"topic": item["topic"], "title": item["title"],
                      "video_file": qc_video})
        changed = True
    if changed:
        save_queue(queue)
    return queue


def _do_upload(video, title, description, template=None):
    tmpl = "" if template is None else f", template={template!r}"
    code = (
        "import sys; sys.path.insert(0, '/home/hatch/data/mcp_server');"
        "import server, json;"
        f"r = server.youtube_upload({video!r}, {title!r}, {description!r}, "
        f"tags='Karen,InstantKarma,Shorts', language='en', ai_disclosure=True{tmpl});"
        "print(json.dumps({'result': r}, ensure_ascii=False))"
    )
    r = subprocess.run([VENV_PY, "-c", code], capture_output=True,
                       text=True, timeout=300)
    out = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "{}"
    try:
        return json.loads(out).get("result", "")
    except Exception:
        return f"[error] {r.stderr[:200]}"


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
                               "prompt": target.get("prompt", "")})
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
                                   "prompt": item.get("prompt", "")})
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
        review_pending(max_wait_minutes=args.wait)
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
