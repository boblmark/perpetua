#!/bin/bash
# Perpetua Linux 二进制构建脚本
# 在源机器上运行：bash build_binary.sh
# 产物：perpetua-linux/ 目录（含二进制 + 安装脚本）

set -e
DATA_DIR="/home/hatch/data"
OUT_DIR="/home/hatch/data/perpetua/deploy"
BUILD_DIR="/tmp/nuitka_build"
PKG_DIR="$OUT_DIR/perpetua-linux"
VENV_PY="$DATA_DIR/mcp_server/venv/bin/python"

echo "=== Perpetua 二进制构建（Nuitka） ==="
echo ""

# 检查 Nuitka
$VENV_PY -m nuitka --version > /dev/null 2>&1 || {
  echo "安装 Nuitka..."
  $DATA_DIR/mcp_server/venv/bin/pip install -q nuitka
}

mkdir -p "$BUILD_DIR" "$PKG_DIR"

echo "[1/3] 编译 MCP 服务器..."
cd /tmp
$VENV_PY -m nuitka --onefile \
  --output-dir="$BUILD_DIR" \
  --output-filename=perpetua-mcp \
  "$DATA_DIR/mcp_server/server.py" 2>&1 | tail -5

echo "[2/3] 编译趋势检测..."
$VENV_PY -m nuitka --onefile \
  --output-dir="$BUILD_DIR" \
  --output-filename=perpetua-trend \
  "$DATA_DIR/trend_spike_detector.py" 2>&1 | tail -3

echo "[3/3] 组装安装包..."
cp "$BUILD_DIR/perpetua-mcp" "$PKG_DIR/"
cp "$BUILD_DIR/perpetua-trend" "$PKG_DIR/"
cp "$OUT_DIR/linux/install.sh" "$PKG_DIR/"
cp "$OUT_DIR/linux/perpetua-mcp-binary.service" "$PKG_DIR/systemd/" 2>/dev/null || \
  (mkdir -p "$PKG_DIR/systemd" && cp "$OUT_DIR/linux/perpetua-mcp-binary.service" "$PKG_DIR/systemd/")
cp "$OUT_DIR/README_BINARY.md" "$PKG_DIR/"

echo ""
echo "完成：$PKG_DIR"
ls -lh "$PKG_DIR/"
echo ""
echo "分发时打包：tar -czf perpetua-linux.tar.gz -C $OUT_DIR perpetua-linux"
