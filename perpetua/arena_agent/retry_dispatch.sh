#!/bin/bash
# arena.ai 恢复后自动重派竞品数据采集
# 由 cron 每 3 小时调用。逻辑：
# 1. 结果已存在 -> 静默退出（任务完成，cron 可停用）
# 2. 有锁且进程存活 -> 跳过（上一轮派发仍在跑）
# 3. 否则运行 arena_dispatch_vm.py（脚本自带 arena.ai 登录态检查，站点未恢复时快速失败 exit 3）
set -u
DIR=/home/hatch/data/perpetua/arena_agent
LOCK=$DIR/.dispatch-competitor-viral.lock
RESULT=$DIR/drops/competitor-viral-20261014.xlsx
LOG=$DIR/retry_dispatch.log
TS=$(date '+%Y-%m-%d %H:%M:%S')

# 1. 已完成
if [ -f "$RESULT" ] && [ "$(stat -c%s "$RESULT")" -gt 1024 ]; then
    echo "$TS 已有结果 $RESULT，跳过" >> "$LOG"
    echo "ALREADY_DONE"
    exit 0
fi

# 2. 锁检查
if [ -f "$LOCK" ]; then
    LPID=$(cat "$LOCK" 2>/dev/null || echo "")
    if [ -n "$LPID" ] && kill -0 "$LPID" 2>/dev/null; then
        echo "$TS 上一轮派发仍在运行 (pid $LPID)，跳过" >> "$LOG"
        echo "LOCKED"
        exit 0
    fi
    rm -f "$LOCK"
fi

# 3. 派发
echo $$ > "$LOCK"
echo "$TS 开始派发" >> "$LOG"
cd "$DIR" && python3 arena_dispatch_vm.py \
    --prompt-file prompts/competitor_viral_data_20261014.txt \
    --job-id competitor-viral-20261014 \
    --max-wait-min 90 >> "$LOG" 2>&1
RC=$?
rm -f "$LOCK"
echo "$TS 派发结束 exit=$RC" >> "$LOG"
if [ "$RC" -eq 0 ] && [ -f "$RESULT" ]; then
    echo "DISPATCH_OK $RESULT"
else
    echo "DISPATCH_RC=$RC"
fi
exit "$RC"
