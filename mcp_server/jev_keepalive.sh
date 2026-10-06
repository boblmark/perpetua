#!/bin/bash
# jev relay 通路保活：确保 VM:127.0.0.1:18080 -> VPS:127.0.0.1:18080 -> typesafe 可用
# 幂等：通路健康时什么都不做。建议由 Muse 调度器或 cron 每 5 分钟跑一次。
set -u

LOG=/home/hatch/data/mcp_server/jev_relay.log
LT=/home/hatch/data/mcp_server/vm_ltunnel.sh
KEY=$(cat /home/hatch/data/jev/.api_key 2>/dev/null)

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

[ -f "$LT" ] || { echo "$(ts) FATAL: $LT missing" >> "$LOG"; exit 1; }

probe() {
  curl -s -m 12 -x http://127.0.0.1:18080 -o /dev/null -w "%{http_code}" \
    https://api.typesafe.ai/v1/models -H "Authorization: Bearer $KEY" 2>/dev/null
}

# 1) 本地监听在不在
if ! ss -tln 2>/dev/null | grep -q '127.0.0.1:18080'; then
  echo "$(ts) listener missing -> rebuild tunnel" >> "$LOG"
  bash "$LT" >> "$LOG" 2>&1
  sleep 3
fi

# 2) 真实探测
code=$(probe)
if [ "$code" = "200" ]; then
  exit 0
fi

echo "$(ts) probe failed (code=$code) -> rebuild" >> "$LOG"
# 注意：pkill -f "18080:127.0.0.1:18080" 会匹配到执行本脚本的 shell 自身
# （命令行里含该字面量），当场自杀。用字符类破坏自匹配。
pkill -f "[1]8080:127.0.0.1:18080" 2>/dev/null
sleep 1
bash "$LT" >> "$LOG" 2>&1
sleep 3
code2=$(probe)
echo "$(ts) after rebuild code=$code2" >> "$LOG"
