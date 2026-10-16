# Perpetua Windows 迁移手册（MIGRATION_WINDOWS.md）

适用：新 VPS 为 Windows Server 2019+（桌面版与 VPS 迁移目标已合一）。

## 0. 前置条件

- Windows Server 2019+，管理员权限
- Python 3.11+（安装时勾选 Add to PATH）
- 系统自带 OpenSSH 客户端（`ssh` 命令可用）
- Task Scheduler 服务运行中

## 1. 安装

1. 解压 `perpetua-windows-migration-YYYYMMDD.tar.gz`
2. 右键 `windows_compat\install_windows.bat` → 以管理员身份运行
3. 按提示检查 `%PROGRAMDATA%\Perpetua\data\perpetua.ini`（隧道目标、密钥路径）

## 2. 凭据迁移（绝不进包，独立通道）

| 凭据 | 方式 |
|---|---|
| YouTube OAuth | 新机器浏览器走授权流程重授（推荐），或旧机经加密通道直传后落地 ACL 锁定 |
| MCP bearer / API key | 旧 VPS → 新 VPS 经 SSH/scp 直传，落地后仅管理员可读 |
| 浏览器 profile/cookie | rsync/scp 机器间直传，不进归档 |

8 项密钥清单见包内 `SECRETS_MANIFEST.md`。

## 3. 运行时数据迁移

1. 旧机器：`python windows_compat/tools_win/snapshot.py --out \\共享\perpetua-snap`
   （或快照后 scp 到新机器）
2. 新机器：`python windows_compat/tools_win/restore.py --from <快照目录> --dry-run`
   先看一遍，再去 `--dry-run` 真执行（自动备份目标为 `*.bak-*`）

## 4. 冒烟验收

```
python windows_compat\tools_win\verify.py --check-tunnels
```

全 PASS（端口类 WARNING 允许，服务起后复查）→ 隧道 dry-run：

```
python windows_compat\tunnel_py.py keepalive-all --dry-run
```

## 5. 调度任务

```
python windows_compat\sched_win.py --scan
```

生成 `windows_compat\tasks_xml\`（XML + `import_tasks.bat` + `COVERAGE.txt`），
管理员运行 `import_tasks.bat` 导入。`COVERAGE.txt` 中 agent 平台类为占位，
需在 Windows 部署 agent 调度运行时后替换。

## 6. 回滚

- 旧机器保留到新机器验收通过；
- `restore.py` 每次写目标前自动备份（`*.bak-YYYYMMDD-HHMMSS`）；
- 隧道/计划任务：`schtasks /DELETE /TN "perpetua-*"` 可整批移除。

## 7. 已知降级（相对 Linux 版）

- 凭据代理鉴权降级为本机+管理员账户+DACL（无 SO_PEERCRED）；
- `chmod 600` 在 Windows 下跳过，靠 NTFS ACL；
- `fcntl` 文件锁未移植（`*.lock`），多实例并发写需注意；
- fcntl/Unix 特有脚本（40+ 一次性 .sh）按需用 Git Bash 或改写。
