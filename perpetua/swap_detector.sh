#!/bin/bash
# swap_detector.sh -- dedicated sandbox machine-swap detector.
# Runs from a 5-minute cron. Compares the current boot_id with the persistent
# state file; on change it runs fleet_recovery.sh (Rule 11) automatically.
# State/history live under /home/hatch/data (survives swaps); /etc and /root
# do not, which is exactly why the detector must be cron-driven, not a timer.
# Modes: (default) check | --check-only verify, no state writes |
#        --dry-run simulate a swap, no changes | --force-recover run recovery now.
# Test overrides (env): SWAP_STATE_FILE, SWAP_HISTORY_FILE.
# Exit: 0 no change / recovery ok-or-degraded; 3 recovery failed; 4 script error.

STATE_FILE="${SWAP_STATE_FILE:-/home/hatch/data/perpetua/swap_detector_state}"
HISTORY_FILE="${SWAP_HISTORY_FILE:-/home/hatch/data/perpetua/swap_history.log}"
LOG=/home/hatch/data/perpetua/swap_detector.log
LOCK=/home/hatch/data/perpetua/swap_detector.lock
RECOVERY=/home/hatch/data/perpetua/fleet_recovery.sh
RETRY_MIN_SECS=900

MODE="check"
case "${1:-}" in
  --check-only) MODE="checkonly" ;;
  --dry-run) MODE="dryrun" ;;
  --force-recover) MODE="force" ;;
  "") MODE="check" ;;
  *) echo "usage: $0 [--check-only|--dry-run|--force-recover]" >&2; exit 4 ;;
esac

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# Single-flight: if another detector run is mid-recovery, stay out.
exec 9>"$LOCK"
if ! flock -n 9; then echo "DETECTOR_BUSY another run holds the lock"; exit 0; fi

BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo "")"
if [ -z "$BOOT_ID" ]; then echo "DETECTOR_ERROR cannot read boot_id"; exit 4; fi
NOW=$(date +%s)
UPTIME_S=$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo "?")

read_state() {
  STORED_BOOT=""; LAST_STATUS="none"; LAST_ATTEMPT="0"; SWAP_COUNT="0"
  [ -f "$STATE_FILE" ] || return 0
  STORED_BOOT=$(grep '^boot_id=' "$STATE_FILE" 2>/dev/null | cut -d= -f2)
  LAST_STATUS=$(grep '^last_recovery_status=' "$STATE_FILE" 2>/dev/null | cut -d= -f2)
  LAST_ATTEMPT=$(grep '^last_recovery_at=' "$STATE_FILE" 2>/dev/null | cut -d= -f2)
  SWAP_COUNT=$(grep '^swap_count=' "$STATE_FILE" 2>/dev/null | cut -d= -f2)
  [ -n "$LAST_STATUS" ] || LAST_STATUS="none"
  [ -n "$LAST_ATTEMPT" ] || LAST_ATTEMPT="0"
  [ -n "$SWAP_COUNT" ] || SWAP_COUNT="0"
}

# Atomic state write (tmp + mv). Never stores secrets: boot_id only.
write_state() {
  local boot="$1" status="$2" attempt="$3" count="$4"
  local tmp="$STATE_FILE.tmp.$$"
  {
    echo "boot_id=$boot"
    echo "updated_at=$NOW"
    echo "last_recovery_at=$attempt"
    echo "last_recovery_status=$status"
    echo "swap_count=$count"
  } > "$tmp" && mv "$tmp" "$STATE_FILE"
}

run_recovery() {
  # Close fd 9 (detector lock) in the child: the detector keeps the lock
  # while waiting; children must never inherit it (2026-11-18: a detached
  # tunnel inherited fd 9 and wedged the detector forever).
  bash "$RECOVERY" 9>&- 2>&1 | tee -a "$LOG"
  return "${PIPESTATUS[0]}"
}

# --- modes that never touch state ---------------------------------------------
if [ "$MODE" = "checkonly" ]; then
  echo "CHECK_ONLY boot_id=$BOOT_ID uptime_s=$UPTIME_S"
  bash "$RECOVERY" --verify-only 9>&- 2>&1 | tail -n 30
  exit "${PIPESTATUS[0]}"
fi
if [ "$MODE" = "dryrun" ]; then
  echo "DRYRUN simulating swap: stored=<old> current=$BOOT_ID (no state written, no changes)"
  bash "$RECOVERY" --dry-run 9>&- 2>&1 | tail -n 40
  exit 0
fi

read_state

# --- force mode: recover now, record result ------------------------------------
if [ "$MODE" = "force" ]; then
  log "FORCE_RECOVER boot_id=$BOOT_ID"
  run_recovery; RC=$?
  case $RC in
    0) ST="ok" ;; 2) ST="degraded" ;; *) ST="failed" ;;
  esac
  write_state "$BOOT_ID" "$ST" "$NOW" "$SWAP_COUNT"
  echo "FORCE_DONE recovery=$ST rc=$RC"
  [ "$ST" = "failed" ] && exit 3 || exit 0
fi

# --- first run: no state file -> seed + verify (recover if broken) -------------
if [ ! -f "$STATE_FILE" ]; then
  log "INIT no state file; seeding boot_id=$BOOT_ID"
  write_state "$BOOT_ID" "initialized" "0" "0"
  if bash "$RECOVERY" --verify-only 9>&- >/dev/null 2>&1; then
    write_state "$BOOT_ID" "ok" "0" "0"
    echo "INIT_SEEDED boot_id=$BOOT_ID verify=ok"
    exit 0
  fi
  log "INIT verify failed; running recovery"
  run_recovery; RC=$?
  case $RC in
    0) ST="ok" ;; 2) ST="degraded" ;; *) ST="failed" ;;
  esac
  write_state "$BOOT_ID" "$ST" "$NOW" "0"
  echo "INIT_RECOVERED recovery=$ST rc=$RC"
  [ "$ST" = "failed" ] && exit 3 || exit 0
fi

# --- swap detected: stored boot_id differs -------------------------------------
if [ "$STORED_BOOT" != "$BOOT_ID" ]; then
  NEW_COUNT=$((SWAP_COUNT + 1))
  log "SWAP_DETECTED #${NEW_COUNT} old=${STORED_BOOT:-none} new=$BOOT_ID uptime_s=$UPTIME_S"
  echo "$NOW swap old=${STORED_BOOT:-none} new=$BOOT_ID" >> "$HISTORY_FILE"
  run_recovery; RC=$?
  case $RC in
    0) ST="ok" ;; 2) ST="degraded" ;; *) ST="failed" ;;
  esac
  echo "$NOW swap_result status=$ST rc=$RC" >> "$HISTORY_FILE"
  write_state "$BOOT_ID" "$ST" "$NOW" "$NEW_COUNT"
  log "SWAP_RECOVERY_DONE status=$ST rc=$RC"
  echo "SWAP_DETECTED old=$STORED_BOOT new=$BOOT_ID recovery=$ST rc=$RC"
  [ "$ST" = "failed" ] && exit 3 || exit 0
fi

# --- same machine, last recovery not ok -> retry (at most every 15 min) --------
if { [ "$LAST_STATUS" = "failed" ] || [ "$LAST_STATUS" = "degraded" ]; } \
   && [ $((NOW - LAST_ATTEMPT)) -ge $RETRY_MIN_SECS ]; then
  log "RETRY recovery status=$LAST_STATUS last_attempt=$LAST_ATTEMPT"
  run_recovery; RC=$?
  case $RC in
    0) ST="ok" ;; 2) ST="degraded" ;; *) ST="failed" ;;
  esac
  write_state "$BOOT_ID" "$ST" "$NOW" "$SWAP_COUNT"
  echo "RETRY_DONE recovery=$ST rc=$RC"
  [ "$ST" = "failed" ] && exit 3 || exit 0
fi

# --- steady state: nothing to do ------------------------------------------------
echo "NO_CHANGE boot_id=$BOOT_ID uptime_s=$UPTIME_S last_status=$LAST_STATUS swap_count=$SWAP_COUNT"
exit 0
