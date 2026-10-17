#!/bin/bash
# 保活：127.0.0.1:3129 转发器（Chromium 代理中转）
# 判活三条件：进程存在 + TCP 端口可连 + 功能探针（经转发器做完整 CONNECT 握手）
# （2026-10-16 23:12 曾出现 /dev/tcp 探针假活：端口实际 refused 但未触发重启）
# （2026-10-17 14:27 事故：进程在、端口可连，但中继已死——accept 后上游建连恒 15s 超时，
#   端口探针判活盲区。补功能探针：CONNECT 经转发器打到上游自身，8s 内无 200 即判死）
LOG=/home/hatch/data/perpetua/browser_proxy_fwd_keepalive.log
FWD_LOG=/home/hatch/data/perpetua/browser_proxy_fwd.log
UPSTREAM_HOST=198.19.0.1
UPSTREAM_PORT=3128
# 功能探针目标：必须是上游之外的外部主机。
# 2026-10-17 22:21 实测：上游对 CONNECT 到 198.19.0.1:3128 自身直接静默断连（空回包），
# 自连探针恒假阴性（误报"上游也挂"、真中继死时跳过重启）。改用 example.com:443。
PROBE_TARGET_HOST=example.com
PROBE_TARGET_PORT=443

# 经转发器做 CONNECT 握手，验证中继真实可用
functional_probe() {
  exec 9<>/dev/tcp/127.0.0.1/3129 2>/dev/null || return 1
  printf 'CONNECT %s:%s HTTP/1.1\r\nHost: %s\r\n\r\n' \
    "$PROBE_TARGET_HOST" "$PROBE_TARGET_PORT" "$PROBE_TARGET_HOST" >&9 2>/dev/null \
    || { exec 9>&- 2>/dev/null; return 1; }
  local line
  if ! IFS= read -r -t 8 line <&9 2>/dev/null; then
    exec 9>&- 2>/dev/null; return 1
  fi
  exec 9>&- 2>/dev/null
  [[ "$line" == *200* ]]
}

# 直连上游做 CONNECT：区分"转发器死"还是"上游挂"
upstream_ok() {
  exec 9<>/dev/tcp/$UPSTREAM_HOST/$UPSTREAM_PORT 2>/dev/null || return 1
  printf 'CONNECT %s:%s HTTP/1.1\r\nHost: %s\r\n\r\n' \
    "$PROBE_TARGET_HOST" "$PROBE_TARGET_PORT" "$PROBE_TARGET_HOST" >&9 2>/dev/null \
    || { exec 9>&- 2>/dev/null; return 1; }
  local line
  if ! IFS= read -r -t 8 line <&9 2>/dev/null; then
    exec 9>&- 2>/dev/null; return 1
  fi
  exec 9>&- 2>/dev/null
  [[ "$line" == *200* ]]
}

alive=1
reason=""
pgrep -f "browser_proxy_fwd[.]py" >/dev/null 2>&1 || { alive=0; reason="no process"; }
if [ "$alive" = "1" ]; then
  (echo > /dev/tcp/127.0.0.1/3129) 2>/dev/null || { alive=0; reason="port refused"; }
fi
if [ "$alive" = "1" ]; then
  if ! functional_probe; then
    if upstream_ok; then
      alive=0; reason="relay dead (functional probe failed, upstream fine)"
    else
      echo "$(date '+%F %T') forwarder relay probe failed but upstream also down, skip restart" >> "$LOG"
    fi
  fi
fi

if [ "$alive" = "1" ]; then
  : # alive
else
  echo "$(date '+%F %T') forwarder dead ($reason), restarting" >> "$LOG"
  pkill -f "browser_proxy_fwd[.]py" 2>/dev/null
  sleep 1
  nohup python3 /home/hatch/data/perpetua/browser_proxy_fwd.py >> "$FWD_LOG" 2>&1 &
fi
