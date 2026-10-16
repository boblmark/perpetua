# Perpetua Windows 移植清单（Linux 绑定点盘点）

生成日期：2026-10-16。盘点范围：`/home/hatch/data/perpetua`（不含 `repo/` 镜像副本与 `.bak*`）。
目标：新 VPS 为 Windows Server 2019+，桌面版与 VPS 迁移目标已合一。

## 1. bash 隧道脚本（vps_console/tunnel_*.sh）——9 个

| 脚本 | 用途 | 端口/方向 |
|---|---|---|
| `tunnel_8080.sh` | 控制台/OA 反向隧道 | R 8080 → VPS 8080 |
| `tunnel_8734_keepalive.sh` | MCP keepalive（supervisor） | 8734 |
| `tunnel_8738_keepalive.sh` | keepalive（supervisor） | 8738 |
| `tunnel_18738.sh` + `tunnel_18738_keepalive.sh` | Gemini Live 语音隧道 | 18738 |
| `tunnel_18901.sh` | 18901 隧道 | 18901 |
| `tunnel_18091.sh` | Semantica 知识图谱隧道 | R 18091 |
| `tunnel_nano.sh` + `tunnel_nano_keepalive.sh` | nanoMuse 反向隧道 | R 18736/18737/18739 |

行为模式（两类）：
- **A 类（while true 自重连）**：`ssh -N -R/-L ... root@192.166.82.123`，断线 sleep 5 重试，日志写 `*.log`。
- **B 类（keepalive supervisor）**：每 5 分钟由 cron 调用，`pgrep -f` 检查 A 类进程，不在则精确清理残留 ssh（按端口匹配，防误杀）后拉起。

Windows 替代：`windows_compat/tunnel_py.py`（subprocess 驱动系统 ssh，supervisor 逻辑跨平台；Windows 用 tasklist 替代 pgrep）。

## 2. systemd unit —— deploy/systemd/ 9 个（生产）+ deploy/linux/ 1 个

`perpetua-mcp.service`、`perpetua-watchdog.service/.timer`、`perpetua-trend-spike.service/.timer`、
`perpetua-post-publish.service/.timer`、`perpetua-align-weekly.service/.timer`、`perpetua-local-proxy.service`、
`perpetua-mcp-binary.service`。

Windows 替代：见 `windows_compat/sched_win.py` 选型（Task Scheduler XML，§5）。

## 3. Unix socket 凭据代理 —— credential_proxy_client.py

- 服务端 socket：`/run/credential-proxy/proxy.sock`（`socket.AF_UNIX`），SO_PEERCRED 鉴权。
- 客户端：`SOCKET_PATH = "/run/credential-proxy/proxy.sock"` 硬编码，`get_token()/revoke()`。
- 调用方：3 处（`credential_proxy_client.py` 及其 repo 镜像）。

Windows 替代：`windows_compat/cred_proxy_win.py`（命名管道 `\\.\pipe\perpetua-cred-proxy`；
鉴权降级为本机回环 + 调用方进程校验，见文件内说明）。

## 4. 硬编码 /home/hatch/data —— 130 个 .py 文件

全部走 `windows_compat/config.py` 的 `DATA_DIR`（环境变量 `PERPETUA_DATA_DIR` /
`perpetua.ini` > Windows 默认 `%PROGRAMDATA%\Perpetua\data` > Linux 默认 `/home/hatch/data`）。
注意：生产 Linux 代码不动；新写代码一律经 config.py 取路径。

## 5. chmod 调用 —— 33 个 .py 文件

模式：密钥文件 `0o600`、目录 `0o700`。Windows 上 `os.chmod` 仅支持只读位，
需改为条件跳过 + 文档说明（Windows 靠 NTFS ACL / 服务账户隔离，见 README_WINDOWS.md）。

## 6. cron 舰队 —— 约 65 个定义

- `~/workspace/cron.d/`：minutely 19 + hourly/daily/weekly/monthly/secondly/yearly/runonce（含 _archive/_invalid）。
- `~/workspace/goals/*/crons/`：98 个 .md（含 minutely/hourly/daily/weekly）。
- 命名模式：`<name>__interval@<Nm>.md` / `<name>__daily@<HH:MM:SS>_user_current.md`，
  正文 frontmatter 含 `schedule:`（kind/timezone/every）。

Windows 替代：`windows_compat/sched_win.py` —— 翻译为 Task Scheduler XML（见 §5 选型）。

## 7. 其他 Linux 绑定（次要）

- `os.getuid()/pwd` 类调用、shebang `#!/bin/bash` 的 .sh 工具脚本约 40+（tunnel 除外多为一次性运维脚本，Windows 下用 Git Bash 或改写，按需处理）。
- `fcntl` 文件锁（`*.lock`）：Windows 用 `msvcrt.locking` 替代，`windows_compat` 预留 `flock_win.py` 接口（本期未实现，见未覆盖项）。

## 8. 假设（Windows 侧）

Windows Server 2019+、管理员权限、Python 3.11+、系统自带 OpenSSH 客户端可用、
Task Scheduler 服务运行中。
