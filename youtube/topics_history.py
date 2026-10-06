#!/usr/bin/env python3
"""topics_history.jsonl 落库 + 回填。

topics_history 的作用：把「每条已发布视频」的
  {video_id, title, published, 预测分, 等级, 当时特征, 真实播放}
固化成一行，形成可追溯的闭环账本。

- 回填（backfill）：从 uploads_full.jsonl 生成历史行，pred_score 用 v2 现算
- 追加（append）：新视频发布后由 publish 流程写入，后续 audit 刷新真实播放

用法:
  python3 topics_history.py backfill     # 幂等，按 video_id 去重
  python3 topics_history.py sync         # 刷新已有行的真实 views/likes
  python3 topics_history.py stats        # 看账本概况
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

YT = Path("/home/hatch/data/youtube")
FULL = YT / "uploads_full.jsonl"
HIST = YT / "topics_history.jsonl"
V2 = YT / "virality_score_v2.py"


def _score(title, duration=10):
    try:
        r = subprocess.run(
            ["python3", str(V2), json.dumps({"title": title, "duration": duration})],
            capture_output=True, text=True, timeout=20,
        )
        d = json.loads(r.stdout)
        return d["score"], d["grade"], [m["feature"] for m in d.get("matched", [])]
    except Exception:
        return None, None, []


def load_hist():
    if not HIST.exists():
        return {}
    out = {}
    for line in HIST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                r = json.loads(line)
                out[r["video_id"]] = r
            except Exception:
                pass
    return out


def save_hist(rows: dict):
    # 按发布时间排序，稳定输出
    items = sorted(rows.values(), key=lambda r: (r.get("published", ""), r.get("video_id", "")))
    HIST.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in items) + "\n",
                    encoding="utf-8")
    return len(items)


def backfill():
    if not FULL.exists():
        print(json.dumps({"error": "uploads_full.jsonl missing"}, ensure_ascii=False))
        return
    src = [json.loads(l) for l in FULL.read_text(encoding="utf-8").splitlines() if l.strip()]
    hist = load_hist()
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    for r in src:
        vid = r.get("video_id")
        if not vid or vid in hist:
            continue
        s, g, feats = _score(r.get("title", ""))
        hist[vid] = {
            "video_id": vid,
            "title": r.get("title", ""),
            "published": r.get("published", ""),
            "duration": r.get("duration", ""),
            "pred_score": s,
            "pred_grade": g,
            "pred_features": feats,
            "views": r.get("views", 0),
            "likes": r.get("likes", 0),
            "comments": r.get("comments", 0),
            "first_seen": now,
            "last_synced": now,
            "source": "backfill",
        }
        added += 1
    n = save_hist(hist)
    print(json.dumps({"ok": True, "added": added, "total": n, "file": str(HIST)},
                     ensure_ascii=False, indent=2))


def sync():
    """用最新真实数据刷新账本中每条视频的播放/点赞。"""
    if not FULL.exists():
        print(json.dumps({"error": "uploads_full.jsonl missing"}, ensure_ascii=False))
        return
    src = {json.loads(l)["video_id"]: json.loads(l)
           for l in FULL.read_text(encoding="utf-8").splitlines() if l.strip()}
    hist = load_hist()
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for vid, row in hist.items():
        cur = src.get(vid)
        if not cur:
            continue
        if cur.get("views") != row.get("views") or cur.get("likes") != row.get("likes"):
            row["views"] = cur.get("views", row.get("views"))
            row["likes"] = cur.get("likes", row.get("likes"))
            row["comments"] = cur.get("comments", row.get("comments"))
            updated += 1
        row["last_synced"] = now
    n = save_hist(hist)
    print(json.dumps({"ok": True, "updated": updated, "total": n},
                     ensure_ascii=False, indent=2))


def stats():
    rows = list(load_hist().values())
    live = [r for r in rows if r.get("views", 0) > 0]
    scored = [r for r in live if r.get("pred_score") is not None]
    buckets = {}
    for r in scored:
        b = (r["pred_score"] // 10) * 10
        buckets.setdefault(b, []).append(r["views"])
    dist = {f"{b}-{b+9}": {"n": len(v), "avg_views": round(sum(v) / len(v))}
            for b, v in sorted(buckets.items())}

    hit = [r for r in scored if r["views"] >= 2138]  # p90
    prec = None
    if scored:
        top = sorted(scored, key=lambda r: -r["pred_score"])[:50]
        prec = round(sum(1 for r in top if r["views"] >= 2138) / max(len(top), 1), 4)

    print(json.dumps({
        "total": len(rows),
        "with_views": len(live),
        "scored": len(scored),
        "score_bucket_vs_avg_views": dist,
        "top50_hit_rate_vs_p90": prec,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backfill"
    {"backfill": backfill, "sync": sync, "stats": stats}.get(cmd, backfill)()
