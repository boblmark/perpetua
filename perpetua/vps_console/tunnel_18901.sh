#!/bin/bash
# 天枢控制台 18901 反向隧道（独立于其他隧道）
# 把本地 18901 暴露到 VPS 公网 18901，供 tianshu.viralloopapp.com 反代
while true; do
  ssh -i /home/hatch/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 0.0.0.0:18901:localhost:18901 \
    root@192.166.82.123
  echo "$(date) tianshu tunnel died, retry in 5s" >> /home/hatch/data/perpetua/vps_console/tunnel_18901.log
  sleep 5
done
