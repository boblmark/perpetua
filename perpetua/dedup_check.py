#!/usr/bin/env python3
"""P0 发布前去重：新标题/概念与近 90 天已发布视频做关键词重叠度检查。

重叠 >60% 判重复，打回。纯标准库。
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta

YT_SCRIPT = "/home/hatch/data/youtube/yt.py"
DUP_THRESHOLD = 0.60
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for",
    "with", "her", "his", "it", "its", "is", "are", "was", "then", "vs",
    "shorts", "short",
}


def _keywords(text):
    words = re.findall(r"[a-zA-Z]+", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _recent_titles(days=90):
    """近 N 天已发布视频标题（走 yt.py recent，失败返回空）。"""
    import subprocess
    try:
        r = subprocess.run(
            ["python3", YT_SCRIPT, "recent", "50"],
            capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout) if r.stdout.strip() else []
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        pub = str(it.get("published", ""))
        try:
            pdt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if pdt.tzinfo is None:
                pdt = pdt.replace(tzinfo=timezone.utc)
            if pdt < cutoff:
                continue
        except Exception:
            pass  # 日期解析失败也纳入比对（宁严勿松）
        out.append(it.get("title", ""))
    return out


def check_duplicate(new_title, new_concept="", days=90, threshold=DUP_THRESHOLD):
    """返回 (is_dup: bool, matched_title: str|None, overlap: float)。"""
    new_kw = _keywords(new_title) | _keywords(new_concept)
    if not new_kw:
        return False, None, 0.0
    best, best_title = 0.0, None
    for t in _recent_titles(days):
        old_kw = _keywords(t)
        if not old_kw:
            continue
        overlap = len(new_kw & old_kw) / max(len(new_kw), len(old_kw))
        if overlap > best:
            best, best_title = overlap, t
    return (best >= threshold), best_title, round(best, 3)


if __name__ == "__main__":
    import sys
    title = sys.argv[1] if len(sys.argv) > 1 else ""
    concept = sys.argv[2] if len(sys.argv) > 2 else ""
    dup, matched, ov = check_duplicate(title, concept)
    print(json.dumps({"is_dup": dup, "matched": matched, "overlap": ov},
                     ensure_ascii=False, indent=2))
