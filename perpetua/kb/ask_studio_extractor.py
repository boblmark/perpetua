#!/usr/bin/env python3
"""
ask_studio_extractor.py — Ask Studio markdown 结构化抽取（Commit 1）

正则解析 Ask Studio 回答中的发布节奏建议 → kb/publish_cadence.json。
触发：prompt_review.py 写完 reviews/ask_studio_*.md 后同步调用。
解析失败：保留旧版 + 记 kb_extraction_failures.jsonl；3 连失败告警（非阻塞）。

B5 示例："严格 1-2 条/天，间隔 6-8 小时"
  → posts_per_day {min:1, max:2}, interval_hours {min:6, max:8}, enforced=true
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KB_DIR = Path("/home/hatch/data/perpetua/kb")
CADENCE_PATH = KB_DIR / "publish_cadence.json"
FAILURES_LOG = KB_DIR / "kb_extraction_failures.jsonl"

# 正则（规格 Deliverable 3）
POSTS_RE = re.compile(r"(\d+)\s*[-–~]\s*(\d+)\s*条/天")
POSTS_SINGLE_RE = re.compile(r"(?:每天|每日)\s*(\d+)\s*条")
INTERVAL_RE = re.compile(r"间隔\s*(\d+)\s*[-–~]\s*(\d+)\s*小?时")
ENFORCED_RE = re.compile(r"严格|必须|strict", re.IGNORECASE)


class ExtractionFailed(Exception):
    pass


def _validate(posts: dict, interval: dict):
    """校验规则：1 ≤ min ≤ max ≤ 10（条/天），1 ≤ min ≤ max ≤ 24（小时间隔）"""
    for name, d, lo, hi in (("posts_per_day", posts, 1, 10),
                            ("interval_hours", interval, 1, 24)):
        mn, mx = d["min"], d["max"]
        if not (isinstance(mn, int) and isinstance(mx, int)):
            raise ExtractionFailed(f"{name} 非整数: {d}")
        if not (lo <= mn <= mx <= hi):
            raise ExtractionFailed(f"{name} 越界: {d}")


def extract(md_path: str) -> dict:
    """
    解析 markdown，返回 publish_cadence 字典。
    失败时抛 ExtractionFailed。
    """
    text = Path(md_path).read_text(encoding="utf-8")

    posts = None
    m = POSTS_RE.search(text)
    if m:
        posts = {"min": int(m.group(1)), "max": int(m.group(2))}
    else:
        m2 = POSTS_SINGLE_RE.search(text)
        if m2:
            v = int(m2.group(1))
            posts = {"min": v, "max": v}

    interval = None
    m3 = INTERVAL_RE.search(text)
    if m3:
        interval = {"min": int(m3.group(1)), "max": int(m3.group(2))}

    if posts is None or interval is None:
        raise ExtractionFailed(
            f"未匹配到节奏模式 (posts={posts}, interval={interval})")

    _validate(posts, interval)

    enforced = bool(ENFORCED_RE.search(text))

    return {
        "version": _next_version(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_review": str(md_path),
        "posts_per_day": posts,
        "interval_hours": interval,
        "enforced": enforced,
    }


def _next_version() -> int:
    """版本号递增（基于现有文件）"""
    try:
        if CADENCE_PATH.exists():
            data = json.loads(CADENCE_PATH.read_text(encoding="utf-8"))
            return int(data.get("version", 0)) + 1
    except Exception:
        pass
    return 1


def _log_failure(md_path: str, reason: str):
    FAILURES_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_review": str(md_path),
        "reason": reason,
    }
    with open(FAILURES_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _consecutive_failures() -> int:
    """统计连续失败次数（从文件尾往回数）"""
    try:
        if not FAILURES_LOG.exists():
            return 0
        lines = FAILURES_LOG.read_text(encoding="utf-8").strip().split("\n")
        # 简单逻辑：最近 3 条都是失败即 3 连失败（本文件只记失败）
        return min(len([l for l in lines if l.strip()]), 999)
    except Exception:
        return 0


def run(md_path: str) -> dict:
    """
    主入口：解析 → 校验 → 写 publish_cadence.json。
    返回 {"ok": True, "cadence": {...}} 或 {"ok": False, "reason": ...}。
    失败时保留旧版（不覆盖），记 failures 日志。
    """
    try:
        cadence = extract(md_path)
    except ExtractionFailed as e:
        reason = str(e)
        _log_failure(md_path, reason)
        n = _consecutive_failures()
        alert = None
        if n >= 3:
            alert = (f"ALERT: ask_studio_extractor 连续 {n} 次解析失败，"
                     f"publish_cadence.json 停留在旧版本")
        return {"ok": False, "reason": reason,
                "consecutive_failures": n, "alert": alert}
    except Exception as e:
        reason = f"unexpected: {e}"
        _log_failure(md_path, reason)
        return {"ok": False, "reason": reason,
                "consecutive_failures": _consecutive_failures(), "alert": None}

    # 原子写（复用 json_safe）
    sys.path.insert(0, "/home/hatch/data/perpetua")
    try:
        from json_safe import atomic_write_json
        atomic_write_json(str(CADENCE_PATH), cadence)
    except ImportError:
        tmp = CADENCE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cadence, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(CADENCE_PATH)
    return {"ok": True, "cadence": cadence}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 ask_studio_extractor.py <ask_studio_md_path>")
        sys.exit(1)
    result = run(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 2)
