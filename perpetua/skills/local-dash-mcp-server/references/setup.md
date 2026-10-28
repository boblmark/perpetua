# 部署与重启手册

## 首次部署（VPS 侧，一次性）
```bash
# 1. 公钥加入 VPS
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo '<id_ed25519.pub内容>' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 2. 开 GatewayPorts（让反向隧道监听公网）
grep -q '^GatewayPorts yes' /etc/ssh/sshd_config || echo 'GatewayPorts yes' >> /etc/ssh/sshd_config
systemctl reload sshd || service ssh reload
```

## 本地启动顺序
```bash
cd /home/hatch/data/mcp_server
# 1. MCP server（FastMCP，venv 已锁 mcp<2）
./venv/bin/python server.py >> mcp-server.out.log 2>&1 &
# 2. SSH 反向隧道（保活脚本）
/bin/bash tunnel.sh >> tunnel.log 2>&1 &
# 3. 看门狗由 cron 每 5 分钟触发（job: mcp-watchdog），无需手动
```

## 验证
```bash
TOKEN=$(cat /home/hatch/data/mcp_server/.token-<调用方>)
# 经 VPS 公网调 tools/list，应返回该 token scope 内的工具名
curl -s --max-time 20 -X POST http://192.166.82.123:8734/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  -D /tmp/h.txt -o /dev/null
SID=$(grep -i mcp-session-id /tmp/h.txt | tr -d '\r' | awk '{print $2}')
curl -s --max-time 20 -X POST http://192.166.82.123:8734/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## 重启 server（改代码/token 后）
```bash
for p in $(pgrep -f "server[.]py"); do
  ps -o cmd= -p $p 2>/dev/null | grep -q "mcp_server" && kill $p
done
sleep 2
cd /home/hatch/data/mcp_server && ./venv/bin/python server.py >> mcp-server.out.log 2>&1 &
```
注意：`pkill -f server.py` 会误杀执行 pkill 的 shell，务必用上面的精确匹配。
