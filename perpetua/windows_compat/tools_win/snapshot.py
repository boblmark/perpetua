#!/usr/bin/env python3
"""跨平台运行时快照（替代 Linux 版 snapshot.sh）。

在旧机器上执行，生成可迁移的运行时数据快照：
  queue.db / ops_center.db（表级导出为 JSON，避免跨平台 sqlite 文件差异）
  + youtube/private_queue.json + ask_studio 双队列 + jev criteria
  + anomaly ledger / escalation inbox / command queue + cron.d 定义。

用法：snapshot.py [--out DIR] [--dry-run]
快照经 SSH/scp 直传到新机器，绝不进静态安装包。
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


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump_sqlite_json(db_path, out_path):
    """表级导出：每表 -> [{...}]，跨平台安全。"""
    if not os.path.exists(db_path):
        return {"skipped": "not found"}
    con = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        data = {}
        for t in tables:
            cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
            rows = con.execute(f"SELECT * FROM {t}").fetchall()
            data[t] = [dict(zip(cols, r)) for r in rows]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        return {"tables": len(tables),
                "rows": sum(len(v) for v in data.values())}
    finally:
        con.close()


def copy_if_exists(src, dst):
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False


SNAPSHOT_FILES = [
    # (相对 DATA_DIR 的源, 快照内相对路径)
    ("youtube/private_queue.json", "youtube/private_queue.json"),
    ("ask_studio/queue.json", "ask_studio/queue.json"),
    ("ask_studio/instant_queue.json", "ask_studio/instant_queue.json"),
    ("jev/criteria.json", "jev/criteria.json"),
    ("perpetua/anomaly_ledger.json", "perpetua/anomaly_ledger.json"),
    ("perpetua/escalation_inbox.json", "perpetua/escalation_inbox.json"),
    ("perpetua/command_queue.json", "perpetua/command_queue.json"),
]

SNAPSHOT_DBS = [
    ("perpetua/queue.db", "db/queue.json"),
    ("perpetua/ops_center.db", "db/ops_center.json"),
    ("mcp_jobs", None),  # 目录特殊处理
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data_dir = get_data_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = a.out or os.path.join(data_dir, "perpetua", f"snapshot-{stamp}")
    print(f"[snapshot] DATA_DIR={data_dir}")
    print(f"[snapshot] 输出目录={out}")

    plan = []
    for src_rel, dst_rel in SNAPSHOT_FILES:
        src = os.path.join(data_dir, src_rel)
        plan.append(("file", src, os.path.join(out, dst_rel),
                     os.path.exists(src)))
    for src_rel, dst_rel in SNAPSHOT_DBS:
        if dst_rel is None:
            continue
        src = os.path.join(data_dir, src_rel)
        plan.append(("db", src, os.path.join(out, dst_rel),
                     os.path.exists(src)))
    # cron.d 定义
    cron_src = os.path.join(os.path.expanduser("~"), "workspace", "cron.d")
    plan.append(("dir", cron_src, os.path.join(out, "cron.d"),
                 os.path.isdir(cron_src)))

    for kind, src, dst, exists in plan:
        print(f"  [{'OK' if exists else 'SKIP'}] {kind:4} {src}")

    if a.dry_run:
        print("[dry-run] 不执行复制/导出")
        return 0

    os.makedirs(out, exist_ok=True)
    manifest = {"created_at": utcnow(), "data_dir": data_dir, "items": []}
    for kind, src, dst, exists in plan:
        if not exists:
            manifest["items"].append({"src": src, "status": "skipped"})
            continue
        try:
            if kind == "db":
                info = dump_sqlite_json(src, dst)
                manifest["items"].append({"src": src, "status": "ok",
                                          "detail": info})
            elif kind == "dir":
                shutil.copytree(src, dst, dirs_exist_ok=True)
                manifest["items"].append({"src": src, "status": "ok"})
            else:
                copy_if_exists(src, dst)
                manifest["items"].append({"src": src, "status": "ok"})
        except Exception as e:
            manifest["items"].append({"src": src, "status": "error",
                                      "detail": str(e)[:120]})
    with open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    n_ok = sum(1 for i in manifest["items"] if i["status"] == "ok")
    print(f"[snapshot] 完成：{n_ok}/{len(manifest['items'])} 项成功 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
