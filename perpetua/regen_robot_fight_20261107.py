#!/usr/bin/env python3
"""Regenerate the robot-fight film with a continuity fix (2026-11-07).

Why: the first generation (job-20261107010248-26f3a6, 10.0s) has a material
continuity defect Dash found by eyeballing frames:
  - 2.0s: robot correctly HEADLESS (neck stump, "SYSTEM ACTIVE")
  - 5.7s: robot has its head BACK ON ("ROUND 2") AND a severed head lies on
    the mat — TWO heads in one frame
  - 8.0s: robot has its head on again while grabbing Karen
The core concept ("headless robot keeps fighting") is broken in the second
half. The pipeline QC only rejected it on the duration metadata (my bug,
fixed separately: duration=10). Rather than ship a flawed film and hope a
gate catches it, regenerate with a hard continuity rule.

Also fixes: the CCTV HUD clock runs backwards (14:22:15 at 5.7s, 14:22:12
at 8.0s) — new rule requires monotonic timestamps.

Changes to the item:
  - prompt: +CONTINUITY HARD RULE (head never returns, one head only, HUD
    clock monotonic), beat-map timing tightened, Cast notes headless state.
  - status: review_passed -> selected (urgent=True still set, so the review
    step skips it and submit_jobs routes it via urgent+selected, no score
    needed). duration=10 kept. slot=22:30 kept.
  - video_file / qc_report cleared (stale flawed film must not be reused);
    qc_retry stays 1 (one QC failure already spent on the metadata bug).
After this script, run `python3 auto_pipeline.py submit` immediately so the
item is job_submitted before the next collect cycle.
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

CONTINUITY_RULE = """
CONTINUITY HARD RULE (head, 2026-11-07 regen fix — the first generation broke this): Karen's kick detaches the robot's head between 0.40s and 0.70s; by 1.00s the head is ON THE MAT and the robot is HEADLESS. For the ENTIRE remainder of the video (1.0s–10.0s) the robot has NO head — an empty neck stump with visible wires. There is exactly ONE head in the video and it stays on the mat. NEVER show the robot with a head on its shoulders after 1.00s. NEVER show two heads in one frame. The severed head on the mat may blink its eyes but NEVER reattaches, NEVER floats back, NEVER appears on the neck again. The robot fights on HEADLESS — that is the entire joke; a head on the neck after 1.0s breaks the video.
"""

REPLACEMENTS = [
    # 1. Insert the continuity rule right after the safety firewall.
    ("NEVER attempt spelling variants to bypass a rejected prompt.",
     "NEVER attempt spelling variants to bypass a rejected prompt." + CONTINUITY_RULE),
    # 2. Tighten the hook timing: head on the mat by 1.00s.
    ("the head detaches and flies at ~0.50s, the most emotionally charged detail",
     "the head detaches and flies off between 0.40s and 0.70s — by 1.00s the head is on the mat and the robot is headless, the most emotionally charged detail"),
    # 3. HUD clock must count up monotonically.
    ("timestamp HUD overlay in the top-LEFT corner (e.g. 'CAM 03 - 14:22:07')",
     "timestamp HUD overlay in the top-LEFT corner (e.g. 'CAM 03 - 14:22:07'). The HUD clock MUST count up monotonically for the whole video — never jump backwards, never repeat a timestamp"),
    # 4. Cast: state the headless condition explicitly.
    ("AI device: a humanoid fighting robot — white/silver humanoid, glowing visor eyes, small chest screen showing deadpan text;",
     "AI device: a humanoid fighting robot — white/silver humanoid, glowing visor eyes, small chest screen showing deadpan text; from 1.0s on it is HEADLESS (empty neck stump with visible wires, never a head on its shoulders — see CONTINUITY HARD RULE);"),
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
            # keep: urgent=True, duration=10, slot=22:30, title, qc_retry=1
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
            assert "CONTINUITY HARD RULE" in it["prompt"], "rule not in prompt"
            assert it.get("video_file") is None, "stale video_file not cleared"
            print("REGEN QUEUED: prompt fixed, item selected+urgent, ready to submit")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
