#!/bin/bash
# nano 实时语音 Web UI (127.0.0.1:18737) 保活
# 每 5 分钟由 cron 调用。18737 只是一个静态文件服务 (perception/web/index.html)，
# 挂掉会导致 https://nano.viralloopapp.com 502。
# 2026-10-14 创建：此前 18737 无保活，静默挂掉多日无人发现。

LOG=/home/hatch/data/perpetua/vps_console/nano_webui_18737_keepalive.log
WEB_DIR=/home/hatch/data/nanomuse-migration/perception/web
TS=$(date '+%Y-%m-%d %H:%M:%S')

# 连续两次探测失败才重启，防单次超时误杀
if curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:18737/ 2>/dev/null | grep -q "200"; then
    exit 0
fi
sleep 10
if curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:18737/ 2>/dev/null | grep -q "200"; then
    exit 0
fi

echo "$TS 18737 Web UI 不健康，重启" >> "$LOG"
for pid in $(pgrep -f "http\.server 18737" 2>/dev/null); do
    kill "$pid" 2>/dev/null
done
sleep 2
# 双 fork: subshell 里后台启动后立即退出,http.server 被 reparent 到 init,
# 主脚本 shell 的 job 表里从不出现它,不依赖 disown(2026-10-16 实测 disown 在后台调用时不可靠)
# 2026-10-18 修正：实测双 fork 仍导致主脚本卡在 do_wait 等子进程永不退出
# （pid 2608，2026-10-18 15:00 CST 实测），回退到 2026-10-16 实测有效的 disown 方案
cd "$WEB_DIR" && setsid nohup python3 -m http.server 18737 --bind 127.0.0.1 > /tmp/nano-webui-18737.log 2>&1 < /dev/null &
disown
sleep 3
if curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:18737/ 2>/dev/null | grep -q "200"; then
    echo "$TS 18737 Web UI 已拉起并健康" >> "$LOG"
else
    echo "$TS 18737 Web UI 拉起后仍不健康，需人工排查" >> "$LOG"
fi
