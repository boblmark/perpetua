#!/bin/bash
# QQ box muse host-side relay keepalive: local 127.0.0.1:8748 -> VPS 127.0.0.1:8747 -> QQ box 127.0.0.1:8101
# Liveness = ssh process + local listen + key-free HTTP response through the tunnel
# (any HTTP status from uvicorn proves end-to-end; 000 = tunnel dead).
LOG=/home/hatch/data/perpetua/box_qq_muse_forward_keepalive.log
KEY=/home/hatch/.ssh/id_ed25519

healthy() {
    pgrep -f "127.0.0.1:8748:127.0.0.1:8747" > /dev/null 2>&1 || return 1
    ss -ltn 2>/dev/null | grep -q "127.0.0.1:8748" || return 1
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:8748/ 2>/dev/null)
    [ "$code" != "000" ] && [ -n "$code" ]
}

if healthy; then
    exit 0
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8748 forward not healthy, restarting" >> "$LOG"

for pid in $(pgrep -f "127.0.0.1:8748:127.0.0.1:8747" 2>/dev/null); do
    if [ "$pid" != "$$" ]; then
        kill "$pid" 2>/dev/null
    fi
done
sleep 2

ssh -i "$KEY" -f -N \
  -L 127.0.0.1:8748:127.0.0.1:8747 \
  root@192.166.82.123 \
  -o StrictHostKeyChecking=no \
  -o "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p" \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  >> "$LOG" 2>&1

sleep 3
if healthy; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8748 forward started OK" >> "$LOG"
    exit 0
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8748 forward FAILED to start" >> "$LOG"
    exit 1
fi
