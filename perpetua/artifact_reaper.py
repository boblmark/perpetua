#!/usr/bin/env python3
"""孤儿 artifact 收割者（AI Studio 规格 #11，2026-10-08）。
终态视频的本地文件 + 失败 artifact 超过保留期就归档/删除，防磁盘堆满。
保留策略：
- uploaded：保留 7 天（供复查），之后移入 archive/
- rejected/review_failed/qc_failed：保留 3 天，之后删除
- 无状态关联的孤儿文件（veo_inbox/ 中 7 天未被引用）：移入 archive/
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta

DATA = "/home/hatch/data"
sys.path.insert(0, os.path.join(DATA, "perpetua"))
from atomic_json import tolerant_read
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db

INBOX = os.path.join(DATA, "veo_inbox")
ARCHIVE = os.path.join(DATA, "veo_inbox", "archive")
QUEUE_PATH = os.path.join(DATA, "perpetua", "pipeline_queue.json")
APPROVAL_PATH = os.path.join(DATA, "perpetua", "awaiting_approval.json")


def now():
    return datetime.now(timezone.utc)


def parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    os.makedirs(ARCHIVE, exist_ok=True)
    # 收集所有被引用的文件
    referenced = set()
    for p in (QUEUE_PATH, APPROVAL_PATH):
        # D20261011-001 P1: QUEUE_PATH（pipeline_queue）已迁 SQLite，其余仍读 JSON
        q = queue_db.pipeline_load() if p == QUEUE_PATH else tolerant_read(p, [])
        items = q if isinstance(q, list) else q.get("items", [])
        for it in items:
            if isinstance(it, dict):
                f = it.get("video_file", "")
                if f:
                    referenced.add(os.path.basename(f))
    # 终态文件的保留期
    terminal = {}
    for p in (QUEUE_PATH, APPROVAL_PATH):
        q = queue_db.pipeline_load() if p == QUEUE_PATH else tolerant_read(p, [])
        items = q if isinstance(q, list) else q.get("items", [])
        for it in items:
            if not isinstance(it, dict):
                continue
            st = it.get("status", "")
            f = it.get("video_file", "")
            if not f:
                continue
            bn = os.path.basename(f)
            ts = it.get("updated_at", "") or it.get("created_at", "")
            dt = parse_time(ts)
            if st == "uploaded":
                terminal[bn] = (dt, 7)  # 7 天后归档
            elif st in ("rejected", "review_failed", "qc_failed", "expired"):
                terminal[bn] = (dt, 3)  # 3 天后删除

    archived, deleted, orphans = 0, 0, 0
    for fn in os.listdir(INBOX):
        fp = os.path.join(INBOX, fn)
        if not os.path.isfile(fp) or fn.startswith("."):
            continue
        if fn in referenced and fn not in terminal:
            continue  # 非终态引用，保留
        mtime = datetime.fromtimestamp(os.path.getmtime(fp), tz=timezone.utc)
        age_d = (now() - mtime).total_seconds() / 86400

        if fn in terminal:
            dt, keep_d = terminal[fn]
            ref_age = (now() - dt).total_seconds() / 86400 if dt else age_d
            if ref_age > keep_d:
                if keep_d == 7:
                    shutil.move(fp, os.path.join(ARCHIVE, fn))
                    archived += 1
                else:
                    os.unlink(fp)
                    deleted += 1
        elif fn not in referenced and age_d > 7:
            # 孤儿文件：7 天无人引用
            shutil.move(fp, os.path.join(ARCHIVE, fn))
            orphans += 1

    print(f"收割完成：归档 {archived}，删除 {deleted}，孤儿 {orphans}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
