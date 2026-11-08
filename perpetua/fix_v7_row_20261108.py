"""Fix the v7 queue row after the upload script saved the wrong list object.
Upload already succeeded: video_id 3W44WW9PyBU, privacyStatus=private confirmed
server-side, privateq entry already written. This script only repairs the pipeline
row fields (video_id / upload_result / uploaded_at / status) and re-verifies
both the row and the privateq entry. Aborts without touching anything if the
row is not in the expected post-Phase-A state.
"""
import json
import sys

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

import queue_db
from auto_pipeline import now_iso

ROW_KEY = "a9c2a7aa876a48a6bf30bc912f2929e0"
V7 = "/home/hatch/data/perpetua/videos/job-20261107035155-01b02c.mp4"
VIDEO_ID = "3W44WW9PyBU"


def find_row(rows):
    for r in rows:
        if r.get("_row_key") == ROW_KEY:
            return r
    return None


rows = queue_db.pipeline_load()
item = find_row(rows)
if item is None:
    print("FATAL: queue row not found")
    sys.exit(1)
print("row now: status=%s video_file=%s video_id=%s" % (
    item.get("status"), item.get("video_file"), item.get("video_id")))
if item.get("status") != "approved" or item.get("video_file") != V7:
    print("FATAL: row is not in the expected post-Phase-A state, refusing to touch it")
    sys.exit(1)
if item.get("video_id"):
    print("FATAL: row already has a video_id=%s, refusing to overwrite" % item.get("video_id"))
    sys.exit(1)

item["video_id"] = VIDEO_ID
item["upload_result"] = "https://youtu.be/" + VIDEO_ID
item["uploaded_at"] = now_iso()
item["status"] = "uploaded_private"
item.pop("throttle_deferred_at", None)
item.pop("throttle_defer_count", None)
item["updated_at"] = now_iso()
queue_db.pipeline_save(rows)

rows2 = queue_db.pipeline_load()
it2 = find_row(rows2)
if it2 is None or it2.get("status") != "uploaded_private" or it2.get("video_id") != VIDEO_ID:
    print("FATAL: queue row re-read verification failed")
    sys.exit(1)
print("row fixed and verified: status=uploaded_private video_id=%s" % VIDEO_ID)

pq = queue_db.privateq_load()
ent = [e for e in pq if e.get("video_id") == VIDEO_ID]
if len(ent) != 1 or ent[0].get("status") != "waiting":
    print("FATAL: privateq verification failed: %s" % ent)
    sys.exit(1)
if ent[0].get("slot") != "22:30" or ent[0].get("gemini_verdict") != "pass":
    print("FATAL: privateq slot/verdict verification failed: %s" % ent)
    sys.exit(1)
print(json.dumps({
    "video_id": VIDEO_ID,
    "link": "https://youtu.be/" + VIDEO_ID,
    "slot": ent[0]["slot"],
    "scheduled_at_utc": ent[0]["scheduled_at"],
    "gemini_verdict": ent[0]["gemini_verdict"],
    "queue_status": it2["status"],
}, ensure_ascii=False))
print("DONE")
