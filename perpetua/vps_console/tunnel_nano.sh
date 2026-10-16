#!/bin/bash
# nano 后端控制台反向隧道：18736 (perception WS) + 18737 (perception UI) + 18738 (主控制台)
while true; do
  ssh -i /home/hatch/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 0.0.0.0:18736:localhost:18736 \
    -R 0.0.0.0:18737:localhost:18737 \
    -R 0.0.0.0:18739:localhost:18739 \
    root@192.166.82.123
  echo "$(date) nano tunnel died, retry in 5s" >> /home/hatch/data/perpetua/vps_console/tunnel_nano.log
  sleep 5
done
