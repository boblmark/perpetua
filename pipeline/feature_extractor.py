#!/usr/bin/env python3
"""
D5 特征提取（2026-10-08 四脑路线图 Priority #3）。

输入：retention_telemetry.jsonl（D4 采集）
逻辑：以 avg_view_pct 中位数为界，比较高于/低于中位数的视频在制作特征
      上的分布差异，输出与高留存最相关的 Top-3 特征。
输出：dynamic_constraints.json（D6 生成器读取）
"""
import json, re
from pathlib import Path
from collections import defaultdict

BASE = Path("/home/hatch/data/perpetua")
TEL = BASE / "retention_telemetry.jsonl"
OUT = BASE / "dynamic_constraints.json"


def extract_features(rec):
    """从一条遥测记录提取可比特征。"""
    f = {}
    title = rec.get("title", "")
    pipe = rec.get("pipeline", {}) or {}
    tags = [t.lower() for t in rec.get("tags", [])]

    # 设备类型（从标题/标签推断）
    tl = title.lower()
    for dev in ["doorbell", "drive-thru", "drivethru", "self-checkout", "selfcheckout",
                "vacuum", "parking meter", "speaker", "fridge", "thermostat",
                "gas pump", "car", "tesla", "dog"]:
        if dev in tl or dev.replace(" ", "") in "".join(tags):
            f["device"] = dev
            break

    # 标题公式元素
    f["has_emoji"] = bool(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", title))
    f["has_karen"] = "karen" in tl
    f["hashtag_n"] = len(re.findall(r"#\w+", title))
    f["title_len"] = len(title)
    f["caps_ratio"] = sum(1 for c in title if c.isupper()) / max(len(title), 1)

    # 管线特征
    f["review_score"] = pipe.get("review_score", 0) or 0
    topic = str(pipe.get("topic", "")).lower()
    f["topic"] = topic[:40] if topic else "unknown"
    return f


def main():
    recs = []
    if TEL.exists():
        for line in TEL.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                # Analytics 无数据的视频视为 0%（0 播放或无观看）
                if r.get("avg_view_pct") is None:
                    r["avg_view_pct"] = 0.0
                recs.append(r)
            except Exception:
                pass
    if len(recs) < 6:
        print(f"not enough data ({len(recs)}), skipping")
        return

    # 去重：同一 video_id 取最新一条
    latest = {}
    for r in recs:
        latest[r["video_id"]] = r
    recs = list(latest.values())

    pcts = sorted(r["avg_view_pct"] for r in recs)
    # 0 播放视频太多，中位数无意义：用 >10% 作为"有效观看"阈值
    THRESH = 10.0
    hi = [r for r in recs if r["avg_view_pct"] > THRESH]
    lo = [r for r in recs if r["avg_view_pct"] <= THRESH]
    print(f"videos: {len(recs)}, threshold: {THRESH}%, hi: {len(hi)}, lo: {len(lo)}")
    if len(hi) < 2 or len(lo) < 2:
        print("not enough contrast, skipping")
        return

    feats = [(r, extract_features(r)) for r in recs]
    scored = []

    # 数值特征：比较 hi/lo 均值差异
    for key in ["hashtag_n", "title_len", "caps_ratio", "review_score"]:
        hv = [f[key] for _, f in feats if f in [x[1] for x in
              [(r, extract_features(r)) for r in hi]]]
        lv = [f[key] for _, f in feats if f in [x[1] for x in
              [(r, extract_features(r)) for r in lo]]]
        # 简化：直接按原始分组算
        h_vals = [extract_features(r)[key] for r in hi]
        l_vals = [extract_features(r)[key] for r in lo]
        hm = sum(h_vals) / max(len(h_vals), 1)
        lm = sum(l_vals) / max(len(l_vals), 1)
        diff = hm - lm
        scored.append((abs(diff), key, hm, lm, diff))

    # 类别特征：device 在 hi 组的富集度
    dev_hi = defaultdict(int)
    dev_all = defaultdict(int)
    for r in recs:
        d = extract_features(r).get("device", "unknown")
        dev_all[d] += 1
        if r["avg_view_pct"] > THRESH:
            dev_hi[d] += 1
    for d, n in dev_all.items():
        if n >= 2:
            enrich = dev_hi[d] / n - len(hi) / len(recs)
            scored.append((abs(enrich), f"device:{d}",
                           dev_hi[d] / n, len(hi) / len(recs), enrich))

    scored.sort(reverse=True)
    top3 = []
    for _, key, hm, lm, diff in scored[:3]:
        direction = "HIGHER in winners" if diff > 0 else "LOWER in winners"
        top3.append({"feature": key, "winners_avg": round(hm, 3),
                     "losers_avg": round(lm, 3), "direction": direction})

    out = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "n_videos": len(recs),
        "threshold_pct": THRESH,
        "n_winners": len(hi),
        "top_features": top3,
        "directives": [
            f"BOOST videos with {t['feature']} {t['direction'].lower()} "
            f"(winners {t['winners_avg']} vs losers {t['losers_avg']})"
            for t in top3
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


def check_phase_shift(metrics):
    """四脑会诊 2026-10-08 Section 3：阶段切换触发器。

    当最近 5 条视频连续 >60% viewed-vs-swiped 且中位数 >500 播放时，
    返回 True → 启用完整多模态 ECR 预测（Phase 2）。

    metrics: list of dicts, keys: 'viewed_vs_swiped_ratio' (0-1), 'view_count'.

    诚实注：YouTube API 不直接给 viewed-vs-swiped 率。当前实现中该字段
    缺失时按 0 处理（= 永不触发），直到我们有可靠的数据源
    （如从 Analytics 估算或人工录入）。不要伪造该指标。
    """
    import statistics
    REQUIRED = 5
    if len(metrics) < REQUIRED:
        return False
    recent = metrics[-REQUIRED:]
    ok_swipe = all(v.get("viewed_vs_swiped_ratio", 0.0) > 0.60 for v in recent)
    med_views = statistics.median(v.get("view_count", 0) for v in recent)
    return bool(ok_swipe and med_views > 500)


if __name__ == "__main__":
    main()
