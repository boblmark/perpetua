# Perpetua Windows 适配层说明

## 组成

| 文件 | 替代的 Linux 绑定 | 说明 |
|---|---|---|
| `config.py` | 硬编码 `/home/hatch/data`（130 处） | `DATA_DIR` 三级优先级：环境变量 `PERPETUA_DATA_DIR` > `perpetua.ini` > 系统默认（Windows `%PROGRAMDATA%\Perpetua\data`，Linux `/home/hatch/data`） |
| `tunnel_py.py` | `vps_console/tunnel_*.sh` + `*_keepalive.sh`（9 个） | subprocess 驱动系统 ssh；`run`（while-true worker）/`keepalive`（supervisor）/`keepalive-all`；进程检查 Linux 用 pgrep+ps 二次确认，Windows 用 tasklist |
| `cred_proxy_win.py` | Unix socket `/run/credential-proxy/proxy.sock` | 命名管道 `\\.\pipe\perpetua-cred-proxy`；客户端 API 与 Linux 版同名（`get_token`/`revoke`），自动按平台选传输 |
| `sched_win.py` | systemd unit（9 个）+ cron 舰队（约65个） | cron .md → Task Scheduler XML（`tasks_xml/`），附 `import_tasks.bat` 与 `COVERAGE.txt` |
| `install_windows.bat` | `tools/install.sh`（apt/systemd） | 一键安装：验管理员/Python→pip 装 pywin32→写 `perpetua.ini`→注册隧道 keepalive→导入 cron XML |
| `task_stub.bat` / `task_direct.bat` | — | Task Scheduler 动作中转：直接命令类分发执行，agent 平台类记日志占位 |

## 调度选型：Task Scheduler XML（不选常驻 Python 服务）

1. 与 Linux 侧对齐：Linux 用系统 cron 而非自研常驻服务，Windows 对等物即 Task Scheduler；
2. 可靠性由系统保证：休眠唤醒、失败重试、错过补跑、电源条件；
3. 无常驻进程，故障面小；`schtasks /CREATE /XML` 批量导入；
4. 常驻 Python 服务需自研调度/保活/日志轮转，重复造轮子。

## 诚实降级项

- **凭据代理鉴权**：Linux 靠 SO_PEERCRED 验调用者；Windows 命名管道无对等凭据，靠“仅本机 + 服务端管理员账户 + 管道 DACL”补偿。同一机器的管理员进程理论可连——Windows 单机模型固有限制。
- **chmod 600**：Windows 上 `os.chmod` 只支持只读位；`config.chmod_private()` 在 Windows 下跳过，靠服务账户 + NTFS ACL 隔离（安装时文档提示）。
- **fcntl 文件锁**：`*.lock` 文件在 Windows 需 `msvcrt.locking`，本期未实现（见未覆盖项）。
- **cron .md 中的 agent 平台任务**：其执行依赖 agent 调度运行时；XML 生成占位任务（`task_stub.bat`），`COVERAGE.txt` 列出清单，需后续在 Windows 部署运行时。
- **ProxyCommand**：现有隧道经 `nc -X connect -x 198.19.0.1:3128` 代理出口；Windows 直连公网时留空，或按实际改写 `tunnels.json`。

## 在 Linux 上已验证

- `python -m py_compile` 全过；`config.py` 模拟 Windows 路径加载测试通过；
- `tunnel_py.py list/--dry-run`、`sched_win.py --scan --dry-run` 通过；
- 打包后脱敏扫描 0 密钥残留（精确模式）。

## 需 Windows 真机验证（未覆盖）

1. `install_windows.bat` 端到端（管理员权限、pywin32、schtasks 导入）；
2. 命名管道服务端收发（需 pywin32 + 真实 vault）；
3. 真实 ssh 隧道拉起（含 ProxyCommand 在 Windows OpenSSH 下的行为）；
4. Task Scheduler XML 导入后触发器实际触发；
5. `verify.py` 全量冒烟（端口/服务/队列）。
