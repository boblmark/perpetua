#!/usr/bin/env bash
# 为 Chromium 补齐缺失的系统库（无 root 环境适用）
#
# 场景：容器/沙箱缺 libnspr4.so 等库，且没有 root 权限执行 apt-get install。
# 解法：apt-get download（不需要 root）下载 .deb → dpkg-deb -x（不需要 root）解包到本地目录。
#
# 用法：bash scripts/fix_chromium_libs.sh [<chromium二进制路径>]
#   默认自动探测 playwright 的 chrome-headless-shell
set -u

LIBDIR="${PIPELINE_LIBS:-$HOME/.pipeline_libs}"

# 找目标二进制
BIN="${1:-}"
if [ -z "$BIN" ]; then
  BIN=$(find "$HOME/.cache/ms-playwright" -name "chrome-headless-shell" -type f 2>/dev/null | head -1)
fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "⚠️  未找到 Chromium 二进制。先运行：python3 -m playwright install chromium"
  exit 0
fi
echo "目标二进制: $BIN"

# lib 文件名 → Debian 包名 映射（trixie 命名，含 t64 过渡名）
declare -A MAP=(
  [libnspr4.so]=libnspr4
  [libnss3.so]=libnss3
  [libnssutil3.so]=libnss3
  [libsmime3.so]=libnss3
  [libatk-1.0.so.0]=libatk1.0-0t64
  [libatk-bridge-2.0.so.0]=libatk-bridge2.0-0t64
  [libatspi.so.0]=libatspi2.0-0t64
  [libcups.so.2]=libcups2t64
  [libasound.so.2]=libasound2t64
  [libXdamage.so.1]=libxdamage1
  [libxkbcommon.so.0]=libxkbcommon0
  [libavahi-common.so.3]=libavahi-common3
  [libavahi-client.so.3]=libavahi-client3
  [libgbm.so.1]=libgbm1
  [libdrm.so.2]=libdrm2
  [libxshmfence.so.1]=libxshmfence1
  [libpango-1.0.so.0]=libpango-1.0-0
  [libcairo.so.2]=libcairo2
  [libXcomposite.so.1]=libxcomposite1
  [libXrandr.so.2]=libxrandr2
  [libXfixes.so.3]=libxfixes3
  [libXext.so.6]=libxext6
  [libX11.so.6]=libx11-6
  [libX11-xcb.so.1]=libx11-xcb1
  [libexpat.so.1]=libexpat1
  [libdbus-1.so.3]=libdbus-1-3
)

mkdir -p "$LIBDIR/debs" "$LIBDIR/root" && cd "$LIBDIR/debs"

for round in 1 2 3 4 5; do
  MISSING=$(LD_LIBRARY_PATH="$LIBDIR/root/usr/lib/x86_64-linux-gnu:$LIBDIR/root/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}" \
            ldd "$BIN" 2>/dev/null | grep "not found" | awk '{print $1}' | sort -u)
  [ -z "$MISSING" ] && echo "✅ 第 $round 轮：已无缺失库" && break
  echo "▸ 第 $round 轮，缺失：$(echo $MISSING | tr '\n' ' ')"
  PKGS=""
  for lib in $MISSING; do
    pkg="${MAP[$lib]:-}"
    if [ -n "$pkg" ]; then PKGS="$PKGS $pkg"; else echo "   ⚠️  未知映射：$lib（尝试跳过）"; fi
  done
  [ -z "$PKGS" ] && break
  for pkg in $(echo $PKGS | tr ' ' '\n' | sort -u); do
    [ -f "${pkg}"*.deb ] || apt-get download "$pkg" >/dev/null 2>&1 || echo "   ✗ 下载失败 $pkg"
  done
  for d in *.deb; do [ -f "$d" ] && dpkg-deb -x "$d" "$LIBDIR/root" 2>/dev/null; done
done

echo
echo "库目录：$LIBDIR/root"
find "$LIBDIR/root" -name "*.so*" -type f 2>/dev/null | wc -l | xargs echo "已提取库文件数："
echo
echo "使用方式（任选其一）："
echo "  1) bash scripts/run_with_libs.sh <命令>"
echo "  2) export LD_LIBRARY_PATH=$LIBDIR/root/usr/lib/x86_64-linux-gnu:\$LD_LIBRARY_PATH"
echo
echo "验证：LD_LIBRARY_PATH=$LIBDIR/root/usr/lib/x86_64-linux-gnu $BIN --version"
