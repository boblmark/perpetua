# 排障手册

| 症状 | 原因 | 处理 |
|---|---|---|
| `421 Misdirected Request`，日志 `Invalid Host header` | FastMCP DNS 重绑定保护拦截了 VPS 域名/IP 的 Host 头 | `server.py` 中 `FastMCP(transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))`，重启 |
| `401 Unauthorized` | token 不一致 | server 启动时加载 `.token`；改 token 后必须重启 server；检查外部 agent 用的是否为当前 `.token` |
| 经 VPS 连不上，`ss` 显示 VPS 无 8734 监听 | 隧道断了 | 查本地 `tunnel.log`；`pgrep -f tunnel.sh` 不在则重启 `tunnel.sh`；看门狗每 5 分钟也会拉起 |
| SSH 直连 `Connection reset by 198.19.0.1:3128` | 出站 22 端口被代理拦截 | 必须加 `ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p"` |
| SSH `Permission denied (publickey)` | VPS 未录入本机公钥 | 在 VPS 执行：`echo '<id_ed25519.pub>' >> ~/.ssh/authorized_keys` |
| 隧道能建但外部连不上 | VPS `GatewayPorts` 未开 | VPS 上 `echo 'GatewayPorts yes' >> /etc/ssh/sshd_config && systemctl reload sshd` |
| `pip install mcp` 后 server 起不来 | mcp 2.x API 不兼容旧代码 | venv 已锁定 `mcp<2`，不要升级；重装用 `./venv/bin/pip install 'mcp<2'` |
| Cloudflare Worker 中继失败 | KV 跨 isolate 不一致 / WS isolate 隔离 / DO 绑定 UI 识别不到 | 已放弃该路线，改用 VPS 反向隧道；`worker*.js` 仅作历史备份 |

## 关键文件清单
- `/home/hatch/data/mcp_server/server.py` — MCP server 实现
- `/home/hatch/data/mcp_server/tunnel.sh` — SSH 反向隧道保活脚本
- `/home/hatch/data/mcp_server/watchdog.py` — 看门狗（cron 每 5 分钟）
- `/home/hatch/data/mcp_server/.tokens.json` — 分权限 token 注册表（600）；旧全量 `.token` 已于 2026-10-28 停用
- `/home/hatch/data/mcp_server/venv` — Python 虚拟环境（mcp<2）
- `/home/hatch/data/collab/inbox.json` — 异步取货货架
- `/home/hatch/data/collab/pilot_status.md` — 试点状态说明
