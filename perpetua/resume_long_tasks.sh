#!/bin/bash
# resume_long_tasks.sh -- resume registered long tasks after a swap (P1-3, 2026-11-18).
# Called fail-open by fleet_recovery.sh in recover mode (fd 9 already closed
# by the caller). Reads /home/hatch/data/perpetua/long_tasks.json; for each
# enabled entry, skips when the done_marker exists or a matching process is
# alive, else relaunches detached (setsid nohup). Never exits non-zero on a
# single-entry failure: a resume failure must never fail fleet recovery.
# Registry entry: {id, name, cwd, command, log, done_marker, match, enabled}
#   match: pgrep -f pattern identifying the live process; empty = no alive check.
# Registration is manual and explicit: NEVER auto-register a task here.
# Kitesurf build #10 is deliberately NOT registered (user's call, Rule 32).

REGISTRY=/home/hatch/data/perpetua/long_tasks.json
TS=$(date '+%F %T')

echo "$TS resume_long_tasks: start"
if [ ! -f "$REGISTRY" ]; then
  echo "$TS resume_long_tasks: registry missing ($REGISTRY), nothing to do"
  exit 0
fi

ENTRIES=$(python3 - "$REGISTRY" <<'PYEOF' 2>/dev/null
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as e:
    print("JSON_ERROR\t%s" % e)
    sys.exit(0)
for t in data.get("tasks", []):
    if not isinstance(t, dict):
        continue
    fields = [
        str(t.get("id", "")),
        "1" if t.get("enabled") else "0",
        str(t.get("match", "")),
        str(t.get("done_marker", "")),
        str(t.get("cwd", "")),
        str(t.get("log", "")),
        str(t.get("command", "")),
        str(t.get("name", "")),
    ]
    print("\t".join(fields))
PYEOF
)
if [ -z "$ENTRIES" ]; then
  echo "$TS resume_long_tasks: registry empty, nothing to do"
  exit 0
fi

launched=0; skipped=0
while IFS=$'\t' read -r id enabled match done_marker cwd logfile command name; do
  [ -z "$id" ] && continue
  if [ "$id" = "JSON_ERROR" ]; then
    echo "$TS resume_long_tasks: registry JSON error: $enabled; skipping all (fail-open)"
    exit 0
  fi
  if [ "$enabled" != "1" ]; then
    echo "$TS resume_long_tasks: skip $id ($name): disabled"
    skipped=$((skipped+1)); continue
  fi
  if [ -n "$done_marker" ] && [ -e "$done_marker" ]; then
    echo "$TS resume_long_tasks: skip $id ($name): done_marker exists ($done_marker)"
    skipped=$((skipped+1)); continue
  fi
  if [ -n "$match" ] && pgrep -f "$match" >/dev/null 2>&1; then
    echo "$TS resume_long_tasks: skip $id ($name): process alive (match=$match)"
    skipped=$((skipped+1)); continue
  fi
  if [ -z "$command" ]; then
    echo "$TS resume_long_tasks: skip $id ($name): empty command"
    skipped=$((skipped+1)); continue
  fi
  if [ -n "$cwd" ] && [ ! -d "$cwd" ]; then
    echo "$TS resume_long_tasks: skip $id ($name): cwd missing ($cwd)"
    skipped=$((skipped+1)); continue
  fi
  [ -n "$logfile" ] && mkdir -p "$(dirname "$logfile")" 2>/dev/null
  if [ -n "$cwd" ]; then
    ( cd "$cwd" && setsid nohup bash -c "$command" >> "${logfile:-/dev/null}" 2>&1 < /dev/null & )
  else
    setsid nohup bash -c "$command" >> "${logfile:-/dev/null}" 2>&1 < /dev/null &
  fi
  echo "$TS resume_long_tasks: launched $id ($name) pid=$!"
  launched=$((launched+1))
done <<EOF
$ENTRIES
EOF

echo "$TS resume_long_tasks: done launched=$launched skipped=$skipped"
exit 0
