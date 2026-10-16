#!/bin/bash
# 8738 隧道保活：本机 MCP server (127.0.0.1:8734) → VPS 192.166.82.123:8738
# 用户 2026-10-14 00:08 CST 明确批准（Tier 3 基建变更）
# 2026-10-14 13:45 改（用户确认）：远端端口 8734→8738，避让 VPS 本机 8734（调度器后端）
# 逻辑：检查 ssh 转发进程，不在则拉起
#
# 2026-10-14 00:49 修（Dash）：原 autossh 方案在本机网络环境下永远建连失败——
# 出站 TCP/22 被透明劫持到 198.19.0.1:3128，非 HTTP-CONNECT 流量在 KEX 阶段即被掐断
# （实测 29ms 断开，kex_exchange_identification: Connection closed）；
# autossh supervisor 虽在、ssh 子进程永不存活，旧 pgrep 检查误判"存活"，
# 隧道实际从 00:08 起就没通。改用与其他 4 条生产隧道（18738/18737/18739、
# 18738、18080、8737→8735）完全相同的 ssh -f + ProxyCommand(nc -X connect) 方案；
# 存活检查锚定真实 ssh 进程（(^|/)ssh 锚定，避免 autossh supervisor 误命中）。

LOG=/home/hatch/data/perpetua/vps_console/tunnel_8738_keepalive.log
KEY=/home/hatch/.ssh/id_ed25519
# 2026-10-14 06:10 修（Dash）：mcp_server/tunnel.sh 自愈 loop 也在持同一条 8734 反向隧道，
# 其写法是 -R 0.0.0.0:8738:localhost:8734（Marvis 走 VPS 公网入口必需的 0.0.0.0 绑定），
# 与本脚本的 -R 8738:127.0.0.1:8734 两种写法都算存活。只认后一种曾导致每 5 分钟误判
# "隧道已死"、反复发起注定失败的 ssh（远端端口被 tunnel.sh 占用 → remote port forwarding failed）。
# 判活锚定"有活的 8734 反向转发 ssh"，不碰 tunnel.sh 的进程（它的清理只针对本脚本自己的写法）。
CHECK='(^|/)ssh .*-R ([0-9.a-zA-Z]*:)?8738:(localhost|127\.0\.0\.1):8734'

if pgrep -f "$CHECK" > /dev/null; then
    exit 0
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8738 tunnel not running, starting ssh" >> "$LOG"

# 精确清理残留进程：所有含 8734 转发字样的 ssh/autossh（不碰其他隧道）
for pid in $(pgrep -f "8738:127.0.0.1:8734" 2>/dev/null); do
    if [ "$pid" != "$$" ]; then
        kill "$pid" 2>/dev/null
    fi
done
sleep 2

# 拉起反向隧道（后台 -f；与其他生产隧道同方案；断线由本脚本下次轮询拉起）
# 2026-10-14 06:10（Dash）：-R 写法与 mcp_server/tunnel.sh 对齐（0.0.0.0 绑定，
# Marvis 经 VPS 公网入口接入必需；VPS sshd 已确认允许该绑定），fallback 与主通道等价。
ssh -i "$KEY" -f -N \
  -R 0.0.0.0:8738:localhost:8734 \
  root@192.166.82.123 \
  -o StrictHostKeyChecking=no \
  -o "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p" \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  >> "$LOG" 2>&1

sleep 3
if pgrep -f "$CHECK" > /dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8738 tunnel started OK" >> "$LOG"
    exit 0
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) 8738 tunnel FAILED to start" >> "$LOG"
    exit 1
fi
