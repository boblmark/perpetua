#!/usr/bin/env python3
"""v3b 深入实验：为什么饱和惩罚无效？测试特征"类别"假设。

假设 H1（mismatch.py 推导）：karen/instantkarma 类是饱和模板，应降权。
假设 H2（反方）：这些特征在**训练集**上确实有正 lift，把它们降权只是丢失信息；
                错配样本说明的是"少数个案不准"，不是"特征无效"。

本脚本做三件更硬的事：
  1. 用 CV 对比：把"模板类"特征整体降权/置零/移除，看 rho 与 Top50 怎么变
  2. 单独测具象物特征（dog/cat/robot/具体物件）加权
  3. 逐特征 CV 贡献度：leave-one-feature-out（把某特征从权重表移除，看 rho 掉多少）
"""
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
from backtest_v3 import featurize, fit, cv, evaluate, pearson, spearman  # noqa

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"

TEMPLATE_FEATS = {"w:karen", "s:karen", "s:dash_twist", "w:her",
                  "w:instantkarma", "w:instantly", "w:karma", "w:hoa", "w:hoafail"}
CONCRETE_FEATS = {"w:dog", "w:cat", "w:robot", "w:watermelon", "w:vacuum",
                  "w:doll", "w:labubu", "w:ball", "w:hand", "w:mirror"}


def cv_mod(docs, mutate=None, folds=5):
    """mutate(weights, stats, n_docs) -> 就地修改权重表。返回 CV 预测。"""
    n = len(docs)
    idx = sorted(range(n), key=lambda i: docs[i][1])
    buckets = [[] for _ in range(folds)]
    for pos, i in enumerate(idx):
        buckets[pos % folds].append(i)
    preds = [None] * n
    for fi in range(folds):
        va = buckets[fi]
        va_set = set(va)
        tr = [docs[i] for i in idx if i not in va_set]
        w, stats, base, n_docs = fit(tr)
        if mutate:
            mutate(w, stats, n_docs)
        for i in va:
            f = docs[i][0]
            hits = sorted([(k, w[k]) for k in f if k in w], key=lambda x: -x[1])
            raw = sum(v * (0.85 ** j) for j, (_, v) in enumerate(hits[:5]))
            preds[i] = max(1, min(99, round(50 + raw * 22.0)))
    return preds


def main():
    rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("views", 0) > 0]
    docs = [(featurize(r["title"]), r["views"], r["title"]) for r in rows]
    views = [d[1] for d in docs]
    print(f"# sample: {len(docs)}")

    def show(name, preds):
        e = evaluate(preds, views, name)
        print(f"{name:<46}rho={e['spearman_rho']:>8.4f}  pe={e['pearson_r']:>7.4f}  "
              f"top50={e['topk_hits']:>2}/{e['topk']}  avg={e['topk_avg_views']:>6}")
        return e

    print("\n=== 实验 A: 模板类特征处置 ===")
    show("baseline (v3a)", cv_mod(docs))

    def zero_template(w, s, n):
        for k in TEMPLATE_FEATS:
            if k in w:
                w[k] = 0.0
    show("zero out template feats", cv_mod(docs, zero_template))

    def half_template(w, s, n):
        for k in TEMPLATE_FEATS:
            if k in w:
                w[k] *= 0.5
    show("halve template feats", cv_mod(docs, half_template))

    def drop_template(w, s, n):
        for k in list(w):
            if k in TEMPLATE_FEATS:
                del w[k]
    show("drop template feats", cv_mod(docs, drop_template))

    print("\n=== 实验 B: 具象物特征加权 ===")

    def boost_concrete(w, s, n, mult=1.5):
        for k in CONCRETE_FEATS:
            if k in w:
                w[k] *= mult
    show("boost concrete x1.5", cv_mod(docs, lambda w, s, n: boost_concrete(w, s, n, 1.5)))
    show("boost concrete x2.0", cv_mod(docs, lambda w, s, n: boost_concrete(w, s, n, 2.0)))

    print("\n=== 实验 C: leave-one-feature-out（全量拟合后逐特征移除，看 rho 变化）===")
    w0, s0, base, nd = fit(docs)
    # in-sample scoring for feature ablation
    def score_all(w):
        return [max(1, min(99, round(50 + sum(v * (0.85 ** j) for j, (_, v) in
                enumerate(sorted([(k, w[k]) for k in d[0] if k in w],
                                 key=lambda x: -x[1])[:5])) * 22.0)))
                for d in docs]
    full = score_all(w0)
    e_full = evaluate(full, views, "full")
    print(f"{'full (in-sample)':<46}rho={e_full['spearman_rho']:>8.4f}  "
          f"top50={e_full['topk_hits']:>2}/{e_full['topk']}  avg={e_full['topk_avg_views']:>6}")

    drops = []
    for k in list(w0):
        w2 = dict(w0)
        del w2[k]
        e = evaluate(score_all(w2), views, k)
        drops.append((k, e["spearman_rho"] - e_full["spearman_rho"],
                      e["topk_hits"] - e_full["topk_hits"], w0[k], s0[k]["df_ratio"]))
    print("\n-- 移除后 rho 掉最多（= 最有用）--")
    for k, dr, dh, wv, dfr in sorted(drops, key=lambda x: x[1])[:12]:
        print(f"  {k:26s} d_rho={dr:+.4f}  d_top50={dh:+3d}  w={wv:6.3f}  df={dfr:.2f}")
    print("\n-- 移除后 rho 反而上升（= 有害，该降权/删）--")
    for k, dr, dh, wv, dfr in sorted(drops, key=lambda x: -x[1])[:12]:
        print(f"  {k:26s} d_rho={dr:+.4f}  d_top50={dh:+3d}  w={wv:6.3f}  df={dfr:.2f}")

    json.dump({"ablation": [{"feature": k, "d_rho": dr, "d_top50": dh,
                             "weight": wv, "df_ratio": dfr}
                            for k, dr, dh, wv, dfr in sorted(drops, key=lambda x: x[1])]},
              open(YT / "ablation_v3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n# wrote ablation_v3.json")


if __name__ == "__main__":
    main()
