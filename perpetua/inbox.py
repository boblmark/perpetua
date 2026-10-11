#!/usr/bin/env python3
"""inbox.py — collab/inbox.json 统一网关（v1.0.0，2026-10-11）。

背景：22 个脚本直接读写 inbox.json（裸 json.load/dump），schema 分散、
写无锁。现收敛到此唯一入口：
- load()：容忍读（损坏回 default），保证顶层 shape。
- save(data)：原子写（lockfile + tmp + fsync + rename）。
- append_notice / append_message：读-改-写追加（网关内串行化写，
  仍建议调用方避免超长持有）。

INBOX_VERSION 版本门：schema 变更时 bump，调用方可 assert。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_json import atomic_write, tolerant_read

INBOX_PATH = "/home/hatch/data/collab/inbox.json"
INBOX_VERSION = "1.0.0"

_DEFAULT = {
    "pending_pickup": [],
    "picked_up": [],
    "notices": [],
    "messages": [],
    "discarded": [],
}


def _default():
    return {k: list(v) for k, v in _DEFAULT.items()}


def load():
    """读 inbox；文件损坏/不存在时回默认 shape（不抛错）。"""
    d = tolerant_read(INBOX_PATH, None)
    if not isinstance(d, dict):
        return _default()
    out = _default()
    for k in out:
        if isinstance(d.get(k), list):
            out[k] = d[k]
    # 保留未知顶层键（前向兼容），但不信任其类型
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


def save(data):
    """全量保存（原子写）。data 必须是 dict。"""
    if not isinstance(data, dict):
        raise TypeError(f"inbox.save: data 必须是 dict，got {type(data).__name__}")
    atomic_write(INBOX_PATH, data)


def append_notice(notice):
    """向 notices 追加一条；notice 必须是 dict。返回追加后的 notices 长度。"""
    if not isinstance(notice, dict):
        raise TypeError("append_notice: notice 必须是 dict")
    d = load()
    d["notices"].append(notice)
    save(d)
    return len(d["notices"])


def append_message(msg):
    """向 messages 追加一条；msg 必须是 dict。"""
    if not isinstance(msg, dict):
        raise TypeError("append_message: msg 必须是 dict")
    d = load()
    d["messages"].append(msg)
    save(d)
    return len(d["messages"])


def get_notices(limit=50):
    """取最近 notices（只读，不加锁）。"""
    return load().get("notices", [])[-limit:]
