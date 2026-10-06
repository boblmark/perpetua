#!/usr/bin/env python3
"""决策实验：封面特征相对现行标题模型（CV ρ≈0.28）是否有**增量**。

三组对照，5 折 CV，同一分折：
  X  = title only   （现行 v2 口径）
  T  = thumb only   （15 个封面特征）
  TX = 合并

判定标准（沿用本项目纪律）：
  - 必须 ρ 与 Top50 **同时改善**才算改进
  - 必须多种子 CV（10 折）+ 配对符号检验排除单调变换
"""
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/home/hatch/data/youtube")
from backtest_v3 import featurize, evaluate  # noqa

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"
THUMB = YT / "thumb_features.jsonl"

TK = ["lum_mean", "lum_std", "dark_ratio", "bright_ratio", "sat_mean",
      "sat_high_ratio", "hue_entropy", "warm_ratio", "rule_of_thirds",
      "center_energy", "salience_entropy", "highfreq_mean",
      "highfreq_ratio", "edge_density", "dominant_band_ratio"]


def load():
    rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    vmap = {r["video_id"]: r for r in rows if r.get("views", 0) > 0}
    tf = {}
    for l in THUMB.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            tf[r["video_id"]] = r
    return [(vid, vmap[vid], tf[vid]) for vid in vmap if vid in tf]


def blocks(both, idx, wmap=None):
    f = featurize(both[idx][1]["title"])
    tv = np.array([both[idx][2][k] for k in TK], dtype=np.float64)
    if wmap is None:
        return tv, f
    xv = np.array([wmap.get(k, 0.0) for k in wmap], dtype=np.float64)
    return tv, xv, f


def run_cv(both, mode, folds=5, lam=3.0, seed=0):
    import random
    from backtest_v3 import fit as tfit
    n = len(both)
    order = sorted(range(n), key=lambda i: both[i][1]["views"])
    if seed:
        random.Random(seed).shuffle(order)
    buckets = [[] for _ in range(folds)]
    for pos, i in enumerate(order):
        buckets[pos % folds].append(i)

    preds = [0.0] * n
    for va in buckets:
        va_set = set(va)
        tr = [i for i in order if i not in va_set]
        y = np.array([math.log1p(both[i][1]["views"]) for i in tr])
        ys = (y - y.mean()) / (y.std() or 1.0)

        Ttr = np.array([[both[i][2][k] for k in TK] for i in tr], dtype=np.float64)
        Tva = np.array([[both[i][2][k] for k in TK] for i in va], dtype=np.float64)

        wmap, _, _, _ = tfit([(featurize(both[i][1]["title"]), both[i][1]["views"])
                              for i in tr], 8, None, True, True)
        keys = sorted(wmap)
        Xtr = np.array([[wmap.get(k, 0.0) if k in featurize(both[i][1]["title"]) else 0.0
                         for k in keys] for i in tr], dtype=np.float64)
        Xva = np.array([[wmap.get(k, 0.0) if k in featurize(both[i][1]["title"]) else 0.0
                         for k in keys] for i in va], dtype=np.float64)

        if mode == "T":
            Atr, Ava = Ttr, Tva
        elif mode == "X":
            Atr, Ava = Xtr, Xva
        else:
            Atr, Ava = np.hstack([Xtr, Ttr]), np.hstack([Xva, Tva])

        mu, sd = Atr.mean(0), Atr.std(0)
        sd[sd < 1e-9] = 1.0
        Atr = (Atr - mu) / sd
        Ava = (Ava - mu) / sd
        Atr = np.hstack([np.ones((len(tr), 1)), Atr])
        Ava = np.hstack([np.ones((len(va), 1)), Ava])

        w = np.linalg.solve(Atr.T @ Atr + lam * np.eye(Atr.shape[1]), Atr.T @ ys)
        pv = Ava @ w
        for j, i in enumerate(va):
            preds[i] = float(pv[j])
    return preds, [both[i][1]["views"] for i in range(n)]


def main():
    both = load()
    views = [b[1]["views"] for b in both]
    print(f"# joined={len(both)}  p90={sorted(views)[int(len(views)*0.9)]}")

    print("\n=== 单分折对比（seed=0）===")
    print(f"{'mode':<8}{'rho':>9}{'pearson':>10}{'top50':>9}{'avg':>8}")
    res = {}
    for mode in ("X", "T", "TX"):
        p, v = run_cv(both, mode)
        e = evaluate(p, v, mode)
        res[mode] = e
        print(f"{mode:<8}{e['spearman_rho']:>9.4f}{e['pearson_r']:>10.4f}"
              f"{e['topk_hits']:>6}/{e['topk']:<3}{e['topk_avg_views']:>8}")

    print("\n=== 多种子 CV（10 折，均值±σ）===")
    agg = {m: {"rho": [], "hits": []} for m in ("X", "T", "TX")}
    for seed in range(10):
        for mode in ("X", "T", "TX"):
            p, v = run_cv(both, mode, seed=seed)
            e = evaluate(p, v, mode)
            agg[mode]["rho"].append(e["spearman_rho"])
            agg[mode]["hits"].append(e["topk_hits"])
    for mode in ("X", "T", "TX"):
        r, h = agg[mode]["rho"], agg[mode]["hits"]
        print(f"  {mode:<4} rho={statistics.mean(r):.4f} ± {statistics.stdev(r):.4f}"
              f"   top50={statistics.mean(h):.1f} ± {statistics.stdev(h):.1f}")

    # 配对：TX vs X
    px, vx = run_cv(both, "X")
    ptx, vtx = run_cv(both, "TX")
    ups = sum(1 for a, b in zip(px, ptx) if b > a)
    dns = sum(1 for a, b in zip(px, ptx) if b < a)
    print(f"\n=== 配对符号检验 TX vs X ===")
    print(f"  TX>X: {ups}   TX<X: {dns}   tie: {len(px)-ups-dns}")
    print(f"  (双向都有 = 真重排序；一边倒 = 单调变换)")

    wins_r = sum(1 for a, b in zip(agg["X"]["rho"], agg["TX"]["rho"]) if b > a)
    wins_h = sum(1 for a, b in zip(agg["X"]["hits"], agg["TX"]["hits"]) if b > a)
    print(f"  多种子胜率: rho {wins_r}/10,  top50 {wins_h}/10")

    json.dump({"n": len(both), "single_fold": res,
               "multiseed": {m: {"rho_mean": statistics.mean(agg[m]["rho"]),
                                 "rho_sd": statistics.stdev(agg[m]["rho"]),
                                 "top50_mean": statistics.mean(agg[m]["hits"]),
                                 "top50_sd": statistics.stdev(agg[m]["hits"])}
                             for m in agg},
               "sign_test": {"ups": ups, "downs": dns},
               "wins": {"rho": wins_r, "top50": wins_h}},
              open(YT / "thumb_decision.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n# wrote {YT/'thumb_decision.json'}")


if __name__ == "__main__":
    main()
