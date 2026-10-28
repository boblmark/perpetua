#!/usr/bin/env python3
"""中央编排器 Commit 2：执行器（2026-10-09 三脑评审落地）。

规格：aistudio.md §4 + MUST-7
- 命令队列只有跃迁门能发射（transition() → emit_command）
- 命令类型：GENERATE / INGEST_ARTIFACT / PUBLISH / SET_PRIVATE / QUARANTINE
- 幂等键：gate:{video_key}:{from}:{to}:{run_id}；executed_commands.json 防重放
- 2026-10-18 新增：① 归因门——自称 human:* 的 actor 无核验一律降级为
  agent:unverified-*（防 worker 冒充用户批准）；② 提前量门禁——PUBLISH 早于
  排期档超过 15 分钟 → skip 并交 privateq 排期执行（用户拍板规则）
- worker 执行副作用（YouTube API），结果写回 pipeline_state

用法：
    from executor import emit_command, process_queue
    emit_command("SET_PRIVATE", "yt:abc", "STABLE_LIVE", "INTENTIONAL_PRIVATE",
                 "gate:yt:abc:STABLE_LIVE:INTENTIONAL_PRIVATE:r1", "human:x", "test")
    process_queue()  # 或 process_queue(handler_overrides={"SET_PRIVATE": mock_fn})
"""
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from json_safe import (atomic_write_json, tolerant_read_json, run_lock,
                       audit_log)

BASE = Path("/home/hatch/data/perpetua")
QUEUE_FILE = BASE / "command_queue.json"
EXECUTED_FILE = BASE / "executed_commands.json"

COMMANDS = {"GENERATE", "INGEST_ARTIFACT", "PUBLISH", "SET_PRIVATE", "QUARANTINE"}


def _now_utc():
    return datetime.now(timezone.utc)


def _inbox_upgrade(title, body, dedup_key):
    """P6：failed_permanent 升级告警（best-effort；inbox 失败绝不
    阻塞队列处理本身）。调用点只在向 failed_permanent 跃迁时，
    故同一命令只告警一次，不重复刷屏。"""
    try:
        sys.path.insert(0, str(BASE))
        import inbox as _inbox
        _inbox.append_notice({
            "ts": _now_utc().isoformat(),
            "level": "warning",
            "dedup_key": dedup_key,
            "title": title,
            "body": body,
        })
    except Exception:
        pass


def _note_failure(cmd):
    """P6：给失败命令记 failed_at/fail_count；满 3 次转
    failed_permanent 并升级，调用方须据此改 status。返回 True
    表示已转 failed_permanent。"""
    cmd["failed_at"] = _now_utc().isoformat()
    cmd["fail_count"] = int(cmd.get("fail_count", 0)) + 1
    if cmd["fail_count"] >= 3:
        cmd["status"] = "failed_permanent"
        audit_log("command_failed_permanent", cmd["video_key"],
                  cmd.get("from_state", ""), cmd.get("to_state", ""),
                  "executor", {"command": cmd["command"],
                               "idempotency_key": cmd["idempotency_key"],
                               "fail_count": cmd["fail_count"],
                               "error": str(cmd.get("error", ""))[:200]})
        _inbox_upgrade(
            "执行命令 3 次失败，已转 failed_permanent",
            "命令 %s（%s，幂等键 %s）连续失败 %d 次，不再自动重试，"
            "需人工处置。" % (cmd["command"], cmd["video_key"],
                             cmd["idempotency_key"], cmd["fail_count"]),
            "executor:failed_permanent:%s" % cmd["idempotency_key"])
        return True
    cmd["status"] = "failed"
    return False


def load_queue():
    return tolerant_read_json(str(QUEUE_FILE), [])


def save_queue(q):
    atomic_write_json(str(QUEUE_FILE), q)


def load_executed():
    return tolerant_read_json(str(EXECUTED_FILE), {})


def save_executed(e):
    atomic_write_json(str(EXECUTED_FILE), e)


def _verify_human_actor(actor, reason):
    """2026-10-18 归因门：任何自称 human:* 的 actor 必须可核验。

    背景：2026-10-09（VID_T5×2）与 2026-10-17（冰箱 xtcUVlQKmIM）三次出现
    worker 手写 actor="human:emergency" + reason="emergency_flip:user_approved"
    冒充用户批准；全仓库无任何代码路径会合法产生 human:* 前缀。
    处理：未核验的一律降级为 agent:unverified-*，原值保留在 claimed_actor，
    命令照常入队（fail-open 不中断流程），但下游不得再误读为"用户批准"。
    audit_log 留 loud 记录供追查。
    """
    if not (isinstance(actor, str) and actor.startswith("human:")):
        return actor, None
    claimed = actor
    downgraded = "agent:unverified-" + claimed[len("human:"):]
    try:
        audit_log("unverified_human_actor_claim", "", "", "", "executor",
                  {"claimed_actor": claimed, "downgraded_to": downgraded,
                   "reason": str(reason)[:200],
                   "note": "no code path legitimately emits human:*; "
                           "treat as worker claim, NOT user approval"})
    except Exception:
        pass
    return downgraded, claimed


def emit_command(command, video_key, from_state, to_state, idempotency_key,
                 actor, reason, run_id=None):
    """跃迁门发射命令（MUST-7）。幂等：已执行或已在队列则返回 duplicate。"""
    if command not in COMMANDS:
        raise ValueError(f"未知命令: {command}")
    actor, claimed_actor = _verify_human_actor(actor, reason)
    executed = load_executed()
    if idempotency_key in executed:
        return {"emitted": False, "duplicate": True,
                "reason": "already executed"}
    q = load_queue()
    for c in q:
        if c.get("idempotency_key") == idempotency_key and \
           c.get("status") == "pending":
            return {"emitted": False, "duplicate": True,
                    "reason": "already queued"}
    entry = {
        "command": command,
        "video_key": video_key,
        "from_state": from_state,
        "to_state": to_state,
        "idempotency_key": idempotency_key,
        "actor": actor,
        "reason": reason,
        "run_id": run_id,
        "enqueued_at": _now_utc().isoformat(),
        "status": "pending",
        "attempts": 0,
    }
    if claimed_actor:
        entry["claimed_actor"] = claimed_actor
    q.append(entry)
    save_queue(q)
    audit_log("command_enqueued", video_key, from_state, to_state, actor,
              {"command": command, "idempotency_key": idempotency_key})
    return {"emitted": True, "duplicate": False}


def _yt_api_call(method, path, params=None, data=None):
    sys.path.insert(0, "/home/hatch/data/youtube")
    from yt import api_call
    return api_call(method, path, params=params, data=data)


def _vid_from_key(video_key):
    return video_key.split(":", 1)[1] if ":" in video_key else video_key


def _h_publish(cmd):
    vid = _vid_from_key(cmd["video_key"])
    return _yt_api_call("PUT", "/youtube/v3/videos", params={"part": "status"},
                       data={"id": vid, "status": {"privacyStatus": "public"}})


def _h_set_private(cmd):
    vid = _vid_from_key(cmd["video_key"])
    return _yt_api_call("PUT", "/youtube/v3/videos", params={"part": "status"},
                       data={"id": vid, "status": {"privacyStatus": "private"}})


def _h_quarantine(cmd):
    # 隔离 = 设为 private（YouTube 侧）+ pipeline_state 已记 QUARANTINED
    return _h_set_private(cmd)


def _h_generate(cmd):
    # 生成由视频子系统（Veo/H3）认领；执行器只记录分发，完成后由子系统经
    # transition() 推进 GENERATING→READY_TO_UPLOAD。诚实标记，不伪造完成。
    return {"delegated": True,
            "note": "generation claimed by video pipeline (Veo/H3)"}


def _h_ingest_artifact(cmd):
    # INGEST_ARTIFACT 在跃迁门已验证 receipt（MUST-8）；worker 只做确认记录
    return {"acknowledged": True, "note": "receipt verified at gate"}


DEFAULT_HANDLERS = {
    "PUBLISH": _h_publish,
    "SET_PRIVATE": _h_set_private,
    "QUARANTINE": _h_quarantine,
    "GENERATE": _h_generate,
    "INGEST_ARTIFACT": _h_ingest_artifact,
}


def _lease_pause_on_failure(video_key, command, error):
    """冲突决议 1：外部依赖未就绪（YouTube API 失败）→ approval TTL 冻结。"""
    try:
        from approval_lease import pause_lease
        pause_lease(video_key, f"command_failed:{command}")
    except Exception as e:
        print(f"WARN: lease pause 失败: {e}", file=sys.stderr)


def _lease_resume_on_success(video_key, command):
    try:
        from approval_lease import resume_lease
        resume_lease(video_key, f"command_done:{command}")
    except Exception as e:
        print(f"WARN: lease resume 失败: {e}", file=sys.stderr)


def _write_back(video_key, command, result):
    """结果写回 pipeline_state 记录。"""
    try:
        from pipeline_state import load_state, save_state
        state = load_state()
        rec = state.get(video_key)
        if rec is not None:
            rec["last_command_result"] = {
                "command": command,
                "ok": bool(result.get("ok", True)),
                "at": _now_utc().isoformat(),
            }
            rec["updated_at"] = _now_utc().isoformat()
            save_state(state)
    except Exception as e:
        print(f"WARN: 写回 pipeline_state 失败: {e}", file=sys.stderr)


def _is_stale_command(cmd):
    """stale 命令检测（2026-10-14 gas-nozzle 空转 bug 修复）：
    若命令入队时间早于该视频最后一次状态变更，则该命令已被后续跃迁 supersede，
    执行它会把视频打回旧状态。仅对 QUARANTINE/SET_PRIVATE（可见性变更）生效。
    """
    if cmd.get("command") not in ("QUARANTINE", "SET_PRIVATE"):
        return False
    try:
        from pipeline_state import load_state
        from datetime import datetime
        state = load_state()
        rec = state.get(cmd.get("video_key"))
        if not rec:
            return False
        enqueued = cmd.get("enqueued_at")
        updated = rec.get("updated_at")
        if not enqueued or not updated:
            return False
        # ISO 8601 字符串可直接比较（同为 UTC）
        return enqueued < updated
    except Exception as e:
        print(f"WARN: stale 检测失败，保守放行: {e}", file=sys.stderr)
        return False  # 检测失败时不拦截，避免误杀正常命令


FLIP_LEAD_MINUTES = 15  # 2026-10-18 用户拍板：翻转提前量超过 15 分钟 → 走排期


def _resolve_flip_slot(cmd):
    """解析 PUBLISH 命令对应的排期档时间（UTC）。返回 (slot_dt, source)。

    source: "privateq"（SQLite 真相源）或 "idempotency_key"
    （形如 private_flip:<vid>:<ISO8601 slot>:<actor>）。都找不到返回 (None, None)。
    """
    import re
    vid = _vid_from_key(cmd.get("video_key", ""))
    # 1) SQLite privateq 真相源
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from queue_db import privateq_load
        for e in privateq_load() or []:
            if not isinstance(e, dict):
                continue
            if e.get("video_id") == vid and e.get("status") == "waiting" \
                    and e.get("scheduled_at"):
                dt = datetime.fromisoformat(
                    str(e["scheduled_at"]).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt, "privateq"
    except Exception as ex:
        print(f"WARN: privateq 读排期失败，fallback 到幂等键: {ex}",
              file=sys.stderr)
    # 2) 幂等键里的时间戳
    try:
        m = re.search(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
            r"(?:Z|[+-]\d{2}:?\d{2})?)",
            str(cmd.get("idempotency_key", "")))
        if m:
            dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, "idempotency_key"
    except Exception:
        pass
    return None, None


def _ensure_privateq_flip(vid, slot_dt):
    """确保排期真相源里有该视频的 waiting 翻转条目（bypass 命令重路由用）。

    成功返回 True；失败返回 False（调用方此时不应 skip 命令，留 pending 下轮重试）。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from queue_db import privateq_load, privateq_save
        pq = privateq_load() or []
        for e in pq:
            if isinstance(e, dict) and e.get("video_id") == vid \
                    and e.get("status") == "waiting":
                return True
        pq.append({
            "video_id": vid,
            "title": f"(executor lead-time reroute {vid})",
            "scheduled_at": slot_dt.astimezone(timezone.utc).isoformat(),
            "slot": "executor-reroute",
            "status": "waiting",
            "review_score": None,
            "video_file": "",
            "gemini_verdict": "",
            "queued_at": _now_utc().isoformat(),
            "note": "2026-10-18 lead-time rule：bypass 的 PUBLISH 命令重路由到排期，"
                    "到点由 private_flip 按档翻转",
        })
        privateq_save(pq)
        return True
    except Exception as ex:
        print(f"WARN: privateq 补条目失败: {ex}", file=sys.stderr)
        return False


def _lead_time_gate(cmd):
    """2026-10-18 用户拍板规则：PUBLISH 提前量 >15 分钟 → 走排期，不立即执行。

    返回 (action, detail)，action ∈ {"execute","skip","hold"}：
    - execute：无排期信息（fail-open）或提前量 ≤15 分钟 → 正常执行
    - skip：排期真相源已拥有该翻转 → 命令记 skipped 终态（无孤儿状态，Rule 15）
    - hold：排期条目补写失败 → 留 pending 下轮重试，不丢翻转
    """
    if cmd.get("command") != "PUBLISH":
        return "execute", ""
    slot_dt, src = _resolve_flip_slot(cmd)
    if slot_dt is None:
        return "execute", "no slot info, fail-open"
    lead_min = (slot_dt - _now_utc()).total_seconds() / 60
    if lead_min <= FLIP_LEAD_MINUTES:
        return "execute", f"lead {lead_min:.1f}min within tolerance"
    vid = _vid_from_key(cmd.get("video_key", ""))
    ensured = _ensure_privateq_flip(vid, slot_dt)
    detail = (f"lead {lead_min:.1f}min > {FLIP_LEAD_MINUTES}min "
              f"(slot {slot_dt.isoformat()} via {src}) → deferred to schedule")
    if ensured:
        return "skip", detail
    return "hold", detail + "; privateq write failed, hold for retry"


def process_queue(handler_overrides=None, max_batch=20):
    """worker：取 pending 命令 → 执行 → 记 executed → 写回。返回处理统计。"""
    handlers = dict(DEFAULT_HANDLERS)
    handlers.update(handler_overrides or {})
    done, failed, skipped = 0, 0, 0
    with run_lock("executor"):
        q = load_queue()
        executed = load_executed()
        # P6：失败命令自动重回 pending（fail_count<3 且距上次失败
        # >10 分钟）；已满 3 次的 failed 在此转为 failed_permanent
        # 并升级（此前无 fail_count 的历史 failed 按可重试处理，
        # 下次失败起正常计次）。本轮结束 save_queue 会落盘这些跃迁。
        _now = _now_utc()
        for _c in q:
            if _c.get("status") != "failed":
                continue
            if int(_c.get("fail_count", 0)) >= 3:
                _c["status"] = "failed_permanent"
                audit_log("command_failed_permanent", _c["video_key"],
                          _c.get("from_state", ""), _c.get("to_state", ""),
                          "executor", {"command": _c["command"],
                                       "idempotency_key": _c["idempotency_key"],
                                       "fail_count": _c.get("fail_count")})
                _inbox_upgrade(
                    "执行命令 3 次失败，已转 failed_permanent",
                    "命令 %s（%s，幂等键 %s）连续失败，需人工处置。"
                    % (_c["command"], _c["video_key"], _c["idempotency_key"]),
                    "executor:failed_permanent:%s" % _c["idempotency_key"])
                continue
            _fa = _c.get("failed_at")
            try:
                _age_min = ((_now - datetime.fromisoformat(
                    str(_fa).replace("Z", "+00:00"))).total_seconds() / 60
                    if _fa else 9999)
            except Exception:
                _age_min = 9999
            if _age_min > 10:
                _c["status"] = "pending"
        pending = [c for c in q if c.get("status") == "pending"][:max_batch]
        for cmd in pending:
            key = cmd["idempotency_key"]
            if key in executed:
                cmd["status"] = "skipped"
                skipped += 1
                continue
            # stale 命令拦截：入队早于视频最后状态变更的可见性命令直接跳过
            if _is_stale_command(cmd):
                cmd["status"] = "skipped"
                cmd["skip_reason"] = "stale: enqueued before last state transition"
                skipped += 1
                audit_log("command_skipped_stale", cmd["video_key"],
                          cmd.get("from_state", ""), cmd.get("to_state", ""),
                          "executor", {"command": cmd["command"],
                                      "idempotency_key": key,
                                      "enqueued_at": cmd.get("enqueued_at")})
                continue
            # 提前量门禁（2026-10-18 用户拍板）：PUBLISH 早于排期档 >15 分钟 → 走排期
            action, gate_detail = _lead_time_gate(cmd)
            if action == "skip":
                cmd["status"] = "skipped"
                cmd["skip_reason"] = gate_detail
                skipped += 1
                audit_log("command_deferred_to_slot", cmd["video_key"],
                          cmd.get("from_state", ""), cmd.get("to_state", ""),
                          "executor", {"command": cmd["command"],
                                      "idempotency_key": key,
                                      "detail": gate_detail})
                continue
            if action == "hold":
                cmd["hold_reason"] = gate_detail
                audit_log("command_hold_retry", cmd["video_key"],
                          cmd.get("from_state", ""), cmd.get("to_state", ""),
                          "executor", {"command": cmd["command"],
                                      "idempotency_key": key,
                                      "detail": gate_detail})
                continue
            handler = handlers.get(cmd["command"])
            if not handler:
                cmd["status"] = "failed"
                cmd["error"] = f"no handler for {cmd['command']}"
                failed += 1
                continue
            cmd["attempts"] = cmd.get("attempts", 0) + 1
            try:
                result = handler(cmd) or {}
                ok = result.get("ok", True)
                cmd["result"] = result
                cmd["completed_at"] = _now_utc().isoformat()
                if ok:
                    cmd["status"] = "done"
                    # P6：executed 只在 ok 时写；ok=False 时写 executed
                    # 会毒化幂等键（下次 emit 直接 already executed，
                    # 失败命令永不能重发）。异常分支本来就不写 executed，
                    # 此处与之对齐。
                    executed[key] = {"result": result, "executed_at": cmd["completed_at"],
                                     "command": cmd["command"], "video_key": cmd["video_key"]}
                else:
                    cmd["error"] = str(result)[:200]
                    _note_failure(cmd)
                audit_log("command_executed", cmd["video_key"],
                          cmd.get("from_state", ""), cmd.get("to_state", ""),
                          "executor", {"command": cmd["command"],
                                      "idempotency_key": key, "ok": ok})
                _write_back(cmd["video_key"], cmd["command"], result)
                if ok:
                    done += 1
                    _lease_resume_on_success(cmd["video_key"], cmd["command"])
                else:
                    failed += 1
                    _lease_pause_on_failure(cmd["video_key"], cmd["command"],
                                            str(result)[:200])
            except Exception as e:
                cmd["error"] = str(e)[:200]
                _note_failure(cmd)
                audit_log("command_failed", cmd["video_key"],
                          cmd.get("from_state", ""), cmd.get("to_state", ""),
                          "executor", {"command": cmd["command"], "error": str(e)[:200]})
                _lease_pause_on_failure(cmd["video_key"], cmd["command"], str(e)[:200])
                failed += 1
        save_queue(q)
        save_executed(executed)
    return {"done": done, "failed": failed, "skipped": skipped}


if __name__ == "__main__":
    import json
    stats = process_queue()
    print(json.dumps(stats, ensure_ascii=False))
