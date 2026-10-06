#!/usr/bin/env python3
"""v1 vs v2 打分器对照回测 —— 产出「打分区间的实际播放分布」图表数据。

输出:
  - backtest_v2.json  : 结构化数据（供画图）
  - backtest_v2.md    : 人类可读报告
"""
import json
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

YT = Path("/home/hatch/data/youtube")
SRC = YT / "uploads_full.jsonl"
V1 = YT / "virality_score.py"
V2 = YT / "virality_score_v2.py"
OUT_JSON = YT / "backtest_v2.json"
OUT_MD = YT / "backtest_v2.md"

sys.path.insert(0, str(YT))
from virality_score import score as v1_score  # noqa


def v2_score(title, duration=10):
    r = subprocess.run(["python3", str(V2), json.dumps({"title": title, "duration": duration})],
                       capture_output=True, text=True, timeout=20)
    try:
        return json.loads(r.stdout)["score"]
    except Exception:
        return None


def pearson(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def spearman(a, b):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0] * len(v)
        for pos, i in enumerate(s):
            rk[i] = pos
        return rk
    return pearson(rank(a), rank(b))


def buckets_of(scored, lo=None, hi=None):
    b = {}
    for r in scored:
        k = (r["_s"] // 10) * 10
        b.setdefault(k, []).append(r)
    out = []
    for k in sorted(b):
        g = b[k]
        vs = sorted(x["views"] for x in g)
        out.append({
            "bucket": f"{k}-{k+9}",
            "n": len(g),
            "avg_views": round(statistics.mean(vs)),
            "median_views": round(statistics.median(vs)),
            "max_views": max(vs),
            "min_views": min(vs),
            "p90_views": vs[int(len(vs) * 0.9)] if len(vs) > 1 else vs[0],
            "views": vs,
        })
    return out


def main():
    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    all_n = len(rows)
    live = [r for r in rows if r["views"] > 0]
    zero = all_n - len(live)

    print(f"# 总样本 {all_n}（0 播放 {zero} 条，有效 {len(live)} 条）")

    for r in live:
        r["_s1"] = v1_score({"title": r["title"], "hook": "",
                             "topic_heat": "medium", "duration": 10})["score"]
        r["_s2"] = v2_score(r["title"], 10)

    live_v2 = [r for r in live if r["_s2"] is not None]
    views = sorted(r["views"] for r in live)
    n = len(live)

    report = {
        "generated_for": "打分区间的实际播放分布",
        "channel": "Mark Bobl | Karen vs AI",
        "sample": {
            "total_rows": all_n,
            "zero_view": zero,
            "effective": n,
        },
        "baseline": {
            "avg_views": round(statistics.mean(views)),
            "median_views": round(statistics.median(views)),
            "p90_views": views[int(n * 0.9)],
            "p75_views": views[int(n * 0.75)],
            "max_views": views[-1],
            "total_views": sum(views),
        },
        "predictive_power": {
            "v1_rule": {
                "pearson_r": round(pearson([r["_s1"] for r in live], [r["views"] for r in live]), 4),
                "spearman_rho": round(spearman([r["_s1"] for r in live], [r["views"] for r in live]), 4),
            },
            "v2_data": {
                "pearson_r": round(pearson([r["_s2"] for r in live_v2], [r["views"] for r in live_v2]), 4),
                "spearman_rho": round(spearman([r["_s2"] for r in live_v2], [r["views"] for r in live_v2]), 4),
            },
        },
        "buckets_v1": None,
        "buckets_v2": None,
    }

    # v1 分区
    for r in live:
        r["_s"] = r["_s1"]
    report["buckets_v1"] = buckets_of(live)

    # v2 分区
    for r in live_v2:
        r["_s"] = r["_s2"]
    report["buckets_v2"] = buckets_of(live_v2)

    # Top-K 命中率（以 p90 为"爆款"阈值）
    p90 = views[int(n * 0.9)]
    def topk_hit(scored, key, k=50):
        srt = sorted(scored, key=lambda r: -r[key])[:k]
        hit = sum(1 for r in srt if r["views"] >= p90)
        avgs = statistics.mean(r["views"] for r in srt)
        return {"k": k, "hits": hit, "hit_rate": round(hit / k, 4),
                "avg_views": round(avgs)}
    report["topk_vs_p90"] = {
        "p90_threshold": p90,
        "v1_rule": topk_hit(live, "_s1"),
        "v2_data": topk_hit(live_v2, "_s2"),
    }

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- markdown ----
    L = []
    def w(s=""): L.append(s)

    w("# 打分区间的实际播放分布（v1 vs v2 对照）")
    w()
    w(f"- 频道：**{report['channel']}**")
    w(f"- 样本：总 {all_n} 行，其中 **0 播放 {zero} 条**（未公开/被删），"
      f"有效 **{n} 条**")
    w(f"- 基线：均值 **{report['baseline']['avg_views']:,}** / "
      f"中位 {report['baseline']['median_views']:,} / "
      f"p90 **{p90:,}** / 最高 {views[-1]:,}")
    w(f"- 累计播放：{sum(views):,}")
    w()
    w("## 一、预测力")
    w()
    w("| 版本 | Pearson r | Spearman ρ |")
    w("|---|---|---|")
    w(f"| v1（人工关键词表） | {report['predictive_power']['v1_rule']['pearson_r']} | "
      f"{report['predictive_power']['v1_rule']['spearman_rho']} |")
    w(f"| **v2（数据驱动）** | **{report['predictive_power']['v2_data']['pearson_r']}** | "
      f"**{report['predictive_power']['v2_data']['spearman_rho']}** |")
    w()
    w(f"判读：ρ>0.3 算弱相关。v1 ρ={report['predictive_power']['v1_rule']['spearman_rho']}"
      f" → 基本无关；v2 ρ={report['predictive_power']['v2_data']['spearman_rho']} → 有明确单调性。")
    w()

    for label, key, bk in (("v1（人工规则）", "v1_rule", "buckets_v1"),
                           ("v2（数据驱动）", "v2_data", "buckets_v2")):
        w(f"## 二、{label} 分区间 vs 实际播放")
        w()
        w("| 分数区间 | 条数 | 平均播放 | 中位播放 | p90 | 最高 |")
        w("|---|---|---|---|---|---|")
        for b in report[bk]:
            w(f"| {b['bucket']} | {b['n']} | **{b['avg_views']:,}** | "
              f"{b['median_views']:,} | {b['p90_views']:,} | {b['max_views']:,} |")
        w()
        tk = report["topk_vs_p90"][key]
        w(f"Top{tk['k']} 命中爆款(line≥p90={p90:,})：**{tk['hits']}/{tk['k']} "
          f"= {tk['hit_rate']*100:.1f}%**，其平均播放 {tk['avg_views']:,}")
        w()

    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n# -> {OUT_MD}")
    print(f"# -> {OUT_JSON}")


if __name__ == "__main__":
    main()
