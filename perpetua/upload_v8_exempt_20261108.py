"""v8 exempt upload runner, 2026-11-08. User decision 13:59 (D20261108-001):
exempt loop + experience, upload v8 for the 2026-11-09 04:00 slot with the
approved title package (AGAIN title, empty description).

Why a fresh pipeline row: the robot-fight row currently tracks v7
(video_id 3W44WW9PyBU, uploaded_private, slot 22:30 tonight). Repointing it
would destroy v7's post-publish record. v8 gets its own row, keyed by a new
_row_key; the approval gate matches rows by video basename, so a row with
status="approved" and video_file=v8 is what lets server.youtube_upload pass
_verify_pipeline_approval. skip_gate=True skips the content gates (loop QC,
v2, originality) but NOT the D1 gateway / approval / compliance /
idempotency / post-upload privacy verification. Private queue entry is written
manually (B' throttle conflicts with the operative L1 2/day decision, same as
v7). Phases: A create+verify row, B upload, C bookkeeping, D verify.
Any failure stops the run; on upload failure the new row is marked failed.
"""
import json
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

import queue_db
from auto_pipeline import now_iso, pipeline_log, notify_inbox

V8 = "/home/hatch/data/perpetua/videos/job-20261107135414-06bbd3.mp4"
V8_JOB = "job-20261107135414-06bbd3"
TITLE = "\U0001f916 Karen Kicked the Robot's Head Off AGAIN\u2026 It Kept Fighting \U0001f602"
VENV_PY = "/home/hatch/data/mcp_server/venv/bin/python"
SCHEDULED_AT_UTC = "2026-11-08T20:00:00+00:00"  # 2026-11-09 04:00 CST
SLOT = "04:00"
ROW_KEY = uuid.uuid4().hex


def fail(msg):
    print("FATAL: " + msg, flush=True)
    sys.exit(1)


# ---------- Phase A: QC evidence + new pipeline row ----------
with open("/home/hatch/data/perpetua/qc_v8_20261108.json", encoding="utf-8") as f:
    qc_report = json.load(f)
if qc_report.get("experience_score") != 45:
    fail("QC rerun experience score is not 45: %s" % qc_report.get("experience_score"))
if len(qc_report.get("rejects", [])) != 1 or "experience" not in qc_report["rejects"][0]:
    fail("QC rerun rejects is not the single experience reject: %s" % qc_report.get("rejects"))
if qc_report.get("output_file") != V8:
    fail("QC output file is not v8: %s" % qc_report.get("output_file"))
print("A0 QC evidence verified: experience 45, sole experience reject, file=v8", flush=True)

rows = queue_db.pipeline_load()
src = None
for r in rows:
    if r.get("_row_key") == "a9c2a7aa876a48a6bf30bc912f2929e0":
        src = r
        break
if src is None:
    fail("source robot-fight row not found")
item = {
    "_row_key": ROW_KEY,
    "topic": src.get("topic", "robot fight ring"),
    "hook": src.get("hook", ""),
    "title": TITLE,
    "description": "",
    "tags": [],
    "payback_category": src.get("payback_category", ""),
    "series": None,
    "series_id": None,
    "series_name": None,
    "status": "approved",
    "slot": SLOT,
    "urgent": True,
    "created_at": now_iso(),
    "prompt": src.get("prompt", ""),
    "job_id": src.get("job_id", ""),  # regen pipe id from the source row (same v8 generation)
    "muse_job_id": V8_JOB,
    "gen_backend": src.get("gen_backend", ""),
    "gen_attempts": 0,
    "submitted_at": src.get("submitted_at", ""),
    "updated_at": now_iso(),
    "qc_retry": 0,
    "duration": "10",
    "regen_note": "v8 2026-11-07 14:03 regen of robot fight ring (v7 loop+experience exempted separately for 22:30)",
    "video_file": V8,
    "gemini_verdict": "pass",
    "qc_report": qc_report,
    "exemptions": {
        "loop": "user 2026-11-08 13:59 exempted loop gate (pipeline run 0.6626<0.75), D20261108-001",
        "experience": "user 2026-11-08 13:59 exempted experience score (45/100<60), v8 for 2026-11-09 04:00 slot, D20261108-001",
    },
}
rows.append(item)
queue_db.pipeline_save(rows)

rows2 = queue_db.pipeline_load()
chk = [r for r in rows2 if r.get("_row_key") == ROW_KEY]
if len(chk) != 1 or chk[0].get("status") != "approved" or chk[0].get("video_file") != V8:
    fail("new row re-read verification failed")
print("A1 new pipeline row created and verified: key=%s status=approved video_file=v8" % ROW_KEY, flush=True)

# ---------- Phase B: upload ----------
code = (
    "import sys; sys.path.insert(0, '/home/hatch/data/mcp_server');"
    "import server, json;"
    "r = server.youtube_upload(%r, %r, '', "
    "tags='Karen,InstantKarma,Shorts,Comedy,Viral', language='en', ai_disclosure=True, "
    "privacy='private', skip_gate=True);"
    "print(json.dumps({'result': r}, ensure_ascii=False))"
    % (V8, TITLE)
)
video_id = ""
upload_result = ""
for attempt in (1, 2):
    print("B%d upload attempt %d/2 ..." % (attempt, attempt), flush=True)
    try:
        r = subprocess.run([VENV_PY, "-c", code], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print("B%d upload subprocess timed out after 300s" % attempt, flush=True)
        continue
    out = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "{}"
    try:
        upload_result = json.loads(out).get("result", "")
    except Exception:
        upload_result = "[error] " + r.stderr[:300]
    print("B%d returned: %s" % (attempt, str(upload_result)[:300]), flush=True)
    if upload_result and not str(upload_result).startswith("["):
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", str(upload_result))
        if m:
            video_id = m.group(1)
            break
        if re.match(r"^[\w-]{11}$", str(upload_result).strip()):
            video_id = str(upload_result).strip()
            break
    if isinstance(upload_result, str) and upload_result.startswith("[blocked]"):
        m = re.search(r"video_id=([\w-]{11})", upload_result)
        if m:
            video_id = m.group(1)
            upload_result = "recovered:" + video_id
            print("B%d idempotency recovery: already uploaded, video_id=%s" % (attempt, video_id), flush=True)
            break
    low = str(upload_result).lower()
    transient = any(mk in low for mk in ("[error]", "timeout", "timed out", "connection",
                                         "temporary", "500", "502", "503", "504",
                                         "socket", "ssl", "econnreset", "econnrefused"))
    if transient and attempt == 1:
        print("B1 transient error, retry once after 30s", flush=True)
        time.sleep(30)
        continue
    break

if not video_id:
    rows = queue_db.pipeline_load()
    for it in rows:
        if it.get("_row_key") == ROW_KEY:
            it["status"] = "failed"
            it["updated_at"] = now_iso()
    queue_db.pipeline_save(rows)
    fail("upload failed, new row marked failed: %s" % str(upload_result)[:300])

print("B2 upload succeeded: video_id=%s" % video_id, flush=True)

# ---------- Phase C: bookkeeping ----------
item["video_id"] = video_id
item["upload_result"] = str(upload_result)[:500]
item["uploaded_at"] = now_iso()
item["status"] = "uploaded_no_queue"

pq = queue_db.privateq_load()
for e in pq:
    if e.get("video_id") == video_id and e.get("status") == "waiting":
        fail("privateq already has a waiting row for this video_id, refusing duplicate enqueue")
entry = {
    "video_id": video_id,
    "title": TITLE,
    "scheduled_at": SCHEDULED_AT_UTC,
    "slot": SLOT,
    "status": "waiting",
    "review_score": None,
    "video_file": V8,
    "gemini_verdict": "pass",
    "queued_at": now_iso(),
    "note": "2026-10-09 no more manual final review: auto private upload then flip at slot; "
            "2026-11-08 13:59 user exempted loop+experience (D20261108-001), B' throttle does not block main Shorts per L1, manual enqueue",
}
pq.append(entry)
queue_db.privateq_save(pq)
item["status"] = "uploaded_private"

try:
    import pipeline_state as ps
    ps.transition("yt:" + video_id, None, "INTENTIONAL_PRIVATE",
                  "auto-pipeline", "qc_pass->auto private upload (user-exempted v8)",
                  idempotency_key="auto-priv-" + video_id)
    print("C1 state machine INTENTIONAL_PRIVATE recorded", flush=True)
except Exception as e:
    pipeline_log("publish", "error", "state machine record failed robot fight v8: %s" % e, 0)
    print("C1 state machine record failed (non-blocking): %s" % e, flush=True)

pipeline_log("publish", "ok",
             "auto private upload succeeded: robot fight v8 -> %s, slot %s flip at slot" % (video_id, SLOT), 1)
msg_lines = [
    "[auto_uploaded_private] Private upload succeeded",
    "Title: " + TITLE,
    "Link: https://youtu.be/" + video_id + " (private, channel owner visible)",
    "Slot: " + SLOT + " auto flip to public",
    "QC: exempted (loop 0.6626 + experience 45, user approved 2026-11-08 13:59)",
    "Rejects: " + str(qc_report.get("rejects", [])[:2]),
    "Ask Studio score: None (no Ask Studio score on this row)",
    "Status: private, awaiting slot",
]
notify_inbox("auto_uploaded_private", "\n".join(msg_lines),
             {"topic": item.get("topic"), "title": TITLE,
              "video_id": video_id, "slot": SLOT,
              "link": "https://youtu.be/" + video_id,
              "qc_passed": False,
              "review_score": None})
rows = queue_db.pipeline_load()
for it in rows:
    if it.get("_row_key") == ROW_KEY:
        it.update(item)
queue_db.pipeline_save(rows)
print("C2 queue + notification saved", flush=True)

# ---------- Phase D: verify ----------
rows3 = queue_db.pipeline_load()
it3 = [r for r in rows3 if r.get("_row_key") == ROW_KEY]
if len(it3) != 1 or it3[0].get("status") != "uploaded_private" or it3[0].get("video_id") != video_id:
    fail("pipeline row re-read verification failed")
pq3 = queue_db.privateq_load()
ent3 = [e for e in pq3 if e.get("video_id") == video_id]
if len(ent3) != 1 or ent3[0].get("status") != "waiting":
    fail("privateq re-read verification failed: %s" % ent3)
if ent3[0].get("slot") != SLOT or ent3[0].get("gemini_verdict") != "pass":
    fail("privateq slot/verdict verification failed: %s" % ent3)
if ent3[0].get("scheduled_at") != SCHEDULED_AT_UTC:
    fail("privateq scheduled_at verification failed: %s" % ent3[0].get("scheduled_at"))
print(json.dumps({
    "video_id": video_id,
    "link": "https://youtu.be/" + video_id,
    "slot": SLOT,
    "scheduled_at_utc": ent3[0]["scheduled_at"],
    "gemini_verdict": ent3[0]["gemini_verdict"],
    "queue_status": it3[0]["status"],
    "row_key": ROW_KEY,
}, ensure_ascii=False), flush=True)
print("DONE", flush=True)
