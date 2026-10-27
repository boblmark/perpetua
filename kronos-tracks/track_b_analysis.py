"""Track B virality scoring — numpy/scipy only (no sklearn in this env).
Reads ONLY the shared dataset + local files. No YouTube API, no writes.
Outputs: track_b_results.json (and prints all numbers for the report).
"""
import json, math, re
from collections import defaultdict
import numpy as np
from scipy.stats import spearmanr, pearsonr

BASE = "/home/hatch/workspace/goals/karenvsai/hidden_files/kronos-tracks"
SHARED = f"{BASE}/shared_dataset.json"

def spear(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3: return None
    r, p = spearmanr(x[m], y[m])
    return {"n": int(m.sum()), "rho": round(float(r), 3), "p": round(float(p), 4)}

def pear(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3: return None
    r, p = pearsonr(x[m], y[m])
    return {"n": int(m.sum()), "r": round(float(r), 3), "p": round(float(p), 4)}

def auc(scores, labels):
    scores = np.asarray(scores, float); labels = np.asarray(labels, int)
    pos = scores[labels == 1]; neg = scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0: return None
    wins = sum(1 for p in pos for n in neg if p > n) + 0.5 * sum(1 for p in pos for n in neg if p == n)
    return round(float(wins / (len(pos) * len(neg))), 3)

def starts_emoji(title):
    if not title: return 0
    c = title[0]
    o = ord(c)
    return 1 if (o > 0x2000 or 0x1F000 <= o <= 0x1FAFF or o in (0x00A9, 0x00AE)) else 0

shared = json.load(open(SHARED))
vids = shared["videos"]

# ---------------- Cohort A: recent, observable launch curve ----------------
rows = []
for vid, v in vids.items():
    pub = v.get("published_at_derived") or (v.get("sequel") or {}).get("published_at")
    daily = v.get("daily_views") or []
    seq = [dv for _, dv in daily]
    seq_v = seq[0] if len(seq) > 0 else None
    tel = v.get("telemetry_latest") or {}
    seqd = v.get("sequel") or {}
    fb = seqd.get("formula_breakdown") or {}
    title = seqd.get("title") or tel.get("title") or ""
    total = sum(seq)
    d = {
        "video_id": vid, "published_at": pub,
        "daily_seq": seq, "n_obs_days": len(seq),
        "d0": seq[0] if len(seq) > 0 else 0,
        "d1": seq[1] if len(seq) > 1 else 0,
        "d2": seq[2] if len(seq) > 2 else 0,
        "total_inwindow": total,
        "sequel_views": seqd.get("views"),
        "telemetry_views": tel.get("views"),
        "avg_view_pct": tel.get("avg_view_pct"),
        "avg_dur_s": tel.get("avg_dur_s"),
        "duration_s": tel.get("duration_s"),
        "likes": tel.get("likes"), "comments": tel.get("comments"),
        "title": title, "title_len": len(title),
        "starts_with_emoji": int(fb["starts_with_emoji"]) if "starts_with_emoji" in fb else starts_emoji(title),
        "has_karen": int(fb["has_karen"]) if "has_karen" in fb else (1 if "karen" in title.lower() else 0),
        "hashtag_n": title.count("#"),
        "ai_device": (fb.get("ai_devices") or [None])[0],
        "formula_key": fb.get("formula_key"),
        "has_instant_karma_signal": int(fb["has_instant_karma_signal"]) if "has_instant_karma_signal" in fb else None,
    }
    d["total_3day"] = d["d0"] + d["d1"] + d["d2"]
    d["tail_after_3day"] = d["total_inwindow"] - d["total_3day"]
    d["day0_share"] = round(d["d0"] / d["total_inwindow"], 3) if d["total_inwindow"] else 0.0
    d["vel_d1_d0"] = round(d["d1"] / (d["d0"] + 1), 3)
    d["vel_d2_d1"] = round(d["d2"] / (d["d1"] + 1), 3)
    first7 = seq[:7]
    d["days_to_peak"] = int(np.argmax(first7)) if first7 else None
    d["peak_day_views"] = max(first7) if first7 else 0
    rows.append(d)

# Recent = published on/after 2026-10-10 (launch inside the 90-day window tail,
# so the full launch curve is observed). Old videos predate the window.
recent = [r for r in rows if r["published_at"] and r["published_at"] >= "2026-10-10"]
old = [r for r in rows if r not in recent]
print(f"total shared videos: {len(rows)}  recent(>=2026-10-10): {len(recent)}  old/excluded-from-early-model: {len(old)}")
for r in sorted(recent, key=lambda x: -x["total_inwindow"]):
    print(f"  {r['video_id']} pub={r['published_at'][:10]} seq={r['daily_seq'][:4]} total={r['total_inwindow']} "
          f"seq_views={r['sequel_views']} tel_views={r['telemetry_views']} d0share={r['day0_share']} "
          f"pct={r['avg_view_pct']} dur={r['avg_dur_s']} title_len={r['title_len']} emoji={r['starts_with_emoji']}")
print("  OLD (in-window sums, mostly pre-window trickle):")
for r in sorted(old, key=lambda x: -(x["telemetry_views"] or 0)):
    print(f"  {r['video_id']} pub={str(r['published_at'])[:10]} inwindow={r['total_inwindow']} lifetime_tel={r['telemetry_views']}")

# ---------------- Viral definition ----------------
A = sorted(recent, key=lambda x: -x["total_inwindow"])
ev = np.array([r["total_inwindow"] for r in A], float)
print("\nCohort A eventual (in-window total) sorted:", sorted(ev.tolist(), reverse=True))
print("median:", float(np.median(ev)), "mean:", round(float(np.mean(ev)), 1),
      "Q1/Q3:", [round(float(q), 1) for q in np.percentile(ev, [25, 75])])
for thr in (500, 600, 700, 1000):
    print(f"  thr >={thr}: {(ev >= thr).sum()}/{len(ev)} viral")

VIRAL_THR = 1000
for r in A:
    r["eventual_views"] = r["total_inwindow"]
    r["viral_label"] = int(r["total_inwindow"] >= VIRAL_THR)
    r["strong_label"] = int(r["total_inwindow"] >= 500)

# ---------------- Feature correlations vs eventual (Cohort A) ----------------
feats = ["d0", "d1", "d2", "total_3day", "vel_d1_d0", "vel_d2_d1", "day0_share",
         "days_to_peak", "avg_view_pct", "avg_dur_s", "duration_s", "title_len",
         "hashtag_n", "starts_with_emoji", "has_karen", "likes", "comments"]
print("\nSpearman vs EVENTUAL (cohort A, n=9 unless noted):")
corr_eventual = {}
for f in feats:
    s = spear([r[f] for r in A], [r["eventual_views"] for r in A])
    corr_eventual[f] = s
    print(f"  {f:20s} {s}")
print("\nSpearman vs TAIL-after-day2 (does early predict LATER growth, not itself?):")
corr_tail = {}
for f in ["d0", "d1", "d2", "total_3day", "vel_d1_d0", "vel_d2_d1", "day0_share", "avg_view_pct", "title_len"]:
    s = spear([r[f] for r in A], [r["tail_after_3day"] for r in A])
    corr_tail[f] = s
    print(f"  {f:20s} {s}")
print("  tails:", [(r["video_id"], r["tail_after_3day"]) for r in A])

# Candidate scores (ranked by Spearman vs eventual)
def score_log_early(r): return math.log1p(r["d0"]) + 0.5 * math.log1p(r["d1"])
def score_d0(r): return float(r["d0"])
def score_3day(r): return float(r["total_3day"])
def score_vel(r): return math.log1p(r["d0"]) + math.log1p(r["d1"]) - 2.0 * abs(math.log((r["d1"] + 1) / (r["d0"] + 1)))
scores = {"d0_only": score_d0, "total_3day": score_3day,
          "log_d0_plus_half_log_d1": score_log_early, "log_early_minus_decay_penalty": score_vel}
print("\nCandidate scores, Spearman vs eventual / vs tail:")
score_eval = {}
for name, fn in scores.items():
    sc = [fn(r) for r in A]
    score_eval[name] = {"spearman_eventual": spear(sc, [r["eventual_views"] for r in A]),
                        "spearman_tail": spear(sc, [r["tail_after_3day"] for r in A]),
                        "auc_viral1000": auc(sc, [r["viral_label"] for r in A]),
                        "auc_strong500": auc(sc, [r["strong_label"] for r in A])}
    print(f"  {name}: {score_eval[name]}")

# LOOCV: decision stump on d0 (threshold = midpoint between classes on train, fallback median)
def loocv_stump(A, feat, labels):
    correct = 0; preds = []
    for i in range(len(A)):
        tr = [r for j, r in enumerate(A) if j != i]
        pos = [r[feat] for r in tr if r["viral_label"] == 1]
        neg = [r[feat] for r in tr if r["viral_label"] == 0]
        thr = (min(pos) + max(neg)) / 2 if pos and neg else float(np.median([r[feat] for r in tr]))
        p = int(A[i][feat] >= thr)
        preds.append(p); correct += int(p == A[i]["viral_label"])
    return {"accuracy": round(correct / len(A), 3), "preds": preds, "n": len(A)}

def loocv_spearman(A, feat):
    # leave-one-out rank correlation of feat vs eventual (stability check)
    rhos = []
    for i in range(len(A)):
        tr = [r for j, r in enumerate(A) if j != i]
        s = spear([r[feat] for r in tr], [r["eventual_views"] for r in tr])
        if s: rhos.append(s["rho"])
    return {"mean_rho": round(float(np.mean(rhos)), 3), "min_rho": round(float(np.min(rhos)), 3),
            "max_rho": round(float(np.max(rhos)), 3), "n_folds": len(rhos)}

def loocv_logreg(A):
    """Tiny numpy logistic regression, L2-regularised, features log1p(d0), log1p(d1) standardised.
    Returns LOOCV accuracy/AUC. With 2 positives this is a stress test, not a product."""
    X = np.array([[math.log1p(r["d0"]), math.log1p(r["d1"])] for r in A], float)
    y = np.array([r["viral_label"] for r in A], float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Xs = (X - mu) / sd
    def fit(Xt, yt, lam=1.0, iters=800, lr=0.1):
        w = np.zeros(Xt.shape[1]); b = 0.0
        for _ in range(iters):
            z = Xt @ w + b; p = 1 / (1 + np.exp(-z))
            gw = Xt.T @ (p - yt) / len(yt) + lam * w / len(yt); gb = float(np.mean(p - yt))
            w -= lr * gw; b -= lr * gb
        return w, b
    preds, probs = [], []
    for i in range(len(A)):
        m = np.ones(len(A), bool); m[i] = False
        w, b = fit(Xs[m], y[m])
        pr = float(1 / (1 + math.exp(-(Xs[i] @ w + b))))
        probs.append(pr); preds.append(int(pr >= 0.5))
    acc = float(np.mean(np.array(preds) == y))
    return {"accuracy": round(acc, 3), "auc": auc(probs, y), "preds": preds, "probs": [round(p, 3) for p in probs]}

loocv = {
    "stump_d0_viral1000": loocv_stump(A, "d0", "viral_label"),
    "stump_3day_viral1000": loocv_stump(A, "total_3day", "viral_label"),
    "loocv_spearman_d0": loocv_spearman(A, "d0"),
    "loocv_spearman_3day": loocv_spearman(A, "total_3day"),
    "logreg_logd0_logd1": loocv_logreg(A),
}
print("\nLOOCV:", json.dumps(loocv, indent=1))
# In-sample stump accuracy (for contrast: how much LOOCV deflates it)
for feat in ("d0", "total_3day"):
    pos = [r[feat] for r in A if r["viral_label"] == 1]; neg = [r[feat] for r in A if r["viral_label"] == 0]
    thr = (min(pos) + max(neg)) / 2
    acc = float(np.mean([int(r[feat] >= thr) == r["viral_label"] for r in A]))
    print(f"  in-sample stump {feat}: thr={thr:.1f} acc={acc:.3f} (vs LOOCV above)")

# ---------------- Cohort C: 72-video telemetry latest snapshot ----------------
rows72 = [json.loads(l) for l in open("/home/hatch/data/perpetua/retention_telemetry.jsonl")]
latest = {}
for r in sorted(rows72, key=lambda x: x["ts"]):
    latest[r["video_id"]] = r
C = list(latest.values())
print(f"\nCohort C: {len(C)} videos (latest snapshot each)")
C_pct = [r for r in C if r.get("avg_view_pct") is not None]
print(f"  with non-null avg_view_pct: {len(C_pct)}")
def tfeat(r):
    t = r.get("title") or ""
    return {"title_len": len(t), "hashtag_n": t.count("#"),
            "starts_with_emoji": starts_emoji(t),
            "has_karen": 1 if "karen" in t.lower() else 0,
            "duration_s": r.get("duration_s"),
            "avg_view_pct": r.get("avg_view_pct"), "avg_dur_s": r.get("avg_dur_s"),
            "likes": r.get("likes"), "comments": r.get("comments"),
            "review_score": (r.get("pipeline") or {}).get("review_score")}
c_feats = {}
for f in ["title_len", "hashtag_n", "starts_with_emoji", "has_karen", "duration_s", "likes", "comments"]:
    c_feats[f] = spear([tfeat(r)[f] for r in C], [r["views"] for r in C])
    print(f"  C spearman {f} vs views: {c_feats[f]}")
c_pct = {}
for f in ["avg_view_pct", "avg_dur_s"]:
    c_pct[f] = spear([r[f] for r in C_pct], [r["views"] for r in C_pct])
    print(f"  C(non-null pct) spearman {f} vs views: {c_pct[f]}")
# review_score: only where present/nonzero?
C_rev = [r for r in C if (r.get("pipeline") or {}).get("review_score")]
print(f"  C with pipeline review_score present: {len(C_rev)}; nonzero: {sum(1 for r in C_rev if r['pipeline']['review_score'])}")
c_rev = spear([r["pipeline"]["review_score"] for r in C_rev], [r["views"] for r in C_rev])
print(f"  C spearman review_score vs views: {c_rev}")
# Winners split a la dynamic_constraints: pct>?? — replicate: pct available, split by views>=1000 vs not, pct means
hi = [r for r in C_pct if r["views"] >= 1000]; lo = [r for r in C_pct if r["views"] < 1000]
print(f"  C_pct views>=1000: {len(hi)} (mean pct {np.mean([r['avg_view_pct'] for r in hi]) if hi else None:.1f}) "
      f"vs <1000: {len(lo)} (mean pct {np.mean([r['avg_view_pct'] for r in lo]) if lo else None:.1f})")

# ---------------- Final per-video table (Cohort A, chosen score) ----------------
for r in A:
    r["score"] = int(r["total_3day"])
    r["score_name"] = "total_3day"
out_rows = []
for r in sorted(A, key=lambda x: -x["score"]):
    out_rows.append({
        "video_id": r["video_id"], "title": r["title"], "published_at": r["published_at"],
        "features": {"d0_views": r["d0"], "d1_views": r["d1"], "d2_views": r["d2"],
                     "total_3day": r["total_3day"], "tail_after_3day": r["tail_after_3day"],
                     "vel_d1_d0": r["vel_d1_d0"], "vel_d2_d1": r["vel_d2_d1"],
                     "day0_share": r["day0_share"], "days_to_peak": r["days_to_peak"],
                     "peak_day_views": r["peak_day_views"], "n_obs_days": r["n_obs_days"],
                     "avg_view_pct": r["avg_view_pct"], "avg_dur_s": r["avg_dur_s"],
                     "duration_s": r["duration_s"], "likes": r["likes"], "comments": r["comments"],
                     "title_len": r["title_len"], "starts_with_emoji": r["starts_with_emoji"],
                     "has_karen": r["has_karen"], "hashtag_n": r["hashtag_n"],
                     "ai_device": r["ai_device"], "formula_key": r["formula_key"],
                     "has_instant_karma_signal": r["has_instant_karma_signal"]},
        "score": r["score"], "eventual_views": r["eventual_views"],
        "viral_label_1000": r["viral_label"], "strong_label_500": r["strong_label"],
        "sequel_views_crosscheck": r["sequel_views"], "telemetry_views_crosscheck": r["telemetry_views"],
    })

result = {
    "track": "B virality scoring", "kronos_used": False,
    "kronos_note": "No Kronos forecast used: Kronos is a forecaster, not a classifier, and no Track A forecast output exists in the shared tracks dir to use as a feature. This is a non-Kronos scoring model, which is a valid Track B result.",
    "cohort_A": {"definition": "Shared-dataset videos published >=2026-10-10 with the full launch curve inside the 90-day Analytics window",
                 "n": len(A), "video_ids": [r["video_id"] for r in A],
                 "excluded_old_n": len(old), "excluded_old_ids": [r["video_id"] for r in old],
                 "excluded_reason": "Published Jan-Jun 2025 (or 2025-07-06); their views predate the 90-day window, so in-window daily sums are 0-180 trickle and no launch curve is observable. Treating them as flat videos would be false."},
    "viral_definition": {"threshold": 1000, "rule": "eventual_views (in-window total) >= 1000",
                         "justification": "Channel top tier is ~1000-1400 views (task brief); 1000 marks the top of the recent cohort's range, not a median split. Secondary 'strong' line 500 also reported.",
                         "class_balance": {"viral": int(sum(r['viral_label'] for r in A)), "non_viral": int(sum(1 - r['viral_label'] for r in A)),
                                           "viral_ids": [r["video_id"] for r in A if r["viral_label"]],
                                           "strong_500": int(sum(r['strong_label'] for r in A))},
                         "eventual_distribution": {"median": float(np.median(ev)), "mean": round(float(np.mean(ev)), 1),
                                                   "min": int(ev.min()), "max": int(ev.max()),
                                                   "sorted_desc": sorted(ev.tolist(), reverse=True)}},
    "eventual_views_definition": "In-window daily-views sum from shared_dataset.json (pulled 2026-10-27). Cross-checked against sequel views (10-25 snapshot) and telemetry views: agreement within ~7% for 8/9 recent videos; 7oUJu0SBexk is the exception (in-window 272 vs sequel 142, sequel snapshot evidently taken ~day 0). In-window total is used consistently for all 9.",
    "early_feature_note": "daily_seq = sequence of observed daily values in file order (day granularity only; no hourly dimension exists in this API pull). d0 = first observed day's views, NOT a clean 24h count: publish-time and Analytics-day-boundary effects shift it (e.g. dHdnBH9q-mg first entry predates its publish timestamp by a day; pnN5V1NKJ2E has calendar gaps). Treat d0 as 'launch-day bucket', not 24h views.",
    "feature_correlations_eventual_cohortA": corr_eventual,
    "feature_correlations_tail_cohortA": corr_tail,
    "candidate_scores": score_eval,
    "chosen_score": {"name": "total_3day",
                     "formula": "score = d0 + d1 + d2 (views in the first 3 observed days)",
                     "why": "Tied-best rank performance (Spearman 0.983, LOOCV stump accuracy 1.0) and available ~72h after publish. The fancier log-blend (ln(1+d0)+0.5*ln(1+d1)) was TESTED AND REJECTED: it scored worse (Spearman 0.833, viral AUC 0.786) because d1 adds noise — e.g. the top video 5gcdjQ0SdrU has d1=1. d0 alone is the day-0 fallback (Spearman 0.983, LOOCV stump 0.889, missing plspTkhTHT8). Shipping the simpler winner, not the prettier formula."},
    "validation_loocv": loocv,
    "validation_note": "N=9 with 2 positives: LOOCV accuracy is fragile (one video = 11 points). Rank correlation (Spearman) is the primary validation; binary metrics are reported with that caveat, not as product claims.",
    "cohort_C_72video": {"n": len(C), "n_with_avg_view_pct": len(C_pct),
                         "spearman_vs_views": c_feats, "spearman_retention_vs_views": c_pct,
                         "spearman_review_score_vs_views": c_rev,
                         "n_with_review_score": len(C_rev),
                         "caveat": "Cohort C mixes lifetime views across Jan-Oct 2025 publishes with different ages/exposures; it tests title/retention associations only, NOT launch prediction. avg_view_pct is null for most videos (only recent snapshots carry it)."},
    "per_video_cohortA": out_rows,
    "data_gaps": ["No hourly data (API day granularity only) — no 1h/6h/24h early signals exist in this pull.",
                  "Retention (avg_view_pct) missing for 3/9 cohort-A videos (plspTkhTHT8, GxSeiQuOPvc, 7oUJu0SBexk have telemetry_latest=null).",
                  "Old videos have no observable launch curve in-window; excluded from the early-signal model, not modelled as zeros.",
                  "Title for GxSeiQuOPvc is truncated mid-word in the source sequel file, so its title_len is a lower bound.",
                  "No Track A Kronos output exists in the tracks dir, so no Kronos-as-feature test was possible."],
}
json.dump(result, open(f"{BASE}/track_b_results.json", "w"), indent=1, ensure_ascii=False)
print(f"\nWROTE {BASE}/track_b_results.json  (cohort A n={len(A)})")
