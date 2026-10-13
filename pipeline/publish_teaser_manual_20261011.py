"""用户 2026-10-11 08:53 明确批准：直接公开发布 teaser-20261010090640-b2c44d
（AI Ring Doorbell & Smart Parcel Vault），B' 限流由用户亲自豁免。
其他硬门禁（D1 间隔、jev、原创度、标题纯度、去重）照常由 youtube_upload 执行。
"""
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import sys, json, os
sys.path.insert(0, "/home/hatch/data/perpetua")
import teaser_validate as tv
import queue_db
from datetime import datetime, timezone

def _iso():
    return datetime.now(timezone.utc).isoformat()

q = queue_db.pipeline_load()
items = q if isinstance(q, list) else q.get("items", [])
target = None
for it in items:
    if it.get("job_id") == "teaser-20261010090640-b2c44d":
        target = it
        break
if not target:
    print(json.dumps({"ok": False, "error": "queue item not found"}))
    sys.exit(1)

vf = target.get("teaser_video_file")
print("uploading:", vf, flush=True)
vid = tv._upload_public(vf, target.get("title", ""), target.get("description", ""),
                        target.get("topic", ""))
if not vid:
    print(json.dumps({"ok": False, "error": "upload failed or blocked by hard gate"}))
    sys.exit(2)

target["status"] = "teaser_published"
target["teaser_video_id"] = vid
target["teaser_url"] = "https://youtu.be/" + vid
target["teaser_published_at"] = _iso()
target["bprime_override_by_user"] = "2026-10-11 08:53 CST"
tv.save_queue(q)
try:
    from bprime_throttle import record_publish
    record_publish(vid, target.get("title", ""))
except Exception as e:
    print("bprime record warn:", e)
try:
    exp = json.load(open("/home/hatch/data/perpetua/teaser_experiment.json"))
    for e in exp.get("experiments", []):
        if e.get("status") == "published":
            continue
        e["status"] = "published"; e["video_id"] = vid
        e["url"] = "https://youtu.be/" + vid; e["published_at"] = _iso()
        e["topic"] = target.get("topic", "")
        break
    atomic_write_json("/home/hatch/data/perpetua/teaser_experiment.json", exp)
except Exception as e:
    print("experiment json warn:", e)
print(json.dumps({"ok": True, "video_id": vid, "url": "https://youtu.be/" + vid,
                  "title": target.get("title", "")}, ensure_ascii=False))
