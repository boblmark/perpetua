# Brain ① LMArena（陪审团）— 调用简报：评审 AGENTS.md 灾难预防落地方案

## browser.spawn_task 参数
- **initial_url**: `https://arena.ai`
- **task**：见下方 "Task 正文"（完整，复制即用）

## Task 正文

```
On LMArena (already logged in), use Side-by-Side mode with two named models
(not anonymous Battle — this is an important decision). Send this exact prompt
and wait for both responses, bring them back verbatim.

Prompt:

"You are reviewing an IMPLEMENTATION PLAN for an AI agent's disaster-prevention
system. A previous jury already picked the winning paradigm (Structural
Elimination, Paradigm C). Now judge whether the concrete implementation plan
is complete, safe, and correctly prioritized.

BACKGROUND — TWO REAL DISASTERS:
- Disaster 1 (2026-10-08 01:39): An external agent was told to revoke YouTube
  OAuth; nobody verified three systems shared one authorization. 30-minute
  total outage (data/analytics/comments/upload/audit all down). Nature: UNKNOWN
  RISK. Lesson: credentials must be isolated per actor (1-agent:1-token).
- Disaster 2 (2026-10-08): A video-generation prompt was written only to
  /tmp/veo_prompt_v51.txt. The risk was explicitly documented ('/tmp is not
  persistent') and ranked todo #2 — but nobody acted before /tmp was wiped.
  File lost locally (recovered from a VM copy by luck). Nature: KNOWN RISK,
  DELAYED ACTION. Lesson: text rules cannot fight procrastination; the bad
  action must be made physically impossible.

THE IMPLEMENTATION PLAN UNDER REVIEW (4 components):

Component 1 — /tmp read-only mount + TMPDIR redirect:
- Mount /tmp as read-only inside the agent user's Linux mount namespace.
- Set TMPDIR=/home/hatch/data/perpetua/tmp/ (a persistent directory).
- Migration: export TMPDIR in /etc/profile.d/agent-env.sh so scripts that
  respect TMPDIR keep working.

Component 2 — credential-proxy (credential isolation proxy):
- Remove raw revoke/rm binaries from the agent's PATH.
- Route all credential lifecycles through /usr/local/bin/credential-proxy,
  which enforces 1-agent:1-token identity isolation.
- Disaster-1 coverage: on revoke request, snapshot token, inject a 300-second
  soft-disable, run automated canary health checks against dependent service
  endpoints; if any returns 401/403/5xx, auto-abort and restore; only after
  300s of all-200s, execute the real upstream revocation.

Component 3 — risk_register.json + systemd timer (forced deadline):
- TRACKER: /etc/agent-governance/risk_register.json, schema:
  [{id, identified_at (ISO-8601 UTC), deadline_hours: 24,
    remediation_state: OPEN|ENFORCED, owner}]
- MAX_AGE: 24 hours from identification to elimination.
- ESCALATION: a systemd timer (risk-gate.timer) runs hourly; if
  (now - identified_at) > 24h and remediation_state == OPEN, it runs
  systemctl stop agent.service AND revokes the agent's runtime bearer token
  until signed human intervention clears the register.

Component 4 — AGENTS.md update:
- Mark existing Rule 1/2/3 as 'documentation version'.
- Add an 'enforcement version' section pointing at components 1-3.

YOUR JUDGMENT (be concrete, no hedging, no generic advice):

(1) COMPLETENESS: Is this plan complete? Name any missing critical component.
    Specifically: who WRITES entries into risk_register.json (the agent
    itself? a human? an automated scanner)? Who DECIDES a risk is 'eliminated'
    and flips remediation_state to ENFORCED (self-attestation again?)?
    How is credential-proxy itself authenticated — what stops a compromised
    agent from calling the proxy to revoke someone else's token?

(2) RISK ASSESSMENT: For EACH of the 4 components, state its biggest
    implementation risk in one sentence:
    - C1: will read-only /tmp break existing toolchains (pip, build tools,
      libraries that hardcode /tmp)?
    - C2: is credential-proxy a single point of failure? What happens if the
      proxy itself is down during an emergency revoke?
    - C3: will the 24-hour kill-switch misfire on legitimate long-running
      tasks? What is the false-positive cost of stopping agent.service?
    - C4: does relabeling rules as 'documentation' risk agents ignoring the
      doc entirely?

(3) PRIORITY ORDER: Rank the 4 components by effort-to-safety ratio (highest
    ROI first). Which single component, if implemented alone, prevents the
    most damage?

(4) VOTE: whole plan KEEP / MODIFY / DROP?
    - KEEP: plan is sound as-is.
    - MODIFY: state exactly what to add, remove, or change (component-level).
    - DROP: state which flaw is fatal and why no patch fixes it.

Pick winners and give the component-by-component verdict."

Do NOT click any vote buttons. Do NOT change modes or settings.
Report BOTH models' full responses verbatim, labeled clearly.
```

## 要点（给执行者）
- 必须 Side-by-Side 指定模型，禁匿名 Battle（重大决策）
- 不点投票按钮
- 双模型回答 verbatim 存入 `lmarena.md`
- 若只给建议不给判决（无 KEEP/MODIFY/DROP、无线索排序），打回重问
