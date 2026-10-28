#!/usr/bin/env python3
"""Approval TTL lease 暂停（2026-10-09 三脑评审冲突决议落地）。

规格：aistudio.md 冲突决议 "approval TTL MODIFY（lease 持有时暂停）"
- Tier-3 操作持有 approval，但因 QUIET_WINDOW / gate 拒绝 / 外部依赖未就绪
  而暂停时，approval TTL（24h）冻结计时，不继续消耗。
- 解决的死循环："批了但没执行、TTL 到了作废、半夜重走审批"。
- pause 事件 → TTL 冻结；resume 事件 → TTL 继续；每次 pause/resume 写 audit.log。

防滥用（工程常量，有明确 rationale）：
- LEASE_PAUSE_MAX_HOURS = 12：最长的"确定性"暂停是夜间静默窗口 8h
  （00:00-08:00 Asia/Shanghai）；12h = 8h + 50% 裕量。BREAKER_OPEN 等
  不确定暂停若 12h 未恢复，说明需要人工介入，不应无限冻结 TTL。
  超限 → 按过期处理（status="expired"）+ inbox 告警。
- LEASE_PAUSE_TOTAL_MAX_HOURS = 24（C25，2026-10-29，审计第 25 条）：
  单次上限可被“暂停 11h→恢复→再暂停 11h”循环绕过，使有效年龄永远
  到不了 24h TTL。累计暂停（含本次暂停已流逝）超 24h 即按过期处理，
  与单次超限同等处理。累计超限只对仍持有 live approval 的 awaiting 项
  生效（非暂停态时）；已 posted/uploaded/expired 的历史条目不改写。

数据：复用 awaiting_approval.json 的条目字段（不另建状态文件，避免状态分裂）：
  lease_paused: bool               是否处于暂停中
  pause_started_at: ISO | None     本次暂停开始时间
  paused_seconds_total: float      历史累计暂停秒数
  pause_history: [{paused_at, resumed_at, reason, seconds}]

用法：
    from approval_lease import pause_lease, resume_lease, effective_age_hours
    pause_lease("yt:abc123", "gate_reject:QUIET_WINDOW")
    resume_lease("yt:abc123", "transition_accepted")
"""
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from json_safe import atomic_write_json, tolerant_read_json, audit_log

BASE = Path("/home/hatch/data/perpetua")
# 测试可 monkeypatch 此变量指向临时文件
APPROVAL_PATH = str(BASE / "awaiting_approval.json")
INBOX_PATH = "/home/hatch/data/collab/inbox.json"

APPROVAL_TTL_HOURS = 24  # 与 dead_state_watchdog.check_approval_ttl 一致
LEASE_PAUSE_MAX_HOURS = 12  # 见模块 docstring rationale
LEASE_PAUSE_TOTAL_MAX_HOURS = 24  # C25：累计暂停上限，与 TTL 等长


def _now_utc():
    return datetime.now(timezone.utc)


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _load():
    return tolerant_read_json(APPROVAL_PATH, [])


def _save(items):
    atomic_write_json(APPROVAL_PATH, items)


def _match_item(items, video_key):
    """video_key 格式 yt:{video_id}；条目有 video_id 字段。无匹配返回 None。"""
    vid = video_key.split(":", 1)[1] if ":" in video_key else video_key
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("video_id") == vid or it.get("video_id") == video_key:
            return it
    return None


def pause_lease(video_key, reason):
    """冻结某视频 approval TTL 计时。幂等：已暂停或无条目则 no-op。

    返回 True 表示本次实际进入暂停；False 表示 no-op。
    """
    items = _load()
    it = _match_item(items, video_key)
    if it is None:
        return False
    if it.get("lease_paused"):
        return False
    now = _now_utc()
    it["lease_paused"] = True
    it["pause_started_at"] = now.isoformat()
    it.setdefault("paused_seconds_total", 0.0)
    it.setdefault("pause_history", [])
    _save(items)
    audit_log("lease_paused", video_key, "", "paused", "approval-lease",
              {"reason": reason,
               "paused_seconds_total": it["paused_seconds_total"]})
    return True


def resume_lease(video_key, reason):
    """恢复某视频 approval TTL 计时，累计暂停时长。幂等。

    返回 True 表示本次实际恢复并累计；False 表示 no-op。
    """
    items = _load()
    it = _match_item(items, video_key)
    if it is None:
        return False
    if not it.get("lease_paused"):
        return False
    now = _now_utc()
    started = _parse_ts(it.get("pause_started_at"))
    seconds = (now - started).total_seconds() if started else 0.0
    seconds = max(0.0, seconds)
    it["paused_seconds_total"] = float(it.get("paused_seconds_total", 0.0)) + seconds
    paused_at_iso = it.get("pause_started_at")
    it["lease_paused"] = False
    it["pause_started_at"] = None
    hist = it.setdefault("pause_history", [])
    hist.append({"paused_at": paused_at_iso,
                 "resumed_at": now.isoformat(),
                 "reason": reason, "seconds": round(seconds, 1)})
    _save(items)
    audit_log("lease_resumed", video_key, "paused", "running", "approval-lease",
              {"reason": reason, "this_pause_seconds": round(seconds, 1),
               "paused_seconds_total": round(it["paused_seconds_total"], 1)})
    return True


def effective_age_hours(item, now=None):
    """有效年龄 = 挂钟年龄 - 累计暂停 - 本次暂停已流逝。"""
    now = now or _now_utc()
    ts = item.get("created_at") or item.get("qc_passed_at")
    created = _parse_ts(ts)
    if not created:
        return 0.0
    paused = float(item.get("paused_seconds_total", 0.0))
    if item.get("lease_paused"):
        started = _parse_ts(item.get("pause_started_at"))
        if started:
            paused += max(0.0, (now - started).total_seconds())
    return max(0.0, (now - created).total_seconds() - paused) / 3600.0


def _expire_item(it, now, reason, detail):
    """C25：把一条目按过期处理 + 审计 + inbox 告警（单次/累计超限共用）。"""
    topic = it.get("topic", "?")
    it["lease_paused"] = False
    it["pause_started_at"] = None
    it["status"] = "expired"
    it["expired_at"] = now.isoformat()
    it["expired_reason"] = reason
    audit_log("lease_pause_expired", it.get("video_id", ""), "paused",
              "expired", "approval-lease", detail)
    _inbox_alert(
        f"lease 暂停超限自动过期：{topic} {reason}，"
        f"approval 已按过期释放，需人工确认")


def enforce_pause_limits():
    """防滥用：单次暂停超 LEASE_PAUSE_MAX_HOURS，或累计暂停超
    LEASE_PAUSE_TOTAL_MAX_HOURS → 按过期处理 + 告警。

    返回被过期的条目列表。调用方：dead_state_watchdog.check_approval_ttl
    （每 30 分钟一轮），故本函数即累计上限的实际执行入口。
    累计口径 = 已累计 paused_seconds_total + 本次暂停已流逝；
    非暂停态的累计超限只对 status == "awaiting" 的 live approval 生效，
    不改写 posted/uploaded/expired 历史条目。
    """
    now = _now_utc()
    items = _load()
    expired = []
    changed = False
    for it in items:
        if not isinstance(it, dict):
            continue
        total = float(it.get("paused_seconds_total", 0.0) or 0.0)
        if it.get("lease_paused"):
            started = _parse_ts(it.get("pause_started_at"))
            if not started:
                continue
            single_h = (now - started).total_seconds() / 3600.0
            total += max(0.0, (now - started).total_seconds())
            total_h = total / 3600.0
            if single_h > LEASE_PAUSE_MAX_HOURS:
                _expire_item(
                    it, now,
                    f"lease 单次暂停 {single_h:.1f}h 超上限 {LEASE_PAUSE_MAX_HOURS}h，"
                    f"按过期处理（防无限冻结 TTL）",
                    {"pause_hours": round(single_h, 1),
                     "limit_hours": LEASE_PAUSE_MAX_HOURS})
                changed = True
                expired.append(it)
            elif total_h > LEASE_PAUSE_TOTAL_MAX_HOURS:
                _expire_item(
                    it, now,
                    f"lease 累计暂停 {total_h:.1f}h 超上限 "
                    f"{LEASE_PAUSE_TOTAL_MAX_HOURS}h，按过期处理（防循环暂停冻结 TTL）",
                    {"paused_seconds_total": round(total, 1),
                     "limit_hours": LEASE_PAUSE_TOTAL_MAX_HOURS})
                changed = True
                expired.append(it)
        elif it.get("status") == "awaiting" and total / 3600.0 > LEASE_PAUSE_TOTAL_MAX_HOURS:
            total_h = total / 3600.0
            _expire_item(
                it, now,
                f"lease 累计暂停 {total_h:.1f}h 超上限 "
                f"{LEASE_PAUSE_TOTAL_MAX_HOURS}h，按过期处理（防循环暂停冻结 TTL）",
                {"paused_seconds_total": round(total, 1),
                 "limit_hours": LEASE_PAUSE_TOTAL_MAX_HOURS})
            changed = True
            expired.append(it)
    if changed:
        _save(items)
    return expired


def _inbox_alert(msg):
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        import inbox as inbox_gw
        entry = {"type": "lease_alert", "title": msg, "message": msg,
                 "created": _now_utc().isoformat(),
                 "created_at": _now_utc().isoformat(), "for": "user"}
        ib = inbox_gw.load()
        ib.setdefault("messages", []).append(entry)
        ib.setdefault("notices", []).append(entry)
        ib["messages"] = ib["messages"][-100:]
        ib["notices"] = ib["notices"][-100:]
        inbox_gw.save(ib)
    except Exception as e:
        print(f"WARN: lease inbox 告警失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    print(f"approval_lease 自检：TTL={APPROVAL_TTL_HOURS}h, "
          f"单次暂停上限={LEASE_PAUSE_MAX_HOURS}h, "
          f"累计暂停上限={LEASE_PAUSE_TOTAL_MAX_HOURS}h")
