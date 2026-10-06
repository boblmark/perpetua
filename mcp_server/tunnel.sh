#!/bin/bash
# SSH 反向隧道保活：把本地 8734 暴露到 VPS 公网
while true; do
  ssh -i ~/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 0.0.0.0:8734:localhost:8734 \
    root@192.166.82.123
  echo "$(date) tunnel died, retry in 5s" >> /home/hatch/data/mcp_server/tunnel.log
  sleep 5
done
