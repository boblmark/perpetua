#!/usr/bin/env python3
"""MIN_DF 扫描：过滤低频高权噪声词。

消融证据：110 个特征里 16 个移除后 ρ 反升，其中 w:elevator(1.277/df0.02)、
w:satire(1.256/df0.02)、w:pizza(0.529/df0.02) 全是"低频高权"——
只出现 9-10 次、均值偶然偏高就被赋了大权重。这是打分模型最典型的污染源。

假设：提高 MIN_DF 门槛能过滤掉这类噪声，提升 CV 泛化。

同时扫描 scale（分值映射斜率）与 topk，因为两者与 MIN_DF 有交互。
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
from backtest_v3 import featurize, fit, evaluate  # noqa

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"


def score_with(weights, feats, decay=0.85, topk=5, scale=22.0):
    hits = sorted([(k, weights[k]) for k in feats if k in weights], key=lambda x: -x[1])
    raw = sum(v * (decay ** j) for j, (_, v) in enumerate(hits[:topk]))
    return max(1, min(99, round(50 + raw * scale)))


def cv(docs, min_df, folds=5, decay=0.85, topk=5, scale=22.0):
    n = len(docs)
    idx = sorted(range(n), key=lambda i: docs[i][1])
    buckets = [[] for _ in range(folds)]
    for pos, i in enumerate(idx):
        buckets[pos % folds].append(i)
    preds = [None] * n
    nfeat = []
    for fi in range(folds):
        va = buckets[fi]
        va_set = set(va)
        tr = [docs[i] for i in idx if i not in va_set]
        w, _, _, _ = fit(tr, min_df, None, True, True)
        nfeat.append(len(w))
        for i in va:
            preds[i] = score_with(w, docs[i][0], decay, topk, scale)
    return preds, round(statistics.mean(nfeat))


def main():
    rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("views", 0) > 0]
    docs = [(featurize(r["title"]), r["views"], r["title"]) for r in rows]
    views = [d[1] for d in docs]
    p90 = sorted(views)[int(len(views) * 0.9)]
    print(f"# sample: {len(docs)}  p90={p90}")

    print("\n=== 扫描 1: MIN_DF（decay/topk/scale 固定）===")
    print(f"{'min_df':>7}{'feats':>7}{'rho':>9}{'pearson':>10}{'top50':>9}{'avg':>8}")
    best = None
    res1 = []
    for md in [4, 6, 8, 12, 15, 20, 25, 30, 40, 50, 60, 80]:
        preds, nf = cv(docs, md)
        e = evaluate(preds, views, f"min_df={md}")
        res1.append({"min_df": md, "feats": nf, **e})
        print(f"{md:>7}{nf:>7}{e['spearman_rho']:>9.4f}{e['pearson_r']:>10.4f}"
              f"{e['topk_hits']:>6}/{e['topk']:<3}{e['topk_avg_views']:>8}")
        if e["spearman_rho"] >= 0.30:
            print("         ^ rho >= 0.30")
        key = (e["spearman_rho"], e["topk_hit_rate"])
        if best is None or key > best[0]:
            best = (key, md, nf, e)

    print(f"\n# best MIN_DF = {best[1]}  (feats={best[2]}, rho={best[3]['spearman_rho']}, "
          f"top50={best[3]['topk_hits']}/{best[3]['topk']})")

    print("\n=== 扫描 2: 在 best MIN_DF 上调 scale / topk / decay ===")
    md = best[1]
    print(f"{'scale':>7}{'topk':>6}{'decay':>7}{'rho':>9}{'top50':>9}{'avg':>8}")
    res2 = []
    for scale in [14, 18, 22, 26, 30, 34]:
        for topk in [3, 5, 7, 9]:
            for decay in [0.75, 0.85, 0.95]:
                preds, _ = cv(docs, md, decay=decay, topk=topk, scale=scale)
                e = evaluate(preds, views, f"s{scale}k{topk}d{decay}")
                res2.append({"scale": scale, "topk": topk, "decay": decay, **e})
    res2.sort(key=lambda r: (-r["spearman_rho"], -r["topk_hit_rate"]))
    for r in res2[:12]:
        print(f"{r['scale']:>7}{r['topk']:>6}{r['decay']:>7}{r['spearman_rho']:>9.4f}"
              f"{r['topk_hits']:>6}/{r['topk']:<3}{r['topk_avg_views']:>8}")
    top = res2[0]
    print(f"\n# best: scale={top['scale']} topk={top['topk']} decay={top['decay']} "
          f"rho={top['spearman_rho']} top50={top['topk_hits']}/{top['topk']}")

    json.dump({"sample": len(docs), "p90": p90, "min_df_scan": res1,
               "param_scan": res2[:30], "best": {"min_df": md, **top}},
              open(YT / "min_df_scan.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"# wrote {YT/'min_df_scan.json'}")


if __name__ == "__main__":
    main()
