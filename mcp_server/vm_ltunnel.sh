#!/bin/bash
# VM -> VPS 本地端口转发：VM:127.0.0.1:18080 ==> VPS:127.0.0.1:18080
pkill -f "[1]8080:127.0.0.1:18080" 2>/dev/null
sleep 1
cd /home/hatch/data/mcp_server
setsid nohup ssh -i /home/hatch/.ssh/id_ed25519 -N \
  -o StrictHostKeyChecking=no \
  -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18080:127.0.0.1:18080 \
  root@192.166.82.123 >> /home/hatch/data/mcp_server/ltunnel.log 2>&1 < /dev/null &
disown
sleep 4
echo "--- ssh procs ---"
ps -eo pid,args | grep "[1]8080:127.0.0.1:18080"
echo "--- listening ---"
ss -tlnp 2>/dev/null | grep 18080
