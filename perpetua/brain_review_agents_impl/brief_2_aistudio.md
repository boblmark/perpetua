# Brain ② AI Studio（总工程师）— 调用简报：落地方案详细实施步骤

> 前置依赖：需先拿到 LMArena 判决（`lmarena.md`）。
> 提问时把 LMArena 判决全文复述（协议要求：大脑互不相识）。

## browser.spawn_task 参数
- **initial_url**: `https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash`
- **task**：见下方 "Task 正文"（先把 lmarena.md 全文填入占位符）

## Task 正文

```
In Google AI Studio (already logged in), open a new chat with the FREE model
(Gemini 3.8 Flash or similar free tier — do NOT use any model marked Paid,
do NOT create an API key, do NOT start any paid plan). Send this exact prompt,
wait for the complete response, bring it back verbatim.

Prompt:

"CONTEXT: An AI agent runs on a Linux VM (user 'hatch', home /home/hatch).
Its workspace data lives in /home/hatch/data/. It previously suffered two
disasters: (1) a shared YouTube OAuth token revoked by mistake killing three
integrations for 30 min; (2) an important prompt file written only to /tmp
and lost when /tmp was wiped. A jury (two models, LMArena Side-by-Side)
reviewed the proposed 4-component implementation plan. Their verdict:

---
<粘贴 lmarena.md 全文：完整性结论 / 风险评估 / 优先级排序 / KEEP-MODIFY-DROP 投票>
---

YOUR TASK — write DETAILED, COPY-PASTE-READY implementation steps for each
component, in the jury's priority order. Output ONLY executable content.
No advice, no explanations, no hedging.

For EACH component, give exactly these four blocks:

COMPONENT <N>: <name>
COMMANDS:
<exact shell commands to implement, one per line, with sudo where needed>
CONFIG:
<exact file contents to write, with absolute paths, e.g.
/etc/profile.d/agent-env.sh:
---
<file content>
---
>
ROLLBACK:
<exact commands to fully undo this component, one per line>
VERIFY:
<exact command whose output proves the component is active, plus what
'good' output looks like, e.g.:
  $ touch /tmp/probe && echo FAIL || echo OK(readonly)
  expected: OK(readonly)>

Then a final section:

ORDER OF EXECUTION:
1. <component> — why first (one line, reference jury ROI ranking)
2. <component> — ...
TEST PLAN (end-to-end):
- <one command simulating Disaster-2 pattern, expected blocked/redirected>
- <one command simulating Disaster-1 pattern, expected canary+rollback>

Rules: every command must be runnable as-is on Ubuntu/Debian Linux. If a step
needs a value you cannot know (e.g. a token), write <FILL: description>.
Do NOT invent services that do not exist. systemd unit files must be valid
INI. Go."

Do NOT create any API key, do NOT start any paid plan, do NOT change settings.
Report the full response verbatim.
```

## 要点（给执行者）
- URL 已预置免费模型 gemini-3.8-flash；明确禁止付费/建 key
- 要求可直接执行的命令+配置+回滚+验证；出现空洞建议（无具体命令）打回重问
- 答案 verbatim 存入 `aistudio.md`
- 注意：这是 infra Tier 3 变更，评审只给技术结论，不代替用户批准——执行者（父级）不要自行应用，只存档
