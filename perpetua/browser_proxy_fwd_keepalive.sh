#!/bin/bash
# 保活：127.0.0.1:3129 转发器（Chromium 代理中转）
# 判活双条件：TCP 端口可连 + 转发器进程存在
# （2026-10-16 23:12 曾出现 /dev/tcp 探针假活：端口实际 refused 但未触发重启）
alive=1
(echo > /dev/tcp/127.0.0.1/3129) 2>/dev/null || alive=0
pgrep -f "browser_proxy_fwd[.]py" >/dev/null 2>&1 || alive=0
if [ "$alive" = "1" ]; then
  : # alive
else
  echo "$(date '+%F %T') forwarder dead, restarting" >> /home/hatch/data/perpetua/browser_proxy_fwd_keepalive.log
  pkill -f "browser_proxy_fwd[.]py" 2>/dev/null
  sleep 1
  nohup python3 /home/hatch/data/perpetua/browser_proxy_fwd.py >> /home/hatch/data/perpetua/browser_proxy_fwd.log 2>&1 &
fi
