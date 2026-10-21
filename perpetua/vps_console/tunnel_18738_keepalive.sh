#!/bin/bash
# 保活：确保 tunnel_18738.sh 在运行
# Rule 9 (2026-10-17)：禁止在含目标字样的同一命令行里宽泛 pkill -f；
# 改为 pgrep 取 PID、排除自身($$)/父进程($PPID) 后再按 PID 精确杀。
WRAPPER="/home/hatch/data/perpetua/vps_console/tunnel_18738.sh"
LOG="/home/hatch/data/perpetua/vps_console/tunnel_18738_keepalive.log"

# wrapper 存活检查：精确匹配 "/.../vps_console/tunnel_18738.sh" 结尾（锚定，防检查器自匹配）
wrapper_pids=""
for pid in $(pgrep -f 'vps_console/tunnel_18738\.sh$' 2>/dev/null); do
  [ "$pid" = "$$" ] && continue
  [ "$pid" = "$PPID" ] && continue
  wrapper_pids="$wrapper_pids $pid"
done
if [ -z "$wrapper_pids" ]; then
  setsid nohup "$WRAPPER" > /dev/null 2>&1 < /dev/null &
  disown 2>/dev/null || true
  echo "$(date) restarted tunnel_18738.sh" >> "$LOG"
fi

# 端口不监听时：只杀真实的 ssh -L 转发进程，按 PID 杀，排除自身链条
if ! ss -tln 2>/dev/null | grep -q "127.0.0.1:18738"; then
  for pid in $(pgrep -f 'ssh .*-L 127\.0\.0\.1:18738:127\.0\.0\.1:18738.*root@192\.166\.82\.123' 2>/dev/null); do
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "$PPID" ] && continue
    kill "$pid" 2>/dev/null
  done
  sleep 1
fi
exit 0
