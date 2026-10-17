#!/usr/bin/env python3
"""竞品池清退检查（规格 v1 D20261017-003，红队 KILL 规则 9 修订）。

每月检查只做"候选标记"：把 60 天断更 / 连续平庸 / 挑战者到期 的频道写入
prune_candidates 表（status=pending）+ reports/prune-YYYY-MM.json。
移除必须人工确认（控制台一键，暂无控制台入口时在种子文件里删掉对应条目）。

唯一自动移除路径：频道被删/停用/转私密（在 youtube_snapshot.py 里检测到
channels.list 返回空时自动归档 archived=1）。
被清退频道历史数据归档但保持可查；恢复 = 重新加回种子文件（archived 自动清零）。

用法：python3 radar_prune.py [--apply-confirm channel_id]  # 人工确认移除时用
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from radar_lib import (
    connect, append_run_log, ts_str, REPORTS_DIR, SHANGHAI,
    normalize_competitors, TIERS, POOL_MAX, PRUNE_DORMANCY_DAYS,
    CHALLENGER_MAX, CHALLENGER_DAYS,
)

COMPETITOR_FILES = {
    "youtube": os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "competitors_youtube.json"),
    "bilibili": os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "competitors_bilibili.json"),
}


def _parse_dt(s):
    try:
        dt = datetime.fromisoformat(s[:19])
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=SHANGHAI)


def channel_last_activity(con, platform, channel_id):
    """频道最近活动：旗下视频最新 published_at（无则回退最新 snapshot_at）。"""
    row = con.execute(
        "SELECT MAX(published_at) AS p, MAX(snapshot_at) AS s FROM video_snapshots"
        " WHERE platform=? AND video_id IN"
        " (SELECT video_id FROM tracked_videos WHERE platform=? AND channel_id=?"
        "  AND label='competitor' AND COALESCE(archived,0)=0)",
        (platform, platform, channel_id)).fetchone()
    p = _parse_dt(row["p"]) if row and row["p"] else None
    s = _parse_dt(row["s"]) if row and row["s"] else None
    return p or s


def channel_signals(con, platform, channel_id, window_days=90):
    """返回 (velocity_signals, confirmed_outliers)：近 window 天的增速信号数和确认 outlier 数。"""
    rows = con.execute(
        """SELECT m.view_velocity, m.outlier_score, m.outlier_status
           FROM metrics m JOIN tracked_videos t
             ON m.platform=t.platform AND m.video_id=t.video_id
           WHERE m.platform=? AND t.channel_id=? AND t.label='competitor'
             AND COALESCE(t.archived,0)=0
             AND date(m.metric_date) >= date('now','-{} days')""".format(window_days),
        (platform, channel_id)).fetchall()
    vels = [r["view_velocity"] for r in rows if r["view_velocity"]]
    med_v = sorted(vels)[len(vels) // 2] if vels else 0
    velocity_signals = sum(1 for r in rows
                           if r["view_velocity"] and r["view_velocity"] > max(med_v, 0))
    confirmed = sum(1 for r in rows
                    if r["outlier_status"] == "OK" and (r["outlier_score"] or 0) >= 2.0)
    return velocity_signals, confirmed


def flag(con, platform, channel_id, reason, detail):
    con.execute(
        "INSERT INTO prune_candidates(platform, channel_id, reason, detail, flagged_at, status)"
        " VALUES(?,?,?,?,?,'pending')"
        " ON CONFLICT(platform, channel_id, reason) DO UPDATE SET"
        " detail=excluded.detail, flagged_at=excluded.flagged_at,"
        " status=CASE WHEN prune_candidates.status='pending' THEN 'pending'"
        " ELSE prune_candidates.status END",
        (platform, channel_id, reason, detail, ts_str()))


def load_seed_channels(platform):
    path = COMPETITOR_FILES[platform]
    if not os.path.exists(path):
        return []
    data = json.load(open(path, encoding="utf-8"))
    key = "channels" if platform == "youtube" else "mids"
    raw = data.get(key) or []
    out = []
    for e in normalize_competitors(raw):
        ch_id = e["channel_id"]
        out.append({"channel_id": ch_id, "tier": e["tier"], "added_at": e["added_at"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-confirm", default=None,
                    help="人工确认移除：频道 ID（需与 prune_candidates 的 pending 记录对应）")
    args = ap.parse_args()
    con = connect()
    now = datetime.now(SHANGHAI)

    if args.apply_confirm:
        # 人工确认移除：只打标 archived，不删历史（恢复=重新加回种子）
        row = con.execute(
            "SELECT platform, channel_id FROM prune_candidates"
            " WHERE channel_id=? AND status='pending' LIMIT 1",
            (args.apply_confirm,)).fetchone()
        if not row:
            print(f"no pending prune candidate for {args.apply_confirm}")
            return
        con.execute("UPDATE tracked_videos SET archived=1, archived_reason='human_confirmed'"
                    " WHERE platform=? AND channel_id=?", (row["platform"], row["channel_id"]))
        con.execute("UPDATE prune_candidates SET status='confirmed', decided_at=?"
                    " WHERE channel_id=? AND status='pending'", (ts_str(), args.apply_confirm))
        con.commit()
        print(f"archived {args.apply_confirm} (history retained, reactivate by re-adding to seed file)")
        append_run_log("radar_prune", f"human confirmed archive channel={args.apply_confirm}")
        return

    flagged = []
    tier_counts = {"tier1": 0, "tier2": 0, "tier3": 0, "challenger": 0, "unassigned": 0}
    for platform in ("youtube", "bilibili"):
        for entry in load_seed_channels(platform):
            ch_id, tier = entry["channel_id"], entry["tier"]
            tier_counts[tier if tier in tier_counts else "unassigned"] += 1
            last = channel_last_activity(con, platform, ch_id)
            if last and (now - last).days > PRUNE_DORMANCY_DAYS:
                detail = f"最近活动 {(now - last).days} 天前（> {PRUNE_DORMANCY_DAYS} 天断更线）"
                flag(con, platform, ch_id, "dormant_60d", detail)
                flagged.append({"platform": platform, "channel_id": ch_id,
                                "reason": "dormant_60d", "detail": detail})
                continue
            vs, co = channel_signals(con, platform, ch_id)
            if vs + co == 0:
                n = con.execute(
                    "SELECT COUNT(*) c FROM tracked_videos WHERE platform=? AND channel_id=?"
                    " AND label='competitor' AND COALESCE(archived,0)=0",
                    (platform, ch_id)).fetchone()["c"]
                if n >= 3:
                    detail = f"近 90 天 0 增速信号、0 确认 outlier（跟踪 {n} 条视频）"
                    flag(con, platform, ch_id, "flatline_90d", detail)
                    flagged.append({"platform": platform, "channel_id": ch_id,
                                    "reason": "flatline_90d", "detail": detail})
            # 挑战者 30 天轮换：留用需 ≥2 增速信号 或 1 确认 outlier
            if tier == "challenger":
                added = _parse_dt(entry["added_at"]) if entry["added_at"] else None
                age = (now - added).days if added else 999
                if age >= CHALLENGER_DAYS and not (vs >= 2 or co >= 1):
                    detail = (f"挑战者已满 {age} 天（轮换期 {CHALLENGER_DAYS} 天），"
                              f"增速信号 {vs}、确认 outlier {co}，未达留用线（≥2 增速或 1 outlier）")
                    flag(con, platform, ch_id, "challenger_expired", detail)
                    flagged.append({"platform": platform, "channel_id": ch_id,
                                    "reason": "challenger_expired", "detail": detail})

    con.commit()
    pending = con.execute(
        "SELECT platform, channel_id, reason, detail, flagged_at FROM prune_candidates"
        " WHERE status='pending' ORDER BY flagged_at DESC").fetchall()
    report = {
        "checked_at": ts_str(),
        "pool_max": POOL_MAX,
        "tier_spec": {k: {"count": v["count"], "subs": v["subs"]} for k, v in TIERS.items()},
        "tier_counts": tier_counts,
        "tier_note": "档位数字是筛选起点不是硬配额，宁可空位不降标准；挑战者名额 0–2 可选",
        "newly_flagged": flagged,
        "pending_all": [dict(r) for r in pending],
        "how_to_decide": "人工确认后执行：python3 radar_prune.py --apply-confirm <channel_id>。"
                         "移除只打标 archived=1，历史快照保留可查；恢复=重新加回种子文件。"
                         "唯一自动移除：频道被删/停用/转私密（采集时自动归档）。",
    }
    os.makedirs(REPORTS_DIR, exist_ok=True)
    rp = os.path.join(REPORTS_DIR, f"prune-{now.strftime('%Y-%m')}.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    con.close()
    line = (f"radar_prune done newly_flagged={len(flagged)} pending_total={len(pending)} "
            f"report={os.path.basename(rp)}")
    append_run_log("radar_prune", line)
    print(line)


if __name__ == "__main__":
    main()
