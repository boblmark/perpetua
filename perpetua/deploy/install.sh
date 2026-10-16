#!/bin/bash
# Perpetua / ViralLoop 一键安装脚本
# 在新机器上运行：tar -xzf perpetua-deploy-*.tar.gz && ./install.sh
# 需要：python3.10+, pip, sudo（装系统包时）

set -e
INSTALL_DIR="/home/hatch/data"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Perpetua 一键部署 ==="
echo ""

echo "[1/8] 检查 Python..."
python3 --version || { echo "需要 python3.10+"; exit 1; }

echo "[2/8] 安装 Python 依赖..."
pip3 install -r "$SRC_DIR/requirements.txt" || pip3 install --break-system-packages -r "$SRC_DIR/requirements.txt"

echo "[3/8] 安装 Playwright 浏览器..."
python3 -m playwright install chromium --with-deps 2>/dev/null || \
  python3 -m playwright install chromium || \
  echo "WARN: Playwright 浏览器安装失败，浏览器上传备用通道不可用，可稍后手动安装"

echo "[4/8] 部署文件到 $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
for d in mcp_server jev youtube ask_studio collab; do
  [ -d "$SRC_DIR/$d" ] && cp -r "$SRC_DIR/$d" "$INSTALL_DIR/" && echo "  + $d"
done
for f in trend_spike_detector.py pipeline_latency.py virality_score.py relay.py; do
  [ -f "$SRC_DIR/$f" ] && cp "$SRC_DIR/$f" "$INSTALL_DIR/" && echo "  + $f"
done
mkdir -p "$INSTALL_DIR/perpetua"
[ -d "$SRC_DIR/perpetua-code" ] && cp -r "$SRC_DIR/perpetua-code/"* "$INSTALL_DIR/perpetua/" && echo "  + perpetua/"
mkdir -p "$INSTALL_DIR/trends" "$INSTALL_DIR/mcp_jobs/pending" "$INSTALL_DIR/mcp_jobs/done"

echo "[5/8] 生成 MCP token..."
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "$TOKEN" > "$INSTALL_DIR/mcp_server/.token"
chmod 600 "$INSTALL_DIR/mcp_server/.token"
echo "  Token 已写入 $INSTALL_DIR/mcp_server/.token（请妥善分发）"

echo "[6/8] 初始化数据文件..."
[ -f "$INSTALL_DIR/collab/inbox.json" ] || echo '{"messages":[]}' > "$INSTALL_DIR/collab/inbox.json"
[ -f "$INSTALL_DIR/trends/daily.json" ] || echo '{"trends":[]}' > "$INSTALL_DIR/trends/daily.json"
[ -f "$INSTALL_DIR/jev/criteria.json" ] || echo '{"version":3}' > "$INSTALL_DIR/jev/criteria.json"
echo "  inbox.json / trends/daily.json / criteria.json 就绪"

echo ""
echo "[7/8] 安装 systemd 服务（独立调度，不依赖 Muse）..."
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
for f in "$SRC_DIR"/systemd/perpetua-*.service "$SRC_DIR"/systemd/perpetua-*.timer; do
  [ -f "$f" ] && cp "$f" "$SYSTEMD_USER_DIR/" && echo "  + $(basename $f)"
done
systemctl --user daemon-reload 2>/dev/null || echo "  WARN: systemctl 不可用，手动复制 systemd/ 下文件到 ~/.config/systemd/user/"
echo "  启动核心服务..."
systemctl --user enable --now perpetua-mcp.service 2>/dev/null || echo "  手动启动: systemctl --user enable --now perpetua-mcp"
systemctl --user enable --now perpetua-local-proxy.service 2>/dev/null || true
systemctl --user enable --now perpetua-watchdog.timer 2>/dev/null || true
systemctl --user enable --now perpetua-trend-spike.timer 2>/dev/null || true
systemctl --user enable --now perpetua-post-publish.timer 2>/dev/null || true
systemctl --user enable --now perpetua-align-weekly.timer 2>/dev/null || true
# 开机自启用户服务（无桌面环境时需要）
loginctl enable-linger "$USER" 2>/dev/null || true

echo ""
echo "[8/8] 后续手动步骤（需人工完成）："
echo "  1. YouTube OAuth: 把 .oauth.json 放到 $INSTALL_DIR/youtube/"
echo "     或运行: python3 $INSTALL_DIR/youtube/test_auth.py 按提示授权"
echo "  2. TypeSafe API key: echo 'KEY' > $INSTALL_DIR/jev/.api_key && chmod 600"
echo "  3. 公网暴露（如需 Marvis 接入）: 配置 SSH 反向隧道到 VPS"
echo "     ssh -N -R 0.0.0.0:8734:localhost:8734 root@<VPS>"
echo "  4. 需要 AI 代理的任务（Ask Studio/媒体任务处理/趋势分析）需另行部署 agent 运行时"
echo ""
echo "=== 部署完成 ==="
