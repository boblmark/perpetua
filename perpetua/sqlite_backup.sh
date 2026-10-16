#!/bin/bash
# SQLite 自动备份：每小时一次，保留 7 天（168 份）
BACKUP_DIR="/home/hatch/data/perpetua/db_backups"
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M)
DB="/home/hatch/data/ops_center.db"

if [ ! -f "$DB" ]; then
  echo "DB 不存在: $DB"
  exit 1
fi

# WAL checkpoint 后复制，保证一致性
sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null
cp "$DB" "$BACKUP_DIR/ops_center-$TS.db"

# 验证备份可读
if sqlite3 "$BACKUP_DIR/ops_center-$TS.db" "SELECT 1;" 2>/dev/null | grep -q 1; then
  echo "✅ 备份成功: ops_center-$TS.db"
else
  echo "❌ 备份损坏，删除"
  rm -f "$BACKUP_DIR/ops_center-$TS.db"
  exit 1
fi

# 只保留最近 168 份（7天×24小时）
ls -1 "$BACKUP_DIR"/ops_center-*.db 2>/dev/null | sort | head -n -168 | xargs -r rm -f
echo "当前备份数: $(ls "$BACKUP_DIR"/ops_center-*.db 2>/dev/null | wc -l)"
