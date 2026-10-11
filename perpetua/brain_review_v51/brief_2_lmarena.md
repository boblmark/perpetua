# Brain ② LMArena（陪审团）— 调用简报

> 前置依赖：需先拿到 Ask Studio 的诊断（`ask_studio.md`）。
> 提问时把 Ask Studio 诊断全文复述（协议要求：三脑互不相识）。

## browser.spawn_task 参数

- **initial_url**: `https://arena.ai`
- **task**（完整，复制即用）：见下方 "Task 正文"

## Task 正文

```
On LMArena (already logged in), use Side-by-Side mode with two named models
(not anonymous Battle — this is an important decision). Send this exact prompt
and wait for both responses, bring them back verbatim.

Prompt:

"You are judging video-generation prompt designs for a YouTube Shorts comedy
channel ('Karen vs AI', 532 subs, 8-second vertical videos, Veo-generated).

DATA DIAGNOSIS from a channel-analytics advisor (Ask Studio, verbatim):
---
<粘贴 ask_studio.md 全文>
---

TWO PROMPT VERSIONS TO COMPARE:

Version v5 (current production):
- Frame 0: tight close-up of Karen mid-expression (peak facial tension)
- Audio: 0.00s at 70% volume with vocal onset, ramps to peak by 2.00s
- Ban: peak-volume Foley at 0s, giant explanatory titles, wide shots in 0-2s
- Structure: 0-2s hook / 2-6s escalation / 6-7s physical karma / 7-8s loop-out

Version v5.1 (adds three modules on top of v5):
- (1) EXTREME CLOSE-UP OPENING: first frame Karen's face fills ≥50% of frame
- (2) MOTION QUANTIFICATION: head/upper body moves ≥20% of frame width every
  second, never still >0.3s, constant handheld shake ±10px, motion blur desired
- (3) LOOP PRE-BURIAL: final 0.5s returns to exact opening pose, 8s = one
  complete oscillation (lunge 0-3s, recoil 3-6s, lunge 6-8s)

Judge on:
(1) Which version is more likely to lift first-3-second retention, and why?
(2) Vote on each of the three v5.1 modules separately: KEEP / MODIFY / DROP.
    For MODIFY, say exactly what to change. For DROP, say why it hurts.
(3) The v5.1 test video's QC found: motion peak at 1.2s instead of the 6.5-7.5s
  climax window, and a flat climax. Does any v5.1 module cause or worsen this?
  If yes, which one and how to fix?

Pick an overall winner (v5 or v5.1) and give the module-by-module verdict.
Be concrete and decisive — no hedging."

Do NOT click any vote buttons. Do NOT change modes or settings.
Report BOTH models' full responses verbatim, labeled clearly.
```

## 要点（给执行者）
- 必须用 Side-by-Side 指定模型，禁用匿名 Battle（重大决策）
- 不点投票按钮（保持中立）
- 两个模型的回答都要 verbatim 带回，分别标注
- 答案存入 `lmarena.md`（两个模型的完整原文）
- 若任一模型只给建议不给判决，打回重问
