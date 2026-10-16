# VPS 完整迁移包机制说明（2026-10-16 生效）

## 定义
用户授权 Dash 决定（2026-10-16）：静态归档 `perpetua-vps-migration-YYYYMMDD.tar.gz`
= 前后台源码递归全量 + 基础设施脚本与脱敏配置 + 迁移工具链 + MIGRATION.md。
OAuth token / MCP bearer / API key / 浏览器 profile-cookie / 实时 queue 快照
**绝不进静态包**，走旧 VPS→新 VPS 的 SSH 加密直传（落地 600）或新机重授权。

## 文件
- `/home/hatch/data/perpetua/build_vps_migration_package.sh` —— 构建脚本（自带漂移检测，`--force` 强制重建）
- `/home/hatch/data/perpetua/vps_migration_checksum.py` —— 漂移检测唯一口径（递归，排除清单与构建脚本的 rsync 排除保持一致）
- `~/workspace/your_files/perpetua-vps-migration-YYYYMMDD.tar.gz` —— 产物
- `~/workspace/your_files/.vps_migration_manifest.json` —— 构建 manifest（sha256/包名/大小/文件数/脱敏计数）

## 包内结构
```
perpetua-vps-migration-YYYYMMDD/
  code/                 # 脱敏后源码全量（525+ 文件范围，排除见下）
  tools/
    install.sh          # 新机安装（幂等：dpkg 检查/mkdir -p/rsync/cmp 比对后才装 unit）
    snapshot.sh         # 旧机快照（只读：sqlite backup API + cp 状态 JSON + cron 导出）
    restore.sh          # 新机恢复（含 perpetua 外的 youtube/ask_studio/jev 状态，原路径放回）
    verify.sh           # 冒烟验收（--dry-run 纯逻辑自洽检查；真实模式 curl 端口+探针）
    rollback.sh         # 回滚（停新机服务，旧机保持权威，需输入 yes 确认）
  MIGRATION.md          # 步骤/检查清单/回滚条件/旧机下线条件
  SECRETS_MANIFEST.md   # 8 项密钥：名称/用途/获取方式/落地路径/权限 + 直传示例
  FILELIST.txt          # 包内完整文件清单
```

## 排除清单（永不进包）
- 密钥：`auth/`、`commander_chat_token`、`distributor/cookies/`、`distributor/vendor/cookies/`
- 实时状态：`queue.db`、`ops_center.db`、`*_queue.json`、`*_ledger.json`、`*_inbox.json`、
  `*_state.json`、`private_queue.json`、`anomaly_ledger.json`、`escalation_inbox.json`、
  `vps_traffic.jsonl`、`video_quota.json` 等（由 snapshot.sh 在迁移窗口实时生成）
- 大体积/运行时：`videos/`、`snapshots/`、`db_backups/`、`logs/`、`repo/`、`build/`、
  `deploy/perpetua-linux/`（88M 二进制）、`*.mp4`、`ai_unhinged/ep1/` 等

## 脱敏
构建时对 staging 做两遍替换（只计数不打印值）：
1. 已知 token 格式：`hsurr:`/`sk-`/`ghp_`/`AIza`/`xox[bap]-` → `__REDACTED__`
2. 密钥键名（api_key/secret/password/bearer/private_key/…）的引号字面量或 token 形值 → `__REDACTED__`
   （跳过 `$()`/`${}`/`(`/`.`/`/` 等代码表达式，避免破坏源码）
实测：当前源码树内无字面量密钥（密钥本就只存于被排除的文件/vault），
唯一命中是 SYNC_NOTES.md 文档中的 `hsurr:...` 示例写法。

## 自动更新链路
`install-package-sync` cron（15m）第 6 步：每轮调用
`build_vps_migration_package.sh`（无参数）。脚本先算 `vps_migration_checksum.py`，
与 manifest 比对：无漂移秒级退出，有漂移才重建。备份：
`/home/hatch/workspace/cron.d/minutely/install-package-sync__interval@15m.md.bak-20261016-1445`
（另：cron 定义文件为只读副本，实际经 `cron.update` 修改，已验证回读）。

## 验证记录（2026-10-16 首次构建）
- 包：`perpetua-vps-migration-20261016.tar.gz`，2.9M，579 文件
- 解包测试：`~/workspace/vps-migration-test/`（持久目录）
- `bash -n`：全部 .sh 通过（含 5 个工具脚本）
- 密钥残留扫描：密钥文件 0、token 格式 0、密钥字面量 0、queue 快照文件 0
- `verify.sh --dry-run`：13 PASS / 0 FAIL
- `snapshot.sh` 实测：queue.db/ops_center.db（0 表，源库即空）+ private_queue +
  ask_studio 双队列 + jev criteria + ledger/inbox/command 队列 + cron.d 全部导出成功
- 未执行项：`install.sh` 未真实跑（会写 /etc/systemd/system + apt，超出只读验证范围）；
  `restore.sh`/`rollback.sh` 未在新机实测（无目标机器）。

## 回滚策略
旧机器保留到新机器冒烟验收通过（verify.sh 全 PASS + 24h 观察 + 用户批准下线）。
回滚 = `tools/rollback.sh` 停新机服务，流量留在旧机。
