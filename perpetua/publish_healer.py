#!/usr/bin/env python3
"""publish_healer.py — 发布健康三级响应：诊断 → 自动修 → 升级（2026-10-11）。

用户亲令"必须补全"。由 publish_health.py 在告警触发时调用，也可单独跑：
    python3 publish_healer.py --diagnose   # 只诊断，输出 JSON
    python3 publish_healer.py --heal       # 诊断 + 自动修 + 升级上报

红线（Tier 3）：绝不自动决定 public 发布、删数据、改阈值。
自动修只做：① 触发已存在的管线入口（auto_pipeline.py review/collect，幂等）；
② transient 生成卡死的打回重试；③ 写结构化升级通知。
翻公开只走用户已批准的 private_flip 自动流，healer 不碰。
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

BASE = "/home/hatch/data/perpetua"
STATE_FILE = os.path.join(BASE, "publish_healer_state.json")
HEALER_VERSION = "1.1.0"  # 2026-10-15: 业务量感知——长视频排期不再掩盖 Shorts 断档

# 有推进希望的状态：诊断为"有料可推"才触发自动修
ACTIONABLE = {"selected", "review_passed", "uploaded", "teaser_validation",
              "teaser_awaiting_check", "generating", "teaser_generating"}
# transient 卡死：超过 N 小时无变化的 generating 类打回重试
STUCK_HOURS = 6
ESCALATE_COOLDOWN_HOURS = 6
# Shorts/长视频分界（秒）：与 private_flip / Rule 8 口径一致
LONGFORM_DURATION_SEC = 180
# Shorts 空转线：沿用 D20261011-005 的 MAX_INTER_PUBLISH_LATENCY_HOURS=18h
SHORTS_STARVE_HOURS = 18


def _now():
    return datetime.now(timezone.utc)


def _load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s):
    sys.path.insert(0, BASE)
    from atomic_json import atomic_write
    atomic_write(STATE_FILE, s)


def _sig(items):
    h = hashlib.sha256()
    for t, s in sorted((str(x.get("topic")), str(x.get("status"))) for x in items):
        h.update(f"{t}|{s};".encode())
    return h.hexdigest()[:16]


# ---------------- 诊断 ----------------

def diagnose():
    """定位卡点。返回 {"bottleneck": ..., "details": {...}}。"""
    import queue_db
    items = queue_db.pipeline_load()
    pq = queue_db.privateq_load()
    dist = {}
    for x in items:
        dist[x.get("status")] = dist.get(x.get("status"), 0) + 1
    actionable = [x for x in items if x.get("status") in ACTIONABLE]
    waiting_flips = [x for x in pq if x.get("status") == "waiting"]
    details = {
        "pipeline_total": len(items),
        "pipeline_by_status": dist,
        "actionable_count": len(actionable),
        "actionable_topics": [x.get("topic") for x in actionable[:10]],
        "privateq_waiting": len(waiting_flips),
        "privateq_next": (waiting_flips[0].get("scheduled_at")
                          if waiting_flips else None),
    }
    # API 存活探针（轻量）
    api_ok, api_err = True, ""
    try:
        from yt import recent_videos
        recent_videos(max_n=1)
    except Exception as e:
        api_ok, api_err = False, str(e)[:120]
    details["youtube_api_ok"] = api_ok
    if api_err:
        details["youtube_api_err"] = api_err

    if not api_ok:
        bottleneck = "api_down"
    elif not actionable and not waiting_flips:
        bottleneck = "no_ready_items"
    elif actionable and not waiting_flips:
        # 有料但排期空：看是"一直没动"还是"刚消费完"
        st = _load_state()
        sig = _sig(items)
        last_sig, last_ts = st.get("sig"), st.get("ts")
        stalled = (sig == last_sig and last_ts and
                   (_now() - datetime.fromisoformat(last_ts)).total_seconds()
                   > STUCK_HOURS * 3600)
        bottleneck = "scheduler_stalled" if stalled else "draining"
    else:
        # 2026-10-15 业务量感知：waiting 的排期可能全是长视频（如 EP1），
        # 不能因此判 flowing 而掩盖 Shorts 断档。只看 Shorts 排期。
        waiting_shorts = [x for x in waiting_flips
                          if (x.get("video_duration_sec") or 0) <= LONGFORM_DURATION_SEC]
        details["waiting_shorts"] = len(waiting_shorts)
        details["waiting_longform"] = len(waiting_flips) - len(waiting_shorts)
        if waiting_shorts:
            bottleneck = "flowing"  # 有 Shorts 排期在等，不是真空转
        else:
            gap_h = _shorts_gap_hours()
            details["hours_since_last_publish"] = gap_h
            if gap_h is not None and gap_h > SHORTS_STARVE_HOURS:
                bottleneck = "shorts_starved"  # 只有长视频排期 + Shorts 超 18h 未发
            else:
                bottleneck = "flowing"
    details["sig"] = _sig(items)
    return {"bottleneck": bottleneck, "details": details}


def _shorts_gap_hours():
    """距上次公开视频发布的小时数（复用 publish_health 口径）。
    API 不可用时返回 None（不断言）。"""
    try:
        import publish_health
        res = publish_health.check()
        m = (res or {}).get("metrics", {})
        return m.get("hours_since_last_publish")
    except Exception:
        return None


# ---------------- 自动修 ----------------

def _run_collect():
    """触发已存在的管线入口（幂等，cron 每 20 分钟也在跑）。返回 (ok, log)。"""
    logs = []
    for args in (["review", "--wait", "0", "--instant-timeout", "0"],
                 ["collect"]):
        try:
            r = subprocess.run(
                [sys.executable, "auto_pipeline.py"] + args,
                cwd=BASE, capture_output=True, text=True, timeout=600)
            logs.append(f"{' '.join(args)}: rc={r.returncode} "
                        f"tail={(r.stdout or '')[-300:]}")
        except Exception as e:
            logs.append(f"{' '.join(args)}: EXC {e}")
            return False, logs
    return True, logs


def _retry_stuck_generating(items):
    """transient 生成卡死打回 PENDING 重试。返回打回的 topic 列表。"""
    import queue_db
    # 用 _row_key 定位行：load 出来的 dict 带 _row_key（v2 upsert 保证）
    retried = []
    changed = [dict(x) for x in items]
    for x in changed:
        if x.get("status") in ("generating", "teaser_generating"):
            x["status"] = "pending"
            x["note"] = (x.get("note") or "") + " [healer: stuck>6h 打回重试]"
            retried.append(x.get("topic"))
    if retried:
        queue_db.pipeline_save(changed)
    return retried


def remediate(diag):
    """按诊断执行自动修。返回 actions: [{action, result}]。"""
    import queue_db
    bn = diag["bottleneck"]
    actions = []
    if bn in ("scheduler_stalled", "draining", "shorts_starved"):
        ok, logs = _run_collect()
        actions.append({"action": "trigger_collect",
                        "result": "ok" if ok else "failed",
                        "log": logs})
    elif bn == "no_ready_items":
        actions.append({"action": "none",
                        "result": "队列无可推进项，无自动修可用，转升级"})
    elif bn == "api_down":
        actions.append({"action": "none",
                        "result": "API 不可用，不做本地动作（熔断转 Ask Studio 另行处理）"})
    elif bn == "flowing":
        actions.append({"action": "none", "result": "有排期在途，非真空转"})
    # 生成卡死打回（独立于 bottleneck，只要有）
    stuck = [x for x in queue_db.pipeline_load()
             if x.get("status") in ("generating", "teaser_generating")]
    if stuck:
        # 用 state 里的 sig 时间判断是否真卡死：简化为 bottleneck 信号 + 存在即打回
        #（collect 本轮若已推进，下一轮诊断 sig 会变；连续两轮仍在才打回）
        st = _load_state()
        if st.get("stuck_seen"):
            retried = _retry_stuck_generating(queue_db.pipeline_load())
            actions.append({"action": "retry_stuck_generating",
                            "result": f"打回 {len(retried)} 条", "topics": retried})
            st.pop("stuck_seen", None)
        else:
            st["stuck_seen"] = _now().isoformat()
            actions.append({"action": "observe",
                            "result": f"{len(stuck)} 条 generating 先观察一轮"})
        _save_state({**st, "sig": diag["details"]["sig"],
                     "ts": _now().isoformat()})
    else:
        st = _load_state()
        st.pop("stuck_seen", None)
        _save_state({**st, "sig": diag["details"]["sig"],
                     "ts": _now().isoformat()})
    return actions


# ---------------- 升级 ----------------

NEED_USER = {
    "no_ready_items": "管线无可推进项：16 条 teaser_failed + 5 retired，生成端持续无产出。需拍板：是否换生成策略/降门禁/手动补选题。",
    "api_down": "YouTube API 不可用：需确认配额/relay 隧道状态，必要时走 Ask Studio 代班。",
    "scheduler_stalled": None,  # 自动修已触发，无需拍板
    "draining": None,
    "flowing": None,
    "shorts_starved": "Shorts 已断档超 18h，但排期里只有长视频（如 EP1）：B-稳每日 2-3 条节奏已断。需拍板：是否紧急补 Shorts 选题/生成，或接受断档等 EP1。",
}

_CNBOTTLENECK_CN = {
    "no_ready_items": "无可推进项",
    "scheduler_stalled": "调度停滞",
    "draining": "排空中",
    "flowing": "有排期在途",
    "api_down": "API 不可用",
    "shorts_starved": "Shorts断档（长视频排期掩盖）",
}


def escalate(alerts, diag, actions):
    """结构化升级：inbox notice（6h 冷却，情况变化才重发）。返回 True=已发送。"""
    import inbox
    bn = diag["bottleneck"]
    need = NEED_USER.get(bn)
    st = _load_state()
    last = st.get("escalated", {})
    # 冷却：同 bottleneck 6h 内不重发
    if last.get("bottleneck") == bn and last.get("ts"):
        dt = (_now() - datetime.fromisoformat(last["ts"])).total_seconds()
        if dt < ESCALATE_COOLDOWN_HOURS * 3600:
            return False
    notice = {
        "type": "publish_healer",
        "level": "CRITICAL" if any(a["level"] == "CRITICAL" for a in alerts) else "WARNING",
        "alerts": [{"rule": a["rule"], "msg": a["msg"]} for a in alerts],
        "bottleneck": bn,
        "bottleneck_cn": _CNBOTTLENECK_CN.get(bn, bn),
        "details": diag["details"].get("pipeline_by_status"),
        "auto_actions": [{"action": x["action"], "result": x["result"]} for x in actions],
        "need_user": need,
        "ts": _now().isoformat(),
    }
    inbox.append_notice(notice)
    st["escalated"] = {"bottleneck": bn, "ts": _now().isoformat()}
    _save_state(st)
    return True


def heal(alerts):
    """三级全流程：诊断 → 自动修 → 升级。返回报告 dict。"""
    diag = diagnose()
    actions = remediate(diag)
    sent = escalate(alerts, diag, actions)
    return {"diagnosis": diag, "actions": actions, "escalated": sent}


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        print(json.dumps(diagnose(), ensure_ascii=False, indent=1))
    elif "--heal" in sys.argv:
        print(json.dumps(heal([{"level": "MANUAL", "rule": "manual",
                                "msg": "手动触发"}]),
                         ensure_ascii=False, indent=1))
    else:
        print("usage: publish_healer.py [--diagnose|--heal]")
