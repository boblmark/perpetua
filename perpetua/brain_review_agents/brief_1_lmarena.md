# Brain ① LMArena（陪审团）— 调用简报

## browser.spawn_task 参数
- **initial_url**: `https://arena.ai`
- **task**：见下方 "Task 正文"（完整，复制即用）

## Task 正文

```
On LMArena (already logged in), use Side-by-Side mode with two named models
(not anonymous Battle — this is an important decision). Send this exact prompt
and wait for both responses, bring them back verbatim.

Prompt:

"You are reviewing an AI agent's self-governance document (AGENTS.md) that
failed to prevent two real disasters. Judge which prevention paradigm would
actually work.

THE DOCUMENT (relevant rules, verbatim):

Rule 1 — Verify blast radius before destructive ops (from YouTube OAuth disaster):
Before revoking/deleting/disabling any credential, token, or permission, must answer:
1. Who else uses this credential? (check all machines, processes, agents)
2. Is it shared? (diff files / check process env / ask user)
3. Is there a rollback plan? (backup old credential, confirm recovery)
If unanswerable — DO NOT ACT.

Rule 2 — Operation tiers:
- Tier 0 read-only: free.
- Tier 1 reversible writes: execute + log.
- Tier 2 high-impact (send external messages, change cron, change prod code):
  'mentally check blast radius' before executing, log after.
- Tier 3 catastrophic (delete data, revoke credentials, public upload, infra
  changes): MANDATORY checklist + explicit user approval of that specific op.

Rule 3 — No important files in /tmp (from prompt-loss disaster):
prompts, configs, keys, pending-release videos, anything needed across
sessions MUST go directly to /home/hatch/data/ or ~/workspace/.
/tmp is only for truly disposable intermediates.

DISASTER 1 (2026-10-08 01:39, YouTube OAuth):
Instructed an external agent (Marvis) to revoke YouTube OAuth to cut its
independent upload path. Never verified that Dash/Marvis/VPS-dispatcher shared
one authorization. All three integrations died for 30 minutes; user had to
manually re-authorize at night.
Nature: UNKNOWN RISK — nobody knew it was shared beforehand.
Rule 1 was added AFTER.

DISASTER 2 (2026-10-08, prompt file loss):
A video-generation prompt was written only to /tmp/veo_prompt_v51.txt.
A session summary explicitly noted '/tmp is not persistent, must save to
/home/hatch/data/perpetua/' and ranked it todo #2. But nobody acted before
/tmp was wiped. File permanently lost locally (later recovered from a VM copy,
by luck).
Nature: KNOWN RISK, NOT ACTED ON IN TIME — identified, documented,
prioritized, but delayed until it was too late.
Rule 3 was added AFTER.

THE CORE CONTRADICTION:
AGENTS.md is currently hindsight wisdom: both rules were added AFTER their
disasters. The document itself does not execute; it relies on the agent's
self-discipline to remember and obey.
- Disaster 1: risk was unknown, so no rule could have prevented it.
- Disaster 2: risk was known and documented, but the rule (as text) could not
  fight procrastination.

THREE PREVENTION PARADIGMS TO COMPARE:

Paradigm A — Document checklist (status quo):
Keep rules as text in AGENTS.md. Rely on the agent reading, remembering,
and obeying them at the right moment.
(Evidence: Disaster 2 proves this fails — the risk was IN the summary,
ranked #2, and still not acted on.)

Paradigm B — Automated pre-guards:
Enforce rules with code that runs BEFORE the risky action. Examples:
- A file-write wrapper that intercepts writes of important file types to /tmp
  and redirects or blocks them.
- A Tier-3 gate script that refuses to run the destructive command until the
  checklist answers are recorded (not just 'mentally checked').

Paradigm C — Structural elimination:
Make the bad action impossible or pointless by design. Examples:
- Make /tmp unwritable for the agent's file tools (only disposable scratch
  via a separate explicit API).
- Route all destructive ops through a dedicated tool that embeds the
  checklist — there is no 'raw command' path to bypass.

YOUR JUDGMENT:
(1) Which paradigm best solves the 'KNOWN risk but DELAYED action' failure
    (Disaster 2's exact pattern)? Why? Be specific about the mechanism —
    what exactly forces timely action that text alone cannot?
(2) Vote on each paradigm: KEEP / MODIFY / DROP as the primary prevention
    strategy. For MODIFY, say exactly what to change. For DROP, say why it
    fails against the Disaster-2 pattern.
(3) Can ANY paradigm have prevented Disaster 1 (unknown shared credential)?
    If yes, which one and through what mechanism? If no, say so directly —
    some failures may be unpreventable by design and only mitigable
    (e.g. faster detection/rollback).

Pick an overall winner. Be concrete and decisive — no hedging, no generic
advice like 'improve awareness'."

Do NOT click any vote buttons. Do NOT change modes or settings.
Report BOTH models' full responses verbatim, labeled clearly.
```

## 要点（给执行者）
- 必须 Side-by-Side 指定模型，禁匿名 Battle（重大决策）
- 不点投票按钮
- 双模型回答 verbatim 存入 `lmarena.md`
- 若只给建议不给判决，打回重问
