#!/usr/bin/env python3
"""雷达指标计算（D20261017-002 / 规格 v1 D20261017-003）：
从快照差分算日增速、按"同龄"第 N 天算 outlier、标题文本 diff、缩略图感知 hash 变更。

纯只读分析：结果写入 radar.db 的 metrics 表 + 每日 JSON 报告（供人工与评审管线参考）。
永不写回选题队列、不触发快车道（D20261016-007 冻结期至 2026-12-10）。

outlier 定义（红队 KILL 规则 4 修订，规格 v1）：
  outlier = 视频第 N 天累计播放 ÷ 基线视频同为第 N 天时的累计播放中位数
  - 同格式（short/long）才比，绝不混算
  - N = 视频当前年龄（天，向下取整），N≥3
  - <48h 新视频不进基线、不算 outlier
  - 基线中位数为 0 → 记 UNDEFINED（不是 0 也不是无穷大）
  - 基线 <10 条 → PROVISIONAL 并显示样本数；<6 条 → INSUFFICIENT_BASELINE
  - 基线 = 同频道、同格式、90 天内上传（目标 15–30 条，低频博主按实际发片量标注）
  - 365 天 cutoff 只约束计算（老视频记 EXCLUDED_STALE），历史数据保留

用法：python3 radar_metrics.py
"""
import json
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from radar_lib import (
    connect, append_run_log, ts_str, today_str, REPORTS_DIR, SHANGHAI,
    hash_distance, THUMB_HASH_DISTANCE_THRESHOLD,
    EXCLUDE_AGE_HOURS, OUTLIER_MIN_AGE_DAYS, BASELINE_WINDOW_DAYS,
    BASELINE_MIN, PROVISIONAL_BELOW, HISTORY_CUTOFF_DAYS,
)


def _parse_dt(s):
    try:
        dt = datetime.fromisoformat(s[:19])
    except Exception:
        return None
    # 快照里的 published_at 是 naive 时间，一律视为 Asia/Shanghai，避免与 aware 的 now 相减报错
    return dt if dt.tzinfo else dt.replace(tzinfo=SHANGHAI)


def latest_two_snapshots(con, platform, video_id):
    rows = con.execute(
        "SELECT snapshot_at, view_count, title, thumbnail_hash, thumb_phash,"
        " thumbnail_url FROM video_snapshots"
        " WHERE platform=? AND video_id=? ORDER BY snapshot_at DESC", (platform, video_id)).fetchall()
    if len(rows) < 2:
        return None, None
    first, prev = rows[0], None
    for r in rows[1:]:
        if r["snapshot_at"][:10] != first["snapshot_at"][:10]:
            prev = r
            break
    return first, prev


def video_published_at(con, platform, video_id):
    row = con.execute(
        "SELECT MIN(published_at) AS p FROM video_snapshots"
        " WHERE platform=? AND video_id=? AND published_at IS NOT NULL",
        (platform, video_id)).fetchone()
    return _parse_dt(row["p"]) if row and row["p"] else None


def video_format_of(con, platform, video_id):
    row = con.execute(
        "SELECT format FROM video_snapshots WHERE platform=? AND video_id=?"
        " AND format IS NOT NULL ORDER BY snapshot_at DESC LIMIT 1",
        (platform, video_id)).fetchone()
    return row["format"] if row and row["format"] else "unknown"


def snapshots_by_age(con, platform, video_id):
    """[(age_days_float, view_count)]，仅含 published_at 已知的快照，按时间升序。"""
    rows = con.execute(
        "SELECT snapshot_at, view_count, published_at FROM video_snapshots"
        " WHERE platform=? AND video_id=? AND published_at IS NOT NULL"
        " AND view_count IS NOT NULL ORDER BY snapshot_at",
        (platform, video_id)).fetchall()
    out = []
    for r in rows:
        pub, snap = _parse_dt(r["published_at"]), _parse_dt(r["snapshot_at"])
        if not pub or not snap:
            continue
        age = (snap - pub).total_seconds() / 86400
        if age >= 0:
            out.append((age, r["view_count"]))
    return out


def views_at_age(ages, target_n, tol=3.0):
    """在年龄序列中找到最接近第 N 天的累计播放；超出容差返回 None。"""
    best = None
    for age, views in ages:
        if best is None or abs(age - target_n) < abs(best[0] - target_n):
            best = (age, views)
    if best is None or abs(best[0] - target_n) > tol:
        return None
    return best[1]


def age_matched_outlier(con, platform, channel_id, video_id, fmt, n_days):
    """同龄 outlier：返回 (score, status, sample_n)。"""
    cutoff = datetime.now(SHANGHAI).date()
    rows = con.execute(
        """SELECT DISTINCT t.video_id FROM tracked_videos t
           JOIN video_snapshots s ON s.platform=t.platform AND s.video_id=t.video_id
           WHERE t.platform=? AND t.channel_id=? AND t.video_id != ?
             AND COALESCE(t.archived,0)=0 AND s.format=?
             AND s.published_at IS NOT NULL
             AND date(s.published_at) >= date('now','-{} days')""".format(BASELINE_WINDOW_DAYS),
        (platform, channel_id, video_id, fmt)).fetchall()
    vals = []
    for r in rows:
        ages = snapshots_by_age(con, platform, r["video_id"])
        v = views_at_age(ages, n_days)
        if v is not None:
            vals.append(v)
    n = len(vals)
    if n < BASELINE_MIN:
        return None, "INSUFFICIENT_BASELINE", n
    med = statistics.median(vals)
    if med == 0:
        return None, "UNDEFINED", n
    cur = con.execute(
        "SELECT view_count FROM video_snapshots WHERE platform=? AND video_id=?"
        " AND view_count IS NOT NULL ORDER BY snapshot_at DESC LIMIT 1",
        (platform, video_id)).fetchone()
    if not cur or not cur["view_count"]:
        return None, "INSUFFICIENT_BASELINE", n
    score = cur["view_count"] / med
    status = "PROVISIONAL" if n < PROVISIONAL_BELOW else "OK"
    return round(score, 2), status, n


def legacy_median_outlier(con, platform, channel_id, video_id):
    """无 published_at/格式数据的降级口径：最新播放 ÷ 同频道中位数，恒标 LEGACY。"""
    rows = con.execute(
        """SELECT s.view_count FROM video_snapshots s
           JOIN (SELECT platform, video_id, MAX(snapshot_at) AS m
                 FROM video_snapshots WHERE platform=? GROUP BY platform, video_id) latest
             ON s.platform=latest.platform AND s.video_id=latest.video_id
                AND s.snapshot_at=latest.m
           JOIN tracked_videos t ON t.platform=s.platform AND t.video_id=s.video_id
           WHERE s.platform=? AND t.channel_id=? AND s.view_count IS NOT NULL
             AND COALESCE(t.archived,0)=0""",
        (platform, platform, channel_id)).fetchall()
    vals = [r["view_count"] for r in rows if r["view_count"]]
    cur = con.execute(
        "SELECT view_count FROM video_snapshots WHERE platform=? AND video_id=?"
        " ORDER BY snapshot_at DESC LIMIT 1", (platform, video_id)).fetchone()
    if len(vals) < 3 or not cur or not cur["view_count"]:
        return None, "INSUFFICIENT_BASELINE", len(vals)
    med = statistics.median(vals)
    if med == 0:
        return None, "UNDEFINED", len(vals)
    return round(cur["view_count"] / med, 2), "LEGACY_NO_FORMAT", len(vals)


def thumbnail_changed(cur, prev):
    """红队 WEAKEN 修订：以图像 hash 距离>阈值为准；URL 变化/CDN 变体不算。

    优先 dHash 感知哈希（缺失时回退 sha256 精确比较，再缺失则不判变）。
    """
    ph1, ph2 = cur["thumb_phash"], prev["thumb_phash"]
    if ph1 and ph2:
        return 1 if hash_distance(ph1, ph2) > THUMB_HASH_DISTANCE_THRESHOLD else 0
    h1, h2 = cur["thumbnail_hash"], prev["thumbnail_hash"]
    if h1 and h2:
        return 1 if h1 != h2 else 0
    return 0


def main():
    con = connect()
    vids = con.execute(
        "SELECT platform, video_id, channel_id, label FROM tracked_videos"
        " WHERE COALESCE(archived,0)=0").fetchall()
    date = today_str()
    now = datetime.now(SHANGHAI)
    rows_out, changes = [], []
    for v in vids:
        p, vid, ch, label = v["platform"], v["video_id"], v["channel_id"], v["label"]
        cur, prev = latest_two_snapshots(con, p, vid)
        if not cur or not prev:
            continue
        # 365 天 cutoff 只约束计算：老视频保留历史上下文，增速/outlier 跳过
        pub = video_published_at(con, p, vid)
        age_days = (now - pub).total_seconds() / 86400 if pub else None
        age_hours = (now - pub).total_seconds() / 3600 if pub else None

        if age_days is not None and age_days > HISTORY_CUTOFF_DAYS:
            velocity = None
        else:
            d1, d0 = _parse_dt(cur["snapshot_at"]), _parse_dt(prev["snapshot_at"])
            days = max((d1 - d0).total_seconds() / 86400, 0.5) if d1 and d0 else 0.5
            velocity = round(((cur["view_count"] or 0) - (prev["view_count"] or 0)) / days, 1)

        # outlier（同龄定义）
        if age_hours is not None and age_hours < EXCLUDE_AGE_HOURS:
            outlier, status, sample_n, age_n = None, "EXCLUDED_NEW", 0, int(age_days or 0)
        elif age_days is not None and age_days > HISTORY_CUTOFF_DAYS:
            outlier, status, sample_n, age_n = None, "EXCLUDED_STALE", 0, int(age_days)
        elif pub is None:
            outlier, status, sample_n = legacy_median_outlier(con, p, ch, vid)
            age_n = None
        else:
            fmt = video_format_of(con, p, vid)
            n = int(age_days)
            if n < OUTLIER_MIN_AGE_DAYS or fmt == "unknown":
                outlier, status, sample_n = legacy_median_outlier(con, p, ch, vid)
                age_n = n
            else:
                outlier, status, sample_n = age_matched_outlier(con, p, ch, vid, fmt, n)
                age_n = n

        title_chg = 1 if (cur["title"] or "").strip() != (prev["title"] or "").strip() else 0
        thumb_chg = thumbnail_changed(cur, prev)
        con.execute(
            "INSERT INTO metrics(platform, video_id, metric_date, view_velocity,"
            " outlier_score, outlier_status, outlier_sample_n, outlier_age_days,"
            " title_changed, thumbnail_changed, computed_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(platform, video_id, metric_date) DO UPDATE SET"
            " view_velocity=excluded.view_velocity, outlier_score=excluded.outlier_score,"
            " outlier_status=excluded.outlier_status,"
            " outlier_sample_n=excluded.outlier_sample_n,"
            " outlier_age_days=excluded.outlier_age_days,"
            " title_changed=excluded.title_changed,"
            " thumbnail_changed=excluded.thumbnail_changed,"
            " computed_at=excluded.computed_at",
            (p, vid, date, velocity, outlier, status, sample_n, age_n,
             title_chg, thumb_chg, ts_str()))
        rec = {"platform": p, "video_id": vid, "label": label, "title": cur["title"],
               "views": cur["view_count"], "velocity_per_day": velocity,
               "outlier_score": outlier, "outlier_status": status,
               "outlier_sample_n": sample_n, "outlier_age_days": age_n}
        rows_out.append(rec)
        if title_chg or thumb_chg:
            changes.append({**rec, "title_changed": bool(title_chg),
                            "thumbnail_changed": bool(thumb_chg)})
    con.commit()
    rows_out.sort(key=lambda r: r["velocity_per_day"] or 0, reverse=True)
    confirmed = [r for r in rows_out
                 if r["outlier_status"] in ("OK", "PROVISIONAL") and r["outlier_score"]]
    report = {"date": date, "computed_at": ts_str(), "n_videos": len(rows_out),
              "top_velocity": rows_out[:20],
              "top_outliers": sorted(confirmed,
                                     key=lambda r: r["outlier_score"], reverse=True)[:20],
              "title_thumbnail_changes": changes}
    os.makedirs(REPORTS_DIR, exist_ok=True)
    rp = os.path.join(REPORTS_DIR, f"metrics-{date}.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    con.close()
    line = (f"radar_metrics done videos={len(rows_out)} changes={len(changes)} "
            f"report={os.path.basename(rp)}")
    append_run_log("radar_metrics", line)
    print(line)


if __name__ == "__main__":
    main()
