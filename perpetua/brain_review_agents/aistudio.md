# Brain ② AI Studio 回答原文（2026-10-08 11:59 CST）
# Model: Gemini 3.8 Flash (免费档)

PARADIGM: C — Structural elimination prevents the known-but-delayed pattern by substituting kernel- and schema-level execution barriers for agent or human follow-through.

STRUCTURE CHANGE:
1. Mount /tmp as ro inside the agent user's Linux mount namespace and set TMPDIR=/home/hatch/data/perpetua/tmp/.
2. Remove raw revoke and rm binaries from the agent PATH; route credential lifecycles exclusively through a credential isolation proxy that enforces 1-agent:1-token identity isolation.

MIGRATION:
- Agent commands writing to /tmp fail with EACCES -> Redirect default script temp paths by exporting TMPDIR=/home/hatch/data/perpetua/tmp/ in /etc/profile.d/agent-env.sh.
- Direct OAuth revocation API calls fail with blocked route -> Rewire revocation calls to /usr/local/bin/credential-proxy revoke --client-id <id> which only acts on identity-isolated credentials.

DEADLINE:
  MAX_AGE: 24
  TRACKER: /etc/agent-governance/risk_register.json
    schema: [{"id": "string", "identified_at": "ISO-8601-UTC", "deadline_hours": 24, "remediation_state": "OPEN|ENFORCED", "owner": "string"}]
  ESCALATION: Systemd timer /etc/systemd/system/risk-gate.timer runs hourly; if (now - identified_at) > 24 hours and remediation_state == "OPEN", it executes systemctl stop agent.service and revokes the agent's runtime bearer token until signed human intervention clears the register.

DISASTER-1: No.
  TRIGGER: Revocation API call received by credential proxy.
  ACTION: Snapshot token; inject 300-second soft-disable mock; execute automated canary health checks against all dependent service endpoints; if any endpoint returns HTTP 401/403/5xx, auto-abort revocation and restore token; if all return 200 after 300 seconds, execute upstream hard revocation.
  LOCATION: /usr/local/bin/credential-proxy (pre-execution interceptor middleware).
