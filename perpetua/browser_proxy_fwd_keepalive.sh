#!/bin/bash
# 保活：127.0.0.1:3129 转发器（Chromium 代理中转）
if ! (echo > /dev/tcp/127.0.0.1/3129) 2>/dev/null; then
  echo "$(date '+%F %T') forwarder dead, restarting" >> /home/hatch/data/perpetua/browser_proxy_fwd_keepalive.log
  pkill -f "browser_proxy_fwd.py" 2>/dev/null
  sleep 1
  nohup python3 /home/hatch/data/perpetua/browser_proxy_fwd.py >> /home/hatch/data/perpetua/browser_proxy_fwd.log 2>&1 &
else
  : # alive
fi
