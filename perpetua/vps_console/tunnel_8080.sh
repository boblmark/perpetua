#!/bin/bash
# Perpetua 控制台 8080 反向隧道保活（独立于 8734 MCP 隧道）
# 把本地 8080 暴露到 VPS 公网 8080
while true; do
  ssh -i /home/hatch/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 0.0.0.0:8080:localhost:8080 \
    root@192.166.82.123
  echo "$(date) console tunnel died, retry in 5s" >> /home/hatch/data/perpetua/vps_console/tunnel_8080.log
  sleep 5
done
