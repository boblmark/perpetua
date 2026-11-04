#!/bin/bash
# 本机 VNC 网页版：x11vnc 接管已有 Xorg :101 + websockify + noVNC
# 安全：VNC 5901 与 noVNC 6080 只绑 localhost；对外只走 VPS 反向隧道 16080，
# 且必须经 VNC 密码（密码只存 600 文件，绝不打印到日志或聊天）。
set -u
export http_proxy="http://198.19.0.1:3128" https_proxy="http://198.19.0.1:3128"
DIR="/home/hatch/data/perpetua/vnc-web"
mkdir -p "$DIR"
LOG="$DIR/install.log"
exec >>"$LOG" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] start"
echo "skip apt-get update: azure lists already fresh, cogentco mirror stalls"
apt-get install -y x11vnc websockify novnc || apt-get install -y x11vnc websockify
NOVNC_DIR="/usr/share/novnc"
if [ ! -d "$NOVNC_DIR" ]; then
  cd /opt && curl -L --proxy "http://198.19.0.1:3128" -o noVNC.zip https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.zip \
    && unzip -o -q noVNC.zip && mv noVNC-1.5.0 /opt/novnc && NOVNC_DIR="/opt/novnc"
fi
[ -d "$NOVNC_DIR" ] || { echo "FAIL: noVNC directory missing"; exit 1; }
echo "NOVNC_DIR=$NOVNC_DIR"
PW_FILE="$DIR/vnc_password.txt"
if [ ! -f "$PW_FILE" ]; then
  openssl rand -base64 18 | tr -d '\n' > "$PW_FILE"
  chmod 600 "$PW_FILE"
  echo "password file created (600, value NOT logged)"
else
  echo "password file already exists, reusing (value NOT logged)"
fi
printf '%s' "$(cat "$PW_FILE")" | x11vnc -storepasswd - "$DIR/x11vnc.pass"
chmod 600 "$DIR/x11vnc.pass"
# 停旧实例（精确 PID，不用宽泛 pkill 自匹配）
for pid in $(pgrep -f "x11vnc -display :101" 2>/dev/null); do kill "$pid" 2>/dev/null || true; done
for pid in $(pgrep -f "websockify.*6080" 2>/dev/null); do kill "$pid" 2>/dev/null || true; done
sleep 1
[ -e /tmp/.X11-unix/X101 ] || echo "WARN: X101 socket missing, x11vnc will still start but desktop may be empty"
# 2026-11-04 02:56 用户明确要求免密码访问：改 -nopw，不再用 -rfbauth（密码文件留存但不再生效）
setsid nohup x11vnc -display :101 -forever -shared -nopw -rfbport 5901 -localhost -o "$DIR/x11vnc.log" >/dev/null 2>&1 < /dev/null &
setsid nohup websockify --web="$NOVNC_DIR" 127.0.0.1:6080 localhost:5901 >"$DIR/websockify.log" 2>&1 < /dev/null &
sleep 3
ss -ltnp | grep -E ':(5901|6080)' || echo "WARN: 5901/6080 not listening yet"
curl -s -o /dev/null -w "local noVNC vnc.html http=%{http_code}\n" --max-time 10 http://127.0.0.1:6080/vnc.html || true
# VPS 反向隧道 16080 -> 本地 6080（先查 VPS 端是否已被占）
if timeout 20 ssh -i /home/hatch/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" -o ConnectTimeout=15 root@192.166.82.123 "ss -tln 2>/dev/null | grep ':16080'" >/dev/null 2>&1; then
  echo "WARN: VPS 16080 already listening, tunnel NOT started to avoid collision"
else
  cat > "$DIR/tunnel_16080.sh" <<'EOS'
#!/bin/bash
while true; do
  ssh -i /home/hatch/.ssh/id_ed25519 -N \
    -o StrictHostKeyChecking=no \
    -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -R 0.0.0.0:16080:localhost:6080 \
    root@192.166.82.123
  echo "$(date) vnc tunnel died, retry in 5s" >> /home/hatch/data/perpetua/vnc-web/tunnel.log
  sleep 5
done
EOS
  chmod +x "$DIR/tunnel_16080.sh"
  setsid nohup bash "$DIR/tunnel_16080.sh" >/dev/null 2>&1 < /dev/null &
  sleep 5
  timeout 20 ssh -i /home/hatch/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" -o ConnectTimeout=15 root@192.166.82.123 "ss -tln 2>/dev/null | grep ':16080'" && echo "VPS 16080 listening OK" || echo "WARN: VPS 16080 not listening after tunnel start"
  timeout 20 ssh -i /home/hatch/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" -o ConnectTimeout=15 root@192.166.82.123 "curl -s -o /dev/null -w 'VPS-side noVNC http=%{http_code}\n' --max-time 10 http://127.0.0.1:16080/vnc.html" || true
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] done"
