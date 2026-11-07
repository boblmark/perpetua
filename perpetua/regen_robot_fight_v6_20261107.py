#!/usr/bin/env python3
"""Regenerate the robot-fight film v6 — blind-flail finale (2026-11-07).

Why: v5 (job-20261107022933-ca895a, 10.0s) passed the early beats but failed
the SAME way as v1-v4 in the final lunge:
  - 0.5s: kick in progress (transitional, OK).
  - 1.0s-5.7s: headless, no severed head anywhere — CORRECT.
  - 8.0s: lunge — the head is BACK (silver helmet, visor), medium shot
    (not the wide shot ordered), robot right in Karen's face.
  - 9.5s: robot half out of frame, no head visible (does not clear 8.0s).
  - HUD clock scrambled again: 14:22:07 -> 06 -> 06 -> 18 -> 10 -> 11.
Five generations, same failure: whenever the robot CLOSES WITH Karen —
grab OR lunge — the model grows the head back. Prompt tightening on the
same staging is exhausted (v5's lunge was already "no contact, wide only"
and it still failed). v6 REMOVES the closing itself: after the kick the
robot NEVER moves toward Karen again. It fights on BLIND — shadowboxing
empty air, walking into the ropes, spinning — while she watches from the
far corner. The joke (head kicked off, headless robot keeps fighting) is
unchanged; the payoff is now "it can't even see her".

Root-cause find while writing v6 (grep of the live prompt): the prompt
CONTRADICTED its own head rule. The 1.2-5.5s section ordered "the severed
head on the mat blinks its visor eyes" — a severed head ON THE MAT, exactly
what the head rule forbids and exactly what v3's double-head failure was.
That line is deleted in v6. Every other approach/contact instruction is
also deleted: the 5.5s scoop ("scoops Karen up"), the "keeps advancing on
her", the "keeps walking toward her", the lunge. The HUD clock is removed
too (five generations of scrambled digits; "CAM 03" + REC dot only).

Changes to the item (same pattern as v2/v3/v4/v5 regen):
  - prompt: V5 HEAD RULE -> V6 HEAD RULE (never closes with Karen);
    V5 FINAL LUNGE RULE -> V6 BLIND FLAIL RULE (wide, mid-ring, air only);
    beat-map escalation/ramp/climax/reaction/finale -> blind flail, no
    contact; secondary escalation severed-head-on-mat line DELETED;
    2.0s twist "walking toward her" -> turns away, shadowboxes air;
    CLIMAX RULES "karma contact" -> "big blind swing"; HUD clock REMOVED;
    CAT_2 / V1.1 payoff / novelty ledger -> blind flail, ignores her;
    cast line adds the 2-meter rule.
  - status: held_user_decision -> selected (urgent=True, duration=10,
    slot=22:30, qc_retry=1 kept). video_file/qc_report cleared (v5 file
    stays on disk for reference, never to be uploaded).
After this script, run `python3 auto_pipeline.py submit` immediately, then
flip the item to held_user_decision at once (user ordered Gemini-first).
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

V6_HEAD_RULE = """V6 HEAD RULE (2026-11-07 — v5 failed: the head came back AGAIN in the 8.0s lunge, five generations in a row; the pattern is now proven: whenever the robot CLOSES WITH Karen — grab OR lunge — the model grows the head back. The robot NEVER closes with her again): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot — and NO sentence anywhere in this prompt describes a severed head lying on the mat. For the ENTIRE remainder (1.0s-10.0s) the robot is HEADLESS — an empty neck stump with visible wires, in EVERY shot including close-ups. After 1.0s the robot NEVER moves toward Karen, NEVER closes distance with her, NEVER touches her, NEVER grabs her — it stays at least 2 meters from her at ALL times, fighting empty air in the middle of the ring while she watches from the far corner. The robot fights on HEADLESS and BLIND — that is the entire joke."""

V6_FLAIL_RULE = """V6 BLIND FLAIL RULE (2026-11-07 — v5 failed: the 8.0s lunge made the model grow the head back AGAIN; five generations prove the head returns whenever the robot CLOSES WITH Karen, so the closing itself is REMOVED, not reworded): the last 2 seconds (8.0s–10.0s) are a WIDE SHOT ONLY — the whole ring visible, both figures full-body, NO close-up, NO zoom, NO reframing. The HEADLESS robot (empty neck stump with visible sparking wires, chest screen glitched to 'NO SIGNAL') stays in the MIDDLE of the ring, at least 2 meters from Karen, flailing at EMPTY AIR — wild punches at nothing, spinning in a slow circle, stumbling into the ropes and bouncing off. Karen is at the FAR corner, doubled over laughing, hands on her knees — she is NEVER approached, NEVER touched, NEVER grabbed. The video hard-cuts at 10.0s on the headless robot shadowboxing thin air. NO body contact anywhere after 1.0s. NO approach, NO lunge toward Karen, NO grab anywhere in the video. A head on the robot, or the robot moving toward Karen in the final 2 seconds, breaks the video exactly as it did in v2/v4/v5."""

REPLACEMENTS = [
    # 1. V5 HEAD RULE -> V6 HEAD RULE (never closes with Karen).
    ("V5 HEAD RULE (2026-11-07 — v4 failed: head came back in the close-up final grab at 8.0s/9.5s; prompt tightening on the same staging is exhausted, so the final grab is REMOVED): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot. For the ENTIRE remainder (1.0s-10.0s) the robot is HEADLESS — an empty neck stump with visible wires, in EVERY shot including close-ups. There is NO final grab in this version — the ending (8.0s-10.0s) is a WIDE-SHOT lunge with NO body contact (see V5 FINAL LUNGE RULE). NEVER show the robot with a head after 1.00s. NEVER show a severed head lying anywhere. NEVER show two heads in one frame. The robot fights on HEADLESS — that is the entire joke.",
     V6_HEAD_RULE),
    # 2. V5 FINAL LUNGE RULE -> V6 BLIND FLAIL RULE.
    ("V5 FINAL LUNGE RULE (2026-11-07 — v4 failed: the close-up final grab at 8.0s/9.5s made the model grow the head back, four generations in a row; the grab is REMOVED, not reworded): the last 2 seconds (8.0s–10.0s) are a WIDE SHOT ONLY — the whole ring visible, both figures full-body, NO close-up, NO zoom, NO reframing. The HEADLESS robot (empty neck stump with visible sparking wires) charges across the ring toward Karen from a distance; Karen stumbles backward toward the ropes, arms raised, face in shock. The robot NEVER touches her, NEVER wraps its arms around her, NEVER grabs her, NEVER holds her — the video hard-cuts at 10.0s on her scream with the headless robot looming in wide. NO body contact in the final 2 seconds. NO close-up grapple anywhere in the video. A head on the robot, or any grab in the final 2 seconds, breaks the video exactly as it did in v2/v4.",
     V6_FLAIL_RULE),
    # 3. Beat-map escalation: "keeps advancing on her" -> ignores her, shadowboxes air.
    ("1.20-3.80s ESCALATION: Karen celebrates and taunts, jabbing at the headless robot; the robot's body keeps advancing on her, unbothered.",
     "1.20-3.80s ESCALATION: Karen celebrates and taunts from the far corner, jabbing at the headless robot; the headless robot ignores her completely — it turns in place, arms twitching, shadowboxing the empty air in the middle of the ring, NEVER moving toward her."),
    # 4. Secondary escalation: DELETE the severed-head-on-mat poison line.
    ("At 3.80-4.50s a SECOND, DIFFERENT unexpected move from the robot (secondary escalation): the severed head on the mat blinks its visor eyes, and the chest screen flashes 'ROUND 2'.",
     "At 3.80-4.50s a SECOND, DIFFERENT unexpected move from the robot (secondary escalation): the headless robot's chest screen glitches to 'NO SIGNAL', it stops dead, then starts shadowboxing the empty air — punching at nothing, completely ignoring Karen."),
    # 5. 2.0s twist: "keeps walking toward her" -> turns away, shadowboxes air.
    ("At 2.00-2.50s the robot delivers the CORE ABSURD TWIST: the headless body calmly rolls one shoulder in a shrug and keeps walking toward her — it does not need its head.",
     "At 2.00-2.50s the robot delivers the CORE ABSURD TWIST: the headless body calmly rolls one shoulder in a shrug and turns AWAY from her, shadowboxing the air — it does not need its head, and it does not need her."),
    # 6. Beat-map payback climax: scoop -> wildest blind flail, no contact.
    ("5.50-6.30s PAYBACK CLIMAX: first karma contact between 5.50-5.80s — the headless robot scoops Karen up and shoves her back against the ropes; peak physical displacement by 6.10s, concludes by 6.30s.",
     "5.50-6.30s PAYBACK CLIMAX: NO contact with Karen — the headless robot's wildest blind flail between 5.50-5.80s: a huge roundhouse swing at EMPTY AIR, then it stumbles forward into the ropes and bounces off, arms pinwheeling; peak motion by 6.10s, concludes by 6.30s. Karen watches from the far corner, untouched."),
    # 7. 5.5-6.3s section: scoop -> blind punch + rope bounce, zero contact.
    ("5.5-6.3s PAYBACK CLIMAX (v5.3 — the punchline window): sudden slapstick mishap in under 2 seconds — the headless robot scoops Karen up and shoves her back against the ropes (tangible physical comedy). She freezes mid-gesture in comic disbelief, caught on camera. The FIRST karma contact MUST land between 5.50-5.80s, peak physical displacement by 6.10s, concluded by 6.30s. The consequence MUST be TANGIBLE and SUDDEN — never a purely verbal burn.",
     "5.5-6.3s PAYBACK CLIMAX (v6 — the punchline window): sudden slapstick mishap in under 2 seconds — the headless robot throws its wildest blind punch at EMPTY AIR, overbalances, and stumbles into the ropes, bouncing off with arms pinwheeling (tangible physical comedy, ZERO contact with Karen). Karen freezes mid-gesture in comic disbelief at the far corner, caught on camera, untouched. The FIRST big blind swing MUST land between 5.50-5.80s, peak motion by 6.10s, concluded by 6.30s. The consequence MUST be TANGIBLE and SUDDEN — never a purely verbal burn."),
    # 8. CLIMAX RULES: "karma contact" -> "big blind swing".
    ("CLIMAX RULES (v5.3): The Climax Energy Ratio (max Motion [5.5s-6.3s] divided by mean Motion [0.0s-3.8s]) MUST equal or exceed 1.60. The FIRST karma contact frame MUST fall between t=5.50s and t=5.80s. NEVER allow the peak karma impact frame before 5.50s or after 6.30s. NEVER execute recoil movements, velocity deceleration, or return-to-pose loops between 3.0s and 5.5s.",
     "CLIMAX RULES (v6): The Climax Energy Ratio (max Motion [5.5s-6.3s] divided by mean Motion [0.0s-3.8s]) MUST equal or exceed 1.60. The FIRST big blind swing frame MUST fall between t=5.50s and t=5.80s — NO contact with Karen in the climax, the peak is the robot's wildest swing at empty air plus the rope bounce. NEVER allow the peak motion frame before 5.50s or after 6.30s. NEVER execute recoil movements, velocity deceleration, or return-to-pose loops between 3.0s and 5.5s."),
    # 9. Beat-map reaction + finale: lunge -> blind flail.
    ("6.30-8.50s REACTION: Karen stunned in consequence state, dangling against the ropes; digital zoom/pan to her stunned expression permitted ONLY in this window. 8.50-10.00s WIDE LUNGE FINALE (v5): WIDE master shot — the headless robot charges across the ring, Karen stumbles back toward the ropes, arms up, screaming; NO contact, NO grab, hard cut at 10.0s. NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required.",
     "6.30-8.50s REACTION: Karen at the far corner, doubled over laughing at the headless robot fighting thin air; the robot shadowboxes the empty center of the ring, spinning slowly, arms swinging at nothing; digital zoom/pan to her laughing expression permitted ONLY in this window. 8.50-10.00s WIDE BLIND FLAIL FINALE (v6): WIDE master shot — the headless robot flails at empty air in the middle of the ring, walks into the ropes and bounces off, spinning; Karen doubled over laughing at the far corner; NO approach, NO contact, NO grab, hard cut at 10.0s. NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required."),
    # 10. 6.3-10s section: lunge finale -> blind flail finale.
    ("6.3-10s REACTION + LOOP-OUT (v5): 6.3-8.5s comic aftermath — she stands frozen mid-gesture in total comic disbelief, dangling against the ropes; digital zoom/pan to her stunned expression permitted ONLY here. 8.5-10s WIDE LUNGE FINALE (see V5 FINAL LUNGE RULE): motion stays high, NO settling to ambient, NO fade, hard cut at 10.0s. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen re-entering, the headless robot advancing) — post-generation verified by loop_check.py (similarity >= 0.75).",
     "6.3-10s REACTION + LOOP-OUT (v6): 6.3-8.5s comic aftermath — she is doubled over laughing at the far corner while the headless robot shadowboxes empty air; digital zoom/pan to her laughing expression permitted ONLY here. 8.5-10s WIDE BLIND FLAIL FINALE (see V6 BLIND FLAIL RULE): motion stays high, NO settling to ambient, NO fade, hard cut at 10.0s. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen re-entering, the headless robot flailing at air) — post-generation verified by loop_check.py (similarity >= 0.75)."),
    # 11. HUD: clock REMOVED (five generations of scrambled digits).
    ("timestamp HUD overlay in the top-LEFT corner showing ONLY 'CAM 03 - 14:22:07' plus a red REC dot — NO date line, NO second timestamp line. The single clock reads exactly 14:22:07 at 0.0s, 14:22:08 at 1.0s, 14:22:09 at 2.0s, 14:22:10 at 3.0s, and so on — one second per second, reaching 14:22:17 at 10.0s — frame-accurate, never backwards, never jumping ahead. (v4 failed: 14:22:08 at 1.0s then 14:22:06 at 2.0s.)",
     "HUD overlay in the top-LEFT corner showing ONLY 'CAM 03' plus a red REC dot — NO timestamp, NO clock digits, NO date line. (v5 failed: the clock scrambled backwards and jumped ahead across five generations; the clock is REMOVED because the model cannot render a counting clock. A clock, timestamp, or any changing digits on screen breaks the video.)"),
    # 12. CAT_2 line: scoop -> blind flail.
    ("This package: CAT_2_MECHANICAL_IMPACT (headless robot physically scoops Karen against the ropes).",
     "This package: CAT_2_MECHANICAL_IMPACT (headless robot flails at empty air, walks into the ropes and bounces off — physical comedy, zero contact with Karen)."),
    # 13. V1.1 payoff: keeps coming for her -> fights the air, ignores her.
    ("she kicked its head off, but the protocol counts movement, not the head — so her own attack made it unstoppable by headshots, and it keeps coming for her. Payoff MUST be tangible AND, where possible, double: a physical consequence (scooped up against the ropes) plus on-site embarrassment (the referee and the crowd's phones filming her panic).",
     "she kicked its head off, but the protocol counts movement, not the head — so her own attack made it unstoppable by headshots, and it keeps fighting — but without a head it cannot see her, so it fights the empty air and ignores her completely. Payoff MUST be tangible AND, where possible, double: a physical consequence (the headless robot's wild blind flail and rope bounce) plus on-site embarrassment (Karen screaming for attention while the robot fights an invisible opponent, the referee and the crowd's phones filming her being ignored)."),
    # 14. Novelty ledger payoff type.
    ("payoff type (scooped against the ropes by the headless robot, new)",
     "payoff type (headless robot flails at empty air and ignores her, new)"),
    # 15. Cast line: add the 2-meter rule.
    ("from 1.0s on it is HEADLESS (empty neck stump with visible wires, never a head on its shoulders — see CONTINUITY HARD RULE); it fights under a combat protocol and stays perfectly calm while the entitled woman escalates — its comedy comes from cold literal enforcement, never arguing back.",
     "from 1.0s on it is HEADLESS (empty neck stump with visible wires, never a head on its shoulders — see CONTINUITY HARD RULE); after losing its head it NEVER moves toward Karen, it fights the air at least 2 meters from her; it fights under a combat protocol and stays perfectly calm while the entitled woman escalates — its comedy comes from cold literal enforcement, never arguing back."),
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
            it["regen_note"] = "v6 2026-11-07 ~10:58: blind-flail finale, robot NEVER closes with Karen (v5 head back 8.0s lunge); severed-head-on-mat poison line deleted; scoop deleted; HUD clock removed; Gemini-first hold after submit"
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
            assert "V6 HEAD RULE" in it["prompt"], "v6 head rule not in prompt"
            assert "V6 BLIND FLAIL RULE" in it["prompt"], "v6 flail rule not in prompt"
            assert "V5 HEAD RULE" not in it["prompt"], "stale v5 head rule remains"
            assert "V5 FINAL LUNGE RULE" not in it["prompt"], "stale v5 lunge rule remains"
            assert "WIDE LUNGE FINALE" not in it["prompt"], "stale lunge finale remains"
            assert "FINAL GRAB" not in it["prompt"], "stale final-grab rule remains"
            assert "severed head on the mat" not in it["prompt"], "poison severed-head line remains"
            assert "scoops Karen" not in it["prompt"], "stale scoop remains"
            assert "scooped" not in it["prompt"], "stale scooped remains"
            assert "advancing on her" not in it["prompt"], "stale advance remains"
            assert "keeps walking toward her" not in it["prompt"], "stale walk-toward remains"
            assert "charges across the ring" not in it["prompt"], "stale charge remains"
            assert "wraps its arms around Karen" not in it["prompt"], "stale grab remains"
            assert "14:22" not in it["prompt"], "stale clock remains"
            assert "ROUND 2" not in it["prompt"], "stale ROUND 2 remains"
            assert it.get("video_file") is None, "stale video_file not cleared"
            print("REGEN V6 QUEUED: prompt redesigned, item selected+urgent, ready to submit")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
