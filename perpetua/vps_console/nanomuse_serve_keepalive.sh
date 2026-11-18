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
    # P0-3 (2026-11-18): systemd owns this service. Unit file present ->
    # systemctl restart. Bare launch ONLY when the unit file is missing
    # (post-swap window). Never pkill the unit's MainPID.
    if [ -f /etc/systemd/system/dash-nanomuse-serve.service ]; then
      systemctl restart dash-nanomuse-serve.service 2>/dev/null
      sleep 8
      if curl -s -m 10 -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/" 2>/dev/null | grep -q "200"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') nanomuse serve 已由 systemctl 重启并健康" >> "$LOG"
      else
        echo "$(date '+%Y-%m-%d %H:%M:%S') nanomuse serve systemctl 重启后仍不健康，需人工排查" >> "$LOG"
      fi
    else
      for pid in $(pgrep -f "nanomuse serve" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        kill "$pid" 2>/dev/null
      done
      sleep 3
      bash /home/hatch/data/perpetua/vps_console/nanomuse_serve_start.sh \
          >> /tmp/nanomuse_serve.log 2>&1 &
      echo "$(date '+%Y-%m-%d %H:%M:%S') 已拉起（裸拉回退），pid $!" >> "$LOG"
    fi
fi
