# Viral Shorts Prompt Template — @karenvsai ("Karen vs AI") — v2 (Ask Studio refined)

Data-driven. Derived from 490 channel videos (criteria.json v3) + YouTube
Analytics signals + Ask Studio audit (2026-10-06). All prompts MUST be in
English (channel is EN).

## Ask Studio audit (2026-10-06): v1 scored 84/100

- Strengths kept: instant in-medias-res hook, Karen-vs-calm-AI archetypes,
  seamless loop structure.
- Two fixes applied in this version:
  1. **Duration 9–11s (not 15s)**: top channel hits average 9–11s with
     111–157% view percentage; 15s risks retention drop-off before the
     punchline.
  2. **CCTV / surveillance aesthetic**: top performers ground the conflict
     in everyday automated friction points (gas pumps, gates, HOA parking,
     self-checkouts) with a raw CCTV/dashcam look — a primary visual hook
     for returning viewers.

Reference winners: HOA Karen towed (30.7K views, 133.5% retention),
gas-pump soak (30.6K views, 111.1% retention).

## Why most AI Shorts flop on this channel

Analytics reality (v3): average watch time 7–20s, traffic is search-heavy
because new videos never enter the Shorts feed. The feed decides in ~3
seconds: strong visual hook + stayed-vs-swiped ratio + loopability. A
generic prompt like "AI comedy short" produces a slow clip with no hook —
exactly what the algorithm buries.

## 1. Video generation prompt structure

Every `generate_video` prompt MUST contain these blocks, in this order.
Total prompt length: 200–350 words. Concrete beats + visual detail, no
adjectives like "high-quality" or "creative".

### Block A — Format lock (always first, verbatim)
```
Vertical 9:16 short, exactly 10 seconds, 30fps. Raw CCTV / dashcam /
smart-camera aesthetic: high contrast, slightly desaturated daylight,
timestamp HUD overlay in the top corner (e.g. "CAM 03 · 14:22:07").
No black bars, no watermark, no cinematic letterbox.
```

### Block B — Cast (pick from the roster, describe once)
- **Karen**: middle-aged white woman, blonde bob or messy bun, oversized
  sunglasses on head, leopard-print or pink tracksuit top. Perpetually
  outraged expression: wide eyes, open mouth mid-rant, finger pointing.
- **AI device**: the specific machine of the episode (smart gas pump,
  automated gate, self-checkout scanner, drive-thru speaker…). It must be
  an EVERYDAY automated friction point, not an abstract studio prop.
  Anthropomorphized just enough: glowing status light / screen face with
  deadpan text. Its comedy comes from being CALM while Karen escalates.
- **Bystanders** (optional, 1): frozen mid-stare, phone out. Sells the
  "caught on camera" realism.

### Block C — 0–2s COLD COLLISION HOOK (the whole video lives or dies here)
Rules, all mandatory:
- Frame 1 = conflict already in progress. Karen is ALREADY yelling at the
  machine, or it has ALREADY retaliated. Zero setup, zero establishing shot.
- SENSORY hook, not narrative: the swipe decision happens in 200–500ms.
  Lead with visual incongruity / motion delta (red circle pulse, LED flash,
  Karen mid-lunge) BEFORE any story setup.
- One giant text overlay in the first second, ALL CAPS, ≤6 words, e.g.
  `AI REFUSED HER EXPIRED COUPON` / `SHE TRIED TO FIGHT THE SMART PUMP`.
  Yellow/white with black stroke. **UI SAFE ZONE: all key text and the visual
  gag MUST sit in the top-middle third of the frame.** NEVER place critical
  text/info on the right edge (engagement icons) or bottom 25% (title/channel
  overlay truncates it). CCTV timestamp HUD goes top-LEFT corner only.
- A visual jolt in second 1–2: gate slamming, red LED flash, Karen's jaw
  dropping. Movement in every frame — nothing static.
- Second 0 audio: ONE crisp Foley hit (glass crack, horn blip, sharp gasp).
  No gradual ambient fade-in — a transient resets attention, hum loses it.

### Block D — 2–6.5s RAPID ESCALATION (one beat)
- Karen pushes the machine to its limit — the exact wrong move. Louder,
  closer to camera, more absurd demand ("I WANT YOUR MANAGER'S MANAGER!").
- The AI responds with cold literal logic. It does not argue; it ENFORCES.
  Robotic chime, red LED flash, deadpan voice: "UNAUTHORIZED OVERRIDE
  DETECTED." Deadpan 0.5s pause before it acts — the pause IS the joke.

### Block E — 6.5–7.5s CLIMAX: SUDDEN PHYSICAL KARMA (the punchline window)
- The consequence MUST land inside seconds 6.5–7.5. This is the single
  highest-leverage second of the video: viewers decide to rewatch or swipe
  here. Late punchlines (8s+) bleed retention before the loop.
- The consequence must be TANGIBLE, SUDDEN, and PHYSICAL — executed in
  under 2 seconds. Examples: safety foam sprays, gate traps the bumper,
  car locks out, sprinkler triggers, tow truck appears, pump soaks her
  outfit. Purely verbal burns underperform on this channel.
- Karen defeated: slumped, silent, soaked, or escorted past the camera.

### Block F — 7.5–9s LOOP-OUT (max 2 seconds of aftermath, then cut)
- Dead-air ratio is critical: more than ~2s of aftermath after the climax
  causes an instant drop-off curve before the repeat. AI chimes a reset
  phrase ("NEXT CUSTOMER, PLEASE.") matching the opening audio/frame.
  Final frame MUST visually rhyme with frame 1 (same angle on the AI
  device, Karen re-entering frame) — verified post-generation by
  `loop_check.py` (first/last frame similarity ≥0.85). Replays must feel
  infinite — loopability (r=0.82 vs views) is the strongest single signal.

### Block G — Audio & text rules (playback-weighted: audio = retention anchor)
- Second 0: ONE crisp Foley transient (glass crack, horn blip, sharp gasp).
  Prefer a mute-drop (sudden ambient hush) INTO the Foley hit — it triggers
  an involuntary orienting reflex. NO gradual ambient fade-ins.
- SFX over music beds: naturalistic Foley + CCTV beep/static keeps the
  surveillance realism. NEVER a loud royalty-free upbeat track (breaks the
  CCTV feel) and NEVER harsh alarm blasts (viewers swipe past harshness).
- CCTV current-hum bed at low level is fine; keep dynamic range
  mobile-safe (no clipping on phone speakers).
- NEVER a silent stretch >1s.
- On-screen text: max 3 overlays total, each ≤6 words, high-contrast
  yellow/white with black stroke, ALL in the top-middle third (safe zone).
  Burned-in subtitles for Karen's key rant line (post-processed; 60%+ watch
  muted).
- Hard cuts only. NO slow motion, NO fade-to-black, NO static text-only
  openings.

## 2. Negative list (hard bans)

1. No run time over 12 seconds — target 9–11s.
2. No slow/establishing opening shot — conflict must be visible in frame 1.
3. No black screen, no fade transitions between beats — hard cuts only.
4. No silent segments longer than 1 second.
5. No photorealistic horror/dark grading — bright CCTV daylight look only.
6. No Karen winning. She ALWAYS loses. Instant karma is the brand.
7. No purely verbal insult battles — the machine MUST deliver a concrete,
   physical consequence (spray, lock, trap, soak, tow).
8. No generic "AI robot" — always the specific everyday device of the
   episode.
9. No dialogue longer than one short sentence per beat — Shorts are watched
   on mute; the visual must carry the joke.

## 3. Title template (viral formula, data-backed)

Pattern: `[Action emoji] [Everyday tech context] Karen + [PHYSICAL karma verb]! + [Reaction emoji] #Shorts #instantkarma`
- Statement, never a question (data: questions underperform 6% vs 13%).
- Front-load the tension: the exact comedy scenario must be clear in the
  first 40–50 characters (feed viewers decide on the title too).
- 50–70 characters. CAPS on the karma verb. 1–2 hashtags, must include
  #Shorts.

Physical karma verb bank — tiered by Ask Studio (2026-10-06):
concrete slapstick verbs BEAT abstract hyperbole. Verb intensity must match
the visual payoff magnitude (promising DESTROYED then showing a mild spray
breaks trust and tanks retention at second 4–5).

- **Tier S (use these)**: `TRAPPED, SLAPPED, SOAKED, TOWED, FLOODED,
  TRIPPED, LOCKED, BOOTED, SPRAYED` — sudden physical retribution /
  entrapment; creates "HOW does she get trapped?" curiosity.
- **Tier B (acceptable)**: `CAUGHT, EXPOSED, BUSTED, MUTED, SNITCHED,
  SHUT DOWN, KICKED OUT, CANCELLED`.
- **BANNED (abstract clickbait)**: `DESTROYED, ANNIHILATED, OBLITERATED,
  DEMOLISHED` — rejected at upload gate.

Everyday tech contexts: smart pump, automated gate, self-checkout,
drive-thru speaker, HOA camera, parking kiosk, elevator panel.

### 5 examples
1. ⛽ Smart Pump LOCKED Karen's Tank After 3 Taps! 😱💦 #Shorts #instantkarma
2. 🛑 Automated Gate TRAPPED Karen's Car Bumper! 🤣🚗 #Shorts #instantkarma
3. 🛒 Self-Checkout SOAKED Karen's Coupon Scam! 🤖💸 #Shorts #instantkarma
4. 🔊 Drive-Thru Speaker MUTED Karen Mid-Rant! 😂🎙️ #Shorts #instantkarma
5. 🚗 HOA Camera TOWED Karen's Car While She Yelled! 🤣🚨 #Shorts #instantkarma

## 4. Description template

```
{title}

Karen vs AI — watch Karen get instant karma! 😂
Caught on cam: {one-line episode recap with a physical detail}.
#Shorts #AICustomerService #Comedy #TechHumor
```

Rules: first line = title (YouTube shows it in search). Include 2+ of the
high-frequency words (karma/caught/instant) in natural sentences. 3–4
specific niche hashtags (Ask Studio: #Shorts #AICustomerService #Comedy
#TechHumor — helps the testing pool match the right audience). Keep under
150 characters so nothing truncates on mobile.

## 5. Posting checklist (before Marvis uploads)

- [ ] privacyStatus = public (NOT private — caused the 2026-10-06 zero-view incident)
- [ ] Duration 9–11s (Ask Studio: 15s is too long for this channel)
- [ ] Title matches formula: [emoji] tech context + Karen + PHYSICAL karma verb! + [emoji], ≤70 chars, front-loads conflict in first 40–50 chars
- [ ] Description: 1–2 sentence recap + #Shorts #AICustomerService #Comedy #TechHumor
- [ ] Assigned to a series playlist ("Karen vs AI")
- [ ] First frame = conflict (spot-check the upload preview)
- [ ] Pinned engagement comment posted after upload ("Who was more out of line here: Karen or the machine? 👇") — breaks the 0-view threshold

## 6. Zero-view response (Ask Studio guidance)

For small-to-mid channels (~500 subs), 0 views for 6–48h is normal testing-pool
delay, not suppression. If a Short is public 6h+ with 0 views:
1. Sharpen the title hook (conflict in first 40–50 chars).
2. Add focused niche metadata (4 hashtags above).
3. Seed engagement: pinned comment + 1 like.
Do NOT delete and reupload — it resets the testing pool.
