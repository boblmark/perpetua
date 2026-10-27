#!/bin/bash
# box REA 主机侧接应保活：本机 127.0.0.1:8744 → VPS 127.0.0.1:8743 → 盒 REA 网关
# 链路：VPS 侧 box-rea-forward.service（VPS→盒）+ 盒侧 rea-gateway.service
# 判活锚定 ssh 转发进程 + /healthz 端点实测（进程在但端点不通也算死）
LOG=/home/hatch/data/perpetua/box_rea_forward_keepalive.log
KEY=/home/hatch/.ssh/id_ed25519
CHECK='(^|/)ssh .*-L 127\.0\.0\.1:8744:127\.0\.0\.1:8743'

if pgrep -f "$CHECK" > /dev/null; then
    if curl -s -m 10 http://127.0.0.1:8744/healthz | grep -q ok; then
        exit 0
    fi
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8744 forward not healthy, restarting" >> "$LOG"

for pid in $(pgrep -f "127.0.0.1:8744:127.0.0.1:8743" 2>/dev/null); do
    if [ "$pid" != "$$" ]; then
        kill "$pid" 2>/dev/null
    fi
done
sleep 2

ssh -i "$KEY" -f -N \
  -L 127.0.0.1:8744:127.0.0.1:8743 \
  root@192.166.82.123 \
  -o StrictHostKeyChecking=no \
  -o "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p" \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  >> "$LOG" 2>&1

sleep 3
if curl -s -m 10 http://127.0.0.1:8744/healthz | grep -q ok; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8744 forward started OK" >> "$LOG"
    exit 0
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8744 forward FAILED to start" >> "$LOG"
    exit 1
fi
