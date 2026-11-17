#!/bin/bash
# VPS daily disk cleanup (192.166.82.123).
# Automated version of the manual cleanup Dash ran 2026-11-17 23:28-23:37 CST
# on user order "清理磁盘！" (100%/0 avail -> 92%/3.4G avail).
# Runs via cron job vps-disk-cleanup-daily. Idempotent; safe to re-run.
# SSH is direct via the 3128 proxy on purpose: NO mux dependency, so the job
# keeps working right after a machine swap, before fleet recovery rebuilds mux.
#
# NEVER TOUCH (hard rule; the remote block below is an allowlist, it cannot
# reach anything else):
#   /opt/mcp-b/data/perpetua/distributor/cookies  (matrix login state, ~901M)
#   /opt/mcp-b/data/output                        (no job->video_id mapping)
#   /opt/NanoJev/checkpoints                      (live model weights, 2.3G)
#   live Chrome profiles, ms-playwright, binaries, wb workspace/sessions,
#   chrome-vids-gui, fastembed_cache, codebuddy staging, org.chromium staging
#
# What it DOES clean (all verified safe 2026-11-17, each with its own guard):
#   1. journal vacuum to 100M
#   2. apt cache clean
#   3. /var/crash/* files (apport reports, dir itself kept)
#   4. /var/backups/dmgw/ daily dirs: keep newest 4, delete older date-named dirs
#   5. /tmp/playwright_chromiumdev_profile-*: only dirs NOT referenced by any
#      live process AND older than 2 hours (a starting browser is young)
#   6. the two exact Crash Reports dirs under /tmp/.config
#   7. /home/wb/.workbuddy/logs files older than 7 days + newly empty dirs
set -u
LOG=/home/hatch/data/perpetua/vps_console/vps_disk_cleanup_daily.log
KEY=/home/hatch/.ssh/id_ed25519
KNOWN=/home/hatch/.ssh/known_hosts_vps
VPS=root@192.166.82.123

SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=25
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN"
  -o "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p")

vps() {
  ssh "${SSH_OPTS[@]}" "$VPS" "$@"
}

STAMP="$(date '+%F %T %Z')"

if ! vps "echo SSH_OK" >/dev/null 2>&1; then
  {
    echo "=== $STAMP daily disk cleanup start ==="
    echo "FATAL: ssh to $VPS failed, abort (no changes made)"
  } >>"$LOG" 2>&1
  echo "FATAL: ssh to $VPS failed, abort (no changes made)"
  exit 1
fi

OUT="$(timeout 280 ssh "${SSH_OPTS[@]}" "$VPS" bash -s <<'REMOTE_EOF' 2>&1
set -u
echo "BEFORE: $(df -h / | tail -1)"
journalctl --vacuum-size=100M >/dev/null 2>&1
echo "journal: $(journalctl --disk-usage 2>/dev/null)"
apt-get clean >/dev/null 2>&1
rm -f /var/crash/* 2>/dev/null
if cd /var/backups/dmgw 2>/dev/null; then
  mapfile -t DIRS < <(ls -d 20[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | sort)
  N=${#DIRS[@]}
  if [ "$N" -gt 4 ]; then
    DEL=$((N - 4))
    for ((i = 0; i < DEL; i++)); do
      d="${DIRS[$i]}"
      if [ -d "$d" ]; then rm -rf -- "$d" && echo "DELETED dmgw backup $d"; fi
    done
  else
    echo "dmgw backups: $N dirs, nothing to prune"
  fi
  cd / || true
else
  echo "WARN: /var/backups/dmgw missing, skip prune"
fi
INUSE=$(ps -eo args | grep -o "playwright_chromiumdev_profile-[A-Za-z0-9]*" | sort -u)
for d in /tmp/playwright_chromiumdev_profile-*; do
  [ -d "$d" ] || continue
  b=$(basename "$d")
  if echo "$INUSE" | grep -qx "$b"; then continue; fi
  if [ -n "$(find "$d" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then
    rm -rf -- "$d" && echo "DELETED stale profile $b"
  fi
done
rm -rf "/tmp/.config/google-chrome-for-testing/Crash Reports" "/tmp/.config/google-chrome/Crash Reports" 2>/dev/null
find /home/wb/.workbuddy/logs -type f -mtime +7 -delete 2>/dev/null
find /home/wb/.workbuddy/logs -mindepth 1 -type d -empty -delete 2>/dev/null
echo "AFTER: $(df -h / | tail -1)"
REMOTE_EOF
)"
RC=$?

{
  echo "=== $STAMP daily disk cleanup start ==="
  echo "$OUT"
  echo "remote exit: $RC"
  echo "=== daily disk cleanup done ==="
} >>"$LOG" 2>&1

echo "$OUT" | grep -E "^(BEFORE|AFTER|DELETED|WARN|FATAL|journal|dmgw)" || true
exit "$RC"
