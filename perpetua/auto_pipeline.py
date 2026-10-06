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
    return out


def select_topics(n=2, slot="12:30"):
    from virality_score import score as vscore
    from dedup_check import check_duplicate
    from viral_prompt import build_viral_prompt

    pool = _load(SCENARIO_POOL, [])
    if not pool:
        print("scenario_pool.json 为空", file=sys.stderr)
        pipeline_log("topic_select", "error", "scenario_pool.json 为空", 0)
        return []
    trends = _trend_heat_map()
    queue = load_queue()
    used = {i["topic"] for i in queue
            if i.get("status") not in ("uploaded", "rejected", "review_failed")}
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
            pipeline_log("topic_select", "ok", f"去重拦截: {topic} (重叠{ov})", 0)
            continue
        try:
            pkg = build_viral_prompt(topic, hook,
                                     emoji_pair=tuple(sc.get("emoji_pair", ["🤖", "😂"])))
        except ValueError as e:
            pipeline_log("topic_select", "error", f"prompt 纯度拒绝 {topic}: {e}", 0)
            continue
        selected.append({
            "topic": topic, "hook": hook,
            "title": pkg["title"], "prompt": pkg["prompt"],
            "description": pkg.get("description", ""),
            "tags": "Karen,InstantKarma,Shorts,AICustomerService,Comedy",
            "virality_score": round(total, 1),
            "status": "selected", "slot": slot,
            "urgent": False, "created_at": now_iso(),
        })
    queue.extend(selected)
    save_queue(queue)
    pipeline_log("topic_select", "ok",
                 f"选中 {len(selected)} 个选题({slot}): "
                 + " / ".join(s["topic"] for s in selected), len(selected))
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
                pipeline_log("topic_select", "error", f"终审超时: {topic}", 0)
                changed = True
                continue
            fb = find_best_review_answer(qid)
            best_score = fb[1] if fb else None
            score = best_score if best_score is not None else parse_review_score(answer)
            item["review_score"] = score
            item["review_qid"] = qid
            if score is not None and score >= REVIEW_THRESHOLD:
                item["status"] = "review_passed"
                pipeline_log("topic_select", "ok", f"终审通过 {score}分: {topic}", 1)
            else:
                item["status"] = "review_failed"
                pipeline_log("topic_select", "error", f"终审未达标 {score}分: {topic}", 0)
            changed = True
        except Exception as e:
            item["status"] = "review_error"
            item["review_error"] = str(e)[:200]
            pipeline_log("topic_select", "error", f"终审异常 {topic}: {e}", 0)
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
            item["status"] = "generate_failed"
            item["generate_error"] = str(res.get("error", ""))[:200]
            pipeline_log("generate", "error", f"生成失败 {item['topic']}", 0)
            changed = True
            continue
        video = res.get("file", "")
        pp = res.get("postprocess") or {}
        final = pp.get("final_video") or video
        item["video_file"] = final
        item["status"] = "generated"
        pipeline_log("generate", "ok",
                     f"生成完成: {item['topic']} → {os.path.basename(final)}", 1)
        try:
            qc = run_qc(final, title=item["title"])
        except Exception as e:
            item["status"] = "qc_error"
            item["qc_error"] = str(e)[:200]
            pipeline_log("qc", "error", f"QC 异常 {item['topic']}: {e}", 0)
            changed = True
            continue
        item["qc_report"] = {"passed": qc.get("passed"),
                             "warnings": len(qc.get("warnings", [])),
                             "rejects": qc.get("rejects", [])}
        if not qc.get("passed"):
            item["status"] = "qc_failed"
            pipeline_log("qc", "error", f"QC 拒绝 {item['topic']}", 0)
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
        pipeline_log("pending_approval", "ok",
                     f"待人工审批: {item['topic']}", 1)
        notify_inbox("approval_needed",
                     f"【人工终审】视频已生成并通过 QC，待批准上传：{item['title'][:80]}",
                     {"topic": item["topic"], "title": item["title"],
                      "video_file": qc_video})
        changed = True
    if changed:
        save_queue(queue)
    return queue


def _do_upload(video, title, description):
    code = (
        "import sys; sys.path.insert(0, '/home/hatch/data/mcp_server');"
        "import server, json;"
        f"r = server.youtube_upload({video!r}, {title!r}, {description!r}, "
        "tags='Karen,InstantKarma,Shorts', language='en', ai_disclosure=True);"
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
                     target.get("description", ""))
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
    pipeline_log("upload", "ok" if ok else "error",
                 f"{'上传成功' if ok else '上传失败'}: {topic}", 1 if ok else 0)
    return {"ok": ok, "result": res[:300]}


def urgent_submit(topic, hook):
    from viral_prompt import build_viral_prompt
    try:
        pkg = build_viral_prompt(topic, hook)
    except ValueError as e:
        pipeline_log("topic_select", "error", f"URGENT 纯度拒绝: {e}", 0)
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
    pipeline_log("topic_select", "ok", f"URGENT 选题: {topic}（豁免终审）", 1)
    return {"ok": True, "topic": item["topic"]}


def urgent_upload_ready():
    queue = load_queue()
    changed = False
    for item in queue:
        if not (item.get("urgent") and item.get("status") == "qc_passed"):
            continue
        res = _do_upload(item["video_file"], item["title"],
                         item.get("description", ""))
        ok = "youtube.com" in res or "youtu.be" in res
        item["status"] = "uploaded" if ok else "upload_failed"
        item["upload_result"] = res[:500]
        pipeline_log("upload", "ok" if ok else "error",
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
        pipeline_log("topic_select", "ok", f"测试选题: {topic}", 1)
        n = submit_jobs()
        print(json.dumps(
            {"ok": True, "submitted": n, "topic": item["topic"],
             "note": "已提交生成，等待 mcp-media-job-processor 处理后跑 collect"},
            ensure_ascii=False, indent=2))
    else:
        ap.print_help()
