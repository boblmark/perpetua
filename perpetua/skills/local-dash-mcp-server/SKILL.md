

# Dash MCP Server（对外）

## Purpose
让外部智能体通过公网调用 Dash 本机的 MCP server，实现跨 agent 自动协作。
MCP 协议是客户端拉取式：外部 agent 主动调 Dash，Dash 无法主动推送。

## Architecture
```
外部Agent → http://192.166.82.123:8734/mcp → VPS → SSH反向隧道 → 本地 127.0.0.1:8734 → MCP server
```
- 本地服务：`127.0.0.1:8734`，Streamable HTTP，路径 `/mcp`，健康检查 `/health`
- VPS：`root@192.166.82.123`，已开 `GatewayPorts yes`
- 隧道脚本：`/home/hatch/data/mcp_server/tunnel.sh`（保活，断线 5s 重连）
- 看门狗：`/home/hatch/data/mcp_server/watchdog.py`（保活 mcp-server + tunnel）
- 本地实现：`/home/hatch/data/mcp_server/server.py`（FastMCP，DNS 重绑定保护已关）

## Auth
- Header：`Authorization: Bearer <token>`
- Token 文件：`/home/hatch/data/mcp_server/.token`（600 权限，勿外传至非授权方）

## Tooling（9 个工具）
| 工具 | 用途 |
|---|---|
| `read_file` | 读 `/home/hatch/data` 下文件（path 相对路径） |
| `write_file` | 写文件到 `/home/hatch/data` 下 |
| `list_dir` | 列目录 |
| `submit_job` | 派任务给 Dash。`job_type`: `generate_video` \| `generate_image` \| `note` \| `collab_poll` \| `ask_dash`，`payload` 为 JSON 字符串，返回 `job_id` |
| `job_status` | 用 `job_id` 查任务状态与结果 |
| `get_protocol` | 读协作协议 `collab/PROTOCOL.md` |
| `exec_shell` | ⚠️ 高权限：在 VM 上执行 shell 命令，工作目录固定 `/home/hatch/data`，超时 5-120s（默认 30s）。可联网、运行任意程序 |
| `web_search` | 网页搜索（DuckDuckGo），返回标题/链接 |
| `fetch_url` | 抓取网页文本（自动去 HTML 标签） |

文件操作全部限制在 `/home/hatch/data` 内，越界拒绝。
`exec_shell` 为最高权限工具，仅授予可信协作方；token 泄露即等同 VM 被接管。

## 异步取货协作模式（inbox）
因 Dash 无法推送，采用货架轮询：
1. Dash 生成产物后，写入 `/home/hatch/data/collab/inbox.json` 的 `pending_pickup` 数组（`status: ready`）
2. 外部 agent 设定时任务（建议 30 分钟），调 `read_file` 读 `inbox.json`
3. 有 `ready` 条目则 `read_file` 取走对应文件，处理完后 `write_file` 把该条目 `status` 改为 `done`
4. 条目 schema：`{file, title, created, status}`，见 `references/agent-onboarding.md`

## 媒体任务与代办求助自动处理
- 定时任务 `mcp-media-job-processor` 每 10 分钟检查 `/home/hatch/data/mcp_jobs/pending/`
- 自动处理 `job_type` 为 `generate_image` / `generate_video` 的任务，生成后存 `/home/hatch/data/`，更新 `job_status` 并上架到 `inbox.json`
- `ask_dash`：外部 agent 把难题描述发给 Dash，Dash 直接动手解决（查资料、跑命令、生成文件等），结果写回 `job_status`
- 外部 agent 流程：`submit_job` → 轮询 `job_status` → `read_file` 取货，全程无需人工

## Operating Rules
1. 对外只暴露 `http://192.166.82.123:8734/mcp`，不要直接给外部 agent 本地地址。
2. Token 只给已授权的协作方；如曾在公开渠道出现过，轮换后更新 `.token` 并重启 server。
3. 改 `server.py` 后必须重启 MCP server（看门狗不会自动重载代码）。
4. 隧道断了先查 `tunnel.log`，再看 VPS 上 `ss -tlnp | grep 8734`。
5. 遇到 `421` 检查 FastMCP `transport_security` 是否误开；遇到 `401` 检查 token 是否过期/不一致（server 启动时加载 `.token`，改 token 后要重启）。
6. SSH 走代理：`ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p"`（直连 22 端口被代理拦截）。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
