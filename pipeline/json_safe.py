#!/usr/bin/env python3
"""统一 JSON 安全读写 + 单飞锁 + 状态变更审计（P0修复4/5/6，2026-10-09）。

- atomic_write_json / tolerant_read_json：复用 atomic_json（AI Studio 规格 #6/#7）
- run_lock：基于 fcntl.flock 的单飞锁，拿不到锁静默退出（exit 0）
- audit_log：状态变更审计，JSON Lines 追加到 audit.log

用法：
    sys.path.insert(0, "/home/hatch/data/perpetua")
    from json_safe import atomic_write_json, tolerant_read_json, run_lock, audit_log

    with run_lock("zero_view_alert"):   # main() 开头
        main()
"""
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_json import atomic_write, tolerant_read

AUDIT_LOG = Path("/home/hatch/data/perpetua/audit.log")
LOCK_DIR = Path("/tmp/perpetua_locks")


def atomic_write_json(path, data):
    """原子写 JSON（写临时文件 + fsync + os.replace）。"""
    atomic_write(str(path), data)


def tolerant_read_json(path, default):
    """容忍读 JSON（损坏/不存在返回 default）。"""
    result = tolerant_read(str(path), default)
    if result is default:
        print(f"WARN: tolerant_read_json 回退到 default: {path}", file=sys.stderr)
    return result


def audit_log(action, video_id="", old_status="", new_status="", actor="",
              extra=None):
    """状态变更审计：JSON Lines 追加写 audit.log，每行带 ISO 时间戳。"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "video_id": video_id,
        "old_status": old_status,
        "new_status": new_status,
        "actor": actor,
    }
    if extra:
        entry["extra"] = extra
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"WARN: audit_log 写入失败: {e}", file=sys.stderr)


@contextmanager
def run_lock(name):
    """单飞锁：同一脚本同时只跑一个实例。拿不到锁则静默退出（exit 0）。

    用法：在 main() 开头：
        with run_lock("zero_view_alert"):
            ...原有逻辑...
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCK_DIR / f"{name}.lock"
    fp = open(lock_path, "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        print(f"[{name}] 另一实例正在运行，本轮跳过（单飞锁）")
        fp.close()
        sys.exit(0)
    try:
        fp.write(f"{os.getpid()}\n")
        fp.flush()
        yield
    finally:
        try:
            fcntl.flock(fp, fcntl.LOCK_UN)
        except Exception:
            pass
        fp.close()
