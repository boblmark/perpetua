#!/usr/bin/env python3
"""哑火视频自动换标题：48h 后播放 <50 的视频，按 Top10 爆款公式生成备选标题。

爆款公式：[emoji开头] Karen + 具体冲突动作 + 物理报应（大写动词） + [emoji]
生成的 3 个备选写入 awaiting_approval.json 等人工审批，不直接修改视频。

用法：
  python3 auto_retitle.py              # 扫描并生成备选（默认 48h / 50播放）
  python3 auto_retitle.py --dry-run    # 只打印不写入
"""
import json
import os
import re
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
from datetime import datetime, timezone

DATA = "/home/hatch/data"
APPROVAL_PATH = f"{DATA}/perpetua/awaiting_approval.json"
LOG_PATH = f"{DATA}/perpetua/auto_retitle.log.json"

# 具体报应动词（Top10 验证）
KARMA_VERBS = ["TOWED", "SOAKED", "BOOTED", "TRAPPED", "DESTROYED",
               "EXPOSED", "CAUGHT", "SPRAYED", "DRENCHED", "EVICTED",
               "EXPLODED", "FLOODED", "LOCKED"]
OPEN_EMOJIS = ["🤯", "🛒", "⛽", "🚪", "💦", "🔥", "😱", "💥"]
CLOSE_EMOJIS = ["🤯", "😂", "😱", "💀", "#Shorts"]


def _load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _save(p, obj):
    atomic_write_json(p, obj)


def _log(entry):
    log = _load(LOG_PATH, [])
    log.append(dict(entry, at=datetime.now(timezone.utc).isoformat()))
    _save(LOG_PATH, log[-200:])


def extract_conflict(title):
    """从原标题提取冲突核心（去掉 emoji/标签/报应部分）。"""
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]+", "", title)
    t = re.sub(r"\s*#\w+\s*", " ", t).strip()
    # 去掉已有的弱报应词
    t = re.sub(r"\s*(Instant Karma|Then Karma Hit It|It BROKE)\s*",
               " ", t, flags=re.I).strip()
    t = re.sub(r"\s+", " ", t)
    # 按词边界截断（≤60 字符）：找到 60 字符内的最后一个空格，避免切断单词
    # （2026-10-08 修复：此前 t[:60] 会把 "She Can't" 切成 "She C"）
    if len(t) > 60:
        cut = t.rfind(" ", 0, 60)
        t = t[:cut] if cut > 0 else t[:60]
    return t


def gen_alt_titles(original_title, video_id=""):
    """按爆款公式生成 3 个备选标题。"""
    conflict = extract_conflict(original_title)
    # 确保含 Karen
    if "karen" not in conflict.lower():
        conflict = "Karen " + conflict
    alts = []
    # 策略1：emoji开头 + 具体报应动词
    for i, verb in enumerate(["TOWED", "SOAKED", "TRAPPED"]):
        emo = OPEN_EMOJIS[i % len(OPEN_EMOJIS)]
        close = CLOSE_EMOJIS[i % len(CLOSE_EMOJIS)]
        # 构造：emoji + Karen + 冲突 + 报应 + emoji
        alt = f"{emo} {conflict} Gets {verb}! {close}"
        alt = re.sub(r"\s+", " ", alt).strip()
        if alt != original_title and alt not in alts:
            alts.append(alt)
        if len(alts) >= 3:
            break
    return alts[:3]


def get_duds(hours=48, max_views=50):
    """从 YouTube API 拉取哑火视频（48h+ 且播放 <50）。"""
    sys.path.insert(0, f"{DATA}/youtube")
    from post_publish_optimizer import get_recent_videos, get_views
    videos = get_recent_videos(4)  # 最近 4 天
    if not videos:
        return []
    views = get_views([v["video_id"] for v in videos])
    now = datetime.now(timezone.utc)
    duds = []
    for v in videos:
        vid = v["video_id"]
        try:
            pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
        except Exception:
            continue
        age_h = (now - pub).total_seconds() / 3600
        vc = views.get(vid, 0)
        if age_h >= hours and vc < max_views:
            duds.append({"video_id": vid, "title": v["title"],
                         "views": vc, "age_h": round(age_h, 1)})
    return duds


def main():
    dry = "--dry-run" in sys.argv
    duds = get_duds()
    print(f"发现 {len(duds)} 条哑火视频（48h+，<50播放）")

    if not duds:
        print(json.dumps({"status": "no duds"}))
        return

    approvals = _load(APPROVAL_PATH, [])
    # 避免重复：仅状态为 awaiting 的条目才去重（P4，2026-10-28 空转审计）。
    # 旧口径不论 awaiting/rejected/expired/applied，只要 video_id 在列即跳过，
    # 同一视频拒绝/过期后永不生成新备选。改后 rejected/expired/applied 的视频
    # 下轮哑火仍可重新生成备选。
    existing = {a.get("video_id") for a in approvals
                if isinstance(a, dict) and a.get("status") == "awaiting"}

    added = 0
    for d in duds:
        if d["video_id"] in existing:
            print(f"  跳过 {d['video_id'][:8]}（已在审批队列）")
            continue
        alts = gen_alt_titles(d["title"], d["video_id"])
        if not alts:
            continue
        entry = {
            "type": "auto_retitle",
            "video_id": d["video_id"],
            # P3（2026-10-28）：补 topic/title 使 approve/reject/list 能跑通。
            # topic 用原标题派生（标题本身即唯一可读键）；title = old_title。
            "topic": d["title"],
            "title": d["title"],
            "old_title": d["title"],
            "alt_titles": alts,
            "views_at_check": d["views"],
            "age_h": d["age_h"],
            "status": "awaiting",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "auto_retitle.py（48h 哑火自动生成）",
        }
        print(f"  {d['video_id'][:8]}: {d['views']}播放 → 备选:")
        for a in alts:
            print(f"    - {a}")
        if not dry:
            approvals.append(entry)
            added += 1
        _log({"video_id": d["video_id"], "old": d["title"][:60],
              "alts": alts, "dry_run": dry})

    if not dry and added:
        _save(APPROVAL_PATH, approvals)
    print(json.dumps({"duds": len(duds), "added_to_approval": added,
                      "dry_run": dry}, ensure_ascii=False))


if __name__ == "__main__":
    main()
