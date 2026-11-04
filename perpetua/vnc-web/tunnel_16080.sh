#!/bin/bash
while true; do
  ssh -i /home/hatch/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 0.0.0.0:16080:localhost:6080 \
    root@192.166.82.123
  echo "$(date) vnc tunnel died, retry in 5s" >> /home/hatch/data/perpetua/vnc-web/tunnel.log
  sleep 5
done
