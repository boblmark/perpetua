#!/bin/bash
# fleet_recovery.sh -- Rule 11 post-swap fleet recovery (automated).
# Restores the systemd layer + mux master after a sandbox machine swap.
# Triggered by swap_detector.sh when boot_id changes. Idempotent: every step
# verifies before acting, so re-running on a healthy machine is a no-op.
# Modes: (default) recover | --verify-only read-only checks | --dry-run plan.
# NEVER prints credential material: the credential-proxy drop-in is copied
# as a file and only its size/mode are verified, never its contents.
# Rule 9: no broad pkill. Bare processes are killed by exact PID only, after
# excluding self/parent/every unit MainPID, and only when the unit is broken.

MODE="recover"
case "${1:-}" in
  --verify-only) MODE="verify" ;;
  --dry-run) MODE="dryrun" ;;
  "") MODE="recover" ;;
  *) echo "usage: $0 [--verify-only|--dry-run]" >&2; exit 4 ;;
esac

SRC=/home/hatch/data/perpetua/systemd_units
LOG=/home/hatch/data/perpetua/fleet_recovery.log
DROPIN_BAK=$SRC/old-dropin-bak/env.conf.bak-20261021-065244
DROPIN_DIR=/etc/systemd/system/dash-credential-proxy.service.d
DROPIN_FILE=$DROPIN_DIR/env.conf
PIN=/home/hatch/.ssh/known_hosts_vps
ROOT_KNOWN=/root/.ssh/known_hosts
MUX_SOCK=/home/hatch/.ssh/vm_mux_192.166.82.123.sock
VPS=root@192.166.82.123
KEY=/home/hatch/.ssh/id_ed25519
PROXY_CMD="nc -X connect -x 198.19.0.1:3128 %h %p"

# Trim runaway log (keep last 2000 lines).
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" 2>/dev/null || echo 0)" -gt 2500 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
logn() { echo "$(date '+%F %T') $*" >> "$LOG"; }

BOOT_ID="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown)"
log "=== fleet_recovery mode=$MODE boot_id=$BOOT_ID ==="

# --- read helpers -----------------------------------------------------------
listener_pid() {
  ss -ltnpH "sport = :$1" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -n 1
}
unit_active() { systemctl is-active "$1" 2>/dev/null || echo unknown; }
unit_mainpid() { systemctl show "$1" -p MainPID --value 2>/dev/null || echo 0; }
# NOTE (2026-11-17): curl -w prints 000 itself on failure; an `|| echo 000`
# suffix yields "000000", which != "000" and reads as healthy. Never add it.
http_code() { local c; c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" 2>/dev/null); [ -n "$c" ] && echo "$c" || echo 000; }

# 3129 CONNECT probe (same method as browser_proxy_fwd_keepalive.sh).
# Returns 0 ok, 1 relay dead, 2 unknown (upstream also down).
probe_3129() {
  local line
  exec 9<>/dev/tcp/127.0.0.1/3129 2>/dev/null || return 1
  printf 'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n' >&9 2>/dev/null || { exec 9>&- 2>/dev/null; return 1; }
  if ! IFS= read -r -t 8 line <&9 2>/dev/null; then exec 9>&- 2>/dev/null; return 1; fi
  exec 9>&- 2>/dev/null
  case "$line" in *200*) return 0 ;; esac
  # Relay probe failed: is the upstream itself down? If yes, verdict unknown.
  exec 9<>/dev/tcp/198.19.0.1/3128 2>/dev/null || return 2
  printf 'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n' >&9 2>/dev/null || { exec 9>&- 2>/dev/null; return 2; }
  if ! IFS= read -r -t 8 line <&9 2>/dev/null; then exec 9>&- 2>/dev/null; return 2; fi
  exec 9>&- 2>/dev/null
  case "$line" in *200*) return 1 ;; *) return 2 ;; esac
}

# Health spec: any | 200:/path | 200body:/path:needle | connect | listen | socket
spec_healthy() {
  local port="$1" spec="$2"
  case "$spec" in
    any)
      [ "$(http_code "http://127.0.0.1:$port/")" != "000" ] ;;
    200:*)
      [ "$(http_code "http://127.0.0.1:$port${spec#200:}")" = "200" ] ;;
    200body:*)
      local rest="${spec#200body:}"; local path="${rest%%:*}" needle="${rest#*:}"
      [ "$(http_code "http://127.0.0.1:$port$path")" = "200" ] && \
        curl -s --max-time 5 "http://127.0.0.1:$port$path" 2>/dev/null | grep -q "$needle" ;;
    connect)
      probe_3129; local rc=$?
      [ $rc -eq 0 ] && return 0
      [ $rc -eq 2 ] && { logn "WARN 3129 probe unknown (upstream down), treating as pass"; return 0; }
      return 1 ;;
    listen)
      [ -n "$(listener_pid "$port")" ] ;;
    socket)
      [ -S /run/credential-proxy/proxy.sock ] ;;
    *) return 1 ;;
  esac
}

# --- exact-PID kill with guards (Rule 9) -------------------------------------
UNITS_ALL="dash-perception.service dash-nano-webui.service dash-nanomuse-serve.service dash-console.service dash-mcp-8734.service dash-nanomuse-mcp-8735.service dash-browser-proxy-fwd.service dash-phone-mcp-tunnel.service tianshu-console-18901.service dash-credential-proxy.service"

safe_kill_pid() {
  local pid="$1" unit="$2" port="$3"
  if [ -z "$pid" ] || [ "$pid" = "1" ] || [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
    log "REFUSE kill pid=$pid (self/parent/init guard) unit=$unit"; return 1
  fi
  local mp
  for u in $UNITS_ALL; do
    mp=$(unit_mainpid "$u")
    if [ -n "$mp" ] && [ "$mp" != "0" ] && [ "$pid" = "$mp" ]; then
      log "REFUSE kill pid=$pid: MainPID of $u (unit=$unit)"; return 1
    fi
  done
  if [ ! -d "/proc/$pid" ]; then logn "pid $pid already gone"; return 0; fi
  local cmd; cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | head -c 200)
  case "$cmd" in *swap_detector*|*fleet_recovery*)
    log "REFUSE kill pid=$pid: own toolchain cmd=[$cmd]"; return 1 ;;
  esac
  log "KILL bare pid=$pid unit=$unit port=$port cmd=[$cmd]"
  kill "$pid" 2>/dev/null || return 0
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [ ! -d "/proc/$pid" ] && break
    sleep 0.5
  done
  if [ -d "/proc/$pid" ]; then kill -9 "$pid" 2>/dev/null; sleep 1; fi
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [ -z "$(listener_pid "$port")" ] && break
    sleep 0.5
  done
  return 0
}

# --- per-unit ensure: three-way verify (active + MainPID==listener + health) -
# P0-2 (2026-11-18): verify-with-retry. Slow-starting units used to fail the
# single immediate post-restart check (listener not yet bound) and record a
# false FAIL, which made every swap's first recovery round report "failed"
# (units_ok=0 on #99 while every unit was fine seconds later). The check now
# retries with backoff, and an "activating" unit gets a settle window before
# any restart is attempted.
verify_unit() {
  local unit="$1" port="$2" spec="$3"
  local active mainpid listener
  active=$(unit_active "$unit"); mainpid=$(unit_mainpid "$unit")
  if [ "$port" = "socket" ]; then
    if [ "$active" = "active" ] && spec_healthy "$port" "$spec"; then return 0; fi
  else
    listener=$(listener_pid "$port")
    if [ "$active" = "active" ] && [ -n "$mainpid" ] && [ "$mainpid" != "0" ] \
       && [ "$listener" = "$mainpid" ] && spec_healthy "$port" "$spec"; then return 0; fi
  fi
  return 1
}

ensure_unit() {
  local unit="$1" port="$2" spec="$3"
  if verify_unit "$unit" "$port" "$spec"; then
    log "PASS $unit active MainPID=$(unit_mainpid "$unit") listener=$(listener_pid "$port")"
    return 0
  fi
  local active mainpid listener
  active=$(unit_active "$unit"); mainpid=$(unit_mainpid "$unit"); listener=$(listener_pid "$port")
  log "BROKEN $unit active=$active MainPID=$mainpid listener=$listener spec=$spec"
  if [ "$MODE" != "recover" ]; then
    log "DRYRUN would: clear holder + reset-failed + restart $unit"
    return 1
  fi
  # Settle window: an activating unit may just be slow. Re-check for up to
  # 30s before restarting; a unit that becomes healthy needs no restart.
  if [ "$active" = "activating" ]; then
    local i
    for i in 1 2 3 4 5 6; do
      sleep 5
      if verify_unit "$unit" "$port" "$spec"; then
        log "PASS $unit settled active MainPID=$(unit_mainpid "$unit")"
        return 0
      fi
    done
    active=$(unit_active "$unit"); mainpid=$(unit_mainpid "$unit"); listener=$(listener_pid "$port")
    log "STILL_BROKEN $unit after settle window active=$active MainPID=$mainpid listener=$listener"
  fi
  if [ "$port" != "socket" ] && [ -n "$listener" ] && [ "$listener" != "$mainpid" ]; then
    safe_kill_pid "$listener" "$unit" "$port" || { log "FAIL $unit: holder kill refused"; return 1; }
  fi
  systemctl reset-failed "$unit" >/dev/null 2>&1 || true
  if ! systemctl restart "$unit" >/dev/null 2>&1; then
    log "FAIL $unit: systemctl restart failed"; return 1
  fi
  # Post-restart verify with backoff: 5+10+15+20+30 = 80s of patience for
  # slow binders (nano-webui, phone-mcp-tunnel, nanomuse-serve). FAIL only
  # after every attempt is exhausted. Exits early on first success.
  local delay
  for delay in 5 10 15 20 30; do
    sleep "$delay"
    if verify_unit "$unit" "$port" "$spec"; then
      log "RECOVERED $unit MainPID=$(unit_mainpid "$unit") listener=$(listener_pid "$port")"
      return 0
    fi
  done
  active=$(unit_active "$unit"); mainpid=$(unit_mainpid "$unit"); listener=$(listener_pid "$port")
  log "FAIL $unit after restart+retries: active=$active MainPID=$mainpid listener=$listener"
  return 1
}

# --- hostname -----------------------------------------------------------------
fix_hostname() {
  local cur; cur=$(hostname 2>/dev/null)
  if [ "$cur" = "dash-runtime" ]; then log "PASS hostname=dash-runtime"; return 0; fi
  if [ "$MODE" != "recover" ]; then log "DRYRUN would: hostname dash-runtime (now $cur)"; return 1; fi
  if hostname dash-runtime 2>/dev/null && [ "$(hostname)" = "dash-runtime" ]; then
    log "RECOVERED hostname -> dash-runtime"; return 0
  fi
  log "FAIL hostname still $cur"; return 1
}

# --- VPS host key in /root/.ssh/known_hosts (from persistent pin) --------------
fix_known_hosts() {
  mkdir -p /root/.ssh 2>/dev/null; chmod 700 /root/.ssh 2>/dev/null || true
  # Entries are hashed (|1|...), so grep for the IP never matches; use -F.
  if ssh-keygen -F 192.166.82.123 -f "$ROOT_KNOWN" >/dev/null 2>&1; then
    log "PASS known_hosts has VPS key"; return 0
  fi
  if [ ! -f "$PIN" ]; then log "FAIL known_hosts pin missing: $PIN"; return 1; fi
  if [ "$MODE" != "recover" ]; then log "DRYRUN would: append pin to $ROOT_KNOWN"; return 1; fi
  cat "$PIN" >> "$ROOT_KNOWN" && chmod 600 "$ROOT_KNOWN" 2>/dev/null
  if ssh-keygen -F 192.166.82.123 -f "$ROOT_KNOWN" >/dev/null 2>&1; then
    log "RECOVERED known_hosts from pin"; return 0
  fi
  log "FAIL known_hosts restore"; return 1
}

# --- units install (install.sh globs dash-* only; tianshu needs explicit cp) ---
fix_units() {
  local missing=0
  local u
  for u in $UNITS_ALL; do
    [ -f "/etc/systemd/system/$u" ] || { missing=1; logn "unit file missing: $u"; }
  done
  if [ $missing -eq 0 ]; then log "PASS all 10 unit files present in /etc"; return 0; fi
  if [ "$MODE" != "recover" ]; then log "DRYRUN would: run install.sh + cp tianshu unit + enable"; return 1; fi
  bash "$SRC/install.sh" >/dev/null 2>&1 || log "WARN install.sh exited $?"
  cp "$SRC/tianshu-console-18901.service" /etc/systemd/system/ 2>/dev/null
  chmod 644 /etc/systemd/system/tianshu-console-18901.service 2>/dev/null
  systemctl daemon-reload 2>/dev/null
  systemctl enable tianshu-console-18901.service >/dev/null 2>&1 || true
  missing=0
  for u in $UNITS_ALL; do
    [ -f "/etc/systemd/system/$u" ] || missing=1
  done
  if [ $missing -eq 0 ]; then log "RECOVERED unit files installed+enabled"; return 0; fi
  log "FAIL unit files still missing"; return 1
}

# --- credential-proxy drop-in: copy backup file, verify size/mode only ---------
fix_dropin() {
  local bak_size live_size
  bak_size=$(stat -c %s "$DROPIN_BAK" 2>/dev/null || echo 0)
  if [ ! -f "$DROPIN_BAK" ] || [ "$bak_size" = "0" ]; then
    log "FAIL drop-in backup missing: $DROPIN_BAK"; return 1
  fi
  if [ -f "$DROPIN_FILE" ]; then
    live_size=$(stat -c %s "$DROPIN_FILE" 2>/dev/null || echo 0)
    if [ "$live_size" = "$bak_size" ] && [ "$(stat -c %a "$DROPIN_FILE")" = "600" ]; then
      log "PASS drop-in present size=$live_size mode=600"; return 0
    fi
    log "WARN drop-in size/mode drift live=$live_size bak=$bak_size (backup authoritative)"
  fi
  if [ "$MODE" != "recover" ]; then log "DRYRUN would: cp drop-in backup + chmod 600 + daemon-reload"; return 1; fi
  mkdir -p "$DROPIN_DIR"
  cp "$DROPIN_BAK" "$DROPIN_FILE" && chmod 600 "$DROPIN_FILE"
  systemctl daemon-reload 2>/dev/null
  live_size=$(stat -c %s "$DROPIN_FILE" 2>/dev/null || echo 0)
  if [ "$live_size" = "$bak_size" ] && [ "$(stat -c %a "$DROPIN_FILE")" = "600" ]; then
    log "RECOVERED drop-in size=$live_size mode=600"; return 0
  fi
  log "FAIL drop-in restore"; return 1
}

# --- mux master rebuild --------------------------------------------------------
mux_check() {
  [ -S "$MUX_SOCK" ] || return 1
  ssh -S "$MUX_SOCK" -O check -o BatchMode=yes -o ConnectTimeout=10 "$VPS" >/dev/null 2>&1
}
fix_mux() {
  if mux_check; then log "PASS mux master alive ($MUX_SOCK)"; return 0; fi
  if [ "$MODE" != "recover" ]; then log "DRYRUN would: clear stale mux socket + rebuild master"; return 1; fi
  rm -f "$MUX_SOCK"
  ssh -M -S "$MUX_SOCK" -fN -i "$KEY" -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o ConnectTimeout=30 \
    -o ProxyCommand="$PROXY_CMD" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes -o BatchMode=yes "$VPS" >/dev/null 2>&1
  sleep 3
  if mux_check; then log "RECOVERED mux master"; return 0; fi
  log "FAIL mux master rebuild (direct SSH still works; keepalives will retry)"
  return 1
}

# --- periphery: verify-only, best-effort relaunch via existing keepalives -----
check_periphery() {
  local notes=""
  # Semantica trio: explorer + kb-search + tunnel (keepalive script is idempotent).
  if [ "$(http_code http://127.0.0.1:18091/)" = "000" ] || [ "$(http_code http://127.0.0.1:18092/healthz)" = "000" ]; then
    if [ "$MODE" = "recover" ]; then
      bash /home/hatch/data/perpetua/vps_console/semantica_keepalive.sh 9>&- >/dev/null 2>&1 || true
      sleep 2
    fi
    notes="$notes semantica=healed-or-down"
  else
    notes="$notes semantica=ok"
  fi
  # 18738 tunnel wrapper.
  if ! ss -tln 2>/dev/null | grep -q "127.0.0.1:18738"; then
    if [ "$MODE" = "recover" ]; then
      bash /home/hatch/data/perpetua/vps_console/tunnel_18738_keepalive.sh 9>&- >/dev/null 2>&1 || true
      sleep 2
    fi
    notes="$notes 18738=check"
  else
    notes="$notes 18738=ok"
  fi
  # Report-only: relay 18080, QQ main route 8748, Chrome CDP 9335, public kb/nano.
  ss -tln 2>/dev/null | grep -q ":18080" && notes="$notes 18080=ok" || notes="$notes 18080=down"
  if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8748/v1/ping 2>/dev/null)" = "200" ]; then
    notes="$notes 8748=ok"
  else
    notes="$notes 8748=down"
  fi
  [ "$(http_code http://127.0.0.1:9335/)" != "000" ] && notes="$notes cdp9335=ok" || notes="$notes cdp9335=down"
  [ "$(http_code https://kb.viralloopapp.com/)" = "200" ] && notes="$notes kb-public=ok" || notes="$notes kb-public=down"
  [ "$(http_code https://nano.viralloopapp.com/)" = "200" ] && notes="$notes nano-public=ok" || notes="$notes nano-public=down"
  log "PERIPHERY:$notes"
}

# --- main ----------------------------------------------------------------------
UNITS_OK=0; UNITS_FAIL=0
fix_hostname || true
fix_known_hosts || true
fix_units || true
fix_dropin || true

ensure_unit dash-perception.service 18736 "any" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-nano-webui.service 18737 "200:/" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-nanomuse-serve.service 18739 "200:/" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-console.service 8080 "200:/oa" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-mcp-8734.service 8734 "200body:/health:ok" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-nanomuse-mcp-8735.service 8735 "200body:/health:ok" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-browser-proxy-fwd.service 3129 "connect" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-phone-mcp-tunnel.service 18766 "listen" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit tianshu-console-18901.service 18901 "200:/" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))
ensure_unit dash-credential-proxy.service socket "socket" && UNITS_OK=$((UNITS_OK+1)) || UNITS_FAIL=$((UNITS_FAIL+1))

MUX_RC=0
fix_mux || MUX_RC=1
check_periphery

# P1-3 (2026-11-18): resume registered long tasks (swap-killed builds etc).
# Fail-open: a resume failure must never fail fleet recovery. Recover mode
# only; the resume script is a no-op when the registry is empty. fd 9 is
# closed so detached children never inherit the detector lock (Rule 34).
if [ "$MODE" = "recover" ] && [ -x /home/hatch/data/perpetua/resume_long_tasks.sh ]; then
  bash /home/hatch/data/perpetua/resume_long_tasks.sh 9>&- >> "$LOG" 2>&1 || log "WARN resume_long_tasks exited $?"
fi

log "=== fleet_recovery done mode=$MODE units_ok=$UNITS_OK units_fail=$UNITS_FAIL mux_rc=$MUX_RC ==="
if [ $UNITS_FAIL -gt 0 ]; then exit 1; fi
if [ $MUX_RC -ne 0 ]; then exit 2; fi
exit 0
