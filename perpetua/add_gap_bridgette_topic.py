"""One-off: add Gap/Bridgette topic as status=selected (user approved 2026-10-30).
Aborts on any dedup hit (topic/title containing gap/bridgette/hiring)."""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db
from datetime import datetime, timezone

q = queue_db.pipeline_load()
for it in q:
    blob = f"{it.get('topic','')} {it.get('title','')}".lower()
    if any(k in blob for k in ("gap", "bridgette")):
        print("DEDUP HIT:", it.get("topic"), "|", it.get("title"))
        sys.exit(2)

item = {
    "topic": "gap_bridgette_hiring",
    "hook": "Karen demands a human hiring manager at Gap; the AI recruiter books her interview for 3AM and auto-rejects her on the spot.",
    "title": "\U0001f916Karen Battles Gap's AI Recruiter \u2014 Auto-Rejected in 10 Seconds\U0001f602",
    "prompt": (
        "Vertical 9:16 comedy short, about 10 seconds, photorealistic Gap clothing store. "
        "A middle-aged woman 'Karen' with a bob haircut storms up to a hiring kiosk and demands a seasonal job "
        "and a human manager. The kiosk screen shows a friendly AI recruiter named Bridgette. "
        "Beat 1: Karen slaps her resume on the counter and yells for a human. "
        "Beat 2: Bridgette cheerfully auto-screens her, schedules her interview for 3:00 AM and flags the application. "
        "Beat 3: the screen flashes REJECTED in red, Karen gasps, nearby shoppers laugh. Instant karma. "
        "Fast cuts, exaggerated facial expressions, bright store lighting, no burned-in subtitles except the kiosk screen text."
    ),
    "description": (
        "Karen walks into Gap for a holiday job and meets Bridgette, the AI recruiter. "
        "She wanted a human. She got an algorithm \u2014 and an instant rejection."
    ),
    "tags": "Karen,InstantKarma,Shorts,AICustomerService,Comedy",
    "virality_score": 0.0,
    "series": "", "series_id": "", "series_name": "",
    "status": "selected", "slot": "23:30",
    "urgent": False,
    "created_at": datetime.now(timezone.utc).isoformat(),
}
q.append(item)
queue_db.pipeline_save(q)

q2 = queue_db.pipeline_load()
found = [i for i in q2 if i.get("topic") == "gap_bridgette_hiring"]
print("items before/after:", len(q), len(q2))
print("found:", len(found), "status:", found[0].get("status") if found else None,
      "row_key:", found[0].get("_row_key") if found else None)
