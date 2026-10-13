#!/usr/bin/env python3
"""判断层（2026-10-09 三脑评审落地）：incident ledger + 6 条检测规则 + 4 档升级。

规格：aistudio.md §5
- J-1 schema（13 字段）→ incident_ledger.jsonl
- R-OPPOSE-1 / R-FLAP-2 / R-VOID-3 / R-ALIAS-4 / R-SINK-5 / R-BYPASS-6
- severity 评分公式 + 4 档：LOG_ONLY / INBOX_ALERT / REVIEW_BRIEF / HALT_ACTOR

用法：
    from judgment import append_incident, scan_all_rules
    append_incident("yt:abc", [{"action": "...", "actor": "...", "at": "...",
                                "transition": "A->B"}], "R-OPPOSE-1")
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from json_safe import atomic_write_json, tolerant_read_json, audit_log

BASE = Path("/home/hatch/data/perpetua")
LEDGER = BASE / "incident_ledger.jsonl"
INBOX = Path("/home/hatch/data/collab/inbox.json")
REVIEWS_DIR = BASE / "reviews"

BASE_SCORE = {
    "R-OPPOSE-1": 30,
    "R-FLAP-2": 25,
    "R-VOID-3": 15,
    "R-ALIAS-4": 20,
    "R-SINK-5": 20,
    "R-BYPASS-6": 60,
}

TIER3_AUTO_ACTORS = {"cron:zero_view_alert", "cron:private_flip"}


def _ulid():
    return f"{int(time.time()*1000):013d}{os.urandom(4).hex()}"


def _now_utc():
    return datetime.now(timezone.utc)


def _transitions_last_24h(video_key):
    """统计某 video_key 24h 内跃迁次数（severity 加权用）。"""
    from json_safe import AUDIT_LOG
    n = 0
    try:
        if not AUDIT_LOG.exists():
            return 0
        cutoff = _now_utc() - timedelta(hours=24)
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get("video_id") != video_key or e.get("action") != "transition":
                    continue
                try:
                    if datetime.fromisoformat(e["ts"]) >= cutoff:
                        n += 1
                except Exception:
                    continue
    except Exception:
        pass
    return n


def _tier3_in_quiet_window(actions):
    """是否有 Tier-3 自动操作者（简化：暂不判断静默窗口时间，只判断 actor）。"""
    return any(a.get("actor") in TIER3_AUTO_ACTORS for a in actions)


def score_severity(detection_rule, conflicting_actions, video_key):
    actors = sorted({a.get("actor", "") for a in conflicting_actions if a.get("actor")})
    base = BASE_SCORE.get(detection_rule, 20)
    score = base + 2 * max(0, len(actors) - 1)
    if _transitions_last_24h(video_key) >= 5:
        score += 10
    if _tier3_in_quiet_window(conflicting_actions):
        score += 15
    score = max(1, min(100, score))
    severity = 1 if score < 25 else 2 if score < 50 else 3 if score < 75 else 4
    return score, severity, actors


def _inbox_alert(incident):
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        import inbox as inbox_gw
        inbox_gw.append_message({
            "type": "incident_alert",
            "incident_id": incident["incident_id"],
            "message": f"意图冲突告警 [{incident['detection_rule']}] "
                       f"{incident['video_key']} severity={incident['severity']}",
            "details": incident,
            "from": "judgment-layer",
            "created_at": _now_utc().isoformat(),
        })
    except Exception as e:
        print(f"WARN: inbox 写入失败: {e}", file=sys.stderr)


def _review_brief(incident):
    try:
        REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        p = REVIEWS_DIR / f"{incident['incident_id']}.md"
        lines = [f"# Incident {incident['incident_id']}",
                 f"- video_key: {incident['video_key']}",
                 f"- rule: {incident['detection_rule']}",
                 f"- severity: {incident['severity']} (score {incident['severity_score']})",
                 f"- gate: {incident.get('gate_decision')}",
                 "", "## conflicting actions"]
        for a in incident["conflicting_actions"]:
            lines.append(f"- {a.get('at')} {a.get('actor')} {a.get('action')} "
                         f"{a.get('transition')}")
        lines += ["", "## recommended resolution",
                  "1. 确认哪个 actor 的意图是权威的（人工 > 定时 > 自愈）",
                  "2. 拒绝/回滚非权威跃迁", "3. 必要时更新 exemption_registry"]
        p.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        print(f"WARN: review brief 写入失败: {e}", file=sys.stderr)


def _halt_actor(incident):
    try:
        from circuit_breaker import trip_cron
        actors = [a for a in incident["actors"] if a.startswith("cron:")]
        for a in actors:
            trip_cron(a.replace("cron:", ""), "HALT_ACTOR",
                      {"incident_id": incident["incident_id"],
                       "rule": incident["detection_rule"]})
    except Exception as e:
        print(f"WARN: halt actor 失败: {e}", file=sys.stderr)


TIER_ACTIONS = {1: "LOG_ONLY", 2: "INBOX_ALERT", 3: "REVIEW_BRIEF", 4: "HALT_ACTOR"}


def append_incident(video_key, conflicting_actions, detection_rule, gate_decision=None,
                    force_severity=None):
    """追加 J-1 记录并按 tier 执行自动升级。返回 incident dict。

    force_severity：强制 severity（如 CB-3 熔断强制 sev4），此时 auto_action_taken
    按强制档位执行。
    """
    score, severity, actors = score_severity(detection_rule, conflicting_actions, video_key)
    if force_severity is not None:
        severity = force_severity
        score = max(score, {1: 1, 2: 25, 3: 50, 4: 75}[force_severity])
    incident = {
        "incident_id": _ulid(),
        "timestamp": _now_utc().isoformat(),
        "video_key": video_key,
        "conflicting_actions": conflicting_actions,
        "actors": actors,
        "severity": severity,
        "severity_score": score,
        "detection_rule": detection_rule,
        "auto_action_taken": TIER_ACTIONS[severity],
        "gate_decision": gate_decision,
        "resolved_at": None,
        "resolved_by": None,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(incident, ensure_ascii=False) + "\n")
    audit_log("incident", video_key, "", f"sev{severity}",
              "judgment-layer", {"incident_id": incident["incident_id"],
                                 "rule": detection_rule, "score": score})
    if severity == 2:
        _inbox_alert(incident)
    elif severity == 3:
        _inbox_alert(incident)
        _review_brief(incident)
    elif severity == 4:
        _inbox_alert(incident)
        _review_brief(incident)
        _halt_actor(incident)
    return incident


# ---- 6 条检测规则的扫描器（扫 audit.log） ----

def _read_audit_entries(hours):
    from json_safe import AUDIT_LOG
    out = []
    try:
        if not AUDIT_LOG.exists():
            return out
        cutoff = _now_utc() - timedelta(hours=hours)
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                try:
                    if datetime.fromisoformat(e.get("ts", "")) >= cutoff:
                        out.append(e)
                except Exception:
                    continue
    except Exception:
        pass
    return out


def check_R_OPPOSE_1():
    """6h 内同一 video_key ≥1 更严格 + ≥1 更宽松跃迁，来自 ≥2 不同 actor。"""
    from pipeline_state import VideoState, VISIBILITY_TAG
    found = []
    entries = [e for e in _read_audit_entries(6)
               if e.get("action") == "transition" and e.get("video_id")]
    by_vk = {}
    for e in entries:
        by_vk.setdefault(e["video_id"], []).append(e)
    for vk, es in by_vk.items():
        tags = set()
        actors = set()
        acts = []
        for e in es:
            try:
                tag = VISIBILITY_TAG[VideoState(e["new_status"])]
            except Exception:
                continue
            tags.add(tag)
            actors.add(e.get("actor", ""))
            acts.append({"action": "transition", "actor": e.get("actor", ""),
                         "at": e.get("ts", ""),
                         "transition": f"{e.get('old_status','')}->{e.get('new_status','')}"})
        if ({"STABLE_LIVE", "QUARANTINED_LOW_VIEW"} <= tags) and len(actors) >= 2:
            found.append(append_incident(vk, acts, "R-OPPOSE-1"))
    return found


def check_R_FLAP_2():
    """24h 内同一 video_key ≥3 次可见性变更。"""
    from pipeline_state import VideoState, VISIBILITY_TAG, _visibility_changing
    found = []
    entries = [e for e in _read_audit_entries(24)
               if e.get("action") == "transition" and e.get("video_id")]
    by_vk = {}
    for e in entries:
        try:
            old_s = VideoState(e["old_status"]) if e.get("old_status") else None
            new_s = VideoState(e["new_status"])
        except Exception:
            continue
        if _visibility_changing(old_s, new_s):
            by_vk.setdefault(e["video_id"], []).append(e)
    for vk, es in by_vk.items():
        if len(es) >= 3:
            acts = [{"action": "transition", "actor": e.get("actor", ""),
                     "at": e.get("ts", ""),
                     "transition": f"{e.get('old_status','')}->{e.get('new_status','')}"}
                    for e in es]
            found.append(append_incident(vk, acts, "R-FLAP-2"))
    return found


def check_R_VOID_3():
    """GENERATE_NEEDED 意图 30min 内无人认领（pipeline_state 无对应 GENERATE 命令）。"""
    found = []
    entries = [e for e in _read_audit_entries(1)
               if e.get("action") in ("GENERATE_NEEDED", "generate_needed")
               and e.get("video_id")]
    try:
        from executor import load_queue
        queued_keys = {c.get("idempotency_key", "") for c in load_queue()
                       if c.get("status") == "pending"}
    except Exception:
        queued_keys = set()
    for e in entries:
        vk = e["video_id"]
        # 简化：若 audit 中无对应 transition 发射 GENERATE，记 incident
        recent = [x for x in _read_audit_entries(1)
                  if x.get("action") == "transition" and x.get("video_id") == vk]
        if not recent:
            found.append(append_incident(
                vk, [{"action": "GENERATE_NEEDED", "actor": e.get("actor", ""),
                      "at": e.get("ts", ""),
                      "transition": "none->GENERATE (unclaimed)"}], "R-VOID-3"))
    return found


def check_R_ALIAS_4():
    """状态别名：相同 visibility_tag + 相同 0 播放窗口，不同 actor 24h 内分歧动作。"""
    found = []
    entries = [e for e in _read_audit_entries(24)
               if e.get("action") in ("quarantined", "skip_scheduled_private")
               and e.get("video_id")]
    by_vk = {}
    for e in entries:
        by_vk.setdefault(e["video_id"], []).append(e)
    for vk, es in by_vk.items():
        actions = {e["action"] for e in es}
        actors = {e.get("actor", "") for e in es}
        if len(actions) >= 2:  # 同一视频既被隔离又被跳过 → 别名分歧
            acts = [{"action": e["action"], "actor": e.get("actor", ""),
                     "at": e.get("ts", ""),
                     "transition": f"{e.get('old_status','')}->{e.get('new_status','')}"}
                    for e in es]
            found.append(append_incident(vk, acts, "R-ALIAS-4"))
    return found


def check_R_SINK_5():
    """远端生成成功 60min 内无 verified artifact_receipt。"""
    from pipeline_state import _verify_receipt
    found = []
    entries = [e for e in _read_audit_entries(2)
               if e.get("action") in ("generate_succeeded", "remote_generate_ok")
               and e.get("video_id")]
    for e in entries:
        run_id = (e.get("extra") or {}).get("run_id", "")
        ok, _ = _verify_receipt(run_id) if run_id else (False, "")
        if not ok:
            found.append(append_incident(
                e["video_id"],
                [{"action": e["action"], "actor": e.get("actor", ""),
                  "at": e.get("ts", ""),
                  "transition": "GENERATING->READY_TO_UPLOAD (no receipt)"}],
                "R-SINK-5"))
    return found


def check_R_BYPASS_6():
    """YouTube API 变更 5min 内无对应 audit.log 跃迁 → 绕过 gate（强制 sev4）。"""
    # 完整实现需 YouTube API 交叉比对；此处提供基于 audit 标记的版本：
    # 任何标记为 direct_api_mutation 的 audit 条目即视为 bypass。
    found = []
    entries = [e for e in _read_audit_entries(0.2)
               if e.get("action") == "direct_api_mutation" and e.get("video_id")]
    for e in entries:
        inc = append_incident(
            e["video_id"],
            [{"action": "direct_api_mutation", "actor": e.get("actor", ""),
              "at": e.get("ts", ""), "transition": "bypass:direct API write"}],
            "R-BYPASS-6")
        # 强制 sev4
        if inc["severity"] < 4:
            inc["severity"] = 4
            inc["severity_score"] = max(inc["severity_score"], 75)
            inc["auto_action_taken"] = "HALT_ACTOR"
            _halt_actor(inc)
        found.append(inc)
    return found


def resolve_incident(incident_id, resolved_by):
    """CB-3 恢复时关闭 incident（resolved_at/resolved_by）。

    ledger 是 JSONL 追加写；本函数整体重写文件（恢复是低频人工操作）。
    返回 True 表示找到并关闭。
    """
    found = False
    incidents = []
    try:
        if LEDGER.exists():
            with open(LEDGER, "r", encoding="utf-8") as f:
                for ln in f:
                    try:
                        incidents.append(json.loads(ln))
                    except Exception:
                        continue
        for inc in incidents:
            if inc.get("incident_id") == incident_id and not inc.get("resolved_at"):
                inc["resolved_at"] = _now_utc().isoformat()
                inc["resolved_by"] = resolved_by
                found = True
        if found:
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            tmp = str(LEDGER) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for inc in incidents:
                    f.write(json.dumps(inc, ensure_ascii=False) + "\n")
            os.replace(tmp, str(LEDGER))
            audit_log("incident_resolved", "", "", "resolved", resolved_by,
                      {"incident_id": incident_id})
    except Exception as e:
        print(f"WARN: resolve_incident 失败: {e}", file=sys.stderr)
        return False
    return found


def scan_all_rules():
    """跑全部 6 条规则，返回 incident 列表。"""
    out = []
    for fn in (check_R_OPPOSE_1, check_R_FLAP_2, check_R_VOID_3,
               check_R_ALIAS_4, check_R_SINK_5, check_R_BYPASS_6):
        try:
            out.extend(fn())
        except Exception as e:
            print(f"WARN: {fn.__name__} 失败: {e}", file=sys.stderr)
    return out


if __name__ == "__main__":
    print("judgment 自检：6 条规则函数就绪")
