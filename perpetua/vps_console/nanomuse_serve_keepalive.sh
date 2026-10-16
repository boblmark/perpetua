#!/bin/bash
# nanoMuse 主控制台保活：确保 nanomuse serve (18739) 在运行
# 每 5 分钟由 cron 调用

PORT=18739
LOG=/home/hatch/data/perpetua/vps_console/nanomuse_serve_keepalive.log

# 连续两次探测失败才重启（防误杀）
fail_count=0
for i in 1 2; do
    if curl -s -m 10 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/" 2>/dev/null | grep -q "200"; then
        exit 0  # 健康
    fi
    fail_count=$((fail_count + 1))
    if [ $i -eq 1 ]; then sleep 10; fi
done

if [ $fail_count -eq 2 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') nanomuse serve 连续两次探测失败，重启" >> "$LOG"
    # 杀掉旧进程（精确匹配，避免误杀）
    pkill -f "nanomuse serve" 2>/dev/null
    sleep 3
    bash /home/hatch/data/perpetua/vps_console/nanomuse_serve_start.sh \
        >> /tmp/nanomuse_serve.log 2>&1 &
    echo "$(date '+%Y-%m-%d %H:%M:%S') 已拉起，pid $!" >> "$LOG"
fi
