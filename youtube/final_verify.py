#!/usr/bin/env python3
"""终验：确认 topk=50/decay=0.95 的改进是真实的，不是 CV 分折运气。

做三件事：
  1. LOO（留一法，481 次拟合）—— 最严格的泛化估计，无分折随机性
  2. 多种子重复 CV（换分折方式 10 次）—— 看均值与标准差，判断 |Δ| 是否越过噪声
  3. 配对显著性：对每个样本算 new-old 的分数差，做符号检验
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
from backtest_v3 import featurize, fit, evaluate, spearman  # noqa

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"


def score_with(weights, feats, decay, topk, scale=22.0):
    hits = sorted([(k, weights[k]) for k in feats if k in weights], key=lambda x: -x[1])
    raw = sum(v * (decay ** j) for j, (_, v) in enumerate(hits[:topk]))
    return max(1, min(99, round(50 + raw * scale)))


def cv_multi(docs, folds=5, seed=0, decay=0.85, topk=5):
    """seed 控制分折方式：0=按 views 交错，k>0=先伪随机置换再切分。"""
    import random
    n = len(docs)
    idx = sorted(range(n), key=lambda i: docs[i][1])
    if seed == 0:
        buckets = [[] for _ in range(folds)]
        for pos, i in enumerate(idx):
            buckets[pos % folds].append(i)
    else:
        rnd = random.Random(seed)
        shuffled = idx[:]
        rnd.shuffle(shuffled)
        buckets = [shuffled[i::folds] for i in range(folds)]
    preds = [None] * n
    for va in buckets:
        va_set = set(va)
        tr = [docs[i] for i in idx if i not in va_set]
        w, _, _, _ = fit(tr)
        for i in va:
            preds[i] = score_with(w, docs[i][0], decay, topk)
    return preds


def loo(docs, decay=0.85, topk=5, cache_every=1):
    """留一法：481 次拟合。每次留出 1 条，用其余 480 条拟合。"""
    n = len(docs)
    preds = [None] * n
    # 优化：先算全量 df，逐个剔除时增量更新太复杂；481 次全量拟合可接受
    for i in range(n):
        tr = docs[:i] + docs[i + 1:]
        w, _, _, _ = fit(tr)
        preds[i] = score_with(w, docs[i][0], decay, topk)
    return preds


def main():
    rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("views", 0) > 0]
    docs = [(featurize(r["title"]), r["views"], r["title"]) for r in rows]
    views = [d[1] for d in docs]
    n = len(docs)
    print(f"# sample: {n}")

    CFG_OLD = dict(decay=0.85, topk=5)
    CFG_NEW = dict(decay=0.95, topk=50)

    print("\n=== 1. 多种子 CV（10 次不同分折，看均值±标准差）===")
    print(f"{'seed':>5}{'old_rho':>10}{'new_rho':>10}{'delta':>9}{'old_t50':>9}{'new_t50':>9}")
    olds, news, o_hits, n_hits = [], [], [], []
    for seed in range(10):
        po = cv_multi(docs, seed=seed, **CFG_OLD)
        pn = cv_multi(docs, seed=seed, **CFG_NEW)
        eo = evaluate(po, views, "old")
        en = evaluate(pn, views, "new")
        olds.append(eo["spearman_rho"]); news.append(en["spearman_rho"])
        o_hits.append(eo["topk_hits"]); n_hits.append(en["topk_hits"])
        print(f"{seed:>5}{eo['spearman_rho']:>10.4f}{en['spearman_rho']:>10.4f}"
              f"{en['spearman_rho']-eo['spearman_rho']:>+9.4f}"
              f"{eo['topk_hits']:>9}{en['topk_hits']:>9}")

    def ms(x):
        return f"{statistics.mean(x):.4f} ± {statistics.stdev(x):.4f}"
    print(f"\n  old rho: {ms(olds)}   new rho: {ms(news)}")
    print(f"  old top50: {statistics.mean(o_hits):.1f} ± {statistics.stdev(o_hits):.1f}"
          f"   new top50: {statistics.mean(n_hits):.1f} ± {statistics.stdev(n_hits):.1f}")
    wins = sum(1 for a, b in zip(olds, news) if b > a)
    print(f"  rho 改善胜率: {wins}/10")
    tw = sum(1 for a, b in zip(o_hits, n_hits) if b > a)
    print(f"  top50 改善胜率: {tw}/10")

    print("\n=== 2. 留一法 LOO（481 次拟合，最严格）===")
    print("  running old config ...")
    lo = loo(docs, **CFG_OLD)
    e_lo = evaluate(lo, views, "LOO-old")
    print(f"  old: rho={e_lo['spearman_rho']}  top50={e_lo['topk_hits']}/{e_lo['topk']}"
          f"  avg={e_lo['topk_avg_views']}")
    print("  running new config ...")
    ln = loo(docs, **CFG_NEW)
    e_ln = evaluate(ln, views, "LOO-new")
    print(f"  new: rho={e_ln['spearman_rho']}  top50={e_ln['topk_hits']}/{e_ln['topk']}"
          f"  avg={e_ln['topk_avg_views']}")

    print("\n=== 3. 配对符号检验（new vs old 逐样本）===")
    ups = sum(1 for a, b in zip(lo, ln) if b > a)
    downs = sum(1 for a, b in zip(lo, ln) if b < a)
    ties = n - ups - downs
    print(f"  new>old: {ups}   new<old: {downs}   tie: {ties}")
    z = (ups - downs) / ((ups + downs) ** 0.5) if (ups + downs) else 0.0
    print(f"  符号检验 z = {z:.3f}  ({'显著(>1.96)' if abs(z) > 1.96 else '不显著'})")

    json.dump({"multiseed": {"old_rho": olds, "new_rho": news,
                             "old_top50": o_hits, "new_top50": n_hits},
               "loo": {"old": e_lo, "new": e_ln},
               "sign_test": {"ups": ups, "downs": downs, "ties": ties, "z": round(z, 4)}},
              open(YT / "final_verify.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n# wrote {YT/'final_verify.json'}")


if __name__ == "__main__":
    main()
