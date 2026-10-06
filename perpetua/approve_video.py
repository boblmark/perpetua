#!/usr/bin/env python3
"""P0 人工终审：批准 / 驳回 awaiting_approval.json 中的待审视频。

批准后才写入 jobs/pending 生成任务；驳回记日志。

用法：
    python3 approve_video.py list                  # 列出待审
    python3 approve_video.py approve "<topic>"     # 批准
    python3 approve_video.py reject "<topic>"      # 驳回
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

APPROVAL_PATH = "/home/hatch/data/perpetua/awaiting_approval.json"
PENDING_DIR = "/home/hatch/data/perpetua/jobs/pending"


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


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def list_awaiting():
    return [a for a in _load(APPROVAL_PATH, [])
            if a.get("status") == "awaiting"]


def approve(topic):
    awaiting = _load(APPROVAL_PATH, [])
    for a in awaiting:
        if a.get("topic") == topic and a.get("status") == "awaiting":
            os.makedirs(PENDING_DIR, exist_ok=True)
            jid = "job-%s-%s" % (
                datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                uuid.uuid4().hex[:6])
            job = {
                "job_id": jid,
                "job_type": "generate_video",
                "payload": {
                    "prompt": a["prompt"],
                    "title": a["title"],
                    "description": a.get("description", ""),
                    "review_score": a.get("review_score"),
                    "review_qid": a.get("review_qid"),
                    "template_version": a.get("template_version", "v2"),
                    "human_approved": True,
                    "approved_at": now_iso(),
                },
                "status": "pending",
                "created_at": now_iso(),
                "from": "dash",
                "idempotency_key": "dash-approved-%s" % topic[:32],
            }
            with open(os.path.join(PENDING_DIR, jid + ".json"), "w",
                      encoding="utf-8") as f:
                json.dump(job, f, ensure_ascii=False, indent=2)
            a["status"] = "approved"
            a["approved_at"] = now_iso()
            a["job_id"] = jid
            _save(APPROVAL_PATH, awaiting)
            return {"ok": True, "job_id": jid, "title": a["title"]}
    return {"ok": False, "error": "topic not found in awaiting: %r" % topic}


def reject(topic, reason=""):
    awaiting = _load(APPROVAL_PATH, [])
    for a in awaiting:
        if a.get("topic") == topic and a.get("status") == "awaiting":
            a["status"] = "rejected"
            a["rejected_at"] = now_iso()
            a["reject_reason"] = reason
            _save(APPROVAL_PATH, awaiting)
            return {"ok": True, "topic": topic}
    return {"ok": False, "error": "topic not found in awaiting: %r" % topic}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        items = list_awaiting()
        print(json.dumps(
            [{"topic": a["topic"], "title": a["title"],
              "score": a.get("review_score"),
              "submitted_at": a.get("submitted_at")}
             for a in items], ensure_ascii=False, indent=2))
    elif cmd == "approve" and len(sys.argv) > 2:
        print(json.dumps(approve(sys.argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "reject" and len(sys.argv) > 2:
        print(json.dumps(reject(sys.argv[2],
                                sys.argv[3] if len(sys.argv) > 3 else ""),
                         ensure_ascii=False, indent=2))
    else:
        print(__doc__)
        sys.exit(1)
