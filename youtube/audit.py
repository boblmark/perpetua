#!/usr/bin/env python3
"""闭环回流：复盘最近 N 天视频的真实表现 vs 当时预测分。

用法:
  python3 audit.py [days] [--refresh] [--sync]

--sync: 先调 topics_history.py sync 刷新账本，再复盘（推荐）

输出: JSON（供 MCP youtube_audit 返回）
"""
import json
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

YT = Path("/home/hatch/data/youtube")
FULL = YT / "uploads_full.jsonl"
HIST = YT / "topics_history.jsonl"
V2 = YT / "virality_score_v2.py"


def refresh_full():
    subprocess.run(["python3", str(YT / "yt_dump.py")],
                   cwd=str(YT), capture_output=True, text=True, timeout=110)


def sync_hist():
    subprocess.run(["python3", str(YT / "topics_history.py"), "sync"],
                   cwd=str(YT), capture_output=True, text=True, timeout=60)


def load_full():
    if not FULL.exists():
        refresh_full()
    rows = [json.loads(l) for l in FULL.read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows


def load_hist():
    if not HIST.exists():
        return {}
    out = {}
    for l in HIST.read_text(encoding="utf-8").splitlines():
        if l.strip():
            try:
                r = json.loads(l)
                out[r["video_id"]] = r
            except Exception:
                pass
    return out


def predict(title):
    r = subprocess.run(["python3", str(V2), json.dumps({"title": title, "duration": 10})],
                       capture_output=True, text=True, timeout=20)
    try:
        return json.loads(r.stdout)["score"]
    except Exception:
        return None


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    if "--refresh" in sys.argv:
        refresh_full()
    if "--sync" in sys.argv:
        sync_hist()

    rows = load_full()
    rows = [r for r in rows if r["views"] > 0]
    if not rows:
        print(json.dumps({"error": "no data"}, ensure_ascii=False))
        return

    hist = load_hist()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [r for r in rows if r["published"] >= cutoff]
    recent.sort(key=lambda r: r["published"], reverse=True)

    # 预测分优先用账本里记录的（发布时锁定，不事后追认），没有再现算
    for r in recent[:40]:
        h = hist.get(r["video_id"])
        r["_pred"] = h["pred_score"] if h and h.get("pred_score") is not None else predict(r["title"])
        r["_pred_source"] = "history" if h and h.get("pred_score") is not None else "recomputed"

    all_views = [r["views"] for r in rows]
    base = statistics.mean(all_views)
    med = statistics.median(all_views)
    p90 = sorted(all_views)[int(len(all_views) * 0.9)]

    # 预测准确率：优先用账本中锁定的历史预测（真实的前瞻性检验）
    ledger = [(h["pred_score"], h["views"]) for h in hist.values()
              if h.get("pred_score") is not None and h.get("views", 0) > 0]
    if len(ledger) >= 20:
        scored, rho_src = ledger, "topics_history(locked predictions)"
    else:
        scored, rho_src = [(predict(r["title"]), r["views"]) for r in rows[:200]], "recomputed"
    scored = [(s, v) for s, v in scored if s is not None]
    rho = None
    if scored:
        a = [s for s, _ in scored]
        b = [v for _, v in scored]
        ma, mb = statistics.mean(a), statistics.mean(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        da = sum((x - ma) ** 2 for x in a) ** 0.5
        db = sum((y - mb) ** 2 for y in b) ** 0.5
        rho = num / (da * db) if da and db else 0.0

    out = {
        "channel_baseline": {
            "avg_views": round(base),
            "median_views": round(med),
            "p90_views": p90,
            "sample": len(rows),
        },
        "window_days": days,
        "recent_count": len(recent),
        "model_predictive_power_pearson_r": round(rho, 4) if rho is not None else None,
        "rho_sample": {"n": len(scored), "source": rho_src},
        "ledger": {
            "file": "youtube/topics_history.jsonl",
            "rows": len(hist),
            "with_locked_pred": sum(1 for h in hist.values() if h.get("pred_score") is not None),
        },
        "recent": [
            {
                "published": r["published"],
                "title": r["title"][:80],
                "views": r["views"],
                "likes": r["likes"],
                "pred_score": r.get("_pred"),
                "pred_source": r.get("_pred_source"),
                "verdict": (
                    "未达基线" if r["views"] < base * 0.5
                    else "达基线" if r["views"] < base
                    else "超基线" if r["views"] < p90
                    else "爆款"
                ),
            }
            for r in recent[:20]
        ],
        "advice": [],
    }

    if out["recent"]:
        miss = [r for r in out["recent"] if r["views"] < base * 0.5]
        if len(miss) > len(out["recent"]) * 0.5:
            out["advice"].append(
                f"{len(miss)}/{len(out['recent'])} 条低于基线半数——"
                f"检查是否偏离已验特征（Karen/HOA 人设、Instant Karma 反转、具象事故）")
        # 高分低走诊断
        overconf = [r for r in out["recent"]
                    if r["pred_score"] and r["pred_score"] >= 70 and r["views"] < base * 0.5]
        if overconf:
            out["advice"].append(
                f"{len(overconf)} 条预测≥70 但实际未达基线半数——模型对这些题材高估，"
                f"典型：{overconf[0]['title'][:50]}")
        underconf = [r for r in out["recent"]
                     if r["pred_score"] and r["pred_score"] < 58 and r["views"] >= p90]
        if underconf:
            out["advice"].append(
                f"{len(underconf)} 条预测<58 却成爆款——模型低估，建议重训吸纳")
    if rho is not None and rho < 0.15:
        out["advice"].append("模型预测力偏弱，建议重训：python3 youtube/virality_score_v2.py --train")
    if not out["advice"]:
        out["advice"].append("表现正常，继续执行已验证选题范式")

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
