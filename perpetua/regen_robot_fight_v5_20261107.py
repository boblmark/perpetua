#!/usr/bin/env python3
"""Regenerate the robot-fight film v5 — wide-lunge finale (2026-11-07).

Why: v4 (job-20261107020319-b72cc0, 10.0s) passed the early beats but failed
the SAME way as v1/v2 in the final grab:
  - 0.5s: kick in progress, head still on (transitional, OK).
  - 1.0s: headless, sparks at neck stump, NO head anywhere — CORRECT.
  - 2.0s: headless, NO head anywhere — CORRECT. (HUD clock 14:22:08 -> 06,
    backwards once — minor.)
  - 5.7s: headless, chest "ROUND 2", Karen laughing — CORRECT.
  - 8.0s: final grab — the head is BACK (silver helmet, red glow).
  - 9.5s: final grab — the head is BACK (silver head, blue visor).
Four generations, same failure: whenever the robot GRABS Karen in close-up,
the model restores a head. Prompt tightening on the same staging is
exhausted (v4's rule already said "in EVERY shot including close-ups and
the final grab" and it still failed). v5 REMOVES the final grab entirely
and replaces it with staging the model has rendered headless before:
a WIDE-SHOT lunge with NO body contact. The mid-video 5.5s scoop is kept
(it rendered headless in v2/v4); only the late close-up grapple goes.
The joke (head kicked off, headless robot keeps fighting) is unchanged.

Changes to the item (same pattern as v2/v3/v4 regen):
  - prompt: V4 HEAD RULE -> V5 HEAD RULE (final grab removed); FINAL GRAB
    HARD RULE -> V5 FINAL LUNGE RULE (wide shot, no contact, hard cut);
    beat-map 8.50-10.00s window -> WIDE LUNGE FINALE; 6.3-10s reaction/
    loop-out -> lunge finale, no settling; HUD rule gets an explicit
    per-second clock mapping (v4 slipped 08 -> 06 once).
  - status: held_user_decision -> selected (urgent=True, duration=10,
    slot=22:30, qc_retry=1 kept). video_file/qc_report cleared (v4 file
    stays on disk for reference, never to be uploaded).
After this script, run `python3 auto_pipeline.py submit` immediately, then
flip the item to held_user_decision at once (user ordered Gemini-first).
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

V5_HEAD_RULE = """V5 HEAD RULE (2026-11-07 — v4 failed: head came back in the close-up final grab at 8.0s/9.5s; prompt tightening on the same staging is exhausted, so the final grab is REMOVED): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot. For the ENTIRE remainder (1.0s-10.0s) the robot is HEADLESS — an empty neck stump with visible wires, in EVERY shot including close-ups. There is NO final grab in this version — the ending (8.0s-10.0s) is a WIDE-SHOT lunge with NO body contact (see V5 FINAL LUNGE RULE). NEVER show the robot with a head after 1.00s. NEVER show a severed head lying anywhere. NEVER show two heads in one frame. The robot fights on HEADLESS — that is the entire joke."""

V5_LUNGE_RULE = """V5 FINAL LUNGE RULE (2026-11-07 — v4 failed: the close-up final grab at 8.0s/9.5s made the model grow the head back, four generations in a row; the grab is REMOVED, not reworded): the last 2 seconds (8.0s–10.0s) are a WIDE SHOT ONLY — the whole ring visible, both figures full-body, NO close-up, NO zoom, NO reframing. The HEADLESS robot (empty neck stump with visible sparking wires) charges across the ring toward Karen from a distance; Karen stumbles backward toward the ropes, arms raised, face in shock. The robot NEVER touches her, NEVER wraps its arms around her, NEVER grabs her, NEVER holds her — the video hard-cuts at 10.0s on her scream with the headless robot looming in wide. NO body contact in the final 2 seconds. NO close-up grapple anywhere in the video. A head on the robot, or any grab in the final 2 seconds, breaks the video exactly as it did in v2/v4."""

REPLACEMENTS = [
    # 1. V4 HEAD RULE -> V5 HEAD RULE (final grab removed).
    ("V4 HEAD RULE (2026-11-07 — v3 failed: robot kept its head until ~2-5.7s AND a duplicate head lay on the mat from 0.5s; the 'head on the mat' beat makes the model draw TWO heads, so the floor head is REMOVED): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot. For the ENTIRE remainder (1.0s-10.0s) the robot is HEADLESS — an empty neck stump with visible wires, in EVERY shot including close-ups and the final grab. NEVER show the robot with a head after 1.00s. NEVER show a severed head lying anywhere. NEVER show two heads in one frame. The robot fights on HEADLESS — that is the entire joke.",
     V5_HEAD_RULE),
    # 2. FINAL GRAB HARD RULE -> V5 FINAL LUNGE RULE.
    ("FINAL GRAB HARD RULE (v3, 2026-11-07 — v2 still grew the head back at 8.0s): the last 2 seconds (8.0s–10.0s) are the headless payoff — the robot lunges and wraps its arms around Karen, and the camera CLEARLY shows its EMPTY NECK STUMP with visible sparking wires where the head was. In EVERY shot after 1.0s, including close-ups, the final grab, and any reframing, the robot's neck ends in an OPEN STUMP — NO head, NO helmet, NO faceplate, NO visor on its body. If a shot would show a head on the robot, reframe it to show the stump instead. There is NO severed head anywhere in the video after the kick — it flew out of the ring and is gone. The final grab shows only the headless robot (empty neck stump with wires) and Karen. A head on the neck in the final grab breaks the video exactly as it did in v2.",
     V5_LUNGE_RULE),
    # 3. Beat-map 8.50-10.00s window -> WIDE LUNGE FINALE.
    ("8.50-10.00s NO-EXIT-RUNWAY (v5.3.1): NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required.",
     "8.50-10.00s WIDE LUNGE FINALE (v5): WIDE master shot — the headless robot charges across the ring, Karen stumbles back toward the ropes, arms up, screaming; NO contact, NO grab, hard cut at 10.0s. NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required."),
    # 4. 6.3-10s REACTION + LOOP-OUT -> lunge finale, no settling.
    ("6.3-10s REACTION + LOOP-OUT (v5.3): 6.3-8.5s comic aftermath — she stands frozen mid-gesture in total comic disbelief, dangling against the ropes; digital zoom/pan to her stunned expression permitted ONLY here. 8.5-10s motion settles to frame-0 ambient level, lighting returns to baseline. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen re-entering, the headless robot advancing) — post-generation verified by loop_check.py (similarity >= 0.75).",
     "6.3-10s REACTION + LOOP-OUT (v5): 6.3-8.5s comic aftermath — she stands frozen mid-gesture in total comic disbelief, dangling against the ropes; digital zoom/pan to her stunned expression permitted ONLY here. 8.5-10s WIDE LUNGE FINALE (see V5 FINAL LUNGE RULE): motion stays high, NO settling to ambient, NO fade, hard cut at 10.0s. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen re-entering, the headless robot advancing) — post-generation verified by loop_check.py (similarity >= 0.75)."),
    # 5. HUD: explicit per-second clock mapping (v4 slipped 08 -> 06 once).
    ("timestamp HUD overlay in the top-LEFT corner showing ONLY 'CAM 03 - 14:22:07' plus a red REC dot — NO date line, NO second timestamp line. The single clock counts up by exactly 1 second per second of video (14:22:07 at 0s through 14:22:17 at 10s), never backwards, never jumping ahead.",
     "timestamp HUD overlay in the top-LEFT corner showing ONLY 'CAM 03 - 14:22:07' plus a red REC dot — NO date line, NO second timestamp line. The single clock reads exactly 14:22:07 at 0.0s, 14:22:08 at 1.0s, 14:22:09 at 2.0s, 14:22:10 at 3.0s, and so on — one second per second, reaching 14:22:17 at 10.0s — frame-accurate, never backwards, never jumping ahead. (v4 failed: 14:22:08 at 1.0s then 14:22:06 at 2.0s.)"),
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
            it["regen_note"] = "v5 2026-11-07 ~10:25: wide-lunge finale, final grab REMOVED (v4 head back 8.0s/9.5s); HUD per-second mapping; Gemini-first hold after submit"
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
            assert "V5 HEAD RULE" in it["prompt"], "v5 head rule not in prompt"
            assert "V5 FINAL LUNGE RULE" in it["prompt"], "v5 lunge rule not in prompt"
            assert "FINAL GRAB" not in it["prompt"], "stale final-grab rule remains"
            assert "wraps its arms around Karen" not in it["prompt"], "stale grab beat remains"
            assert it.get("video_file") is None, "stale video_file not cleared"
            print("REGEN V5 QUEUED: prompt redesigned, item selected+urgent, ready to submit")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
