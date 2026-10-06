#!/usr/bin/env python3
"""错配样本分析：全量样本上找 高分低走 / 低分爆款，定位 v2 特征权重该往哪调。

用法:
  python3 mismatch.py [top_n]

输出: JSON — {baseline, high_low:[], low_high:[], feature_delta, summary}
"""
import json
import statistics
import subprocess
import sys
from pathlib import Path

YT = Path("/home/hatch/data/youtube")
FULL = YT / "uploads_full.jsonl"
HIST = YT / "topics_history.jsonl"
V2 = YT / "virality_score_v2.py"


def load_full():
    rows = [json.loads(l) for l in FULL.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if r.get("views", 0) > 0]


def load_hist():
    out = {}
    for l in HIST.read_text(encoding="utf-8").splitlines():
        if l.strip():
            try:
                r = json.loads(l)
                out[r["video_id"]] = r
            except Exception:
                pass
    return out


def main():
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    rows = load_full()
    hist = load_hist()

    joined = []
    for r in rows:
        h = hist.get(r["video_id"])
        if not h or h.get("pred_score") is None:
            continue
        joined.append({
            "video_id": r["video_id"],
            "title": r["title"],
            "published": r.get("published", ""),
            "duration": r.get("duration"),
            "views": r["views"],
            "likes": r.get("likes", 0),
            "pred_score": h["pred_score"],
            "pred_grade": h.get("pred_grade"),
            "pred_features": h.get("pred_features") or {},
        })

    all_views = [r["views"] for r in joined]
    base = statistics.mean(all_views)
    med = statistics.median(all_views)
    p90 = sorted(all_views)[int(len(all_views) * 0.9)]

    high_low = sorted(
        [r for r in joined if r["pred_score"] >= 70 and r["views"] < base * 0.5],
        key=lambda r: r["pred_score"] - r["views"] / base * 20, reverse=True)
    low_high = sorted(
        [r for r in joined if r["pred_score"] < 60 and r["views"] >= p90],
        key=lambda r: r["views"], reverse=True)

    def feat_stats(group):
        ctr = {}
        for r in group:
            for f in (r["pred_features"] or []):
                ctr[f] = ctr.get(f, 0) + 1
        n = len(group) or 1
        return {k: round(v / n, 3) for k, v in sorted(ctr.items(), key=lambda kv: -kv[1])}

    decay = {
        "baseline_avg": round(base),
        "baseline_median": round(med),
        "baseline_p90": p90,
        "n_joined": len(joined),
        "high_low_n": len(high_low),
        "low_high_n": len(low_high),
        "high_low_feat_rate": feat_stats(high_low),
        "low_high_feat_rate": feat_stats(low_high),
        "all_feat_rate": feat_stats(joined),
    }

    out = {
        "baseline": {"avg": round(base), "median": round(med), "p90": p90, "n": len(joined)},
        "high_low": [
            {k: r[k] for k in ("published", "pred_score", "pred_grade", "views", "likes", "duration", "title")}
            for r in high_low[:top_n]
        ],
        "low_high": [
            {k: r[k] for k in ("published", "pred_score", "pred_grade", "views", "likes", "duration", "title")}
            for r in low_high[:top_n]
        ],
        "feature_delta": decay,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
