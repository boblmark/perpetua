#!/bin/bash
# Perpetua Linux 一键安装（编译版，无源码）
# 用法：sudo ./install.sh
# 前置：已解压安装包到当前目录

set -e
INSTALL_DIR="/opt/perpetua"
DATA_DIR="/home/hatch/data"
BIN_DIR="/usr/local/bin"

echo "=== Perpetua Linux 一键安装（编译版） ==="
echo ""

if [ "$EUID" -ne 0 ]; then
  echo "请用 sudo 运行"
  exit 1
fi

echo "[1/6] 创建目录..."
mkdir -p "$INSTALL_DIR/bin" "$DATA_DIR"

echo "[2/6] 安装主程序..."
cp perpetua-mcp "$INSTALL_DIR/bin/"
cp perpetua-trend "$INSTALL_DIR/bin/" 2>/dev/null || true
chmod +x "$INSTALL_DIR/bin/"*
ln -sf "$INSTALL_DIR/bin/perpetua-mcp" "$BIN_DIR/perpetua-mcp"

echo "[3/6] 生成 MCP Token..."
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "$TOKEN" > "$DATA_DIR/.token"
chmod 600 "$DATA_DIR/.token"
echo "Token 已写入 $DATA_DIR/.token"

echo "[4/6] 安装 systemd 服务..."
cp systemd/perpetua-mcp-binary.service /etc/systemd/system/perpetua-mcp.service
# 修改 ExecStart 指向二进制
sed -i "s|ExecStart=.*|ExecStart=$INSTALL_DIR/bin/perpetua-mcp|" /etc/systemd/system/perpetua-mcp.service
systemctl daemon-reload
systemctl enable perpetua-mcp

echo "[5/6] 初始化数据目录..."
mkdir -p "$DATA_DIR/trends" "$DATA_DIR/mcp_jobs/pending" "$DATA_DIR/mcp_jobs/done"
[ -f "$DATA_DIR/collab/inbox.json" ] || echo '{"messages":[]}' > "$DATA_DIR/collab/inbox.json"

echo "[6/6] 启动服务..."
systemctl start perpetua-mcp
sleep 3
systemctl is-active perpetua-mcp && echo "服务运行中 ✓" || echo "服务启动失败，请检查 journalctl -u perpetua-mcp"

echo ""
echo "=== 安装完成 ==="
echo "MCP 地址：http://127.0.0.1:8734/mcp"
echo "数据目录：$DATA_DIR"
echo "程序目录：$INSTALL_DIR/bin"
echo ""
echo "后续手动步骤："
echo "1. YouTube OAuth: 将 .oauth.json 放到 $DATA_DIR/youtube/"
echo "2. TypeSafe API Key: 写入 $DATA_DIR/jev/.api_key && chmod 600"
echo ""
echo "注意：本安装包不含 Python 源码，所有逻辑已编译为二进制。"
