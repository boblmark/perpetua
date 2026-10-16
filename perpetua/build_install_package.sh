#!/bin/bash
# 安装包自动同步构建脚本
# 用途：从当前运行系统构建 Windows 安装包，确保下载包与运行系统完全同步
# 触发：手动 ./build_install_package.sh，或由 install-package-sync cron 定时检查漂移后调用

set -e
SRC=/home/hatch/data/perpetua
OUT=/home/hatch/workspace/your_files
DATE=$(date +%Y%m%d)
TMPDIR=$(mktemp -d)
MANIFEST="$OUT/.install_package_manifest.json"

echo "[build] 构建日期: $DATE"

# ===== 基础包 perpetua-windows =====
PKG1="perpetua-windows-$DATE.tar.gz"
mkdir -p "$TMPDIR/perpetua-windows/code" "$TMPDIR/perpetua-windows/platform_scripts" "$TMPDIR/perpetua-windows/docs" "$TMPDIR/perpetua-windows/data"

# 核心代码（当前运行的 79 脚本中精选）
for f in pipeline.py auto_pipeline.py publish_health.py queue_db.py dead_state_watchdog.py approval_lease.py inbox.py circuit_breaker.py executor.py; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$TMPDIR/perpetua-windows/code/"
done
# 控制台
mkdir -p "$TMPDIR/perpetua-windows/vps_console"
cp "$SRC/vps_console/console_server.py" "$TMPDIR/perpetua-windows/vps_console/" 2>/dev/null || true
cp "$SRC/vps_console/index.html" "$TMPDIR/perpetua-windows/vps_console/" 2>/dev/null || true
# 安装脚本
[ -d "$SRC/platform_scripts" ] && cp -r "$SRC/platform_scripts/"* "$TMPDIR/perpetua-windows/platform_scripts/" 2>/dev/null || true
# 文档
[ -f "$SRC/WINDOWS_TEST_CHECKLIST.md" ] && cp "$SRC/WINDOWS_TEST_CHECKLIST.md" "$TMPDIR/perpetua-windows/"
# 配置
[ -f "$SRC/platform_config.yaml" ] && cp "$SRC/platform_config.yaml" "$TMPDIR/perpetua-windows/"
[ -f "$SRC/requirements.txt" ] && cp "$SRC/requirements.txt" "$TMPDIR/perpetua-windows/"

cd "$TMPDIR" && tar -czf "$OUT/$PKG1" perpetua-windows/
echo "[build] $PKG1 完成 ($(du -h "$OUT/$PKG1" | cut -f1))"

# ===== 完整包 perpetua-windows-full =====
PKG2="perpetua-windows-full-$DATE.tar.gz"
cp -r "$TMPDIR/perpetua-windows" "$TMPDIR/perpetua-windows-full"
# 完整包加：全部 79 脚本
mkdir -p "$TMPDIR/perpetua-windows-full/code_full"
cp "$SRC"/*.py "$TMPDIR/perpetua-windows-full/code_full/" 2>/dev/null || true
# 数据目录结构（不含敏感数据）
mkdir -p "$TMPDIR/perpetua-windows-full/data"
# cron 定义新鲜导出（2026-10-16 起：每次构建实时生成，替代 2026-10-14 旧快照）
if [ -d /home/hatch/workspace/cron.d ]; then
  mkdir -p "$TMPDIR/cronexport/goal_crons"
  cp -r /home/hatch/workspace/cron.d "$TMPDIR/cronexport/" 2>/dev/null || true
  for d in /home/hatch/workspace/goals/*/crons; do
    [ -d "$d" ] && cp -r "$d" "$TMPDIR/cronexport/goal_crons/$(basename $(dirname $d))" 2>/dev/null || true
  done
  tar -czf "$TMPDIR/perpetua-windows-full/cron_export_$DATE.tar.gz" -C "$TMPDIR/cronexport" . 2>/dev/null || true
  echo "[build] cron 新鲜导出完成"
fi

cd "$TMPDIR" && tar -czf "$OUT/$PKG2" perpetua-windows-full/
echo "[build] $PKG2 完成 ($(du -h "$OUT/$PKG2" | cut -f1))"

# ===== 写 manifest（源文件校验和，口径见 package_checksum.py，唯一真相源）=====
python3 -c "
import json, sys
sys.path.insert(0, '$SRC')
from package_checksum import checksum
digest, n = checksum()
manifest = {'built_at': '$DATE', 'sha256': digest, 'file_count': n, 'packages': ['$PKG1', '$PKG2']}
json.dump(manifest, open('$MANIFEST','w'), indent=2)
print('[build] manifest 已更新:', digest[:16], '文件数:', n)
"

rm -rf "$TMPDIR"
echo "[build] 完成"

# ===== GitHub 自动同步（每次改动构建后推送，失败不影响安装包）=====
"$SRC/github_sync.sh" || echo "[build] GitHub 同步失败（网络或认证），下次构建重试"
