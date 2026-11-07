#!/usr/bin/env python3
"""Regenerate the robot-fight film v3 — final-grab head fix (2026-11-07).

Why: v2 (job-20261107012101-d58015, 10.0s) fixed the 5.7s double-head but
STILL breaks continuity at 8.0s: in the final grab the robot has its head
back on (white head + dark faceplate visible behind Karen). The v2 rule
("never a head after 1.0s") was not enough — the generator restores a head
for the close grapple. v3 hardens the FINAL BEAT explicitly: the last
2 seconds must show the empty neck stump, no head/helmet/faceplate in ANY
shot after 1.0s including close-ups and the final grab.

Also: v2's secondary HUD line (2026-11-07 19:45:xx) still jumps backwards
(19:45:12 -> 19:45:11 -> 19:45:15 -> 19:45:09) while the CAM clock was
monotonic. v3 requires BOTH timestamp lines monotonic.

Changes to the item (same pattern as v2 regen):
  - prompt: +FINAL GRAB HARD RULE after the v2 continuity rule; HUD rule
    extended to both timestamp lines.
  - status: held_user_decision -> selected (urgent=True still set, so the
    review step skips it and submit_jobs routes it via urgent+selected).
    duration=10, slot=22:30, qc_retry=1 kept. video_file/qc_report cleared
    (v2 file stays on disk for reference, never to be uploaded).
  - hold_reason popped (v2 hold is superseded by the v3 flow).
After this script, run `python3 auto_pipeline.py submit` immediately, then
flip the item to held_user_decision at once (user ordered Gemini-first:
Gemini must pass on the local file BEFORE any private upload, so the item
must not sit job_submitted where collect would auto-upload it).
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

FINAL_GRAB_RULE = """
FINAL GRAB HARD RULE (v3, 2026-11-07 — v2 still grew the head back at 8.0s): the last 2 seconds (8.0s–10.0s) are the headless payoff — the robot lunges and wraps its arms around Karen, and the camera CLEARLY shows its EMPTY NECK STUMP with visible sparking wires where the head was. In EVERY shot after 1.0s, including close-ups, the final grab, and any reframing, the robot's neck ends in an OPEN STUMP — NO head, NO helmet, NO faceplate, NO visor on its body. If a shot would show a head on the robot, reframe it to show the stump instead. The severed head stays on the blue mat (visible in wide shots, may be out of frame in the tight final grab) and NEVER returns to the neck. A head on the neck in the final grab breaks the video exactly as it did in v2.
"""

REPLACEMENTS = [
    # 1. Append the final-grab rule right after the v2 continuity rule.
    ("a head on the neck after 1.0s breaks the video.",
     "a head on the neck after 1.0s breaks the video." + FINAL_GRAB_RULE),
    # 2. HUD: BOTH timestamp lines must count up monotonically.
    ("The HUD clock MUST count up monotonically for the whole video — never jump backwards, never repeat a timestamp",
     "BOTH HUD timestamp lines MUST count up monotonically for the whole video — the CAM clock (14:22:xx) AND the date-time line (2026-11-07 19:45:xx) — never jump backwards, never repeat a timestamp, never go 19:45:15 then 19:45:09"),
]

def main():
    items = queue_db.pipeline_load()
    for it in items:
        if it.get("topic") == "robot fight ring":
            print("before: status=%r duration=%r qc_retry=%r video_file=%r" % (
                it.get("status"), it.get("duration"), it.get("qc_retry"),
                it.get("video_file")))
            prompt = it["prompt"]
            for old, new in REPLACEMENTS:
                if old not in prompt:
                    print("REPLACEMENT NOT FOUND, aborting:", old[:80])
                    return 1
                prompt = prompt.replace(old, new, 1)
            it["prompt"] = prompt
            it["status"] = "selected"
            it.pop("video_file", None)
            it.pop("qc_report", None)
            it.pop("hold_reason", None)
            it["regen_note"] = "v3 2026-11-07 09:4x: final-grab head fix (v2 head back at 8.0s); Gemini-first hold after submit"
            queue_db.pipeline_save(items)
            break
    else:
        print("NOT FOUND: robot fight ring")
        return 1
    for it in queue_db.pipeline_load():
        if it.get("topic") == "robot fight ring":
            print("after:  status=%r duration=%r urgent=%r qc_retry=%r video_file=%r" % (
                it.get("status"), it.get("duration"), it.get("urgent"),
                it.get("qc_retry"), it.get("video_file")))
            assert it.get("status") == "selected", "status not selected"
            assert it.get("duration") == 10, "duration lost"
            assert it.get("urgent") is True, "urgent lost"
            assert "FINAL GRAB HARD RULE" in it["prompt"], "v3 rule not in prompt"
            assert it.get("video_file") is None, "stale video_file not cleared"
            print("REGEN V3 QUEUED: prompt fixed, item selected+urgent, ready to submit")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
