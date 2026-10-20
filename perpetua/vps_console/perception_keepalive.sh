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
    # 2026-10-20 升级线触发（当日 5 次重启，间隔加速至 <1h）：重启前取证，判别"进程已死"还是"进程在但端口掉了"
    {
        echo "=== FORENSICS $(date '+%Y-%m-%d %H:%M:%S') ==="
        echo "-- 进程表 --"; ps -o pid,stat,etime,rss,cmd -C python 2>/dev/null | grep perception || echo "无 perception 进程残留"
        echo "-- 监听表 --"; ss -tlnp 2>/dev/null | grep -E "18736|LISTEN" | head -8
        echo "-- server 日志尾 10 行 --"; tail -10 /tmp/perception.log 2>/dev/null || echo "无 /tmp/perception.log"
        echo "=== END FORENSICS ==="
    } >> "$LOG"
    echo "$(date '+%Y-%m-%d %H:%M:%S') perception server 连续两次探测失败，重启" >> "$LOG"
    pkill -f "perception_server.py" 2>/dev/null
    sleep 3
    cd /home/hatch/data/nanomuse-migration/perception/server
    env NO_PROXY="localhost,127.0.0.1,::1" no_proxy="localhost,127.0.0.1,::1" \
        /home/hatch/data/nanomuse-migration/nanomuse-venv/bin/python perception_server.py \
        >> /tmp/perception.log 2>&1 &
    echo "$(date '+%Y-%m-%d %H:%M:%S') 已拉起，pid $!" >> "$LOG"
fi
