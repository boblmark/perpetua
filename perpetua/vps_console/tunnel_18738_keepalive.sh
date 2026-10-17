#!/bin/bash
# 保活：确保 tunnel_18738.sh 在运行
if ! pgrep -f "tunnel_18738.sh" > /dev/null; then
  setsid nohup /home/hatch/data/perpetua/vps_console/tunnel_18738.sh > /dev/null 2>&1 < /dev/null &
  disown 2>/dev/null || true
  echo "$(date) restarted tunnel_18738.sh" >> /home/hatch/data/perpetua/vps_console/tunnel_18738_keepalive.log
fi
# 也确保端口在监听
if ! ss -tln 2>/dev/null | grep -q "127.0.0.1:18738"; then
  pkill -f "ssh.*-L 127.0.0.1:18738" 2>/dev/null
  sleep 1
fi
exit 0
