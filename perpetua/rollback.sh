#!/bin/bash
# Perpetua 回滚机制：每次修改生产系统前自动快照，出问题一键回滚
# 用法：
#   rollback.sh snapshot "改动描述"   # 修改前打快照
#   rollback.sh list                  # 列出快照
#   rollback.sh restore <快照ID>       # 回滚到指定快照
#   rollback.sh rollback              # 回滚到最近一次快照

SNAP_DIR="/home/hatch/data/perpetua/snapshots"
mkdir -p "$SNAP_DIR"

case "$1" in
  snapshot)
    ID=$(date +%Y%m%d-%H%M%S)
    DESC="${2:-manual}"
    D="$SNAP_DIR/$ID"
    mkdir -p "$D"
    echo "📸 快照 $ID ($DESC)"
    # 备份关键代码
    cp /home/hatch/data/perpetua/vps_console/console_server.py "$D/" 2>/dev/null
    cp /home/hatch/data/perpetua/vps_console/index.html "$D/" 2>/dev/null
    cp /home/hatch/data/youtube/private_flip.py "$D/" 2>/dev/null
    cp /home/hatch/data/perpetua/distributor/platform_matrix_sync.py "$D/" 2>/dev/null
    # 备份数据库（SQLite 需要先 checkpoint）
    sqlite3 /home/hatch/data/ops_center.db "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null
    cp /home/hatch/data/ops_center.db "$D/ops_center.db" 2>/dev/null
    cp /home/hatch/data/perpetua/distributor/platform_matrix.json "$D/" 2>/dev/null
    echo "$DESC" > "$D/desc.txt"
    echo "$ID" > "$SNAP_DIR/latest"
    echo "✅ 快照完成：$D"
    # 只保留最近 10 个快照
    ls -1 "$SNAP_DIR" | grep -E '^[0-9]{8}-[0-9]{6}$' | sort | head -n -10 | while read old; do
      rm -rf "$SNAP_DIR/$old" && echo "🗑️ 清理旧快照 $old"
    done
    ;;
  list)
    echo "📋 快照列表："
    for d in $(ls -1 "$SNAP_DIR" | grep -E '^[0-9]{8}-[0-9]{6}$' | sort -r); do
      desc=$(cat "$SNAP_DIR/$d/desc.txt" 2>/dev/null)
      latest=""
      [ "$(cat $SNAP_DIR/latest 2>/dev/null)" = "$d" ] && latest=" ← 最新"
      echo "  $d : $desc$latest"
    done
    ;;
  restore|rollback)
    ID="$2"
    [ -z "$ID" ] && ID=$(cat "$SNAP_DIR/latest" 2>/dev/null)
    [ -z "$ID" ] && { echo "❌ 没有可用快照"; exit 1; }
    D="$SNAP_DIR/$ID"
    [ ! -d "$D" ] && { echo "❌ 快照不存在: $ID"; exit 1; }
    echo "⏪ 回滚到 $ID ..."
    # 停服务
    pkill -f "console_server.py" 2>/dev/null
    sleep 2
    # 恢复文件
    [ -f "$D/console_server.py" ] && cp "$D/console_server.py" /home/hatch/data/perpetua/vps_console/
    [ -f "$D/index.html" ] && cp "$D/index.html" /home/hatch/data/perpetua/vps_console/
    [ -f "$D/private_flip.py" ] && cp "$D/private_flip.py" /home/hatch/data/youtube/
    [ -f "$D/platform_matrix_sync.py" ] && cp "$D/platform_matrix_sync.py" /home/hatch/data/perpetua/distributor/
    [ -f "$D/ops_center.db" ] && cp "$D/ops_center.db" /home/hatch/data/ops_center.db
    [ -f "$D/platform_matrix.json" ] && cp "$D/platform_matrix.json" /home/hatch/data/perpetua/distributor/
    # 重启服务
    cd /home/hatch/data/perpetua/vps_console && nohup python3 console_server.py > /tmp/console.log 2>&1 & disown
    sleep 3
    CODE=$(curl -s -m 8 -o /dev/null -w "%{http_code}" "http://127.0.0.1:8080/oa")
    if [ "$CODE" = "200" ]; then
      echo "✅ 回滚完成，控制台正常 (HTTP 200)"
    else
      echo "⚠️ 回滚完成但控制台未响应 (HTTP $CODE)，请检查"
    fi
    ;;
  *)
    echo "用法: rollback.sh snapshot|list|restore|rollback"
    ;;
esac
