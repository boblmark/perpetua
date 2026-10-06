# Perpetua 独立控制台（VPS 公网版）

## 访问地址
- 公网：http://192.166.82.123:8080/
- 本地：http://127.0.0.1:8080/
- 认证：Bearer Token（与 MCP 共用 `/home/hatch/data/mcp_server/.token`）

## 架构
```
用户浏览器
  → http://192.166.82.123:8080 (VPS 公网)
  → SSH 反向隧道 (tunnel_8080.sh，独立于 8734 隧道)
  → 本地 127.0.0.1:8080 (console_server.py，纯标准库)
  → 读 /home/hatch/data 本地数据
```
VPS 上无数据、无后端，只做端口转发。8734 的 MCP 隧道完全不动。

## 文件
| 文件 | 说明 |
|---|---|
| console_server.py | 后端（纯标准库 http.server），REST API |
| index.html | 前端（单文件，深色主题） |
| tunnel_8080.sh | 8080 独立反向隧道保活 |
| perpetua-console.service | systemd：后端 |
| perpetua-console-tunnel.service | systemd：隧道 |
| deploy.sh | 一键部署 |

## API
| 端点 | 认证 | 说明 |
|---|---|---|
| GET / | 否 | 控制台页面 |
| GET /api/health | 是 | 系统健康（MCP/隧道/磁盘） |
| GET /api/pipeline | 是 | 七阶段流水线遥测 |
| GET /api/tenants | 是 | 租户/YouTube 账号列表 |
| GET /api/logs?lines=100 | 是 | 实时日志 tail |
| POST /api/exec | 是 | Web 终端（30s 超时，审计，危险命令拦截） |

## 运维
- 重启后端：`systemctl restart perpetua-console`
- 重启隧道：`systemctl restart perpetua-console-tunnel`
- 看门狗：`mcp-watchdog` 每 5 分钟检查（已接入）
- 审计日志：`/home/hatch/data/perpetua/terminal_audit.log`

## 部署（2026-10-06）
- 后端 + 隧道 systemd 已启用开机自启
- 外网验证通过：首页 200，各 API 正常，401 拦截正常
