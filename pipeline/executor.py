#!/usr/bin/env python3
"""中央编排器 Commit 2：执行器（2026-10-09 三脑评审落地）。

规格：aistudio.md §4 + MUST-7
- 命令队列只有跃迁门能发射（transition() → emit_command）
- 命令类型：GENERATE / INGEST_ARTIFACT / PUBLISH / SET_PRIVATE / QUARANTINE
- 幂等键：gate:{video_key}:{from}:{to}:{run_id}；executed_commands.json 防重放
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


def load_queue():
    return tolerant_read_json(str(QUEUE_FILE), [])


def save_queue(q):
    atomic_write_json(str(QUEUE_FILE), q)


def load_executed():
    return tolerant_read_json(str(EXECUTED_FILE), {})


def save_executed(e):
    atomic_write_json(str(EXECUTED_FILE), e)


def emit_command(command, video_key, from_state, to_state, idempotency_key,
                 actor, reason, run_id=None):
    """跃迁门发射命令（MUST-7）。幂等：已执行或已在队列则返回 duplicate。"""
    if command not in COMMANDS:
        raise ValueError(f"未知命令: {command}")
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
    q.append({
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
    })
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


def process_queue(handler_overrides=None, max_batch=20):
    """worker：取 pending 命令 → 执行 → 记 executed → 写回。返回处理统计。"""
    handlers = dict(DEFAULT_HANDLERS)
    handlers.update(handler_overrides or {})
    done, failed, skipped = 0, 0, 0
    with run_lock("executor"):
        q = load_queue()
        executed = load_executed()
        pending = [c for c in q if c.get("status") == "pending"][:max_batch]
        for cmd in pending:
            key = cmd["idempotency_key"]
            if key in executed:
                cmd["status"] = "skipped"
                skipped += 1
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
                cmd["status"] = "done" if ok else "failed"
                cmd["result"] = result
                cmd["completed_at"] = _now_utc().isoformat()
                executed[key] = {"result": result, "executed_at": cmd["completed_at"],
                                 "command": cmd["command"], "video_key": cmd["video_key"]}
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
                cmd["status"] = "failed"
                cmd["error"] = str(e)[:200]
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
