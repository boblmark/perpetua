# Browser 调用配方（三脑议会）

三脑都用 `browser.spawn_task` 调起，`initial_url` 直达各自入口。
浏览器 profile 共享登录态（bat08738@gmail.com），一般无需重复登录。

## ① Ask Studio（传感器）

```python
browser.spawn_task(
    initial_url="https://studio.youtube.com",
    task="""In YouTube Studio (already signed in, channel "Mark Bobl | Karen vs AI"),
open the Ask Studio panel and ask this exact question. Wait for the complete
answer and bring it back verbatim.

Question:
<带上实时数据的问题，示例：>
"Here is my channel's LIVE data from the last 7 days (26 Shorts): average
viewed 56.8% (target 110%+), total shares 0. <具体问题>"

If login expired, sign in with bat08738@gmail.com. If CAPTCHA/2FA blocks,
stop and report. Report the FULL answer verbatim.""",
)
```

要点：问题里必须带实时数据；要求 verbatim 带回全文；问完清空输入框。

## ② LMArena（陪审团）

```python
browser.spawn_task(
    initial_url="https://arena.ai",
    task="""On LMArena (already logged in), use Direct mode (1 model) or
Side-by-Side (2 named models) for important decisions. Send this exact prompt
and wait for the complete response, bring it back verbatim.

Prompt:
<带上 Ask Studio 诊断 + 2-N 个待横评方案，示例：>
"You are advising <背景>. A data diagnosis found: <诊断>.
Compare these TWO approaches and tell me which is stronger and why:
Approach A — <方案A>
Approach B — <方案B>
Judge on: (1) <标准1>, (2) <标准2>, (3) <标准3>.
Pick a winner and give 3 concrete rules for <应用场景>."

Do NOT click any vote buttons. Do NOT change modes or settings.
Report the full response verbatim.""",
)
```

要点：不点投票按钮（保持中立）；重大决策用 Side-by-Side 指定模型而非匿名 Battle。

## ③ AI Studio（总工程师）

```python
browser.spawn_task(
    initial_url="https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash",
    task="""In Google AI Studio (already logged in), open a new chat with the
FREE model (Gemini 3.8 Flash or similar free tier — do NOT use any model
marked Paid, do NOT create an API key). Send this exact prompt, wait for the
complete response, bring it back verbatim.

Prompt:
<带上前两步结论 + 要落笔的位置，示例：>
"Two AI advisors concluded: 1. <诊断> 2. <判决+规则>.
My pipeline uses <模板结构>. Write me the exact replacement text for
<section> implementing the rules above. Keep it terse, imperative,
copy-paste ready — no explanations, just the template text with clear
MUST/NEVER directives."

Do NOT create any API key, do NOT start any paid plan, do NOT change settings.
Report the full response verbatim.""",
)
```

要点：URL 里预置免费模型；明确禁止付费/建 key；要求输出"可粘贴条文"而非解释。

## 会诊记录模板

每次三脑会诊后，在 `/home/hatch/data/ask_studio/` 下存档（沿用现有习惯）：

```json
{
  "date": "2026-10-08",
  "topic": "前3秒留存瓶颈",
  "live_data": "26条/7天, 平均观看56.8%, 分享0",
  "ask_studio": "诊断摘要...",
  "lmarena": "判决: A方案胜 + 3条规则",
  "ai_studio": "Block C/G 替换文本",
  "landed": "viral_prompt_template.md v4",
  "verdict": "三脑一致通过"
}
```
