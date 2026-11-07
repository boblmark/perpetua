#!/usr/bin/env python3
"""Inject the user-approved robot-fight film (2026-11-07, 22:30 slot) into the
pipeline queue as urgent+selected, then submit_jobs() routes it to generation
without Ask Studio review (channel down 17 straight; user approved the exact
title/description package at 08:58 CST).

Package (approved verbatim):
  title: 🤖 Karen Kicked the Robot's Head Off… It Kept Fighting 😂
  description: (empty)
  concept: Karen challenges a humanoid robot in the ring, kicks its head clean
    off at 0.5s, the head flies, the headless robot shrugs and keeps coming
    for her. First frame = the head-kick moment.
  recipe: lemo 10s / 1080x1920 / 24fps
  source trend: Shenzhen URKL, EngineAI T800 head kicked off, kept fighting
    (Sunday Guardian / Future Stacked (X), Nov 4-5, 2026)
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db
from datetime import datetime, timezone

PROMPT = """SAFETY FIREWALL (hard gate): All characters are fictional adults age 25+. No minors. No real people, celebrities, public figures, likenesses, or real names. No real brands, logos, or trademarked products — use generic objects and fictional locations. Non-graphic slapstick only: no blood, gore, injury detail, threats, weapons, sexual content, hate, harassment, or illegal acts. NEVER attempt spelling variants to bypass a rejected prompt.

MANDATORY OPENING — DYNAMIC PUNCH-IN HOOK (v5.4, 2026-10-15 模板手术 D20261015-009): 0.00s–~1.00s: TIGHT CLOSE-UP (face, hands, or key object) — the hook frame; must contain the most emotionally charged detail of the scene. At ~1.00s: HARD SNAP to a WIDE or MEDIUM-WIDE master shot. ~1.00s–5.50s: HOLD the wide/master — NO cuts, NO digital reframing, NO additional punch-in zooms. REQUIREMENTS: the close-up and the wide must show the SAME continuous scene (no time jump); the hook detail must appear in the wide at the same scale position; audio/VO begins at 0.00s and continues unbroken across the snap. FORBIDDEN: fixed-perspective wide/medium-wide from 0.00s; slow push-ins; fade from black; title cards in the first 1.5s. CCTV STYLE PACK (optional): fisheye distortion, timestamp HUD, CAM id, REC indicator may be added as aesthetic wrapper. NOT required.

BEAT MAP (v5.3 adapted, 10.00s total): 0.00-1.00s HOOK: tight close-up punch-in on Karen's boot connecting with the humanoid robot's head — the head detaches and flies at ~0.50s, the most emotionally charged detail; at ~1.00s HARD SNAP to wide/master of the boxing ring. 1.20-3.80s ESCALATION: Karen celebrates and taunts, jabbing at the headless robot; the robot's body keeps advancing on her, unbothered. 3.80-5.50s UH-OH RAMP: the robot telegraphs override (servo whir, arms rising into a fighting stance); Karen stays oblivious, still celebrating. 5.50-6.30s PAYBACK CLIMAX: first karma contact between 5.50-5.80s — the headless robot scoops Karen up and shoves her back against the ropes; peak physical displacement by 6.10s, concludes by 6.30s. 6.30-8.50s REACTION: Karen stunned in consequence state, dangling against the ropes; digital zoom/pan to her stunned expression permitted ONLY in this window. 8.50-10.00s NO-EXIT-RUNWAY (v5.3.1): NEVER linger, fade, or settle back to opening mood. End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. Loop-back is OPTIONAL, never required.

MOTION RAMP (v5.3, critical for QC):
MUST maintain baseline motion within [0.25, 0.40] normalized optical-flow magnitude from 0.00s to 3.80s. MUST execute continuous linear upward ramp from 0.40 to ≥0.75 between 3.80s and 5.50s. MUST register peak motion magnitude ≥0.85 inside the 5.50s-6.30s climax window. MUST NOT decelerate motion to <0.15 between 8.50s and 10.00s unless a loop is specifically requested. NEVER allow motion magnitude to drop below 0.20 between 1.20s and 5.50s. NEVER hold still for more than 0.3 seconds before 8.50s. Motion blur is DESIRED.

CLIMAX RULES (v5.3): The Climax Energy Ratio (max Motion [5.5s-6.3s] divided by mean Motion [0.0s-3.8s]) MUST equal or exceed 1.60. The FIRST karma contact frame MUST fall between t=5.50s and t=5.80s. NEVER allow the peak karma impact frame before 5.50s or after 6.30s. NEVER execute recoil movements, velocity deceleration, or return-to-pose loops between 3.0s and 5.5s.

EARLY TWIST RULE (v5.4, critical — Ask Studio final review 2026-10-12): The CORE ABSURD TWIST — the moment the AI device does something genuinely unexpected that REFRAMES the conflict (NOT just the entitled woman shouting louder, NOT just a status-light color change, NOT a bigger version of the same gag) — MUST occur between 2.00s and 2.50s. By 2.50s the viewer MUST already feel 'this is NOT the the entitled woman video I expected.' A SECONDARY ESCALATION — a second, DIFFERENT unexpected move by the device — MUST occur between 3.80s and 4.50s, before the uh-oh ramp. NEVER save all surprise for the 5.5s payback: a viewer who has seen ZERO twists by 3.0s has already swiped. The 5.50-6.30s payback climax stays, but it is now the THIRD escalation, not the first.

TITLE RULE (D20261030-001, CTR-first): Title MAY name the exact physical payoff (result-first) to buy CTR. Spoiler titles are ALLOWED; the former AUTO-REJECT spoiler list is void. Prefer: conflict + payoff up front, within title length limits. Rationale: teardown winners show spoiler titles average 2.1x mean views; clicks prioritized over interaction per user decision D20261030-001.

PAYBACK ROTATION (v5.3 hard gate): Every package MUST be classified into exactly one of six categories: CAT_1_LIQUID_FOAM (liquid jets, foam, sanitizer deluge), CAT_2_MECHANICAL_IMPACT (gate arm, turnstile block, conveyor jerk), CAT_3_ACOUSTIC_PNEUMATIC (speaker feedback blast, air gust), CAT_4_CONTAINMENT_LOCKOUT (shutter drop, airlock trap, barricade), CAT_5_POWDER_DISCHARGE (receipt avalanche, powder puff, coin overspill), CAT_6_SOCIAL_EXPOSURE (receipt shown to everyone, footage sent to group chat, license plate displayed — embarrassment reversals). NEVER compile a package whose category appears in the previous 4 published/queued packages (rolling 1-in-5 hard cap, enforced indefinitely). This package: CAT_2_MECHANICAL_IMPACT (headless robot physically scoops Karen against the ropes).

TITLE GRAMMAR GATE (v5.3 hard gate): Title MUST pass subject-verb-object validation (the entitled woman + 3rd-person-singular present-tense verb + direct object). AUTO-REJECT malformed verb forms matching: (?i)\\b(thied|complimentaried|unauthorizeded|hoaed|\\d+ed|holded|zoned|convertibled|speaked|turboed|ied|doubled|sittinged)\\b or any [verb-stem]+ed double-inflection. NEVER use passive voice or past tense. (Note: the user-approved title for this package governs as-is; it was approved verbatim 2026-11-07 08:58 CST.)

V1.1 CAUSAL EVOLUTION (2026-10-28 council consensus, precedence over conflicting wording elsewhere on goal / payoff causality / title / dialogue): Runtime stays 9-11 seconds. the entitled woman MUST have ONE concrete goal stated within the first 25% of runtime — hers: beat the humanoid robot in the ring and prove she is tougher than the machine. The AI device MUST have ONE rule or capability established early — the robot's combat protocol: the bout runs until the bell, and a fighter is only out when it stops moving. The payoff MUST follow causally from a request, rule, or action already established in the Short: she kicked its head off, but the protocol counts movement, not the head — so her own attack made it unstoppable by headshots, and it keeps coming for her. Payoff MUST be tangible AND, where possible, double: a physical consequence (scooped up against the ropes) plus on-site embarrassment (the referee and the crowd's phones filming her panic). Conflict MUST be visually legible within the first 1.5 seconds, with no setup longer than 5 words on screen and no title card used as the hook. The loop MUST be causal: the final frame rhymes with the opening AND is a consequence of the payoff, not a mere visual reset. Dialogue: the entitled woman speaks at most 6 words in total, total spoken English at most 22 words, and the AI never delivers a long rebuttal sentence. Title: at most 55 characters, strong verb-object structure, spoiler payoff name ALLOWED per D20261030-001 (CTR-first), 'Then the AI Read...' pattern allowed emoji may decorate the title at the end only and must never carry plot information. Novelty ledger (output field, required): previous six Shorts were self-checkout kiosk, smart fitting-room mirror, pool-cleaning robot, gym locker, EV charger, delivery drone — this package changes setting (boxing ring, new), AI mechanism (headless combat humanoid that fights on without its head, new), and payoff type (scooped against the ropes by the headless robot, new); at least two of the four elements changed versus the previous six. NEVER: manager jokes, surreal punishments, a single static dialogue-only retaliation without strong visual feedback, a second unrelated twist after the punchline, an explanatory line after the punchline, or tiny UI text / an unexplained rule as the sole explanation for the reversal.

Vertical 9:16 short, exactly 10 seconds, 1080x1920, 24fps. Raw arena-cam / CCTV aesthetic: high contrast, slightly desaturated daylight, timestamp HUD overlay in the top-LEFT corner (e.g. 'CAM 03 - 14:22:07'). No black bars, no watermark, no cinematic letterbox.

Cast: The entitled woman: middle-aged woman, blonde bob or messy bun, oversized sunglasses pushed up on her head, pink tracksuit top. Perpetually outraged: wide eyes, mouth open mid-rant, finger jabbing. AI device: a humanoid fighting robot — white/silver humanoid, glowing visor eyes, small chest screen showing deadpan text; it fights under a combat protocol and stays perfectly calm while the entitled woman escalates — its comedy comes from cold literal enforcement, never arguing back. One referee frozen mid-stare, phone out, selling the 'caught on camera' realism.

0-1.2s SPATIAL CONTEXT (v5.3): frame 0.00s OPENS on a TIGHT CLOSE-UP — Karen's boot connecting with the robot's head, the head detaching mid-air; the hook frame. At ~1.00s HARD SNAP to a WIDE master of the boxing ring — Karen's torso AND the headless robot visible simultaneously, her face ≤20% of frame. Conflict already in progress, zero setup: Karen kicks the robot's head clean off and the head flies across the ring. Premise hook text on screen at 0.00s, MAX 6 words, upper-third placement — 'SHE KICKED ITS HEAD OFF'. TRIGGER MICRO-BEAT (2026-10-09 council #3): at 1.10-1.35s the robot's chest screen does ONE blue-to-red pulse then back to blue — single state-change cue, same fixed shot, visual ONLY, no alarm sound. Movement in every frame, nothing static. UI SAFE ZONE (hard rule): every key text overlay and the visual gag MUST sit in the top-middle third of the frame. NEVER place critical info on the right edge (engagement icons cover it) or in the bottom 25% (Shorts title/channel overlay truncates it). CCTV timestamp HUD goes top-LEFT corner only.

1.2-5.5s ESCALATION + TWISTS + UH-OH RAMP (v5.4): Karen pushes the robot to its limit — celebrating, taunting, jabbing at the headless body. At 2.00-2.50s the robot delivers the CORE ABSURD TWIST: the headless body calmly rolls one shoulder in a shrug and keeps walking toward her — it does not need its head. Deadpan ~1.2s pause before it acts — the pause IS the joke. At 3.80-4.50s a SECOND, DIFFERENT unexpected move from the robot (secondary escalation): the severed head on the mat blinks its visor eyes, and the chest screen flashes 'ROUND 2'. From 4.5s the robot telegraphs override (servo whir, arms rising into a fighting stance); Karen stays oblivious and keeps celebrating.

5.5-6.3s PAYBACK CLIMAX (v5.3 — the punchline window): sudden slapstick mishap in under 2 seconds — the headless robot scoops Karen up and shoves her back against the ropes (tangible physical comedy). She freezes mid-gesture in comic disbelief, caught on camera. The FIRST karma contact MUST land between 5.50-5.80s, peak physical displacement by 6.10s, concluded by 6.30s. The consequence MUST be TANGIBLE and SUDDEN — never a purely verbal burn. KARMA DROP (2026-10-09 council #1): at the exact karma contact, brief ambient duck then ONE dry diegetic thud (peak <=-6dBFS) — never a cinematic bass drop, never muted dialogue.

6.3-10s REACTION + LOOP-OUT (v5.3): 6.3-8.5s comic aftermath — she stands frozen mid-gesture in total comic disbelief, dangling against the ropes; digital zoom/pan to her stunned expression permitted ONLY here. 8.5-10s motion settles to frame-0 ambient level, lighting returns to baseline. Final frame MUST visually rhyme with frame 1 (same arena-cam angle on the ring, Karen re-entering, the headless robot advancing) — post-generation verified by loop_check.py (similarity >= 0.75).

Audio (v5 1.2s Snap): MUST begin at 0.00s at 70% volume (mid-level, NOT max) with an instantly recognizable vocal onset — e.g. "Ha! Take THAT—". The onset creates curiosity, not alarm. MUST ramp volume continuously to peak by 2.00s, synced to the entitled woman's visual expression peak. NEVER start at peak volume, NEVER start silent, NEVER a loud Foley transient / mute-drop hit at 0s (v4 peak-open overturned: triggers ad/bot instinct → instant swipe). NEVER background music, SFX, or silence masking the vocal onset in 0.00-2.00s. Naturalistic Foley + low arena current-hum after 2s, mobile-safe dynamic range, no clipping. NEVER a loud royalty-free upbeat track, NEVER harsh alarm blasts, NEVER silent for more than 1 second. On-screen text: max 3 overlays, each 6 words or fewer, high-contrast white/yellow with black stroke, ALL inside the top-middle third of the frame (UI safe zone — never right edge or bottom 25%). 0-2s premise hook text visible for the ENTIRE 0-2s window. CCTV timestamp HUD top-LEFT corner only. Subtitles show SPOKEN DIALOGUE ONLY — never meta-titles, scene labels, 'POV', 'Wait for it', or character names. Hard cuts only — no slow motion, no fade-to-black, no fade-in, no static text-only openings. The AI always gets the last laugh; instant karma is the brand.
DATA-DRIVEN DIRECTIVES (from channel's own retention telemetry, 79 videos, 2026-10-29):
- BOOST videos with review_score higher in winners (winners 23.04 vs losers 1.63)
- BOOST videos with title_len lower in winners (winners 67.12 vs losers 68.87)
- BOOST videos with hashtag_n lower in winners (winners 0.12 vs losers 1.389)
Treat these as weighted preferences, not hard rules."""

ITEM = {
    "topic": "robot fight ring",
    "hook": "Karen steps into the ring to prove she can beat a humanoid robot, kicks its head clean off at 0.5s — the head flies, the headless robot shrugs and keeps coming for her",
    "title": "🤖 Karen Kicked the Robot's Head Off… It Kept Fighting 😂",
    "description": "",
    "tags": [],
    "payback_category": "CAT_2_MECHANICAL_IMPACT",
    "series": None,
    "series_id": None,
    "series_name": None,
    "status": "selected",
    "slot": "22:30",
    "urgent": True,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "prompt": PROMPT,
}

def main():
    items = queue_db.pipeline_load()
    # idempotency: do not inject twice
    for it in items:
        if it.get("topic") == "robot fight ring" and it.get("status") in (
            "selected", "job_submitted", "review_passed", "teaser_validation",
            "uploaded_private", "uploaded", "published"):
            print("ALREADY PRESENT:", it.get("status"), it.get("job_id", ""), it.get("muse_job_id", ""))
            return 0
    items.append(ITEM)
    queue_db.pipeline_save(items)
    # verify
    items2 = queue_db.pipeline_load()
    for it in items2:
        if it.get("topic") == "robot fight ring" and it.get("status") == "selected":
            print("INJECTED OK: topic=robot fight ring status=selected urgent=True slot=22:30")
            print("title:", it["title"])
            print("row_key:", it.get("_row_key"))
            return 0
    print("INJECT FAILED: item not found after save")
    return 1

if __name__ == "__main__":
    sys.exit(main())
