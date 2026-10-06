#!/usr/bin/env python3
"""对比 v1（规则版）与 v2（数据版）在同一批历史数据上的预测力。"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
from virality_score import score as v1_score
from virality_score_v2 import score_v2, load_model

HIST = Path("/home/hatch/data/youtube/uploads_full.jsonl")
rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
rows = [r for r in rows if r["views"] > 0]


def pearson(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def spearman(a, b):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        for pos, i in enumerate(s):
            rk[i] = pos
        return rk
    return pearson(rank(a), rank(b))


v1s, v2s, ys = [], [], []
for r in rows:
    v1s.append(v1_score({"title": r["title"], "hook": "", "topic_heat": "medium",
                         "duration": 10})["score"])
    v2s.append(score_v2(r["title"], 10)["score"])
    ys.append(r["views"])

print(f"样本 {len(rows)} 条")
print()
print(f"{'版本':<10} {'Pearson r':>12} {'Spearman ρ':>12}")
print("-" * 36)
print(f"{'v1 规则':<10} {pearson(v1s, ys):>12.4f} {spearman(v1s, ys):>12.4f}")
print(f"{'v2 数据':<10} {pearson(v2s, ys):>12.4f} {spearman(v2s, ys):>12.4f}")
print()

# 分档看平均播放
print("v2 分数区间 -> 实际播放")
buckets = {}
for s, r in zip(v2s, rows):
    b = (s // 10) * 10
    buckets.setdefault(b, []).append(r["views"])
for b in sorted(buckets):
    vs = sorted(buckets[b])
    print(f"  {b:2d}-{b+9}: n={len(vs):3d}  avg={statistics.mean(vs):8,.0f}  median={statistics.median(vs):8,.0f}")
print()

# Top10 命中率
by_v2 = sorted(zip(v2s, rows), key=lambda x: -x[0])
by_v1 = sorted(zip(v1s, rows), key=lambda x: -x[0])
top50_target = set(id(r) for r in sorted(rows, key=lambda r: -r["views"])[:49])

for name, arr in (("v1", by_v1), ("v2", by_v2)):
    top50 = arr[:49]
    hit = sum(1 for _, r in top50 if id(r) in top50_target)
    avg = statistics.mean(r["views"] for _, r in top50)
    print(f"{name} Top50 中命中真实 Top50 的比例: {hit}/49 = {hit/49*100:.1f}%  平均播放={avg:,.0f}")
