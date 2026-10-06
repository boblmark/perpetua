#!/usr/bin/env python3
"""封面特征是否有预测力？—— 用和前几轮完全相同的 CV 口径评估。

对比三组：
  T (thumbnail only)   —— 只用 14 个封面特征
  X (title only)       —— 现行 v2 口径（86 个标题特征）
  T+X (combined)       —— 合并，看封面是否带来增量

方法：
  1. 特征标准化（z-score，用训练集均值/方差）
  2. 线性模型（numpy 最小二乘，岭正则）+ 树模型替代（分位数分箱 lift）
  3. 5 折 CV，报 ρ / Top50
  4. 若 T+X > X 显著，说明封面有增量信息
"""
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/home/hatch/data/youtube")
from backtest_v3 import featurize, evaluate, spearman, pearson  # noqa

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"
THUMB = YT / "thumb_features.jsonl"

THUMB_KEYS = ["lum_mean", "lum_std", "dark_ratio", "bright_ratio", "sat_mean",
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
    both = [(vid, vmap[vid], tf[vid]) for vid in vmap if vid in tf]
    return both


def title_vec(title, w):
    f = featurize(title)
    return np.array([w.get(k, 0.0) for k in f], dtype=np.float64), sorted(f)


def ridge_fit(X, y, lam=1.0):
    n, d = X.shape
    A = X.T @ X + lam * np.eye(d)
    b = X.T @ y
    return np.linalg.solve(A, b)


def zfit(X):
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return mu, sd


def cv_eval(both, mode, folds=5, lam=1.0):
    """mode: 'T' | 'X' | 'TX'。返回 (preds, views)。

    设计：所有特征先在训练集标准化再喂线性模型，避免量纲差异。
    标题组用 v2 同款 log-lift 权重（训练集拟合），封面组直接用 15 个原始特征。
    """
    n = len(both)
    order = sorted(range(n), key=lambda i: both[i][1]["views"])
    buckets = [[] for _ in range(folds)]
    for pos, i in enumerate(order):
        buckets[pos % folds].append(i)

    preds = [0.0] * n
    for va in buckets:
        va_set = set(va)
        tr = [i for i in order if i not in va_set]

        y = np.array([math.log1p(both[i][1]["views"]) for i in tr], dtype=np.float64)
        ys = (y - y.mean()) / (y.std() or 1.0)

        blocks_tr, blocks_va = [], []
        if mode in ("T", "TX"):
            blocks_tr.append(np.array([[both[i][2][k] for k in THUMB_KEYS] for i in tr],
                                      dtype=np.float64))
            blocks_va.append(np.array([[both[i][2][k] for k in THUMB_KEYS] for i in va],
                                      dtype=np.float64))
        if mode in ("X", "TX"):
            from backtest_v3 import fit as tfit
            docs = [(featurize(both[i][1]["title"]), both[i][1]["views"]) for i in tr]
            wmap, _, _, _ = tfit(docs, 8, None, True, True)
            keys = sorted(wmap)
            blocks_tr.append(np.array([[wmap.get(k, 0.0) for k in keys] for i in tr],
                                      dtype=np.float64))
            blocks_va.append(np.array(
                [[wmap.get(k, 0.0) if k in featurize(both[i][1]["title"]) else 0.0
                  for k in keys] for i in va], dtype=np.float64))

        Xtr = np.hstack(blocks_tr)
        Xva = np.hstack(blocks_va)
        mu, sd = zfit(Xtr)
        Xtr = (Xtr - mu) / sd
        Xva = (Xva - mu) / sd
        Xtr = np.hstack([np.ones((len(tr), 1)), Xtr])
        Xva = np.hstack([np.ones((len(va), 1)), Xva])

        w = ridge_fit(Xtr, ys, lam)
        pv = Xva @ w
        for j, i in enumerate(va):
            preds[i] = float(pv[j])

    views = [both[i][1]["views"] for i in range(n)]
    return preds, views


def main():
    both = load()
    print(f"# joined rows: {len(both)} (thumb + views)")
    views = [b[1]["views"] for b in both]
    p90 = sorted(views)[int(len(views) * 0.9)]
    print(f"# p90={p90}  avg={round(statistics.mean(views))}")

    # --- 单特征相关性（封面特征各自与 log(views) 的关系）---
    print("\n=== 封面单特征与 log1p(views) 的相关性 ===")
    ly = [math.log1p(v) for v in views]
    rows = []
    for k in THUMB_KEYS:
        x = [b[2][k] for b in both]
        rows.append((k, pearson(x, ly), spearman(x, views)))
    rows.sort(key=lambda r: -abs(r[1]))
    print(f"{'feature':<22}{'pearson':>10}{'spearman':>11}")
    for k, pe, sp in rows:
        flag = "  <<<" if abs(pe) > 0.10 else ""
        print(f"{k:<22}{pe:>10.4f}{sp:>11.4f}{flag}")

    # --- 分组均值对比：Top10% vs Bottom10% ---
    print("\n=== Top10% vs Bottom10% 封面特征均值 ===")
    n = len(both)
    idx = sorted(range(n), key=lambda i: views[i])
    bot = idx[:max(1, n // 10)]
    top = idx[-max(1, n // 10):]
    print(f"{'feature':<22}{'bottom10%':>12}{'top10%':>12}{'diff':>10}")
    for k in THUMB_KEYS:
        mb = statistics.mean([both[i][2][k] for i in bot])
        mt = statistics.mean([both[i][2][k] for i in top])
        print(f"{k:<22}{mb:>12.3f}{mt:>12.3f}{mt-mb:>+10.3f}")

    json.dump({"n": len(both), "p90": p90,
               "single_feature": [{"feature": k, "pearson": pe, "spearman": sp}
                                  for k, pe, sp in rows]},
              open(YT / "thumb_corr.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n# wrote {YT/'thumb_corr.json'}")


if __name__ == "__main__":
    main()
