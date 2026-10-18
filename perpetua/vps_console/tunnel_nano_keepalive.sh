#!/bin/bash
# nano 隧道保活：确保 tunnel_nano.sh 脚本本身在运行
# 每 5 分钟由 cron 调用（脚本内已有 while true 重连，这里只保脚本进程）

LOG=/home/hatch/data/perpetua/vps_console/tunnel_nano_keepalive.log

if pgrep -f "[/]tunnel_nano\.sh" > /dev/null 2>&1; then
    exit 0  # 脚本在运行（[/] 字符类避免 pgrep 匹配到执行器自身命令行，Rule 9 自匹配教训）
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') tunnel_nano.sh 不在运行，拉起" >> "$LOG"
# 先清掉可能残留的 ssh 转发进程（精确匹配端口，避免误杀其他隧道）
for pid in $(pgrep -f "ssh.*18736.*18737.*18739" 2>/dev/null); do
    # 确认是我们的 nano 隧道（检查命令行包含三个端口）
    if ps -p "$pid" -o args= 2>/dev/null | grep -q "18736.*18737.*18739"; then
        kill "$pid" 2>/dev/null
    fi
done
sleep 3
bash /home/hatch/data/perpetua/vps_console/tunnel_nano.sh > /tmp/tunnel_nano.out 2>&1 &
disown 2>/dev/null
echo "$(date '+%Y-%m-%d %H:%M:%S') 已拉起" >> "$LOG"
