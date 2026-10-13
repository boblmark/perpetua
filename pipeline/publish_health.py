#!/usr/bin/env python3
"""publish_health.py — 发布健康常量监控（D20261011-005，2026-10-11）。

三项管线健康常量（2026-10-11 四脑架构议会，Ask Studio 传感器）：
1. MAX_INTER_PUBLISH_LATENCY_HOURS = 18：距上次发布超过 18h → CRITICAL（空转）
2. DAILY_PUBLISH_COUNT_MIN = 2：过去 24h 发布数 < 2 → WARNING
3. SCHEDULE_DEVIATION_MINUTES = 15：排期 vs 实际发布偏差 > 15min → WARNING

数据源：YouTube Data API（youtube/yt.py recent_videos）+ 本地 privateq 排期记录。
告警：经 inbox 网关写 notices + 日志。设计给 cron 每 30 分钟调一次。
API 熔断（配额耗尽）时静默跳过（不误报），由 API 熔断转 Ask Studio 机制另行处理。
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

MAX_INTER_PUBLISH_LATENCY_HOURS = 18
DAILY_PUBLISH_COUNT_MIN = 2
SCHEDULE_DEVIATION_MINUTES = 15

HEALTH_VERSION = "1.0.0"


def _parse(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def check():
    """返回 {"ok": bool, "alerts": [...], "metrics": {...}}。"""
    from yt import recent_videos
    alerts, metrics = [], {}
    try:
        videos = recent_videos(max_n=20)
    except Exception as e:
        # API 熔断：静默跳过，不误报（熔断转 Ask Studio 另有机制）
        return {"ok": True, "skipped": f"api_unavailable: {e}",
                "alerts": [], "metrics": {}}
    now = datetime.now(timezone.utc)
    pubs = sorted(
        [(_parse(v.get("published")), v) for v in videos if _parse(v.get("published"))],
        key=lambda x: x[0], reverse=True)
    if not pubs:
        alerts.append({"level": "CRITICAL", "rule": "inter_publish_latency",
                       "msg": "频道无任何可读发布时间，无法计算空转"})
        return {"ok": False, "alerts": alerts, "metrics": metrics}
    last_pub, last_v = pubs[0]
    gap_h = (now - last_pub).total_seconds() / 3600
    metrics["hours_since_last_publish"] = round(gap_h, 1)
    metrics["last_video"] = {"id": last_v.get("id"),
                             "title": (last_v.get("title") or "")[:60],
                             "published": last_v.get("published")}
    if gap_h > MAX_INTER_PUBLISH_LATENCY_HOURS:
        alerts.append({"level": "CRITICAL", "rule": "inter_publish_latency",
                       "msg": f"距上次发布 {gap_h:.1f}h，超过 {MAX_INTER_PUBLISH_LATENCY_HOURS}h 空转线"})
    day_ago = now - timedelta(hours=24)
    n24 = sum(1 for p, _ in pubs if p >= day_ago)
    metrics["publishes_last_24h"] = n24
    if n24 < DAILY_PUBLISH_COUNT_MIN:
        alerts.append({"level": "WARNING", "rule": "daily_publish_count",
                       "msg": f"过去 24h 仅发布 {n24} 条，低于 {DAILY_PUBLISH_COUNT_MIN} 条线"})
    # 排期偏差：拿 privateq 的 scheduled_at 对最近 48h 发布的视频。
    # 只取 status=published 的行——waiting 的（如 EP1）是 private 预传，
    # 它的"发布时间"是上传时间，跟未来的翻公开排期比没有意义。
    try:
        import queue_db
        sched = {}
        for it in queue_db.privateq_load():
            vid = it.get("video_id")
            sa = _parse(it.get("scheduled_at"))
            if vid and sa and it.get("status") == "published":
                sched[vid] = sa
        worst = 0
        for p, v in pubs:
            if (now - p).total_seconds() > 48 * 3600:
                continue
            sa = sched.get(v.get("id"))
            if sa:
                dev = abs((p - sa).total_seconds()) / 60
                worst = max(worst, dev)
        metrics["max_schedule_deviation_min_48h"] = round(worst, 1)
        if worst > SCHEDULE_DEVIATION_MINUTES:
            alerts.append({"level": "WARNING", "rule": "schedule_deviation",
                           "msg": f"排期偏差最大 {worst:.0f}min，超过 {SCHEDULE_DEVIATION_MINUTES}min 线"})
    except Exception as e:
        metrics["schedule_check"] = f"skipped: {e}"
    return {"ok": not alerts, "alerts": alerts, "metrics": metrics}


def main():
    import inbox
    r = check()
    if r.get("skipped"):
        print("publish_health: skipped -", r["skipped"])
        return 0
    print(f"publish_health: ok={r['ok']} metrics={r['metrics']}")
    for a in r["alerts"]:
        print(f"  [{a['level']}] {a['rule']}: {a['msg']}")
    if not r["ok"]:
        # 三级响应：诊断 → 自动修 → 升级（2026-10-11 用户亲令"必须补全"）
        try:
            import publish_healer
            rep = publish_healer.heal(r["alerts"])
            d = rep["diagnosis"]
            print(f"  healer: bottleneck={d['bottleneck']} "
                  f"actions={[x['action']+':'+x['result'] for x in rep['actions']]} "
                  f"escalated={rep['escalated']}")
        except Exception as e:
            print(f"  healer 异常（降级为纯告警）: {e}")
            try:
                inbox.append_notice({
                    "type": "publish_health",
                    "level": "CRITICAL" if any(x["level"] == "CRITICAL" for x in r["alerts"]) else "WARNING",
                    "alerts": r["alerts"],
                    "metrics": r["metrics"],
                    "healer": f"failed: {e}",
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e2:
                print(f"  inbox 写入失败: {e2}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
