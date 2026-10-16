# Viral Shorts Prompt Template — @karenvsai ("Karen vs AI") — v5 (four-brain council 2026-10-08)

Data-driven. Derived from 490 channel videos (criteria.json v3) + YouTube
Analytics signals + Ask Studio audits + LMArena jury + Google AI Studio
spec authoring + NotebookLM gap review (2026-10-08).
All prompts MUST be in English (channel is EN).

## v5 changes (2026-10-08 four-brain council: "publish = viral" roadmap)
LMArena adjudicated a direct conflict: v4's "peak volume at 0.00s" vs
Ask Studio's "peak volume triggers ad/bot instinct → instant swipe".
Verdict: intensity is THREE independent channels, not one knob.
"1.2-Second Karen Snap" reconciled formula:
- Visual MAX: tight close-up of Karen mid-expression, high contrast
- Audio MID→ESCALATE: start 70% with recognizable vocal onset, ramp to peak by 2.00s
  (ENFORCED IN POST: postprocess_video.py audio_envelope step applies
  ffmpeg volume='if(lt(t,2),0.7+0.15*t,1)' — Muse Video accepts no audio
  input, so the prompt alone cannot guarantee this; verified 2026-10-08
  with sine-tone test: -23.3dB@0-1s → -21.8dB@1-2s → -21.1dB@2s+)
- Text MAX: ≤6-word premise hook on screen for the full 0-2s window
Changes:
1. **Block C rewritten**: audio NEVER starts at peak (v4 was wrong on this);
   70%→100% ramp synced to visual expression peak.
2. **Block G rewritten**: no music/SFX/silence may mask the vocal onset in 0-2s.
3. Version bumped v4 → v5. (NotebookLM's "algorithmic poisoning" claim was
   verified FALSE by direct API check — channel keywords/tags are clean.)

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

### Block C — 0–2s HOOK ENGINE (1.2-Second Karen Snap, v5)
Rules, all mandatory (v5, LMArena jury verdict 2026-10-08):
- [VISUAL] MUST open at frame 0.00s on a tight close-up of Karen
  mid-expression (peak facial tension: disbelief, outrage, or confusion —
  NOT generic screaming), high-contrast lighting.
- [VISUAL] NEVER show wide shots, establishing scenes, logos, or fade-ins
  in Block C. Camera NEVER pulls back before 2.00s.
- [AUDIO] MUST begin at 70% volume (mid-level, NOT max) with an instantly
  recognizable vocal onset (e.g. "Excuse me—", "No, no, NO—"). The onset
  creates curiosity, not alarm.
- [AUDIO] MUST ramp volume continuously to peak by second 2.00s.
- [AUDIO] NEVER start at peak volume or silence. (v4's "peak at 0.00s" was
  overturned: it triggers viewers' ad/bot instinct → instant swipe.)
- [TEXT] MUST display premise hook on screen at 0.00s: MAX 6 words,
  upper-third placement, high-contrast, visible for the ENTIRE 0-2s window.
- [TEXT] NEVER exceed 6 words; NEVER placeholder titles or generic CTAs.
  Subtitles show spoken dialogue ONLY — NEVER meta-titles, scene labels,
  "POV", "Wait for it", or character names.
- **UI SAFE ZONE: all key text and the visual gag MUST sit in the top-middle
  third of the frame.** NEVER place critical text/info on the right edge
  (engagement icons) or bottom 25% (title/channel overlay truncates it).
  CCTV timestamp HUD goes top-LEFT corner only.
- Movement in every frame — nothing static.

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
  `loop_check.py` (first/last frame similarity ≥0.75; 0.85 实测不可达，
  已校准). Replays must feel
  infinite — loopability (r=0.82 vs views) is the strongest single signal.

### Block G — Audio & text rules (SYNC TO 1.2s SNAP, v5)
Rules, all mandatory (v5, AI Studio spec from four-brain council):
- [AUDIO SYNC] MUST sync the mid→escalate audio ramp (70%→peak by 2.00s)
  to the visual expression peak.
- [AUDIO SYNC] NEVER allow background music, SFX, or silence to mask the
  vocal onset in 0.00s–2.00s.
- **TTS voice direction (v5)**: Karen's voice starts at 70% — recognizable,
  indignant, human — then escalates to unhinged screech by 2.00s. The ramp
  IS the hook: curiosity first, alarm second. NEVER monotone narration.
  AI voice stays deadpan-calm (contrast IS the joke). Specify emotion beats:
  e.g. "Karen's voice: indignant (70%) → shrill (escalating) → defeated whimper."
- [TEXT SYNC] MUST keep on-screen premise hook (≤6 words) visible for the
  entire 0.00s–2.00s window.
- [TEXT SYNC] MUST reinforce the visual premise; NEVER contradict the facial
  expression or vocal onset.
- Subtitles MUST contain spoken dialogue ONLY. NEVER meta-titles, scene
  labels, captions, or contextual markers (NEVER "Karen vs AI", "POV",
  "Wait for it", character names).
- Max 3 overlays total, each ≤6 words, high-contrast yellow/white with
  black stroke, ALL in the top-middle third (safe zone). Burned-in
  subtitles for Karen's key rant line (post-processed; 60%+ watch muted).
- SFX over music beds: naturalistic Foley + CCTV beep/static keeps the
  surveillance realism. NEVER a loud royalty-free upbeat track (breaks the
  CCTV feel) and NEVER harsh alarm blasts (viewers swipe past harshness).
- CCTV current-hum bed at low level is fine; keep dynamic range
  mobile-safe (no clipping on phone speakers).
- NEVER a silent stretch >1s.
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

Pattern: `[Action emoji] [Everyday tech context] Karen + [PHYSICAL karma verb]! + [Reaction emoji] #Shorts #Comedy #Viral`
- Statement, never a question (data: questions underperform 6% vs 13%).
- Front-load the tension: the exact comedy scenario must be clear in the
  first 40–50 characters (feed viewers decide on the title too).
- 50–70 characters for the title proper. CAPS on the karma verb.
- 3–5 hashtags at the end, MUST include #Shorts (feed categorization signal,
  D2/D3 2026-10-08: jury mandates explicit Shorts-feed hooks). Suggested set:
  #Shorts #Comedy #Viral + 1–2 topical (e.g. #instantkarma #TechHumor).

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

## 进化附录 2026-10-15

每日复盘发现（自动写入）：
- 2 条 RED（teaser 未达 AVD≥75%+views≥30）：检查钩子/前3秒与发布时间

## 进化附录 2026-10-15

每日复盘发现（自动写入）：
- 2 条 RED（teaser 未达 AVD≥75%+views≥30）：检查钩子/前3秒与发布时间

## 进化附录 2026-10-16（每日进化议会首轮 D20261015-010，红队 R2 修订）

**实证标题 pattern（加权候选，非强制）**：Gas Nozzle（139.3% 完播，重播极多）验证有效。
结构：`{emoji} Karen {过去式物理报应动词} The {道具名词} {现在分词截断短句}…`
示例：`⛽ Karen Yanked The Gas Nozzle Demanding A Dis…`
用法：每日 6 个选题中约 2 个采用此结构，其余保持多样性（红队 KILL：全量复用=同质化互食+品牌风险）。
注意：2026-10-15 的"2 RED" headline 已被证伪（一条系翻转脏数据误判），此前基于该结论的进化条目冻结，不再追加同类。
