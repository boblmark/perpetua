#!/usr/bin/env python3
"""Round 7: 独立封面评分器 (standalone cover scorer) — 修正版。

修正点 (相对第六轮的错误推论):
- 第六轮把 "单特征 in-sample Pearson(-0.24)" 和 "15 维模型 CV Spearman(0.19)" 直接比,
  混合了度量(Pearson vs Spearman)与口径(in-sample vs CV), 得出"稀释"结论是错的。
- 本轮统一: CV 一律 Spearman(排名能力) 与 Pearson(对 log1p(views) 线性能力), 口径一致。
- Pearson 必须对齐 log1p 空间 (模型预测的是 log1p(views), 不是原始 views)。
"""
import json, math, statistics as st, random
from pathlib import Path

THUMB = "/home/hatch/data/youtube/thumb_features.jsonl"
UPLOADS = "/home/hatch/data/youtube/uploads_full.jsonl"
OUT = "/home/hatch/data/youtube/thumb_scorer.json"
MODEL_OUT = "/home/hatch/data/youtube/cover_score_model.json"

ALL_FEATS = ["lum_mean", "lum_std", "dark_ratio", "bright_ratio", "sat_mean",
             "sat_high_ratio", "hue_entropy", "warm_ratio", "rule_of_thirds",
             "center_energy", "salience_entropy", "highfreq_mean",
             "highfreq_ratio", "edge_density", "dominant_band_ratio"]
# 紧凑 6 维: 按单特征 |Pearson| 取前 6 (可解释 + 低维易部署)
TOP6 = ["salience_entropy", "center_energy", "rule_of_thirds", "hue_entropy",
        "lum_mean", "highfreq_ratio"]
SEL3 = ["salience_entropy", "center_energy", "warm_ratio"]

P90 = 2138


def load():
    thumbs, ups = {}, {}
    with open(THUMB) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line); thumbs[d["video_id"]] = d
    with open(UPLOADS) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line); ups[d["video_id"]] = d
    rows = []
    for vid, t in thumbs.items():
        if vid in ups:
            v = ups[vid].get("views", 0)
            if v and v > 0:
                rows.append((vid, t, int(v)))
    return rows


def rank(x):
    idx = sorted(range(len(x)), key=lambda i: x[i])
    r = [0] * len(x); i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[idx[j + 1]] == x[idx[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[idx[k]] = avg
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = rank(a), rank(b); n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    da = [ra[i] - ma for i in range(n)]; db = [rb[i] - mb for i in range(n)]
    num = sum(da[i] * db[i] for i in range(n))
    den = math.sqrt(sum(d * d for d in da) * sum(d * d for d in db))
    return num / den if den else 0.0


def pearson(a, b):
    n = len(a); ma, mb = sum(a) / n, sum(b) / n
    da = [a[i] - ma for i in range(n)]; db = [b[i] - mb for i in range(n)]
    num = sum(da[i] * db[i] for i in range(n))
    den = math.sqrt(sum(d * d for d in da) * sum(d * d for d in db))
    return num / den if den else 0.0


def top50_hit(pred, views):
    n = len(views); k = min(50, n)
    actual_top = set(i for i, _ in sorted(enumerate(views), key=lambda x: -x[1])[:k])
    pred_top = set(i for i, _ in sorted(enumerate(pred), key=lambda x: -x[1])[:k])
    return len(actual_top & pred_top)


def zscore_cols(train, val, feats):
    n = len(train)
    means = [sum(train[i][j] for i in range(n)) / n for j in range(len(feats))]
    stds = []
    for j in range(len(feats)):
        m = means[j]
        var = sum((train[i][j] - m) ** 2 for i in range(n)) / n
        stds.append(math.sqrt(var) or 1.0)
    z = lambda mat: [[(mat[i][j] - means[j]) / stds[j] for j in range(len(feats))]
                     for i in range(len(mat))]
    return z(train), z(val)


def ols_fit(X, y):
    n, p = len(X), len(X[0])
    Xt = list(zip(*X))
    XtX = [[sum(Xt[i][k] * Xt[j][k] for k in range(n)) for j in range(p)] for i in range(p)]
    Xty = [sum(Xt[i][k] * y[k] for k in range(n)) for i in range(p)]
    A = [row[:] + [Xty[i]] for i, row in enumerate(XtX)]
    for c in range(p):
        piv = max(range(c, p), key=lambda r: abs(A[r][c]))
        A[c], A[piv] = A[piv], A[c]
        pv = A[c][c] or 1e-9
        A[c] = [v / pv for v in A[c]]
        for r in range(p):
            if r != c:
                f = A[r][c]; A[r] = [A[r][k] - f * A[c][k] for k in range(p + 1)]
    return [A[i][p] for i in range(p)]


def score(X, coef):
    return [sum(X[i][j] * coef[j] for j in range(len(coef))) for i in range(len(X))]


def cv_eval(rows, feats, n_fold=5, seeds=10):
    views = [r[2] for r in rows]
    ylog = [math.log1p(v) for v in views]
    mat = [[r[1].get(f, 0.0) for f in feats] for r in rows]
    rhos, pears, tops = [], [], []
    for s in range(seeds):
        idx = list(range(len(rows)))
        random.seed(s); random.shuffle(idx)
        fold_pred = [0.0] * len(rows)
        for f in range(n_fold):
            val_idx = set(idx[f::n_fold])
            tr = [i for i in range(len(rows)) if i not in val_idx]
            Xtr, Xva = zscore_cols([mat[i] for i in tr], [mat[i] for i in val_idx], feats)
            coef = ols_fit(Xtr, [ylog[i] for i in tr])
            sp = score(Xva, coef)
            for k, i in enumerate(val_idx):
                fold_pred[i] = sp[k]
        rhos.append(spearman(fold_pred, views))
        pears.append(pearson(fold_pred, ylog))   # 修正: 对齐 log1p
        tops.append(top50_hit(fold_pred, views))
    return {"feats": feats, "n": len(rows), "k": len(feats),
            "rho_mean": st.mean(rhos), "rho_std": st.pstdev(rhos),
            "pearson_mean": st.mean(pears), "pearson_std": st.pstdev(pears),
            "top50_mean": st.mean(tops), "top50_std": st.pstdev(tops),
            "top50_raw": tops}


def insample(rows, feats):
    views = [r[2] for r in rows]; ylog = [math.log1p(v) for v in views]
    mat = [[r[1].get(f, 0.0) for f in feats] for r in rows]
    Xtr, Xva = zscore_cols(mat, mat, feats)
    coef = ols_fit(Xtr, ylog)
    sp = score(Xva, coef)
    return {"rho": spearman(sp, views), "pearson": pearson(sp, ylog),
            "coef": coef, "intercept": 0.0}


def single_feat_corr(rows):
    views = [r[2] for r in rows]; ylog = [math.log1p(v) for v in views]
    out = []
    for f in ALL_FEATS:
        xs = [r[1].get(f, 0.0) for r in rows]
        out.append((f, pearson(xs, ylog), spearman(xs, views)))
    out.sort(key=lambda t: -abs(t[1]))
    return out


def main():
    rows = load()
    print(f"joined valid rows (views>0): {len(rows)}")
    sfc = single_feat_corr(rows)
    print("\n=== single-feature correlation (Pearson on log1p(views), Spearman on views) ===")
    for f, pr, sp in sfc:
        print(f"  {f:20s} Pearson={pr:+.4f}  Spearman={sp:+.4f}")

    models = {"sel3": SEL3, "top6": TOP6, "full15": ALL_FEATS}
    results = {}
    for name, feats in models.items():
        cv = cv_eval(rows, feats, seeds=10)
        ins = insample(rows, feats)
        results[name] = {"cv": cv, "in_sample": ins}
        print(f"\n=== {name} ({len(feats)} feat) ===")
        print(f"  CV      ρ={cv['rho_mean']:+.4f}±{cv['rho_std']:.4f}  "
              f"Pearson={cv['pearson_mean']:+.4f}±{cv['pearson_std']:.4f}  "
              f"Top50={cv['top50_mean']:.1f}±{cv['top50_std']:.1f}")
        print(f"  in-samp ρ={ins['rho']:+.4f}  Pearson={ins['pearson']:+.4f}  "
              f"(overfit gap ρ={ins['rho']-cv['rho_mean']:+.4f})")

    # 推荐: 用户的原始设想是"3 维、可解释、用于封面优化" → 默认推荐 sel3 (过拟合缺口仅 0.02, 最稳)。
    # full15 预测力最强(CV ρ 0.20)但维数高、缺口 0.05、可解释性差, 列为"最大功率"备选。
    best = "sel3"
    rec = results[best]
    print(f"\n>>> recommended (per user's interpretable-3dim intent): {best} ({len(rec['cv']['feats'])} feat)")
    print(f">>> alt max-power: full15 (CV ρ={results['full15']['cv']['rho_mean']:+.4f}, "
          f"gap={results['full15']['in_sample']['rho']-results['full15']['cv']['rho_mean']:+.4f})")

    def write_model(name, res, path):
        feats = res["cv"]["feats"]; ins = res["in_sample"]
        mat = [[r[1].get(f, 0.0) for f in feats] for r in rows]
        n = len(mat)
        means = [sum(mat[i][j] for i in range(n)) / n for j in range(len(feats))]
        sds = [math.sqrt(sum((mat[i][j] - means[j]) ** 2 for i in range(n)) / n) or 1.0
               for j in range(len(feats))]
        model = {
            "name": f"cover_score_{name}",
            "predicts": "log1p(views)",
            "features": feats,
            "coef": [round(c, 5) for c in ins["coef"]],
            "mean": [round(m, 5) for m in means],
            "std": [round(s, 5) for s in sds],
            "cv_rho": round(res["cv"]["rho_mean"], 4),
            "cv_pearson": round(res["cv"]["pearson_mean"], 4),
            "cv_top50": round(res["cv"]["top50_mean"], 2),
            "in_sample_rho": round(res["in_sample"]["rho"], 4),
            "overfit_gap_rho": round(res["in_sample"]["rho"] - res["cv"]["rho_mean"], 4),
            "n_train": n,
            "note": "独立封面评分器, 不参与选题排名, 用于已定选题后的封面优化",
        }
        with open(path, "w") as fo:
            json.dump(model, fo, indent=2, ensure_ascii=False)
        print(f">>> written model: {path}")
        return model

    write_model("sel3", results["sel3"], "/home/hatch/data/youtube/cover_score_model_sel3.json")
    write_model("full15", results["full15"], "/home/hatch/data/youtube/cover_score_model.json")

    result = {
        "n": len(rows), "p90_threshold": P90,
        "single_feat_corr": [{"feat": f, "pearson": pr, "spearman": sp}
                             for f, pr, sp in sfc],
        "models": {k: {"cv": v["cv"], "in_sample": {"rho": v["in_sample"]["rho"],
                   "pearson": v["in_sample"]["pearson"]}} for k, v in results.items()},
        "recommended": best,
        "model_file": MODEL_OUT,
    }
    with open(OUT, "w") as fo:
        json.dump(result, fo, indent=2, ensure_ascii=False)
    print(f">>> written: {OUT}")


if __name__ == "__main__":
    main()
