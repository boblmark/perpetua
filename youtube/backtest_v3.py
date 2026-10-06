#!/usr/bin/env python3
"""v3 权重实验：留一/交叉验证对比 v2 与 v3-饱和惩罚，并输出可上线的模型。

诊断依据（mismatch.py 的产出）：
  高分低走组 karen=61% vs 全样本 28% vs 低分爆款 0%
  → "人设模板"类特征被高估，是赛道饱和信号，不是增量信号。

v3 的三处改动（每处可独立开关，便于归因）：
  A. 目标改为 log1p(views)：重尾分布下均值被爆款拉偏，几何均值更稳
  B. 饱和惩罚：weight *= 1 / (1 + (df_ratio / SAT_REF))，用得多 → 边际收益衰减
  C. 负 lift 裁剪：低于基线的特征不该产生正贡献（v2 让它们拉低是因为分值同号，
     但 top5 只取最大者，实际影响有限 —— 保留但显式化）

用法:
  python3 backtest_v3.py              # 跑 CV 对比，打印表格
  python3 backtest_v3.py --deploy     # CV 达标后写出 score_model_v3.json + v3 评分器
"""
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"

STOP = set("""the a an and or of to in for with on at is are you your i it this that
my we our vs shorts short ai film video ep epic cinematic must watch new""".split())

MIN_DF = 8
SAT_REF = 0.35   # 特征使用率到达 35% 时，权重被压到 1/(1+1)=0.5
N_FOLDS = 5
import re


def featurize(title: str):
    t = title.lower()
    f = set()
    for w in re.findall(r"[a-z0-9]{3,}", t):
        if w not in STOP:
            f.add("w:" + w)
    if re.search(r"\d", title):
        f.add("s:has_number")
    if "?" in title or "？" in title:
        f.add("s:question")
    if "!" in title or "！" in title:
        f.add("s:exclaim")
    if any(e in title for e in "🤯😱😂💀🤣😳🚨💦⚔️"):
        f.add("s:emoji_strong")
    if any(e in title for e in "🔥🐶🛒🏋️🧳🚪"):
        f.add("s:emoji_object")
    if "—" in title or " - " in title:
        f.add("s:dash_twist")
    if "karen" in t:
        f.add("s:karen")
    if "#shorts" in t or "#short" in t:
        f.add("s:hashtag_shorts")
    if len(title) <= 60:
        f.add("s:title_short")
    elif len(title) >= 100:
        f.add("s:title_long")
    return f


def fit(docs, min_df=MIN_DF, sat_ref=None, use_log1p=True, clip_neg=True):
    """docs: [(feat_set, views[, title])] -> weights dict"""
    n_docs = len(docs)
    vs_all = [d[1] for d in docs]
    base = statistics.mean(vs_all)
    log_base = math.log1p(base) if use_log1p else math.log(base)

    df = defaultdict(int)
    for d in docs:
        for k in d[0]:
            df[k] += 1

    weights, stats = {}, {}
    for k, n in df.items():
        if n < min_df:
            continue
        vs = [d[1] for d in docs if k in d[0]]
        if len(vs) < min_df:
            continue
        m = statistics.mean(vs)
        tgt = math.log1p(m) if use_log1p else math.log(max(m, 1))
        w = tgt - log_base
        if clip_neg:
            w = max(w, 0.0)
        if sat_ref:
            ratio = n / n_docs
            w *= 1.0 / (1.0 + ratio / sat_ref)
        weights[k] = w
        stats[k] = {"n": n, "avg_views": round(m), "lift": round(m / base, 3),
                    "df_ratio": round(n / n_docs, 3)}
    return weights, stats, base, n_docs


def score_with(weights, title, decay=0.85, topk=5, scale=22.0):
    f = featurize(title)
    hits = [(k, weights[k]) for k in f if k in weights]
    hits.sort(key=lambda x: -x[1])
    raw = sum(v * (decay ** i) for i, (_, v) in enumerate(hits[:topk]))
    return max(1, min(99, round(50 + raw * scale)))


def spearman(a, b):
    def rank(x):
        s = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        for pos, i in enumerate(s):
            r[i] = pos
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da and db else 0.0


def pearson(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def evaluate(scored, views, label):
    p90 = sorted(views)[int(len(views) * 0.9)]
    order = sorted(range(len(scored)), key=lambda i: -scored[i])
    k = min(50, len(order))
    top = order[:k]
    hits = sum(1 for i in top if views[i] >= p90)
    return {
        "label": label,
        "pearson_r": round(pearson(scored, views), 4),
        "spearman_rho": round(spearman(scored, views), 4),
        "p90": p90,
        "topk": k,
        "topk_hits": hits,
        "topk_hit_rate": round(hits / k, 4),
        "topk_avg_views": round(statistics.mean([views[i] for i in top])),
    }


def cv(docs, folds=N_FOLDS, **kw):
    """K 折交叉验证：每折在训练集拟合，在验证集打分，拼起来算全局指标。"""
    n = len(docs)
    idx = list(range(n))
    # 确定性打散（按 views 排序后交错，保证各折分布均匀）
    idx.sort(key=lambda i: docs[i][1])
    buckets = [[] for _ in range(folds)]
    for pos, i in enumerate(idx):
        buckets[pos % folds].append(i)

    preds = [None] * n
    for fi in range(folds):
        va = buckets[fi]
        va_set = set(va)
        tr = [docs[i] for i in idx if i not in va_set]
        w, _, _, _ = fit(tr, kw.get("min_df", MIN_DF),
                         kw.get("sat_ref"), kw.get("use_log1p", True),
                         kw.get("clip_neg", True))
        for i in va:
            preds[i] = score_with(w, docs[i][2])
    return preds


def main():
    rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("views", 0) > 0]
    docs = [(featurize(r["title"]), r["views"], r["title"]) for r in rows]
    views = [d[1] for d in docs]
    print(f"# sample: {len(docs)} rows (zero-view excluded)")

    configs = [
        ("v2 baseline (log, no sat, keep neg)", dict(sat_ref=None, use_log1p=False, clip_neg=False)),
        ("v3a log1p only",                       dict(sat_ref=None, use_log1p=True,  clip_neg=True)),
        ("v3b v3a + saturation(0.35)",           dict(sat_ref=0.35, use_log1p=True,  clip_neg=True)),
        ("v3c v3a + saturation(0.20)",           dict(sat_ref=0.20, use_log1p=True,  clip_neg=True)),
        ("v3d v3a + saturation(0.50)",           dict(sat_ref=0.50, use_log1p=True,  clip_neg=True)),
    ]
    results = []
    for name, kw in configs:
        preds = cv(docs, folds=N_FOLDS, **kw)
        results.append(evaluate(preds, views, name))

    print(f"\n{'config':<40}{'rho':>9}{'pearson':>9}{'top50 hit':>11}{'top50 avg':>11}")
    for r in results:
        print(f"{r['label']:<40}{r['spearman_rho']:>9.4f}{r['pearson_r']:>9.4f}"
              f"{r['topk_hits']:>6}/{r['topk']:<4}{r['topk_avg_views']:>11}")

    best = max(results, key=lambda r: (r["spearman_rho"], r["topk_hit_rate"]))
    print(f"\n# best by rho: {best['label']}  rho={best['spearman_rho']}")

    if "--deploy" in sys.argv:
        kw = dict([(c[0], c[1]) for c in configs])[best["label"]]
        w, stats, base, n_docs = fit(docs, MIN_DF, kw.get("sat_ref"),
                                     kw.get("use_log1p"), kw.get("clip_neg"))
        model = {"version": "v3-data", "trained_on": n_docs,
                 "base_avg_views": round(base), "min_df": MIN_DF,
                 "config": {"sat_ref": kw.get("sat_ref"), "use_log1p": kw.get("use_log1p"),
                            "clip_neg": kw.get("clip_neg")},
                 "weights": w, "stats": stats}
        out = YT / "score_model_v3.json"
        out.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"# wrote {out} ({len(w)} features)")

        top = sorted(stats.items(), key=lambda kv: -kv[1]["lift"])[:25]
        print("\n=== v3 最强正特征（原始 lift）===")
        for k, v in top:
            sat = w[k]
            print(f"  {k:26s} lift={v['lift']:6.2f}  df={v['df_ratio']:5.2f}  w={sat:6.3f}  n={v['n']:3d}")

    json.dump({"sample": len(docs), "results": results},
              open(YT / "backtest_v3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"# wrote {YT/'backtest_v3.json'}")


if __name__ == "__main__":
    main()
