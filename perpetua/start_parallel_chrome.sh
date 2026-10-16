#!/bin/bash
# 并行 Chrome 实例（9223），供 agent-browser 并行任务使用
# 用法：bash start_parallel_chrome.sh
ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no \
  -o 'ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p' \
  root@192.166.82.123 '
if curl -s -m 3 http://127.0.0.1:9223/json/version >/dev/null 2>&1; then
  echo "9223 已在运行"
else
  mkdir -p /tmp/chrome-parallel-profile
  nohup /usr/bin/google-chrome --headless --no-sandbox --disable-gpu \
    --disable-dev-shm-usage --remote-debugging-port=9223 \
    --user-data-dir=/tmp/chrome-parallel-profile about:blank >/dev/null 2>&1 &
  sleep 3
  curl -s -m 5 http://127.0.0.1:9223/json/version | python3 -c "import json,sys; print(\"9223 启动:\", json.load(sys.stdin)[\"Browser\"])"
fi
'
