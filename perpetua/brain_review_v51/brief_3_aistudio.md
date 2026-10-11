# Brain ③ AI Studio（总工程师）— 调用简报

> 前置依赖：需先拿到 Ask Studio 诊断（`ask_studio.md`）和 LMArena 判决（`lmarena.md`）。
> 提问时把两份结论全文复述（协议要求：三脑互不相识）。

## browser.spawn_task 参数

- **initial_url**: `https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash`
- **task**（完整，复制即用）：见下方 "Task 正文"

## Task 正文

```
In Google AI Studio (already logged in), open a new chat with the FREE model
(Gemini 3.8 Flash or similar free tier — do NOT use any model marked Paid,
do NOT create an API key, do NOT start any paid plan). Send this exact prompt,
wait for the complete response, bring it back verbatim.

Prompt:

"Two AI advisors reviewed my video-generation prompt. Their conclusions:

1. CHANNEL DIAGNOSIS (Ask Studio, verbatim):
---
<粘贴 ask_studio.md 全文>
---

2. JURY VERDICT (LMArena, both models verbatim):
---
<粘贴 lmarena.md 全文>
---

MY PIPELINE:
- Template file: viral_prompt.py, function build_viral_prompt()
- Current constants: V51_CLOSEUP_OPENING, V51_MOTION_QUANT, V51_LOOP_SEED
  (the three v5.1 modules), plus v5 base (FORMAT_LOCK_VEO, AUDIO_RULES, etc.)
- QC gate: pre_upload_qc.py, experience_score 100-point, <60 rejects

YOUR TASK — write the v5.2 spec delta. Output ONLY constants, no advice:

A. KEEP: list which v5.1 modules stay exactly as-is (name them).
B. MODIFY: for each module to change, give the EXACT replacement text,
   terse and imperative, copy-paste ready, with clear MUST/NEVER directives.
C. ADD: any brand-new MUST/NEVER clauses the two advisors jointly imply
   (e.g. a climax-intensity rule if both flagged the flat climax).
   Each new clause: one sentence, MUST or NEVER, with a number where possible.

Format:
KEEP: <names>
MODIFY <NAME>:
<replacement text>
ADD:
- <clause>
- <clause>

No explanations. No suggestions. Only the spec text."

Do NOT create any API key, do NOT start any paid plan, do NOT change settings.
Report the full response verbatim.
```

## 要点（给执行者）
- URL 已预置免费模型 gemini-3.8-flash；明确禁止付费/建 key
- 要求输出"可粘贴条文"而非解释；出现建议性措辞打回重问
- 答案存入 `aistudio.md`（完整原文）
