#!/bin/bash
# GitHub 自动同步：把运行系统的前后台代码镜像到 repo/perpetua/，经 REST API 推送到
# boblmark/perpetua 的 main 分支（git HTTPS 不接受 surrogate token，故走 API）。
# 合并语义：远端 perpetua/* 由本地全量接管；perpetua/* 之外（pipeline/、youtube/、
# deploy/、.github/ 等）原样保留、不覆盖。
# 触发：build_install_package.sh 构建末尾自动调用；也可手动 ./github_sync.sh [--dry-run]
# 幂等：远端已是最新时零写操作。
set -e
# 定锚 cwd：调用方（build_install_package.sh）可能刚删掉自己的 TMPDIR，
# 此时 cwd 悬空，Python 启动会 FileNotFoundError。先落到安全目录。
cd /home/hatch 2>/dev/null || cd /
SRC=/home/hatch/data/perpetua
REPO=$SRC/repo
MIRROR=$REPO/perpetua
DATE=$(date +%Y%m%d-%H%M%S)
DRY=$1

mkdir -p "$MIRROR"

# ===== 1. 镜像运行系统 -> repo/perpetua/（与 github_push_api.py 的准入规则对齐）=====
# 注意：rsync 按顺序首个匹配生效，目录排除必须放在 --include='*/' 之前，
# 否则 snapshots/ 这类目录会被 */ 穿透（2026-10-16 实测教训）
rsync -a --delete \
  --exclude='videos/***' --exclude='snapshots/***' --exclude='db_backups/***' \
  --exclude='deleted_backup/***' --exclude='artifacts/***' --exclude='logs/***' \
  --exclude='hidden_logs/***' --exclude='audit/***' --exclude='auth/***' \
  --exclude='tenants/***' --exclude='billing/***' --exclude='models/***' \
  --exclude='jobs/***' --exclude='__pycache__/***' --exclude='repo/***' \
  --exclude='build/***' --exclude='dist/***' --exclude='node_modules/***' \
  --exclude='img_cache/***' --exclude='.git/***' \
  --exclude='*.bak*' --exclude='*.lock' --exclude='*.log' --exclude='*.json' \
  --include='*/' \
  --include='*.py' --include='*.html' --include='*.js' --include='*.css' \
  --include='*.sh' --include='*.md' --include='*.txt' --include='*.yaml' \
  --include='*.yml' --include='*.service' --include='*.ini' \
  --exclude='*' \
  "$SRC/" "$MIRROR/" 2>/dev/null || true

# cron 定义新鲜导出（每次同步实时生成，只保留最新 3 份）
mkdir -p "$MIRROR/crons"
if [ -d /home/hatch/workspace/cron.d ]; then
  tar -czf "$MIRROR/crons/cron_export_${DATE}.tar.gz" -C /home/hatch/workspace cron.d 2>/dev/null || true
  ls -t "$MIRROR"/crons/cron_export_*.tar.gz 2>/dev/null | tail -n +4 | xargs -r rm -f
fi

# ===== 2. 经 API 推送 =====
if [ "$DRY" = "--dry-run" ]; then
  python3 "$SRC/github_push_api.py" "$REPO" "auto-sync $DATE" --dry-run
  exit 0
fi
# 失败标记：推送失败时立 flag，下次 install-package-sync 即使无代码漂移也会重试推送
PENDING_FLAG="$SRC/.github_push_pending"
NEW_SHA=$(python3 "$SRC/github_push_api.py" "$REPO" "auto-sync $DATE") || {
  echo "[github] API 推送失败，本地镜像已就绪，已立 flag 下次重试"
  touch "$PENDING_FLAG"
  exit 1
}
rm -f "$PENDING_FLAG"
if [ "$NEW_SHA" = "NO_CHANGES" ]; then
  # plan 行已由 push 脚本打印
  exit 0
fi
# 推送审计日志（本地 .git 对象库无远端对象，update-ref 不可用；
# 真相源与完整历史在 GitHub 网页，本地记 SHA 备查）
echo "{\"at\":\"$DATE\",\"sha\":\"$NEW_SHA\"}" >> "$REPO/.push_log.jsonl"
echo "[github] 已推送 $DATE，SHA ${NEW_SHA:0:8}"
