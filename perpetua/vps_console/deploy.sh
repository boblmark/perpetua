#!/bin/bash
# Perpetua 独立控制台一键部署（本地 VM 端）
# 后端跑本地 8080，VPS 经独立隧道转发 8080
set -e
DIR="/home/hatch/data/perpetua/vps_console"

echo "=== 部署 Perpetua 独立控制台 ==="

echo "[1/5] 脚本加执行权限..."
chmod +x "$DIR/console_server.py" "$DIR/tunnel_8080.sh"

echo "[2/5] 安装 systemd 服务..."
cp "$DIR/perpetua-console.service" /etc/systemd/system/
cp "$DIR/perpetua-console-tunnel.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable perpetua-console perpetua-console-tunnel

echo "[3/5] 启动控制台后端..."
systemctl restart perpetua-console
sleep 2
systemctl is-active perpetua-console && echo "  后端运行中" || (echo "  后端启动失败"; journalctl -u perpetua-console -n 10 --no-pager; exit 1)

echo "[4/5] 启动 8080 隧道..."
systemctl restart perpetua-console-tunnel
sleep 5
systemctl is-active perpetua-console-tunnel && echo "  隧道运行中" || echo "  隧道启动失败，请检查"

echo "[5/5] 本地验证..."
curl -s -o /dev/null -w "  本地首页: %{http_code}\n" http://127.0.0.1:8080/

echo ""
echo "=== 部署完成 ==="
echo "本地: http://127.0.0.1:8080/"
echo "公网: http://192.166.82.123:8080/"
echo "认证: Bearer token（与 MCP 共用 .token）"
