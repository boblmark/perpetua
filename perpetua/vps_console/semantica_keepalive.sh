#!/bin/bash
# Semantica 知识图谱保活：explorer 本体 + 18091 反向隧道
# /etc/systemd/system 在 VM 替换时会清空，所以这里做双保险：
# systemd unit 优先，unit 丢失时重装；explorer 进程挂了就拉起。
LOG=/home/hatch/data/perpetua/vps_console/semantica_keepalive.log

# 1. explorer 本体
if ! curl -s -o /dev/null --max-time 5 http://127.0.0.1:18091/ ; then
  echo "$(date '+%F %T') explorer down, restarting" >> "$LOG"
  cd /home/hatch/data/research/semantica-pilot && \
    SEMANTICA_ALLOW_ANONYMOUS=true nohup ./venv/bin/python -m semantica.explorer --graph graph_kb.json \
      --port 18091 --host 127.0.0.1 --no-browser >> explorer_run.log 2>&1 &
fi

# 2. 反向隧道（ssh -R 18091/18092）
if ! pgrep -f "ssh.*-R 0.0.0.0:18091:localhost:18091" > /dev/null ; then
  echo "$(date '+%F %T') tunnel down, reinstalling unit and restarting" >> "$LOG"
  cp /home/hatch/data/perpetua/vps_console/semantica-tunnel.service /etc/systemd/system/ 2>/dev/null
  systemctl daemon-reload 2>/dev/null
  systemctl enable --now semantica-tunnel.service 2>/dev/null || \
    nohup /bin/bash /home/hatch/data/perpetua/vps_console/tunnel_18091.sh >> /home/hatch/data/perpetua/vps_console/tunnel_18091.log 2>&1 &
fi

# 3. kb-search 混合检索 sidecar（127.0.0.1:18092）
if ! curl -s -o /dev/null --max-time 5 http://127.0.0.1:18092/healthz ; then
  echo "$(date '+%F %T') kb-search down, restarting" >> "$LOG"
  cp /home/hatch/data/perpetua/vps_console/kb-search.service /etc/systemd/system/ 2>/dev/null
  systemctl daemon-reload 2>/dev/null
  systemctl enable --now kb-search.service 2>/dev/null || \
    (cd /home/hatch/data/research/kb-search && \
     NO_PROXY="localhost,127.0.0.1,::1" nohup ./venv/bin/python server.py \
       >> server.log 2>&1 &)
fi
