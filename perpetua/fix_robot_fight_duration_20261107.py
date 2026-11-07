#!/usr/bin/env python3
"""Fix the robot-fight item's missing duration metadata (2026-11-07).

Root cause: the injected item had no `duration` field, so auto_pipeline's QC
call passed prompt_meta={"expected_duration": item.get("duration", 8)} and the
10.0s film failed duration_match (10.0 vs 8). The user-approved lemo recipe
is 10s, and the film is exactly 10.0s — the metadata was wrong, not the film.

Fix: set duration=10 (the approved value). This restores the intended check
(10.0 vs 10) and changes nothing else: every other QC gate still runs in
full on the re-run. No gate is lowered or bypassed.

Status is deliberately LEFT at review_passed (held): the next collect must
not re-run QC / auto-upload until the Gemini semantic review (pre-upload
gate in the approved package) has passed. After Gemini passes, set
status=job_submitted and the next collect re-runs the full QC; on pass it
auto-uploads private and schedules 22:30.
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

def main():
    items = queue_db.pipeline_load()
    for it in items:
        if it.get("topic") == "robot fight ring":
            print("before: duration=%r status=%r qc_retry=%r" % (
                it.get("duration"), it.get("status"), it.get("qc_retry")))
            it["duration"] = 10
            # status stays review_passed (held for Gemini review)
            queue_db.pipeline_save(items)
            break
    else:
        print("NOT FOUND: robot fight ring")
        return 1
    for it in queue_db.pipeline_load():
        if it.get("topic") == "robot fight ring":
            print("after:  duration=%r status=%r qc_retry=%r video_file=%r" % (
                it.get("duration"), it.get("status"), it.get("qc_retry"),
                it.get("video_file")))
            assert it.get("duration") == 10, "duration not persisted"
            assert it.get("status") == "review_passed", "status moved unexpectedly"
            print("FIX VERIFIED: duration=10 persisted, item held at review_passed")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
