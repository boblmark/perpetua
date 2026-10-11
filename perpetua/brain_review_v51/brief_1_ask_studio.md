# Brain ① Ask Studio（传感器）— 调用简报

## browser.spawn_task 参数

- **initial_url**: `https://studio.youtube.com`
- **task**（完整，复制即用）：见下方 "Task 正文"

## Task 正文

```
In YouTube Studio (already signed in, channel "Mark Bobl | Karen vs AI"),
open the Ask Studio panel and ask this exact question. Wait for the complete
answer and bring it back verbatim.

Question:

"Context: My channel 'Mark Bobl | Karen vs AI' (532 subscribers) makes scripted
comedy Shorts: a fictional Karen character vs AI devices, ending in slapstick
instant karma. Videos are 8 seconds, vertical 9:16, CCTV aesthetic, generated
by Veo.

LIVE CHANNEL DATA (last 7 days, 18 videos):
- Average viewed: 48.8% (target is 110%+ for loop replays)
- Total shares: 0
- Bottleneck is clearly early retention, not discovery.

PROMPT VERSION HISTORY:
- v5 template (current production): 1.2-Second Karen Snap — frame 0 opens on
  tight close-up of Karen mid-expression; audio starts at 0.00s at 70% volume
  with vocal onset, ramps to peak by 2.00s; no peak-volume Foley at 0s
  (overturned: triggers ad-instinct swipe); ban giant explanatory titles.
- v5.1 (one test video, QC 79/100 PASS): added three modules on top of v5:
  (1) EXTREME CLOSE-UP OPENING — first frame Karen's face fills ≥50% of frame;
  (2) MOTION QUANTIFICATION — head/upper body moves ≥20% of frame width every
  second, never still >0.3s, constant handheld shake ±10px, motion blur desired;
  (3) LOOP PRE-BURIAL — final 0.5s returns to exact opening pose, 8s is one
  complete oscillation cycle (lunge 0-3s, recoil 3-6s, lunge 6-8s).

QC 79/100 WEAKNESSES on the v5.1 test video:
- First-frame central subject slightly weak
- Climax intensity flat
- Motion peak at 1.2s instead of 6.5-7.5s (climax window)

MY QUESTION:
Do v5.1's three new modules hit the actual bottleneck, or do they miss it?
What is the single biggest retention bottleneck right now, stated as a
measurable constant (e.g. 'first X seconds need Y, threshold Z')?
Rank the three v5.1 modules by how much each addresses the bottleneck.

Answer ONLY with constants and rankings. No general advice."

If login expired, sign in with bat08738@gmail.com. If CAPTCHA/2FA blocks,
stop and report. Report the FULL answer verbatim. After getting the answer,
clear the Ask Studio input box.
```

## 要点（给执行者）
- 问题里已带实时数据（18条/48.8%/分享0/532订阅）
- 要求 verbatim 带回全文
- 要求只输出常量和排名，不输出泛泛建议；不合格打回重问
- 答案存入 `ask_studio.md`（完整原文）
