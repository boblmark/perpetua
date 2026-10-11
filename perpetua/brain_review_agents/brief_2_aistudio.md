# Brain ② AI Studio（总工程师）— 调用简报

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

"An AI agent's self-governance doc (AGENTS.md) failed to prevent two disasters:

DISASTER 1: External agent told to revoke YouTube OAuth; nobody verified
three systems shared one authorization. 30-min total outage. (Unknown risk.)

DISASTER 2: Prompt file written only to /tmp. Risk was explicitly documented
('/tmp not persistent, must persist to /home/hatch/data/perpetua/') and ranked
todo #2 — but nobody acted before /tmp was wiped. (Known risk, delayed action.)

JURY VERDICT from two models on LMArena (verbatim):
---
<粘贴 lmarena.md 全文>
---

YOUR TASK — write the EXECUTABLE prevention mechanism. Not document prose.
Output ONLY buildable spec:

A. PARADIGM: name the winning paradigm (A/B/C) and one sentence on why it
   beats the others against the 'known-but-delayed' pattern.

B. GUARD SPEC (if B won) — for each guard, give:
   - TRIGGER: exact condition (e.g. 'any write() call where path startswith
     /tmp/ AND file_type in [prompt, config, key]')
   - ACTION: block | redirect | require-confirmation (pick one, justify in
     5 words)
   - LOCATION: which function/file to wrap (e.g. 'muse.write', 'muse.exec
     with > redirection', 'cron body interpreter')
   - BYPASS: who can bypass and how (must be explicit; 'nobody' is valid)

   If C won instead, give:
   - STRUCTURE CHANGE: exact step (e.g. 'mount /tmp noexec for agent uid',
     'remove raw exec path for rm/revoke, force via safe_rm tool')
   - MIGRATION: what breaks and how to handle it (one line per breakage)

C. DEADLINE MECHANISM (mandatory): a known risk going from IDENTIFIED to
   ELIMINATED must have a forced clock. Specify:
   - MAX_AGE: hours from identification to elimination (give a number)
   - TRACKER: where the open risk lives (file + schema, e.g.
     risk_register.json: [{id, identified_at, deadline, owner}])
   - ESCALATION: what happens at deadline breach (e.g. 'block all Tier-2+
     ops until cleared', 'page user', 'auto-apply safest remediation')
   Pick concrete values. No 'should be timely'.

D. DISASTER-1 COVERAGE: state plainly whether your mechanism would have
   caught the unknown-shared-credential case. If yes: which component and
   how. If no: what DETECTION/ROLLBACK mechanism you add instead
   (e.g. 'pre-revoke snapshot + 5-min canary + auto-rollback on health
   check failure'), with the same TRIGGER/ACTION/LOCATION format.

Format:
PARADIGM: <A/B/C> — <one sentence>
GUARD 1:
  TRIGGER: ...
  ACTION: ...
  LOCATION: ...
  BYPASS: ...
DEADLINE:
  MAX_AGE: ...
  TRACKER: ...
  ESCALATION: ...
DISASTER-1: ...

No explanations. No suggestions. Only the spec."

Do NOT create any API key, do NOT start any paid plan, do NOT change settings.
Report the full response verbatim.
```

## 要点（给执行者）
- URL 已预置免费模型；禁付费/建 key
- 要求可执行规格；出现空洞建议打回重问
- 答案 verbatim 存入 `aistudio.md`
