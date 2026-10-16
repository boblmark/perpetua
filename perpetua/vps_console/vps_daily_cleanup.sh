#!/bin/bash
# VPS 每日清理 + 恢复（192.166.82.123）
# 用途：杀无主 agent-browser 残留、处理 wedged 的 x11vnc、探活关键服务、清理可再生垃圾
# 调度：由 cron 每天运行一次（脚本本身不建 cron）
# 要求：幂等、有日志、只做安全操作；不确定的不杀只告警
#
# 经验沉淀（2026-10-12 大扫除）：
# - 17 个 agent-browser 残留全是 ppid=1 的孤儿，任务早已结束，可杀
# - x11vnc 是 systemd 服务（x11vnc.service），wedged 时（CPU>30% 且无活跃客户端）
#   应该 systemctl restart 而不是直接 kill（kill 会被 systemd 拉起，但新实例健康）
# - Chrome 的 /tmp profile（chrome-vids-profile 等）任务结束即僵尸，可删；
#   非 /tmp 的 profile（/opt/arena-chrome）和 1 小时内的新进程不动
# - SSH 只能走 mux socket：ssh -S ~/.ssh/vm_mux_192.166.82.123.sock
# - kb.viralloopapp.com 依赖：本地 explorer(18091) + kb-search(18092) + 经 mux 的 -R 反向隧道

set -u
LOG=/home/hatch/data/perpetua/vps_console/vps_daily_cleanup.log
VPS=192.166.82.123
MUX=~/.ssh/vm_mux_192.166.82.123.sock
SSH="ssh -S $MUX -o BatchMode=yes -o ConnectTimeout=20 $VPS"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
log "=== daily cleanup start ==="

# 前置：mux 通道必须通，不通则退出（由 parent 决定）
if ! $SSH "echo ok" >/dev/null 2>&1; then
  log "FATAL: mux ssh to $VPS failed, abort"
  exit 1
fi

# 1. 杀无主 agent-browser 残留（ppid=1 且启动超过 2 小时）
ORPHANS=$($SSH 'ps -eo pid,ppid,etime,args | grep "[a]gent-browser/bin/agent-browser-linux-x64" | awk "\$2==1"' 2>/dev/null)
if [ -n "$ORPHANS" ]; then
  echo "$ORPHANS" | while read -r pid ppid etime rest; do
    # etime 含 "-" 表示超过 1 天，或 HH:MM:SS 中小时>=2
    if [[ "$etime" == *"-"* ]] || [[ "${etime%%:*}" -ge 2 ]] 2>/dev/null; then
      $SSH "kill $pid 2>/dev/null" && log "killed orphan agent-browser pid=$pid etime=$etime" \
        || log "WARN: failed to kill agent-browser pid=$pid"
    else
      log "skip young agent-browser pid=$pid etime=$etime (may be active)"
    fi
  done
else
  log "no agent-browser orphans"
fi
# SIGTERM 杀不掉的再补 SIGKILL（只针对上面已确认的孤儿）
sleep 3
STILL=$($SSH 'ps -eo pid,ppid,args | grep "[a]gent-browser/bin/agent-browser-linux-x64" | awk "\$2==1 {print \$1}"' 2>/dev/null)
for pid in $STILL; do
  $SSH "kill -9 $pid 2>/dev/null" && log "kill -9 orphan agent-browser pid=$pid"
done

# 2. x11vnc：systemd 服务，CPU 持续>30% 且无活跃客户端则 restart
XVNC_PID=$($SSH 'ps -eo pid,pcpu,args | grep "[x]11vnc" | awk "{print \$1}" | head -1' 2>/dev/null)
if [ -n "$XVNC_PID" ]; then
  CPU=$($SSH "ps -o pcpu= -p $XVNC_PID 2>/dev/null" | tr -d ' ' | cut -d. -f1)
  ACTIVE=$($SSH 'ss -tn state established 2>/dev/null | grep -c ":5900"' 2>/dev/null)
  if [ "${CPU:-0}" -gt 30 ] && [ "${ACTIVE:-0}" -eq 0 ]; then
    $SSH "systemctl restart x11vnc 2>/dev/null" && log "restarted wedged x11vnc (cpu=${CPU}%, no active clients)" \
      || log "WARN: x11vnc restart failed"
  else
    log "x11vnc ok (cpu=${CPU:-?}%, active_clients=${ACTIVE:-?})"
  fi
else
  log "x11vnc not running"
fi

# 3. 关键服务探活（只读检查，异常只记录）
for svc in "https://oa.viralloopapp.com/|301" "https://nano.viralloopapp.com/|200" "https://kb.viralloopapp.com/|200"; do
  url="${svc%%|*}"; want="${svc##*|}"
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$url" 2>/dev/null)
  if [ "$code" = "$want" ]; then log "probe ok $url -> $code";
  else log "ALERT: probe $url -> $code (want $want)"; fi
done
# VPS 本地端口
for p in 18091 18092; do
  if $SSH "ss -tln 2>/dev/null | grep -q ':$p '" 2>/dev/null; then log "vps port $p listening";
  else log "ALERT: vps port $p NOT listening"; fi
done

# 4. 清理可再生垃圾（只删确认无主的）
# 4a. /tmp 下无主 chrome profile（>24h 且无进程使用）
for d in $($SSH 'ls -d /tmp/chrome-* /tmp/arena-proxy-chrome /tmp/fb_reel 2>/dev/null'); do
  base=$(basename "$d")
  inuse=$($SSH "ps -eo args | grep -c '[u]ser-data-dir=$d'" 2>/dev/null)
  age_h=$($SSH "find '$d' -maxdepth 0 -mmin +1440 2>/dev/null | wc -l")
  if [ "${inuse:-1}" -eq 0 ] && [ "${age_h:-0}" -ge 1 ]; then
    $SSH "rm -rf '$d'" && log "cleaned stale tmp dir $d"
  fi
done
# 4b. 本地轮转：只保留最近 30 天的 perpetua 日志（.log）
find /home/hatch/data/perpetua -maxdepth 2 -name "*.log" -mtime +30 -delete 2>/dev/null \
  && log "rotated perpetua logs >30d"
# 4c. /tmp 一次性测试产物
rm -rf /tmp/p0test 2>/dev/null

# 5. 收尾状态
$SSH 'free -h | head -2 | tail -1' 2>/dev/null | while read -r line; do log "vps mem: $line"; done
$SSH 'df -h / | tail -1' 2>/dev/null | while read -r line; do log "vps disk: $line"; done
$SSH 'uptime' 2>/dev/null | while read -r line; do log "vps $line"; done
log "=== daily cleanup done ==="
exit 0
