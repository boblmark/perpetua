#!/bin/bash
# QQ box REA host-side relay keepalive: local 127.0.0.1:8746 -> VPS 127.0.0.1:8745 -> QQ box 127.0.0.1:18790
# NOTE: QQ box has no REA gateway yet, so liveness here is ssh process + local port listen only,
# NOT /healthz (that check applies once REA is installed inside the box).
LOG=/home/hatch/data/perpetua/box_qq_rea_forward_keepalive.log
KEY=/home/hatch/.ssh/id_ed25519
CHECK='(^|/)ssh .*-L 127\.0\.0\.1:8746:127\.0\.0\.1:8745'

if pgrep -f "$CHECK" > /dev/null; then
    if ss -ltn 2>/dev/null | grep -q "127.0.0.1:8746"; then
        exit 0
    fi
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8746 forward not healthy, restarting" >> "$LOG"

for pid in $(pgrep -f "127.0.0.1:8746:127.0.0.1:8745" 2>/dev/null); do
    if [ "$pid" != "$$" ]; then
        kill "$pid" 2>/dev/null
    fi
done
sleep 2

ssh -i "$KEY" -f -N \
  -L 127.0.0.1:8746:127.0.0.1:8745 \
  root@192.166.82.123 \
  -o StrictHostKeyChecking=no \
  -o "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p" \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  >> "$LOG" 2>&1

sleep 3
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:8746"; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8746 forward started OK" >> "$LOG"
    exit 0
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8746 forward FAILED to start" >> "$LOG"
    exit 1
fi
