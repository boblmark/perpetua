#!/bin/bash
# OA console 看门狗：连续两次探测失败才重启（防单线程服务偶发慢响应被误杀）
# 2026-10-11 修复：此前 5 秒单次探测，内存紧张时慢响应即被 pkill -9 误杀
if ! curl -s -m 10 -o /dev/null http://127.0.0.1:8080/oa; then
  sleep 10
  if ! curl -s -m 10 -o /dev/null http://127.0.0.1:8080/oa; then
    echo "$(date) OA 连续两次探测失败，重启" >> /tmp/oa_watchdog.log
    # P0-3 (2026-11-18): systemd owns this service. Unit file present ->
    # systemctl restart. Bare launch ONLY when the unit file is missing
    # (post-swap window before fleet_recovery reinstalls units). Never
    # pkill the unit's MainPID (2026-11-17 OA self-match incident).
    if [ -f /etc/systemd/system/dash-console.service ]; then
      systemctl restart dash-console.service 2>/dev/null
      sleep 5
      if curl -s -m 10 -o /dev/null http://127.0.0.1:8080/oa; then
        echo "$(date) OA 已由 systemctl 重启并健康" >> /tmp/oa_watchdog.log
      else
        echo "$(date) OA systemctl 重启后仍不健康，需人工排查" >> /tmp/oa_watchdog.log
      fi
    else
      for pid in $(pgrep -f "console_server\.py" 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        kill "$pid" 2>/dev/null
      done
      sleep 2
      cd /home/hatch/data/perpetua/vps_console
      setsid nohup python3 console_server.py > /tmp/console.log 2>&1 < /dev/null &
    fi
  else
    echo "$(date) OA 单次探测超时、复测正常，未重启" >> /tmp/oa_watchdog.log
  fi
fi
