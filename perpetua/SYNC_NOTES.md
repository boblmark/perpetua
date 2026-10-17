# GitHub 自动同步机制（2026-10-16 生效）

## 目标
用户要求：前后台所有代码永远最新，每次改动后自动更新到 GitHub。

## 链路
```
代码改动
  -> install-package-sync cron（每 15 分钟，package_checksum.py 检测漂移）
  -> build_install_package.sh（重建安装包 + 新鲜 cron 导出）
  -> github_sync.sh（镜像运行系统 -> repo/perpetua/，经 REST API 推送）
  -> github.com/boblmark/perpetua 的 main 分支
```

## 为什么走 REST API 而不是 git push
保险库里的 GitHub 凭据是 authd surrogate token（`hsurr:...`），`api.github.com`
认它，但 `github.com` 的 git HTTPS 不认（报 Invalid username or token）。
所以推送走 GitHub git-database REST API（create blob/tree/commit + 更新 ref），
token 经 authd 实时获取，永不落盘、永不打印。
（另：GitHub 更新 ref 用复数 `/git/refs/`，读取用单数 `/git/ref/`，两处不一样。）

## 合并语义
- 远端 `perpetua/*` 由本地运行系统全量接管：新增/更新/删除以本地为准。
- 远端 `perpetua/*` 之外的路径（`pipeline/`、`youtube/`、`deploy/`、`.github/`、
  `mcp_server/` 等）原样保留，一个 blob 都不重建，GitHub 侧手工改动不会被覆盖。
- 命中本地排除规则的远端路径（如 `perpetua/billing/`）视为保留，不删除。
- 无变化时零写操作（只读 2 个 API 就返回）。

## 镜像准入（github_sync.sh rsync 规则，与 github_push_api.py 对齐）
- 扩展名：.py/.html/.js/.css/.sh/.md/.txt/.yaml/.yml/.service/.ini（+crons/*.tar.gz）
- 排除：*.bak*/*.lock/*.log/*.json（状态文件不进版本库）、
  videos/snapshots/db_backups/deleted_backup/artifacts/logs/hidden_logs/
  audit/auth/tenants/billing/models/jobs/__pycache__/repo/build/dist（运行时/大体积）
- custom-skills（2026-10-18 用户要求纳入）：~/workspace/custom-skills/ -> repo/perpetua/skills/，
  同一推送链路、同一全量接管语义；技能目录只含 curated 文档与脚本无运行时状态，
  故 *.json 允许进入（与主树不同）；不进安装包（build_install_package.sh 按显式文件清单打包，不受影响）
- 教训：rsync 的目录排除必须放在 `--include='*/'` 之前，否则会被穿透；
  用 `dir/***` 写法确保目录内容整体排除。

## 本地 repo/ 目录的定位
`repo/` 是同步 staging 区，不是完整 clone：
- `repo/perpetua/` = 待推送的代码镜像（rsync --delete 严格镜像，手工放里面的文件会被删）
- 真相源与完整提交历史在 GitHub 网页（boblmark/perpetua，main 分支）
- 本地审计：`repo/.push_log.jsonl` 记录每次推送的时间与 SHA；
  `github_sync.sh --dry-run` 可预览下次推送的计划（新增/更新/删除）
- 不要用 `git status`/`git log` 判断远端状态（本地对象库无远端对象）

## 相关文件
- `/home/hatch/data/perpetua/github_sync.sh` —— 镜像 + 推送入口
- `/home/hatch/data/perpetua/github_push_api.py` —— REST API 推送实现（含重试）
- `/home/hatch/data/perpetua/package_checksum.py` —— 漂移检测唯一口径
- `/home/hatch/data/perpetua/build_install_package.sh` —— 构建 + 触发同步
- `/home/hatch/data/perpetua/.git-credential-helper.sh` —— 保险库取 token（git 留用）
