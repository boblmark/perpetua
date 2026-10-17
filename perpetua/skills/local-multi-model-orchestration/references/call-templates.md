# 调用模板

## LMArena 横评模板

```
On LMArena (already logged in), use Side-by-Side mode with two named models
(not anonymous Battle — this is an important decision). Send this exact prompt
and wait for both responses, bring them back verbatim.

Prompt:

"[背景：具体事实]
[T待评审对象]
[你的判断要求：be concrete, no hedging, no generic advice]
[输出格式：明确列出要回答的编号问题]
[投票：KEEP / MODIFY / DROP 的定义]"

Do NOT click any vote buttons. Do NOT change modes or settings.
Report BOTH models' full responses verbatim, labeled clearly.
```

要点：
- 必须具名模型 Side-by-Side，禁匿名 Battle（重大决策要可追溯）
- 不点投票按钮（只收集文字，不做平台内投票）
- 双模型 verbatim，标清楚哪个是哪个

## AI Studio 规格模板

```
In Google AI Studio (already logged in), open a new chat with the FREE model
(Gemini 3.8 Flash or similar free tier — do NOT use any model marked Paid,
do NOT create an API key, do NOT start any paid plan). Send this exact prompt,
wait for the complete response, bring it back verbatim.

Prompt:

"CONTEXT: [前置结论，如 LMArena 的判决，没有就写无]
YOUR TASK: [要输出的具体内容，如 COMMANDS/CONFIG/ROLLBACK/VERIFY]
Output ONLY concrete implementation content. No generic advice, no hedging."
```

要点：
- 免费档，不建 key，不付费
- 把上游大脑的结论喂进去（大脑互不相识，靠你传话）

## 串行调度顺序

```
1. LMArena（陪审团）：先定方向（KEEP/MODIFY/DROP）
2. AI Studio（工程师）：基于 LMArena 结论出可执行规格
3. 你写 verdict.md：综合 + 分歧处理
```

不要并行：B 需要 A 的输出做输入。
