#!/usr/bin/env python3
"""跨平台快照恢复（与 tools_win/snapshot.py 配对）。

在新机器上执行，把 snapshot.py 的产物放回原路径：
  db/*.json -> 反写回 sqlite（建表+插入；表已存在则清空重建）
  其余文件 -> 原相对路径放回。

用法：restore.py --from DIR [--dry-run]
危险操作前先备份目标（*.bak-YYYYMMDD-HHMMSS）。
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from config import get_data_dir  # noqa: E402


def backup(path):
    if os.path.exists(path):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, f"{path}.bak-{stamp}")
        print(f"  备份: {path}.bak-{stamp}")


def restore_db(json_path, db_path, dry_run):
    data = json.load(open(json_path, encoding="utf-8"))
    if dry_run:
        n = sum(len(v) for v in data.values())
        print(f"  [dry-run] {db_path}: {len(data)} 表 / {n} 行")
        return
    backup(db_path)
    con = sqlite3.connect(db_path)
    try:
        for table, rows in data.items():
            if not rows:
                continue
            cols = list(rows[0].keys())
            coldef = ", ".join(f'"{c}" TEXT' for c in cols)
            con.execute(f'DROP TABLE IF EXISTS "{table}"')
            con.execute(f'CREATE TABLE "{table}" ({coldef})')
            ph = ", ".join("?" for _ in cols)
            con.executemany(
                f'INSERT INTO "{table}" VALUES ({ph})',
                [[str(r.get(c, "")) for c in cols] for r in rows])
        con.commit()
        print(f"  恢复: {db_path}（{len(data)} 表）")
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data_dir = get_data_dir()
    manifest_p = os.path.join(a.src, "MANIFEST.json")
    if not os.path.exists(manifest_p):
        print(f"快照目录无效（无 MANIFEST.json）: {a.src}", file=sys.stderr)
        return 2
    manifest = json.load(open(manifest_p, encoding="utf-8"))
    print(f"[restore] 快照时间: {manifest.get('created_at')} -> DATA_DIR={data_dir}")

    # 恢复映射：快照内相对路径 -> DATA_DIR 下相对路径
    for root, _, files in os.walk(a.src):
        for fn in files:
            if fn == "MANIFEST.json":
                continue
            sp = os.path.join(root, fn)
            rel = os.path.relpath(sp, a.src)
            if rel.startswith("db" + os.sep) and fn.endswith(".json"):
                # db/queue.json -> perpetua/queue.db
                db_name = fn[:-5] + ".db"
                dst = os.path.join(data_dir, "perpetua", db_name)
                if a.dry_run:
                    restore_db(sp, dst, True)
                else:
                    restore_db(sp, dst, False)
            else:
                dst = os.path.join(data_dir, rel)
                if a.dry_run:
                    print(f"  [dry-run] {rel} -> {dst}")
                else:
                    backup(dst)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(sp, dst)
                    print(f"  恢复: {rel}")
    print("[restore] 完成" + ("（dry-run，未写入）" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
