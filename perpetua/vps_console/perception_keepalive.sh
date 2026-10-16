#!/bin/bash
# perception server 保活：确保 ws://127.0.0.1:18736 在运行
# 每 5 分钟由 cron 调用

PORT=18736
LOG=/home/hatch/data/perpetua/vps_console/perception_keepalive.log

# WebSocket 端口用 ss 检查监听状态，连续两次失败才重启
fail_count=0
for i in 1 2; do
    if ss -tln 2>/dev/null | grep -q "127.0.0.1:${PORT}"; then
        exit 0  # 健康
    fi
    fail_count=$((fail_count + 1))
    if [ $i -eq 1 ]; then sleep 10; fi
done

if [ $fail_count -eq 2 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') perception server 连续两次探测失败，重启" >> "$LOG"
    pkill -f "perception_server.py" 2>/dev/null
    sleep 3
    cd /home/hatch/data/nanomuse-migration/perception/server
    env NO_PROXY="localhost,127.0.0.1,::1" no_proxy="localhost,127.0.0.1,::1" \
        /home/hatch/data/nanomuse-migration/nanomuse-venv/bin/python perception_server.py \
        >> /tmp/perception.log 2>&1 &
    echo "$(date '+%Y-%m-%d %H:%M:%S') 已拉起，pid $!" >> "$LOG"
fi
