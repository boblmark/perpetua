#!/bin/bash
# 检查 Dash MCP 对外链路状态
# 用法: mcp-status.sh
HERE=/home/hatch/data/mcp_server
TOKEN=$(cat $HERE/.token 2>/dev/null)
echo "=== 本地 MCP server ==="
# server 以相对路径启动（./venv/bin/python server.py），cmdline 无 mcp_server 目录名，故同时匹配相对与绝对两种写法
pgrep -f "mcp_server/server[.]py|[ /]server[.]py$" >/dev/null && echo "OK: server 运行中" || echo "FAIL: server 未运行"
curl -s --max-time 5 http://127.0.0.1:8734/health | head -c 60; echo
echo "=== SSH 反向隧道 ==="
pgrep -f "tunnel[.]sh" >/dev/null && echo "OK: tunnel.sh 运行中" || echo "FAIL: tunnel.sh 未运行"
echo "=== VPS 监听 ==="
ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
  root@192.166.82.123 "ss -tlnp 2>/dev/null | grep ':8738' | head -1" 2>&1
echo "=== 公网 tools/list ==="
SID=$(curl -s --max-time 15 -X POST http://192.166.82.123:8738/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  -D - -o /dev/null 2>/dev/null | grep -i mcp-session-id | tr -d '\r' | awk '{print $2}')
if [ -n "$SID" ]; then
  curl -s --max-time 15 -X POST http://192.166.82.123:8738/mcp \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: $SID" \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' 2>/dev/null | \
    python3 -c "import json,sys; raw=sys.stdin.read(); ds=[l[6:] for l in raw.splitlines() if l.startswith('data:')]; print('TOOLS:', [t['name'] for t in json.loads(ds[0])['result']['tools']] if ds else 'FAIL')"
else
  echo "FAIL: 无法建立 MCP 会话"
fi
