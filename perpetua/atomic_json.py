#!/usr/bin/env python3
"""原子 JSON 读写（AI Studio 规格 #6/#7，2026-10-08）。
NEVER 原地写 JSON；MUST 写临时文件 + fsync + 原子 rename。
读时容忍损坏，自动回退到备份。
"""
import fcntl
import json
import os
import shutil
import tempfile


def atomic_write(path, data, backup=True):
    """原子写 JSON：lockfile 串行 + tmp + fsync + 原子 rename。
    失败时原文件不动。v2.0.0 (2026-10-11, D20261011-006, 红队 KILL 3)：
    补上 LMArena Rule 1 要求的 lockfile——并发写同一文件时串行化，
    不再出现两个进程同时 replace 造成的 .bak 交错。
    backup=False：不写 .bak（凭据类文件用，避免密钥多一份副本）。"""
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    lock_path = os.path.abspath(path) + ".lock"
    with open(lock_path, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX)
        except OSError:
            pass  # 拿不到锁也继续写：最坏退化为无锁原子 replace
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            # 成功后更新备份（保留一份最后好的；凭据文件跳过）
            if backup:
                try:
                    shutil.copy2(path, path + ".bak")
                except Exception:
                    pass
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
        finally:
            try:
                fcntl.flock(lockf, fcntl.LOCK_UN)
            except OSError:
                pass


def tolerant_read(path, default):
    """容忍损坏的读：JSON 坏了就回退 .bak，再坏就回 default。"""
    for p in (path, path + ".bak"):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return default
