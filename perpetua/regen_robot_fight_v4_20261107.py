#!/usr/bin/env python3
"""Regenerate the robot-fight film v4 — head-out-of-ring redesign (2026-11-07).

Why: v3 (job-20261107013913-0d0599, 10.0s) failed Dash eye-check WORSE than
v2 in the early beats:
  - 0.5s: robot STILL has its head on AND a severed head already lies on the
    mat — TWO heads in one frame.
  - 2.0s: robot STILL has its head on, severed head on the mat — TWO heads,
    robot not headless (rule required headless by 1.00s).
  - 5.7s: correctly headless, one head on mat (the only good frame).
  - 8.0s: final grab looks headless (neck stump + wires), but the damage is
    done at 0.5s/2.0s.
  - HUD: CAM clock 14:22:07->08->19->11 and date line 19:45:02->04->17->12 —
    both jump backwards. Non-monotonic again.
Root cause of the duplication: the "head on the mat" beat makes the model
draw TWO heads (one on the neck, one on the mat) — it treats them as
independent elements. v1/v2/v3 all failed the same rule three different
ways, so prompt-only tightening is exhausted: v4 REMOVES the floor head
entirely. New staging: the head flies OVER THE ROPES and OUT OF THE RING
between 0.40-0.70s and is GONE — never seen again, nowhere in the video.
The joke (head kicked off, headless robot keeps fighting) is unchanged;
only the staging changes. HUD is also simplified to a SINGLE clock line
(no date line) with an explicit 1-second-per-second count, since the model
cannot keep two timestamp lines consistent.

Changes to the item (same pattern as v2/v3 regen):
  - prompt: v4 head rule replaces the v2 continuity rule; final-grab rule
    floor-head sentence removed; beat-map hook + spatial context updated to
    head-out-of-ring; HUD simplified to one clock line.
  - status: held_user_decision -> selected (urgent=True, duration=10,
    slot=22:30, qc_retry=1 kept). video_file/qc_report cleared (v3 file
    stays on disk for reference, never to be uploaded).
After this script, run `python3 auto_pipeline.py submit` immediately, then
flip the item to held_user_decision at once (user ordered Gemini-first).
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

V4_RULE = """V4 HEAD RULE (2026-11-07 — v3 failed: robot kept its head until ~2-5.7s AND a duplicate head lay on the mat from 0.5s; the 'head on the mat' beat makes the model draw TWO heads, so the floor head is REMOVED): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot. For the ENTIRE remainder (1.0s-10.0s) the robot is HEADLESS — an empty neck stump with visible wires, in EVERY shot including close-ups and the final grab. NEVER show the robot with a head after 1.00s. NEVER show a severed head lying anywhere. NEVER show two heads in one frame. The robot fights on HEADLESS — that is the entire joke."""

REPLACEMENTS = [
    # 1. Replace the v2 continuity rule (line 1) wholesale with the v4 rule.
    ("CONTINUITY HARD RULE (head, 2026-11-07 regen fix — the first generation broke this): Karen's kick detaches the robot's head between 0.40s and 0.70s; by 1.00s the head is ON THE MAT and the robot is HEADLESS. For the ENTIRE remainder of the video (1.0s–10.0s) the robot has NO head — an empty neck stump with visible wires. There is exactly ONE head in the video and it stays on the mat. NEVER show the robot with a head on its shoulders after 1.00s. NEVER show two heads in one frame. The severed head on the mat may blink its eyes but NEVER reattaches, NEVER floats back, NEVER appears on the neck again. The robot fights on HEADLESS — that is the entire joke; a head on the neck after 1.0s breaks the video.",
     V4_RULE),
    # 2. Final-grab rule: drop the floor-head sentence.
    ("The severed head stays on the blue mat (visible in wide shots, may be out of frame in the tight final grab) and NEVER returns to the neck.",
     "There is NO severed head anywhere in the video after the kick — it flew out of the ring and is gone. The final grab shows only the headless robot (empty neck stump with wires) and Karen."),
    # 3. Beat-map hook: head out of the ring, not on the mat.
    ("by 1.00s the head is on the mat and the robot is headless, the most emotionally charged detail",
     "by 1.00s the head has flown over the ropes and out of the ring and is gone for good; the robot is headless, the most emotionally charged detail"),
    # 4. HUD: single clock line only, explicit 1s-per-1s count.
    ("timestamp HUD overlay in the top-LEFT corner (e.g. 'CAM 03 - 14:22:07'). BOTH HUD timestamp lines MUST count up monotonically for the whole video — the CAM clock (14:22:xx) AND the date-time line (2026-11-07 19:45:xx) — never jump backwards, never repeat a timestamp, never go 19:45:15 then 19:45:09.",
     "timestamp HUD overlay in the top-LEFT corner showing ONLY 'CAM 03 - 14:22:07' plus a red REC dot — NO date line, NO second timestamp line. The single clock counts up by exactly 1 second per second of video (14:22:07 at 0s through 14:22:17 at 10s), never backwards, never jumping ahead."),
    # 5. Spatial context: head flies out of the ring.
    ("Karen kicks the robot's head clean off and the head flies across the ring.",
     "Karen kicks the robot's head clean off and the head flies over the ropes and out of the ring, gone for good."),
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
            it["regen_note"] = "v4 2026-11-07 ~10:0x: head-out-of-ring redesign (v3 duplicate head + late detach); HUD single clock; Gemini-first hold after submit"
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
            assert "V4 HEAD RULE" in it["prompt"], "v4 rule not in prompt"
            assert "ON THE MAT" not in it["prompt"], "stale mat-head beat remains"
            assert it.get("video_file") is None, "stale video_file not cleared"
            print("REGEN V4 QUEUED: prompt redesigned, item selected+urgent, ready to submit")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
