#!/usr/bin/env python3
"""publish_health.py — 发布健康常量监控（D20261011-005，2026-10-11）。

三项管线健康常量（2026-10-11 四脑架构议会，Ask Studio 传感器）：
1. MAX_INTER_PUBLISH_LATENCY_HOURS = 18：距上次发布超过 18h → CRITICAL（空转）
2. DAILY_PUBLISH_COUNT_MIN = 2：过去 24h 发布数 < 2 → WARNING
3. SCHEDULE_DEVIATION_MINUTES = 15：排期 vs 实际发布偏差 > 15min → WARNING

数据源：YouTube Data API（youtube/yt.py recent_videos）+ 本地 privateq 排期记录。
告警：经 inbox 网关写 notices + 日志。设计给 cron 每 30 分钟调一次。
API 熔断（配额耗尽）时不再报 ok=True（C10，2026-10-28）：check() 返回
独立状态 unknown（既非 ok 也非 alert），main() 退出码 2、每轮写 runlog、
并经 inbox 触发一次浏览器 Studio 口径备用检查（用户 2026-10-25 指令；
浏览器动作本身由读到 urgent 的主 agent 执行，本模块只发触发器）。
C11（2026-10-28）：发布口径拆分——publishes_last_24h 只计
privacyStatus==public（预传不再算发布）；排期偏差无匹配时记
unmeasured 而不再以 0 充数。浏览器上传写回 privateq 暂无自动
代码路径（人工浏览器动作），unmeasured 计数即为该缺口的可观测形态。
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

# C10：runlog 路径（W1 tripwire 的数据源；行格式须与 anomaly_watchdog
# 的解析 regex 一致：行首日期 + `publishes_last_24h:<数字>` 冒号格式，
# unknown 轮次写 `publishes_last_24h:unknown` 使 W1 忽略该行、不误判）。
RUNLOG_PATH = "/home/hatch/data/perpetua/publish_health_runlog.txt"


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
        # C10（2026-10-28）：API 不可用不再是 ok=True（检查器自盲，
        # 配额耗尽期间全程报绿）。改为独立 unknown 状态：既非 ok 也非
        # alert；main() 据此退出码 2、写 runlog、发 inbox 触发器。
        return {"ok": None, "status": "unknown",
                "skipped": f"api_unavailable: {e}",
                "alerts": [], "metrics": {}}
    now = datetime.now(timezone.utc)
    pubs = sorted(
        [(_parse(v.get("published")), v) for v in videos if _parse(v.get("published"))],
        key=lambda x: x[0], reverse=True)
    if not pubs:
        alerts.append({"level": "CRITICAL", "rule": "inter_publish_latency",
                       "msg": "频道无任何可读发布时间，无法计算空转"})
        return {"ok": False, "alerts": alerts, "metrics": metrics}
    # C11（2026-10-28）：铁律口径拆分——预传（private 上传）不再算发布。
    # 只有 privacyStatus==public 才进“发布”口径；private/unlisted（待翻公开
    # 的预传、Studio 浏览器路排期中）只计 preuploads 补充数。缺 privacyStatus
    # 的旧数据 fail-closed：不计入公开数（宁可少算，不虚报发布）。
    # 诚实限定：公开时间的 publishedAt 对 private→public 翻转视频未必等于
    # 翻转时刻（以 privacyStatus 首次变 public 的快照为准更精确，见 foundation
    # 小时快照）；本处以 privacyStatus 为门、publishedAt 为时间，是单次巡检
    # 可用的最优口径，不宣称等于精确翻公开时刻。
    pubs_public = [(p, v) for p, v in pubs
                   if v.get("privacyStatus") == "public"]
    pubs_pre = [(p, v) for p, v in pubs
                if v.get("privacyStatus") != "public"]
    day_ago = now - timedelta(hours=24)
    n24_public = sum(1 for p, _ in pubs_public if p >= day_ago)
    n24_pre = sum(1 for p, _ in pubs_pre if p >= day_ago)
    metrics["publishes_last_24h"] = n24_public
    metrics["publishes_last_24h_public"] = n24_public
    metrics["preuploads_last_24h"] = n24_pre
    if pubs_public:
        last_pub, last_v = pubs_public[0]
        gap_h = (now - last_pub).total_seconds() / 3600
        metrics["hours_since_last_publish"] = round(gap_h, 1)
        metrics["last_video"] = {"id": last_v.get("id"),
                                 "title": (last_v.get("title") or "")[:60],
                                 "published": last_v.get("published")}
        if gap_h > MAX_INTER_PUBLISH_LATENCY_HOURS:
            alerts.append({"level": "CRITICAL", "rule": "inter_publish_latency",
                           "msg": f"距上次公开 {gap_h:.1f}h，超过 {MAX_INTER_PUBLISH_LATENCY_HOURS}h 空转线"})
    else:
        metrics["hours_since_last_publish"] = None
        metrics["last_video"] = None
        alerts.append({"level": "WARNING", "rule": "inter_publish_latency",
                       "msg": "窗口内无公开视频，无法确认上次公开时间（预传不计入公开）"})
    if n24_public < DAILY_PUBLISH_COUNT_MIN:
        alerts.append({"level": "WARNING", "rule": "daily_publish_count",
                       "msg": f"过去 24h 仅公开 {n24_public} 条（预传 {n24_pre} 条不计），"
                              f"低于 {DAILY_PUBLISH_COUNT_MIN} 条线"})
    # 排期偏差：拿 privateq 的 scheduled_at 对最近 48h 公开的视频。
    # 只取 status=published 的行——waiting 的（如 EP1）是 private 预传，
    # 它的"发布时间"是上传时间，跟未来的翻公开排期比没有意义。
    # C11：无匹配时不再以 worst=0 充数（空真值）——改为 unmeasured 计数，
    # 偏差记 None；Studio 浏览器路视频不在 privateq 里，正是这批 unmeasured。
    try:
        import queue_db
        sched = {}
        for it in queue_db.privateq_load():
            vid = it.get("video_id")
            sa = _parse(it.get("scheduled_at"))
            if vid and sa and it.get("status") == "published":
                sched[vid] = sa
        worst = 0
        matched = 0
        unmeasured = 0
        for p, v in pubs_public:
            if (now - p).total_seconds() > 48 * 3600:
                continue
            sa = sched.get(v.get("id"))
            if sa:
                matched += 1
                dev = abs((p - sa).total_seconds()) / 60
                worst = max(worst, dev)
            else:
                unmeasured += 1
        metrics["schedule_matched_count"] = matched
        metrics["schedule_unmeasured_count"] = unmeasured
        if matched:
            metrics["max_schedule_deviation_min_48h"] = round(worst, 1)
            if worst > SCHEDULE_DEVIATION_MINUTES:
                alerts.append({"level": "WARNING", "rule": "schedule_deviation",
                               "msg": f"排期偏差最大 {worst:.0f}min，超过 {SCHEDULE_DEVIATION_MINUTES}min 线"})
        else:
            metrics["max_schedule_deviation_min_48h"] = None
            metrics["schedule_check"] = (
                f"unmeasured: {unmeasured} 部 48h 内公开视频无 privateq 排期"
                "（可能为 Studio 浏览器路径，偏差无法度量，不记 0）")
    except Exception as e:
        metrics["schedule_check"] = f"skipped: {e}"
    return {"ok": not alerts, "alerts": alerts, "metrics": metrics}


def _write_runlog(status, metrics):
    """C10：每轮向 runlog append 一行（best-effort，写失败不影响巡检结论）。
    行格式与 anomaly_watchdog W1 的解析 regex 对齐：行首日期 +
    `publishes_last_24h:<数字>`；unknown 轮次写 `publishes_last_24h:unknown`
    使 W1 忽略该行（失明既不报绿也不误判低发布日）。"""
    try:
        m = metrics or {}
        n24 = m.get("publishes_last_24h")
        n24_s = str(n24) if isinstance(n24, int) else "unknown"
        gap = m.get("hours_since_last_publish", "-")
        gap_s = gap if isinstance(gap, (int, float)) else "-"
        dev = m.get("max_schedule_deviation_min_48h", "-")
        dev_s = dev if isinstance(dev, (int, float)) else "-"
        pre = m.get("preuploads_last_24h", "-")
        unm = m.get("schedule_unmeasured_count", "-")
        line = (f"{datetime.now(timezone.utc).isoformat()} publish_health "
                f"status={status} publishes_last_24h:{n24_s} "
                f"preuploads_last_24h:{pre} "
                f"hours_since_last_publish:{gap_s} "
                f"max_schedule_deviation_min_48h:{dev_s} "
                f"schedule_unmeasured:{unm}\n")
        with open(RUNLOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _notify_api_blind(skipped):
    """C10：API 失明触发器——24h 内去重，只发一次 inbox urgent 给主 agent，
    请其按用户 2026-10-25 指令走浏览器 Studio 口径核验发布状态。
    本模块不做浏览器动作（浏览器任务只能由主 agent 派发）。"""
    try:
        import inbox
        now = datetime.now(timezone.utc)
        for n in inbox.get_notices(50):
            if n.get("type") != "publish_health_api_blind":
                continue
            ts = _parse(n.get("created") or n.get("created_at") or "")
            if ts and (now - ts).total_seconds() < 24 * 3600:
                return False
        inbox.append_notice({
            "type": "publish_health_api_blind",
            "title": "publish_health API 失明，需浏览器 Studio 口径核验",
            "message": ("YouTube Data API 不可用，publish_health 无法判定发布健康 "
                        f"（{skipped}）。请按用户 2026-10-25 指令走浏览器 Studio "
                        "口径核验 24h 发布数与排期偏差，API 恢复前不要把失明报成健康。"),
            "created": now.isoformat(), "created_at": now.isoformat(),
            "for": "dash_main", "level": "WARNING",
        })
        return True
    except Exception:
        return False


def main():
    import inbox
    r = check()
    status = "unknown" if r.get("skipped") else ("ok" if r["ok"] else "alert")
    _write_runlog(status, r.get("metrics", {}))
    if r.get("skipped"):
        print("publish_health: unknown -", r["skipped"])
        _notify_api_blind(r["skipped"])
        return 2
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
