#!/usr/bin/env python3
"""Regenerate the robot-fight film v7 — off-screen exit (2026-11-07).

Why: v6 (job-20261107030039-d85ea9, 10.0s) failed the SAME way as v1-v5,
but this time it KILLED the working hypothesis:
  - 0.5s: kick in progress (transitional, OK).
  - 1.0s-2.0s: headless, sparking stump — CORRECT.
  - 5.7s: head BACK (silver helmet, blue visor — crop-verified).
  - 8.0s/9.5s: blind flail WITH a head.
  - HUD clock fixed (CAM 03 + REC only). Chest screen stayed "SYSTEM
    ONLINE"; "NO SIGNAL" ended up on the wall banners instead.
The v6 design (robot never approaches Karen, stays >=2m away, fights the
air) did NOT save it — the robot was in the far corner, Karen far away,
and the head STILL came back at 5.7s. Conclusion: the model cannot hold
a headless robot ON SCREEN for 10 seconds, period. Proximity was never
the cause; screen time was. Prompt tightening on the same staging is
exhausted after six generations. v7 REMOVES the robot from the frame:
after the kick, the headless body stumbles out of frame at 2.0s and is
NEVER seen again. The remaining 8 seconds are ONLY Karen, the referee,
and the crowd — there is no neck left for the model to re-head. The joke
(she kicked its head off) is unchanged; the payoff is now "it just left —
she wins by walkover against an empty corner".

Changes to the item (same pattern as v2-v6 regen):
  - prompt: V6 HEAD RULE -> V7 OFF-SCREEN RULE (robot exits frame at
    2.0s, NEVER seen again after 2.0s); V6 BLIND FLAIL RULE -> V7
    VICTORY FINALE RULE (medium shot of Karen only); beat-map
    escalation/ramp/climax/reaction/finale -> Karen-only, no robot
    after 2.0s; "shadowboxing"/"blind flail"/"NO SIGNAL"/"2 meters"
    language all deleted (they were v6 staging, now gone);
    CAT_2 / V1.1 payoff / novelty ledger / cast line -> walkover
    against an empty corner.
  - status: held_user_decision -> selected (urgent=True, duration=10,
    slot=22:30, qc_retry=1 kept). video_file/qc_report cleared (v6 file
    stays on disk for reference, never to be uploaded).
After this script, run `python3 auto_pipeline.py submit` immediately, then
flip the item to held_user_decision at once (user ordered Gemini-first).
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

V7_OFFSCREEN_RULE = """V7 OFF-SCREEN RULE (2026-11-07 — v6 failed: the head came back AGAIN at 5.7s even though the robot NEVER approached Karen; six generations prove the model cannot keep a headless robot ON SCREEN for 10 seconds, so the robot LEAVES THE FRAME — it is not re-staged, it is REMOVED): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot — and NO sentence anywhere in this prompt describes a severed head lying on the mat. From 1.0s to 2.0s the robot is HEADLESS — an empty neck stump with visible sparking wires — and it stumbles backward and walks OUT OF FRAME to the left. At 2.0s the robot is GONE from the frame and it NEVER comes back: from 2.0s to 10.0s there is NO robot in ANY shot — NOT in the foreground, NOT in the background, NOT in a wide shot, NOT in a mirror, NOT at the edge of the frame. The camera NEVER shows the robot after 2.0s and NEVER cuts back to it. The remaining 8 seconds are ONLY Karen, the referee, and the crowd. The joke is now: she kicked its head off and it just LEFT — she wins by walkover against an empty corner."""

V7_FINALE_RULE = """V7 VICTORY FINALE RULE (2026-11-07 — v6 failed: the head came back at 5.7s with the robot on screen the whole time; the robot is REMOVED from the frame after 2.0s, so there is no neck left for the model to re-head): the last 2 seconds (8.0s–10.0s) are a MEDIUM SHOT of KAREN ONLY — she raises both arms in victory, laughing, the crowd on its feet behind her, the referee raising her hand. NO robot anywhere in the frame, NO robot in the background, NO wide shot of the ring. The video hard-cuts at 10.0s on Karen's victory pose. NO body contact anywhere after 1.0s — there is nobody left for her to touch. A robot visible anywhere in the frame after 2.0s breaks the video exactly as the head did in v1–v6."""

REPLACEMENTS = [
    # 1. V6 HEAD RULE -> V7 OFF-SCREEN RULE.
    ("V6 HEAD RULE (2026-11-07 — v5 failed: the head came back AGAIN in the 8.0s lunge, five generations in a row; the pattern is now proven: whenever the robot CLOSES WITH Karen — grab OR lunge — the model grows the head back. The robot NEVER closes with her again): Karen's kick detaches the robot's head between 0.40s and 0.70s and the head flies OVER THE ROPES and OUT OF THE RING — it is GONE, never seen again. There is NO severed head anywhere in the video after the kick: NOT on the mat, NOT on the floor, NOT on the neck, NOT in any shot — and NO sentence anywhere in this prompt describes a severed head lying on the mat. For the ENTIRE remainder (1.0s-10.0s) the robot is HEADLESS — an empty neck stump with visible wires, in EVERY shot including close-ups. After 1.0s the robot NEVER moves toward Karen, NEVER closes distance with her, NEVER touches her, NEVER grabs her — it stays at least 2 meters from her at ALL times, fighting empty air in the middle of the ring while she watches from the far corner. The robot fights on HEADLESS and BLIND — that is the entire joke.",
     V7_OFFSCREEN_RULE),
    # 2. V6 BLIND FLAIL RULE -> V7 VICTORY FINALE RULE.
    ("V6 BLIND FLAIL RULE (2026-11-07 — v5 failed: the 8.0s lunge made the model grow the head back AGAIN; five generations prove the head returns whenever the robot CLOSES WITH Karen, so the closing itself is REMOVED, not reworded): the last 2 seconds (8.0s–10.0s) are a WIDE SHOT ONLY — the whole ring visible, both figures full-body, NO close-up, NO zoom, NO reframing. The HEADLESS robot (empty neck stump with visible sparking wires, chest screen glitched to 'NO SIGNAL') stays in the MIDDLE of the ring, at least 2 meters from Karen, flailing at EMPTY AIR — wild punches at nothing, spinning in a slow circle, stumbling into the ropes and bouncing off. Karen is at the FAR corner, doubled over laughing, hands on her knees — she is NEVER approached, NEVER touched, NEVER grabbed. The video hard-cuts at 10.0s on the headless robot shadowboxing thin air. NO body contact anywhere after 1.0s. NO approach, NO lunge toward Karen, NO grab anywhere in the video. A head on the robot, or the robot moving toward Karen in the final 2 seconds, breaks the video exactly as it did in v2/v4/v5.",
     V7_FINALE_RULE),
    # 3. Beat-map escalation: robot shadowboxes air -> robot exits frame at 2.0s, Karen owns the ring.
    ("1.20-3.80s ESCALATION: Karen celebrates and taunts from the far corner, jabbing at the headless robot; the headless robot ignores her completely — it turns in place, arms twitching, shadowboxing the empty air in the middle of the ring, NEVER moving toward her.",
     "1.20-3.80s ESCALATION: 1.20-2.00s the headless robot sparks, stumbles backward and walks OUT OF FRAME to the left — it is GONE. At 2.00s the camera whips to Karen: she is alone in the frame, laughing, pointing at the empty corner where the robot was, the crowd going wild behind her. 2.00-3.80s Karen owns the ring — she struts, she points at the empty corner, she plays to the crowd. NO robot in any shot after 2.0s."),
    # 4. Secondary escalation: chest-screen NO SIGNAL + shadowboxing -> Karen victory lap, referee confused, no robot.
    ("At 3.80-4.50s a SECOND, DIFFERENT unexpected move from the robot (secondary escalation): the headless robot's chest screen glitches to 'NO SIGNAL', it stops dead, then starts shadowboxing the empty air — punching at nothing, completely ignoring Karen.",
     "At 3.80-4.50s a SECOND, DIFFERENT unexpected move (secondary escalation): Karen does a victory lap around the EMPTY ring, taunting the corner where the robot used to be — she throws mock punches at the empty air herself, mocking it; the referee scratches his head, looking around for a robot that is not there; the crowd roars. NO robot in the frame."),
    # 5. 2.0s twist: turns away shadowboxing -> walks out of frame, camera stays on Karen.
    ("At 2.00-2.50s the robot delivers the CORE ABSURD TWIST: the headless body calmly rolls one shoulder in a shrug and turns AWAY from her, shadowboxing the air — it does not need its head, and it does not need her.",
     "At 2.00-2.50s the CORE ABSURD TWIST: the headless body calmly rolls one shoulder in a shrug and walks OUT OF FRAME to the left — it does not need its head, and it does not need the fight. The camera does NOT follow it; it stays on Karen, who is pointing and laughing at the empty space."),
    # 6. Beat-map payback climax: blind flail -> Karen's victory move, empty corner stays empty.
    ("5.50-6.30s PAYBACK CLIMAX: NO contact with Karen — the headless robot's wildest blind flail between 5.50-5.80s: a huge roundhouse swing at EMPTY AIR, then it stumbles forward into the ropes and bounces off, arms pinwheeling; peak motion by 6.10s, concludes by 6.30s. Karen watches from the far corner, untouched.",
     "5.50-6.30s PAYBACK CLIMAX: NO robot in the frame — Karen's biggest victory move between 5.50-5.80s: she jumps, spins, and throws both arms up as the crowd surges to its feet; peak motion by 6.10s, concludes by 6.30s. The empty corner where the robot was stays EMPTY."),
    # 7. 5.5-6.3s section: blind punch + rope bounce -> Karen victory move.
    ("5.5-6.3s PAYBACK CLIMAX (v6 — the punchline window): sudden slapstick mishap in under 2 seconds — the headless robot throws its wildest blind punch at EMPTY AIR, overbalances, and stumbles into the ropes, bouncing off with arms pinwheeling (tangible physical comedy, ZERO contact with Karen). Karen freezes mid-gesture in comic disbelief at the far corner, caught on camera, untouched. The FIRST big blind swing MUST land between 5.50-5.80s, peak motion by 6.10s, concluded by 6.30s. The consequence MUST be TANGIBLE and SUDDEN — never a purely verbal burn.",
     "5.5-6.3s PAYBACK CLIMAX (v7 — the punchline window): sudden slapstick payoff in under 2 seconds — Karen jumps and spins in a victory move as the crowd surges, then freezes mid-gesture in comic disbelief, staring at the EMPTY corner, caught on camera (tangible physical comedy, ZERO robot in the frame). The FIRST big victory move MUST land between 5.50-5.80s, peak motion by 6.10s, concluded by 6.30s. The consequence MUST be TANGIBLE and SUDDEN — never a purely verbal burn."),
    # 8. CLIMAX RULES: "big blind swing" -> "big victory move".
    ("CLIMAX RULES (v6): The Climax Energy Ratio (max Motion [5.5s-6.3s] divided by mean Motion [0.0s-3.8s]) MUST equal or exceed 1.60. The FIRST big blind swing frame MUST fall between t=5.50s and t=5.80s — NO contact with Karen in the climax, the peak is the robot's wildest swing at empty air plus the rope bounce. NEVER allow the peak motion frame before 5.50s or after 6.30s. NEVER execute recoil movements, velocity deceleration, or return-to-pose loops between 3.0s and 5.5s.",
     "CLIMAX RULES (v7): The Climax Energy Ratio (max Motion [5.5s-6.3s] divided by mean Motion [0.0s-3.8s]) MUST equal or exceed 1.60. The FIRST big victory move frame MUST fall between t=5.50s and t=5.80s — NO robot in the frame in the climax, the peak is Karen's victory jump and spin plus the crowd surging. NEVER allow the peak motion frame before 5.50s or after 6.30s. NEVER execute recoil movements, velocity deceleration, or return-to-pose loops between 3.0s and 5.5s."),
    # 9. Beat-map reaction + finale: blind flail -> Karen victory finale.
    ("6.30-8.50s REACTION: Karen at the far corner, doubled over laughing at the headless robot fighting thin air; the robot shadowboxes the empty center of the ring, spinning slowly, arms swinging at nothing; digital zoom/pan to her laughing expression permitted ONLY in this window. 8.50-10.00s WIDE BLIND FLAIL FINALE (v6): WIDE master shot — the headless robot flails at empty air in the middle of the ring, walks into the ropes and bounces off, spinning; Karen doubled over laughing at the far corner; NO approach, NO contact, NO grab, hard cut at 10.0s. NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required.",
     "6.30-8.50s REACTION: Karen alone in the ring, doubled over laughing at the empty corner, playing to the roaring crowd; the referee holds up her hand in confused victory; digital zoom/pan to her laughing expression permitted ONLY in this window. 8.50-10.00s KAREN VICTORY FINALE (v7): MEDIUM shot — Karen raises both arms in victory, laughing, crowd on its feet behind her; NO robot anywhere in the frame; hard cut at 10.0s. NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required."),
    # 10. 6.3-10s section: blind flail finale -> Karen victory finale.
    ("6.3-10s REACTION + LOOP-OUT (v6): 6.3-8.5s comic aftermath — she is doubled over laughing at the far corner while the headless robot shadowboxes empty air; digital zoom/pan to her laughing expression permitted ONLY here. 8.5-10s WIDE BLIND FLAIL FINALE (see V6 BLIND FLAIL RULE): motion stays high, NO settling to ambient, NO fade, hard cut at 10.0s. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen re-entering, the headless robot flailing at air) — post-generation verified by loop_check.py (similarity >= 0.75).",
     "6.3-10s REACTION + LOOP-OUT (v7): 6.3-8.5s comic aftermath — she is doubled over laughing alone in the ring while the crowd roars; digital zoom/pan to her laughing expression permitted ONLY here. 8.5-10s KAREN VICTORY FINALE (see V7 VICTORY FINALE RULE): motion stays high, NO settling to ambient, NO fade, hard cut at 10.0s. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen center-frame) — post-generation verified by loop_check.py (similarity >= 0.75). Loop-back is OPTIONAL, never required."),
    # 11. CAT_2 line: blind flail -> walkover against an empty corner.
    ("This package: CAT_2_MECHANICAL_IMPACT (headless robot flails at empty air, walks into the ropes and bounces off — physical comedy, zero contact with Karen).",
     "This package: CAT_2_MECHANICAL_IMPACT (headless robot exits the frame at 2.0s and never comes back; Karen wins by walkover against an empty corner)."),
    # 12. V1.1 payoff: fights the air and ignores her -> stumbles out and is gone.
    ("she kicked its head off, but the protocol counts movement, not the head — so her own attack made it unstoppable by headshots, and it keeps fighting — but without a head it cannot see her, so it fights the empty air and ignores her completely. Payoff MUST be tangible AND, where possible, double: a physical consequence (the headless robot's wild blind flail and rope bounce) plus on-site embarrassment (Karen screaming for attention while the robot fights an invisible opponent, the referee and the crowd's phones filming her being ignored).",
     "she kicked its head off, but the protocol counts movement, not the head — so her own attack made it unstoppable by headshots, and it keeps going — but without a head it cannot find her, so it stumbles out of the ring and is GONE. Payoff MUST be tangible AND, where possible, double: a physical consequence (the robot exits the frame entirely, Karen wins by walkover) plus on-site embarrassment (Karen taunting an empty corner, the referee looking around for a robot that is not there, the crowd's phones filming her victory over nobody)."),
    # 13. Novelty ledger payoff type.
    ("payoff type (headless robot flails at empty air and ignores her, new)",
     "payoff type (headless robot exits the frame and never returns, new)"),
    # 14. Cast line: fights the air >=2m -> out of frame at 2.0s, never seen again.
    ("from 1.0s on it is HEADLESS (empty neck stump with visible wires, never a head on its shoulders — see CONTINUITY HARD RULE); after losing its head it NEVER moves toward Karen, it fights the air at least 2 meters from her; it fights under a combat protocol and stays perfectly calm while the entitled woman escalates — its comedy comes from cold literal enforcement, never arguing back.",
     "from 1.0s on it is HEADLESS (empty neck stump with visible wires, never a head on its shoulders — see CONTINUITY HARD RULE); after losing its head it stumbles backward OUT OF FRAME at 2.0s and is NEVER seen again for the rest of the video; it fights under a combat protocol and stays perfectly calm while the entitled woman escalates — its comedy comes from cold literal enforcement, never arguing back."),
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
            it["regen_note"] = "v7 2026-11-07 ~11:52: off-screen exit — robot leaves frame at 2.0s, NEVER seen again after 2.0s (v6 head back 5.7s even with no approach; model cannot hold headless on screen 10s); remaining 8s Karen + referee + crowd only; Gemini-first hold after submit"
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
            assert "V7 OFF-SCREEN RULE" in it["prompt"], "v7 off-screen rule not in prompt"
            assert "V7 VICTORY FINALE RULE" in it["prompt"], "v7 finale rule not in prompt"
            assert "V6 HEAD RULE" not in it["prompt"], "stale v6 head rule remains"
            assert "V6 BLIND FLAIL RULE" not in it["prompt"], "stale v6 flail rule remains"
            assert "WIDE BLIND FLAIL FINALE" not in it["prompt"], "stale flail finale remains"
            assert "shadowbox" not in it["prompt"], "stale shadowbox remains"
            assert "flail" not in it["prompt"], "stale flail remains"
            assert "BLIND" not in it["prompt"], "stale BLIND remains"
            assert "NO SIGNAL" not in it["prompt"], "stale NO SIGNAL remains"
            assert "2 meters" not in it["prompt"], "stale 2 meters remains"
            assert "severed head on the mat" not in it["prompt"], "poison severed-head line remains"
            assert "14:22" not in it["prompt"], "stale clock remains"
            assert "ROUND 2" not in it["prompt"], "stale ROUND 2 remains"
            assert it.get("video_file") is None, "stale video_file not cleared"
            print("REGEN V7 QUEUED: prompt redesigned, item selected+urgent, ready to submit")
            return 0
    print("VERIFY FAILED")
    return 1

if __name__ == "__main__":
    sys.exit(main())
