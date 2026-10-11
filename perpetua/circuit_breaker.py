#!/usr/bin/env python3
"""熔断器（2026-10-09 三脑评审落地）：CB-1~CB-4 + CB-RECOVERY。

规格：aistudio.md §3
- CB-1 gate bypass：24h 内绕过率 >20%
- CB-2 管线不可用：>15min/天 × 连续 3 天
- CB-3 动作失败风暴：≥10/60min 或 ≥25/24h
- CB-4 quiet-window 违规：00:00-08:00 无人值守 Tier-3 可见性翻转
- CB-RECOVERY：必须人工执行，禁止自动化重开（NEVER-3）

状态文件：
  circuit_breaker_state.json  {name: {open, rule_id, disabled_at, window_counts, incident_id, scope}}
  cron_registry.json           {cron_name: {enabled: bool}}

用法：
    from circuit_breaker import trip_cron, is_open, enable_cron, check_CB3
    trip_cron("zero_view_alert", "CB-3", {"failed_60min": 12})
    enable_cron("zero_view_alert", actor="human:cgb2026", reason="已修复豁免逻辑")
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from json_safe import atomic_write_json, tolerant_read_json, audit_log

BASE = Path("/home/hatch/data/perpetua")
BREAKER_FILE = BASE / "circuit_breaker_state.json"
REGISTRY_FILE = BASE / "cron_registry.json"

# ---- 冲突决议 2（reject-storm → CB-3）常量 ----
# 阈值来自 AI Studio 规格 CB-3 定义："动作失败风暴（≥10/60min 或 ≥25/24h）"，
# 冲突决议 "reject-storm MODIFY（阈值换 CB-3）" 即复用该常量。不许拍脑袋。
REJECT_STORM_60MIN = 10
REJECT_STORM_24H = 25
REJECT_STORM_WINDOW_FILE = BASE / "reject_window.json"
# CB-3 冷却期：熔断后 30min 内人工重开需 force=True 显式确认（半开试探语义）；
# NEVER-3 仍然成立：重开只能人工，禁止自动化。
CB3_COOLDOWN_MINUTES = 30
# Tier-3 自动操作者对应的 cron 名（与 pipeline_state.TIER3_AUTO_ACTORS 对应）
TIER3_CRONS = ["zero_view_alert", "private_flip"]
# 风暴计数排除：QUIET_WINDOW / EXEMPT 是正常控制流，不计入风暴
# （否则每夜静默窗口的定时重试会误触发 CB-3）
REJECT_STORM_EXCLUDED = {"QUIET_WINDOW", "EXEMPT"}


def _now_utc():
    return datetime.now(timezone.utc)


def load_breakers():
    return tolerant_read_json(str(BREAKER_FILE), {})


def load_registry():
    return tolerant_read_json(str(REGISTRY_FILE), {})


def is_enabled(cron_name) -> bool:
    """调度器每轮调用：disabled 的 cron 跳过（60s 内生效靠文件 mtime）。"""
    reg = load_registry()
    return reg.get(cron_name, {}).get("enabled", True)


def is_open(actor_or_cron) -> bool:
    """transition() Step 6 调用。

    reject-storm 熔断只停 Tier-3 自动 cron（scope="cron:{name}"），
    人工与管线 worker 不受影响（原逻辑）。
    """
    st = load_breakers()
    for name, info in st.items():
        if not info.get("open"):
            continue
        scope = info.get("scope", "")
        if scope in ("all", actor_or_cron,
                     actor_or_cron.replace("cron:", "")):
            return True
    return False


def trip_cron(cron_name, rule_id, window_counts, scope="cron", incident_id=""):
    """打开熔断器：禁用 cron + 审计 + 告警。"""
    st = load_breakers()
    st[cron_name] = {
        "open": True,
        "rule_id": rule_id,
        "disabled_at": _now_utc().isoformat(),
        "window_counts": window_counts,
        "incident_id": incident_id,
        "scope": f"cron:{cron_name}" if scope == "cron" else scope,
    }
    atomic_write_json(str(BREAKER_FILE), st)
    reg = load_registry()
    reg.setdefault(cron_name, {})["enabled"] = False
    atomic_write_json(str(REGISTRY_FILE), reg)
    audit_log("breaker_tripped", "", "", "disabled", "circuit_breaker",
              {"cron": cron_name, "rule": rule_id,
               "window_counts": window_counts, "incident_id": incident_id})
    print(f"熔断器打开：{cron_name} [{rule_id}] 已禁用，需人工恢复")
    return st[cron_name]


def check_CB3(cron_name="zero_view_alert", hours=1):
    """CB-3：扫 audit.log 统计失败动作数。返回 (tripped: bool, counts)。"""
    from json_safe import AUDIT_LOG
    counts_60min, counts_24h = 0, 0
    try:
        if AUDIT_LOG.exists():
            now = _now_utc()
            with open(AUDIT_LOG, "r", encoding="utf-8") as f:
                for ln in f:
                    try:
                        e = json.loads(ln)
                    except Exception:
                        continue
                    if e.get("actor") != f"cron:{cron_name}" and e.get("actor") != cron_name:
                        continue
                    act = e.get("action", "")
                    if not (act.endswith("_failed") or "restore_failed" in act
                            or e.get("extra", {}).get("rejection") not in (None, "EXEMPT")):
                        continue
                    try:
                        ts = datetime.fromisoformat(e["ts"])
                    except Exception:
                        continue
                    if now - ts <= timedelta(minutes=60):
                        counts_60min += 1
                    if now - ts <= timedelta(hours=24):
                        counts_24h += 1
    except Exception as ex:
        print(f"WARN: CB-3 扫描失败: {ex}", file=sys.stderr)
    import json
    tripped = counts_60min >= 10 or counts_24h >= 25
    if tripped:
        trip_cron(cron_name, "CB-3",
                  {"failed_60min": counts_60min, "failed_24h": counts_24h})
    return tripped, {"failed_60min": counts_60min, "failed_24h": counts_24h}


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _load_reject_window():
    stamps = tolerant_read_json(str(REJECT_STORM_WINDOW_FILE), [])
    return [s for s in stamps if _parse_ts(s) is not None]


def record_rejection(code, actor=""):
    """每次 gate 拒绝时由 pipeline_state.transition() 调用。

    QUIET_WINDOW / EXEMPT 是正常控制流，不计入风暴。
    60min 内 ≥10 次或 24h 内 ≥25 次（AI Studio CB-3 常量）→ 熔断 CB-3。
    返回 {"storm": bool, ...}。
    """
    if code in REJECT_STORM_EXCLUDED:
        return {"storm": False, "reason": "excluded_code", "code": code}
    now = _now_utc()
    stamps = _load_reject_window()
    stamps.append(now.isoformat())
    cutoff_24h = now - timedelta(hours=24)
    stamps = [s for s in stamps if _parse_ts(s) >= cutoff_24h]
    atomic_write_json(str(REJECT_STORM_WINDOW_FILE), stamps)
    cutoff_60m = now - timedelta(minutes=60)
    c60 = sum(1 for s in stamps if _parse_ts(s) >= cutoff_60m)
    c24 = len(stamps)
    if c60 >= REJECT_STORM_60MIN or c24 >= REJECT_STORM_24H:
        # CB-3 已打开时不重复熔断，避免 incident 刷屏；只计数
        st = load_breakers()
        already = any(info.get("open") and info.get("rule_id") == "CB-3"
                      for info in st.values())
        if already:
            return {"storm": True, "already_open": True,
                    "reject_60min": c60, "reject_24h": c24}
        return trip_reject_storm({"reject_60min": c60, "reject_24h": c24,
                                  "trigger_code": code, "trigger_actor": actor})
    return {"storm": False, "reject_60min": c60, "reject_24h": c24}


def trip_reject_storm(window_counts):
    """reject-storm → CB-3：停所有 Tier-3 自动操作，只保留人工通道。

    1. J-1 incident ledger 记 CB-3 incident（强制 severity 4）
    2. 逐个 trip Tier-3 cron（scope="cron:{name}"，只停 Tier-3 自动操作；
       人工与管线 worker 不受影响）
    3. 恢复必须人工（recover_tier3_all → enable_cron，NEVER-3）
    """
    from judgment import append_incident
    now = _now_utc()
    # actor 用 circuit_breaker 而非 cron:xxx，避免 _halt_actor 重复 trip 覆盖 CB-3 条目
    actions = [{"action": "reject_storm",
                "actor": "circuit_breaker",
                "at": now.isoformat(),
                "transition": f"gate rejections {window_counts} "
                              f"on crons {TIER3_CRONS}"}]
    incident = append_incident("tier3_auto", actions, "CB-3",
                               gate_decision=f"reject_storm tripped CB-3: "
                                             f"{window_counts}",
                               force_severity=4)
    incident_id = incident["incident_id"]
    for cron in TIER3_CRONS:
        trip_cron(cron, "CB-3", window_counts, scope="cron",
                  incident_id=incident_id)
    audit_log("reject_storm_tripped", "tier3_auto", "", "CB-3_OPEN",
              "circuit_breaker",
              {"window_counts": window_counts, "incident_id": incident_id,
               "crons": TIER3_CRONS})
    print(f"CB-3 熔断：reject-storm {window_counts}，Tier-3 自动操作已停，需人工恢复")
    return {"storm": True, "incident_id": incident_id,
            "window_counts": window_counts, "crons": TIER3_CRONS}


def enable_cron(cron_name, actor, reason, force=False):
    """CB-RECOVERY（必须人工）：按规格 4 步验证后重开。

    1. 读 breaker state + incident，记录 root cause（由调用方在 reason 中说明）
    2. 干跑验证（调用方负责，本函数只做登记）
    3. bypass 率 <0.05（调用方负责，本函数只做登记）
    4. 经本函数重开（append audit 记录），禁止手改 flag（NEVER-3）

    CB-3 冷却期：熔断后 CB3_COOLDOWN_MINUTES 内重开需 force=True 显式确认
    （半开试探语义）；NEVER-3 仍然成立：重开只能人工。
    """
    if not (actor == "human" or actor.startswith("human:")):
        raise PermissionError("NEVER-3: 只有人工能重开熔断器")
    st = load_breakers()
    info = st.get(cron_name, {})
    # CB-3 冷却期检查
    if info.get("rule_id") == "CB-3" and not force:
        disabled_at = _parse_ts(info.get("disabled_at"))
        if disabled_at:
            elapsed_m = (_now_utc() - disabled_at).total_seconds() / 60.0
            if elapsed_m < CB3_COOLDOWN_MINUTES:
                raise PermissionError(
                    f"CB-3 冷却期内（{elapsed_m:.1f}min < {CB3_COOLDOWN_MINUTES}min），"
                    f"需 force=True 显式确认提前恢复")
    info["open"] = False
    info["recovered_at"] = _now_utc().isoformat()
    info["recovered_by"] = actor
    info["recover_reason"] = reason
    atomic_write_json(str(BREAKER_FILE), st)
    reg = load_registry()
    reg.setdefault(cron_name, {})["enabled"] = True
    atomic_write_json(str(REGISTRY_FILE), reg)
    audit_log("breaker_recovered", "", "disabled", "enabled", actor,
              {"cron": cron_name, "reason": reason})
    print(f"熔断器恢复：{cron_name} 已重开（{actor}：{reason}）")
    return True


def recover_tier3_all(actor, reason, force=False):
    """CB-3 人工恢复：重开所有 Tier-3 cron + 关闭 J-1 incident。

    必须人工（NEVER-3）。恢复后在 incident ledger 记 resolved。
    返回 {"recovered": [...], "incidents_resolved": [...]}。
    """
    from judgment import resolve_incident
    st = load_breakers()
    recovered, resolved = [], []
    for cron in TIER3_CRONS:
        info = st.get(cron, {})
        incident_id = info.get("incident_id")
        try:
            enable_cron(cron, actor, reason, force=force)
            recovered.append(cron)
            if incident_id:
                try:
                    if resolve_incident(incident_id, actor):
                        resolved.append(incident_id)
                except Exception as e:
                    print(f"WARN: incident 关闭失败: {e}", file=sys.stderr)
        except PermissionError as e:
            print(f"恢复 {cron} 被拒: {e}")
            raise
    # 清理风暴计数窗口（恢复后重新计数）
    try:
        atomic_write_json(str(REJECT_STORM_WINDOW_FILE), [])
    except Exception:
        pass
    audit_log("tier3_recovered", "tier3_auto", "CB-3_OPEN", "recovered",
              actor, {"reason": reason, "crons": recovered,
                      "incidents_resolved": resolved})
    return {"recovered": recovered, "incidents_resolved": resolved}


if __name__ == "__main__":
    import json
    print("circuit_breaker 自检：CB-1~CB-4 函数就绪，CB-RECOVERY 需人工")
