"""TRACK C — publish-slot analysis. CPU only, local files only, no API, no writes.
Conversion: published_at UTC + 8h = Beijing time (Asia/Shanghai, no DST).
Buckets (fixed before looking at outcomes beyond the slot table):
  late-night 22:00-23:59, early-morning 03:00-06:59, daytime 07:00-21:59, deep-night 00:00-02:59
Near-current: within +/-90 min of the slot for that BJ day-type
  (weekday Mon-Fri: 23:30, 05:30; weekend Sat-Sun: 22:30, 04:00).
Outcome: lifetime/snapshot views (NOT in-window daily views — see caveats).
Retention: telemetry avg_view_pct / avg_dur_s only; sequel avg_watch_secs is
  flagged unreliable (values 89s/117s on 9-11s videos) and NOT used as retention.
"""
import json, math, statistics
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from scipy.stats import mannwhitneyu, kruskal

BJ = timedelta(hours=8)
OUT = "/home/hatch/workspace/goals/karenvsai/hidden_files/kronos-tracks"

def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def bj_of(utc_dt):
    return utc_dt + BJ

def slot_distance_min(bj_dt):
    """Minutes to nearest applicable current slot (circular, same BJ date + neighbours)."""
    wd = bj_dt.weekday()  # Mon=0
    weekend = wd >= 5
    slots = [(22, 30), (4, 0)] if weekend else [(23, 30), (5, 30)]
    mins = bj_dt.hour * 60 + bj_dt.minute
    best = 1e9
    for h, m in slots:
        sm = h * 60 + m
        for shift in (-1440, 0, 1440):
            best = min(best, abs(mins - (sm + shift)))
    return best

def hour_bucket(bj_dt):
    h = bj_dt.hour
    if 22 <= h <= 23: return "late-night 22:00-23:59"
    if 3 <= h <= 6: return "early-morning 03:00-06:59"
    if 0 <= h <= 2: return "deep-night 00:00-02:59"
    return "daytime 07:00-21:59"

def grp_stats(vals):
    vals = sorted(vals)
    if not vals: return {"n": 0, "median": None, "mean": None, "min": None, "max": None, "values": []}
    return {"n": len(vals), "median": statistics.median(vals),
            "mean": round(statistics.mean(vals), 1), "min": vals[0], "max": vals[-1],
            "values": vals}

def mw(a, b, label):
    if len(a) < 2 or len(b) < 2:
        return {"comparison": label, "n_a": len(a), "n_b": len(b),
                "note": "too small for MWU (need >=2 per group)", "U": None, "p_two_sided": None}
    try:
        u, p = mannwhitneyu(a, b, alternative="two-sided")
    except Exception as e:
        return {"comparison": label, "n_a": len(a), "n_b": len(b), "error": str(e), "U": None, "p_two_sided": None}
    return {"comparison": label, "n_a": len(a), "n_b": len(b), "U": float(u),
            "p_two_sided": round(float(p), 4),
            "median_a": statistics.median(a), "median_b": statistics.median(b),
            "median_ratio_a_over_b": round(statistics.median(a) / statistics.median(b), 3) if statistics.median(b) else None}

# ---------- Dataset S21: shared_dataset.json ----------
sd = json.load(open(f"{OUT}/shared_dataset.json"))
s21 = []
for vid, v in sd["videos"].items():
    pa = v["published_at_derived"]
    utc = parse_ts(pa)
    bj = bj_of(utc)
    seq = v.get("sequel") or {}
    tel = v.get("telemetry_latest") or {}
    views = seq.get("views") if seq.get("views") is not None else tel.get("views")
    s21.append({
        "video_id": vid, "published_at_utc": pa, "published_at_bj": bj.strftime("%Y-%m-%d %H:%M"),
        "publish_weekday_bj": bj.strftime("%a"), "publish_weekday_num": bj.weekday(),
        "publish_hour_bj": bj.hour, "publish_minute_bj": bj.minute,
        "hour_bucket": hour_bucket(bj), "near_current_slot_90min": slot_distance_min(bj) <= 90,
        "dist_to_slot_min": slot_distance_min(bj),
        "is_weekend_bj": bj.weekday() >= 5,
        "views": views, "telemetry_views": tel.get("views"),
        "avg_view_pct": tel.get("avg_view_pct"), "avg_dur_s": tel.get("avg_dur_s"),
        "duration_s": tel.get("duration_s"),
        "title": (seq.get("title") or tel.get("title") or "")[:120],
        "formula": (seq.get("formula_breakdown") or {}).get("formula_key"),
        "ai_devices": (seq.get("formula_breakdown") or {}).get("ai_devices"),
        "source": "exact_sequel" if seq else "derived_telemetry_first_snapshot_minus_age",
        "in_window_views": sum(x[1] for x in v.get("daily_views", [])),
    })
s21.sort(key=lambda r: r["published_at_bj"])
recent21 = [r for r in s21 if r["published_at_bj"] >= "2026-10-01"]  # 9 videos, Oct era
old21 = [r for r in s21 if r["published_at_bj"] < "2026-10-01"]

# ---------- Dataset T72: retention_telemetry.jsonl, latest snapshot per video ----------
rows = [json.loads(l) for l in open("/home/hatch/data/perpetua/retention_telemetry.jsonl") if l.strip()]
by_vid = defaultdict(list)
for r in rows: by_vid[r["video_id"]].append(r)
seq_map = {x["video_id"]: x for x in json.load(open("/home/hatch/data/sequel_candidates.json"))}
t72 = []
for vid, rs in by_vid.items():
    rs_sorted = sorted(rs, key=lambda r: r["ts"])
    first, latest = rs_sorted[0], rs_sorted[-1]
    if vid in seq_map:  # exact beats derived
        utc = parse_ts(seq_map[vid]["published_at"]); src = "exact_sequel"
    else:
        utc = parse_ts(first["ts"]) - timedelta(hours=first["age_hours"]); src = "derived_telemetry_first_snapshot_minus_age"
    bj = bj_of(utc)
    age_h_latest = first["age_hours"] + (parse_ts(latest["ts"]) - parse_ts(first["ts"])).total_seconds() / 3600
    t72.append({
        "video_id": vid, "published_at_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "published_at_bj": bj.strftime("%Y-%m-%d %H:%M"),
        "publish_weekday_bj": bj.strftime("%a"), "publish_weekday_num": bj.weekday(),
        "publish_hour_bj": bj.hour, "publish_minute_bj": bj.minute,
        "hour_bucket": hour_bucket(bj), "near_current_slot_90min": slot_distance_min(bj) <= 90,
        "dist_to_slot_min": slot_distance_min(bj), "is_weekend_bj": bj.weekday() >= 5,
        "views": latest["views"], "avg_view_pct": latest["avg_view_pct"], "avg_dur_s": latest["avg_dur_s"],
        "duration_s": latest["duration_s"], "title": (latest.get("title") or "")[:120],
        "formula": seq_map[vid]["formula_breakdown"]["formula_key"] if vid in seq_map else None,
        "ai_devices": seq_map[vid]["formula_breakdown"]["ai_devices"] if vid in seq_map else None,
        "source": src, "n_snapshots": len(rs),
        "age_days_at_latest": round(age_h_latest / 24, 1),
        "views_per_day_alive": round(latest["views"] / max(age_h_latest / 24, 0.1), 1) if latest["views"] is not None else None,
        "latest_ts": latest["ts"],
    })
t72.sort(key=lambda r: r["published_at_bj"])
recent72 = [r for r in t72 if r["published_at_bj"] >= "2026-10-01"]

def analyse(rows_, name):
    V = lambda rs: [r["views"] for r in rs if r["views"] is not None]
    R = lambda rs: [r["avg_view_pct"] for r in rs if r["avg_view_pct"] is not None]
    out = {"dataset": name, "n": len(rows_)}
    # weekday
    out["by_weekday_views"] = {d: grp_stats(V([r for r in rows_ if r["publish_weekday_bj"] == d]))
                               for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
    out["by_weekday_retention"] = {d: grp_stats(R([r for r in rows_ if r["publish_weekday_bj"] == d]))
                                   for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
    out["tests"] = [
        mw(V([r for r in rows_ if r["publish_weekday_bj"] == "Fri"]), V([r for r in rows_ if r["publish_weekday_bj"] != "Fri"]), "Fri vs rest (views)"),
        mw(V([r for r in rows_ if r["publish_weekday_bj"] == "Mon"]), V([r for r in rows_ if r["publish_weekday_bj"] != "Mon"]), "Mon vs rest (views)"),
        mw(V([r for r in rows_ if r["publish_weekday_bj"] in ("Fri", "Mon")]), V([r for r in rows_ if r["publish_weekday_bj"] not in ("Fri", "Mon")]), "Fri+Mon vs rest (views)"),
        mw(V([r for r in rows_ if r["is_weekend_bj"]]), V([r for r in rows_ if not r["is_weekend_bj"]]), "weekend vs weekday (views)"),
        mw(V([r for r in rows_ if r["near_current_slot_90min"]]), V([r for r in rows_ if not r["near_current_slot_90min"]]), "near-current slot vs other times (views)"),
        mw(V([r for r in rows_ if r["hour_bucket"] == "late-night 22:00-23:59"]), V([r for r in rows_ if r["hour_bucket"] != "late-night 22:00-23:59"]), "late-night vs rest (views)"),
        mw(V([r for r in rows_ if r["hour_bucket"] == "early-morning 03:00-06:59"]), V([r for r in rows_ if r["hour_bucket"] != "early-morning 03:00-06:59"]), "early-morning vs rest (views)"),
        mw(R([r for r in rows_ if r["near_current_slot_90min"]]), R([r for r in rows_ if not r["near_current_slot_90min"]]), "near-current vs other (retention pct)"),
    ]
    out["by_hour_bucket_views"] = {b: grp_stats(V([r for r in rows_ if r["hour_bucket"] == b]))
                                   for b in sorted(set(r["hour_bucket"] for r in rows_))}
    out["near_vs_other_views"] = {"near": grp_stats(V([r for r in rows_ if r["near_current_slot_90min"]])),
                                  "other": grp_stats(V([r for r in rows_ if not r["near_current_slot_90min"]]))}
    out["near_vs_other_retention"] = {"near": grp_stats(R([r for r in rows_ if r["near_current_slot_90min"]])),
                                      "other": grp_stats(R([r for r in rows_ if not r["near_current_slot_90min"]]))}
    # Kruskal-Wallis across weekdays with n>=1 groups (report only, tiny groups)
    groups = [V([r for r in rows_ if r["publish_weekday_bj"] == d]) for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) >= 3:
        try:
            h, p = kruskal(*groups); out["kruskal_weekday_views"] = {"H": round(float(h), 3), "p": round(float(p), 4), "n_groups_ge2": len(groups)}
        except Exception as e: out["kruskal_weekday_views"] = {"error": str(e)}
    # log-views sensitivity for the headline near-vs-other test
    import math as _m
    out["near_vs_other_log10views_mw"] = mw([_m.log10(r["views"]) for r in rows_ if r["near_current_slot_90min"] and r["views"] and r["views"] > 0],
                                            [_m.log10(r["views"]) for r in rows_ if not r["near_current_slot_90min"] and r["views"] and r["views"] > 0],
                                            "near vs other (log10 views)")
    return out

res = {
    "methods": {"conversion": "UTC +8h = Beijing; weekday/hour from Beijing datetime",
                "near_current_def": "within 90 min of weekday 23:30/05:30 or weekend 22:30/04:00 (BJ), circular",
                "outcome": "lifetime/snapshot views; in-window daily views NOT used as outcome",
                "retention_source": "telemetry avg_view_pct only; sequel avg_watch_secs NOT used (89s/117s outliers on 9-11s videos)",
                "tests": "Mann-Whitney U two-sided on raw views; Kruskal-Wallis across weekdays where >=3 groups have n>=2; no multiple-testing correction claimed — all p are exploratory"},
    "s21": s21, "recent21": recent21, "old21": old21,
    "t72": t72, "recent72": recent72,
    "analysis_s21_all": analyse(s21, "S21 all (n=21, mixed eras)"),
    "analysis_recent21": analyse(recent21, "S21 recent Oct 2026 only (n=9, comparable era)"),
    "analysis_t72_all": analyse(t72, "T72 all telemetry latest (n=72, mixed eras/ages)"),
    "analysis_recent72": analyse(recent72, "T72 recent Oct 2026 only"),
    "analysis_t72_views_per_day": None,
}
# T72 views-per-day sensitivity (age-normalised)
VPD = lambda rs: [r["views_per_day_alive"] for r in rs if r["views_per_day_alive"] is not None]
res["analysis_t72_views_per_day"] = {
    "near": grp_stats(VPD([r for r in t72 if r["near_current_slot_90min"]])),
    "other": grp_stats(VPD([r for r in t72 if not r["near_current_slot_90min"]])),
    "mw_near_vs_other_vpd": mw(VPD([r for r in t72 if r["near_current_slot_90min"]]), VPD([r for r in t72 if not r["near_current_slot_90min"]]), "near vs other (views/day alive, T72)"),
    "mw_fri_vs_rest_vpd": mw(VPD([r for r in t72 if r["publish_weekday_bj"] == "Fri"]), VPD([r for r in t72 if r["publish_weekday_bj"] != "Fri"]), "Fri vs rest (views/day, T72)"),
    "mw_mon_vs_rest_vpd": mw(VPD([r for r in t72 if r["publish_weekday_bj"] == "Mon"]), VPD([r for r in t72 if r["publish_weekday_bj"] != "Mon"]), "Mon vs rest (views/day, T72)"),
}
# topic control slices
def topic_slice(rows_, label):
    return {"label": label,
            "kiosk_near": [(r["video_id"], r["views"], r["published_at_bj"]) for r in rows_ if r.get("ai_devices") and any("kiosk" in d for d in r["ai_devices"])],
            "by_formula": {f: grp_stats([r["views"] for r in rows_ if r.get("formula") == f]) for f in sorted(set(r.get("formula") for r in rows_ if r.get("formula")))}}
res["topic_control"] = {"recent21": topic_slice(recent21, "recent21"),
                        "t72": topic_slice(t72, "t72")}
json.dump(res, open(f"{OUT}/track_c_intermediate.json", "w"), ensure_ascii=False, indent=1)
# console summary
for k in ["analysis_recent21", "analysis_s21_all", "analysis_t72_all", "analysis_recent72"]:
    a = res[k]; print("=" * 80); print(a["dataset"], "n=", a["n"])
    print(" weekday views:", {d: (v["n"], v["median"], v["mean"]) for d, v in a["by_weekday_views"].items()})
    print(" hour buckets:", {b: (v["n"], v["median"]) for b, v in a["by_hour_bucket_views"].items()})
    print(" near vs other:", a["near_vs_other_views"]["near"]["n"], a["near_vs_other_views"]["near"]["median"], "vs",
          a["near_vs_other_views"]["other"]["n"], a["near_vs_other_views"]["other"]["median"])
    for t in a["tests"]: print("  ", t)
print("T72 vpd:", res["analysis_t72_views_per_day"])
print("recent21 rows:")
for r in recent21: print(" ", r["video_id"], r["published_at_bj"], r["publish_weekday_bj"], r["hour_bucket"], "near" if r["near_current_slot_90min"] else "OTHER", r["views"], r["avg_view_pct"], r["formula"], r["ai_devices"])
print("recent72 n=", len(recent72), "near=", sum(r["near_current_slot_90min"] for r in recent72))
print("t72 near=", sum(r["near_current_slot_90min"] for r in t72), "of", len(t72))
print("t72 weekday counts:", {d: sum(1 for r in t72 if r['publish_weekday_bj']==d) for d in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]})
