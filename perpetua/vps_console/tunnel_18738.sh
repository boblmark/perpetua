#!/bin/bash
# Gemini Live bridge 本地转发：VM 127.0.0.1:18738 -> VPS 127.0.0.1:18738
while true; do
  ssh -i /home/hatch/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -L 127.0.0.1:18738:127.0.0.1:18738 \
    root@192.166.82.123
  echo "$(date) 18738 tunnel died, retry in 5s" >> /home/hatch/data/perpetua/vps_console/tunnel_18738.log
  sleep 5
done
