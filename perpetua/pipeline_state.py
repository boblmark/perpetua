#!/usr/bin/env python3
"""中央编排器 Commit 1：规范状态存储 + 跃迁门（2026-10-09 三脑评审落地）。

规格：/home/hatch/data/perpetua/brain_review_patrol_20261009/aistudio.md
- MUST-1: cron 脚本的 YouTube 状态变更必须走 transition()
- MUST-2: visibility_tag 三态（MANAGED_SCHEDULED_DRAFT/QUARANTINED_LOW_VIEW/STABLE_LIVE）
- MUST-4: audit.log 追加带 seq + prev_hash 链
- MUST-9: 00:00-08:00 Asia/Shanghai 夜间静默，max_unattended_flips=0
- MUST-12: 豁免统一读 exemption_registry.json
- 拒绝码闭集：QUIET_WINDOW/LEASE_HELD/STALE_FROM_STATE/ILLEGAL_TRANSITION/
  BREAKER_OPEN/EXEMPT/RECEIPT_UNVERIFIED/INTENT_CONFLICT

状态文件（/home/hatch/data/perpetua/）：
  pipeline_state.json      {video_key: record}  规范记录
  transition_index.json    {idempotency_key: result}  幂等
  exemption_registry.json  {video_key: {exemption_id, reason, owner, expires_at}}
  circuit_breaker_state.json / cron_registry.json  熔断器（circuit_breaker.py）
  incident_ledger.jsonl    J-1（judgment.py）

用法：
    from pipeline_state import transition, VideoState, ensure_live_record
    r = transition("yt:abc123", VideoState.QUARANTINED, VideoState.STABLE_LIVE,
                   actor="cron:zero_view_alert", reason="auto_restore_views>0")
    if not r["accepted"]:
        print("拒绝:", r["rejection_code"])
"""
import fcntl
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from json_safe import atomic_write_json, tolerant_read_json, audit_log

BASE = Path("/home/hatch/data/perpetua")
STATE_FILE = BASE / "pipeline_state.json"
INDEX_FILE = BASE / "transition_index.json"
EXEMPTION_FILE = BASE / "exemption_registry.json"
BREAKER_FILE = BASE / "circuit_breaker_state.json"
ARTIFACTS_DIR = BASE / "artifacts"
GLOBAL_LOCK = Path("/tmp/perpetua_locks/pipeline_state.lock")

SHANGHAI = ZoneInfo("Asia/Shanghai")
QUIET_START_HOUR = 0
QUIET_END_HOUR = 8  # [0, 8) Asia/Shanghai

# Tier-3 自动操作者（无人值守下能改可见性的 cron）
TIER3_AUTO_ACTORS = {"cron:zero_view_alert", "cron:private_flip"}

# 意图冲突检测窗口（R-OPPOSE-1）
INTENT_CONFLICT_WINDOW_H = 6


class VideoState(str, Enum):
    MANAGED_SCHEDULED_DRAFT = "MANAGED_SCHEDULED_DRAFT"
    GENERATING = "GENERATING"
    READY_TO_UPLOAD = "READY_TO_UPLOAD"
    INTENTIONAL_PRIVATE = "INTENTIONAL_PRIVATE"
    QUARANTINED = "QUARANTINED"
    STABLE_LIVE = "STABLE_LIVE"
    DELETED = "DELETED"


# MUST-2: 三态可见性映射
VISIBILITY_TAG = {
    VideoState.MANAGED_SCHEDULED_DRAFT: "MANAGED_SCHEDULED_DRAFT",
    VideoState.GENERATING: "MANAGED_SCHEDULED_DRAFT",
    VideoState.READY_TO_UPLOAD: "MANAGED_SCHEDULED_DRAFT",
    VideoState.INTENTIONAL_PRIVATE: "QUARANTINED_LOW_VIEW",
    VideoState.QUARANTINED: "QUARANTINED_LOW_VIEW",
    VideoState.DELETED: "QUARANTINED_LOW_VIEW",
    VideoState.STABLE_LIVE: "STABLE_LIVE",
}

# 跃迁表：(from, to) -> {actors: 允许的 actor 集合（"human" 前缀匹配 human:<id>）,
#                         command: 发射的执行器命令, tier3: 是否 Tier-3 自动操作}
TRANSITIONS = {
    (None, VideoState.MANAGED_SCHEDULED_DRAFT): {"actors": {"intake_worker"}, "command": None},
    (None, VideoState.GENERATING): {"actors": {"intake_worker"}, "command": "GENERATE"},
    (VideoState.MANAGED_SCHEDULED_DRAFT, VideoState.GENERATING): {"actors": {"gate"}, "command": "GENERATE"},
    (VideoState.GENERATING, VideoState.READY_TO_UPLOAD): {"actors": {"generate_worker"}, "command": "INGEST_ARTIFACT", "guard": "receipt"},
    (VideoState.GENERATING, VideoState.MANAGED_SCHEDULED_DRAFT): {"actors": {"generate_worker"}, "command": None, "guard": "retry<3"},
    (VideoState.GENERATING, VideoState.QUARANTINED): {"actors": {"generate_worker"}, "command": None, "guard": "retry>=3"},
    (VideoState.READY_TO_UPLOAD, VideoState.STABLE_LIVE): {"actors": {"upload_worker"}, "command": "PUBLISH"},
    (VideoState.READY_TO_UPLOAD, VideoState.QUARANTINED): {"actors": {"upload_worker"}, "command": None},
    (VideoState.STABLE_LIVE, VideoState.QUARANTINED): {"actors": {"cron:zero_view_alert"}, "command": "QUARANTINE", "tier3": True},
    (VideoState.STABLE_LIVE, VideoState.INTENTIONAL_PRIVATE): {"actors": {"human"}, "command": "SET_PRIVATE"},
    (VideoState.QUARANTINED, VideoState.STABLE_LIVE): {"actors": {"cron:zero_view_alert"}, "command": None, "tier3": True},
    (VideoState.QUARANTINED, VideoState.INTENTIONAL_PRIVATE): {"actors": {"human"}, "command": None},
    (VideoState.QUARANTINED, VideoState.DELETED): {"actors": {"human"}, "command": None, "tier3": True},
    (VideoState.INTENTIONAL_PRIVATE, VideoState.STABLE_LIVE): {"actors": {"human", "cron:private_flip"}, "command": "PUBLISH", "tier3": True},
    (VideoState.INTENTIONAL_PRIVATE, VideoState.DELETED): {"actors": {"human"}, "command": None},
    (VideoState.INTENTIONAL_PRIVATE, VideoState.QUARANTINED): {"actors": {"system"}, "command": None},
}
# 特殊规则：任何非 DELETED → DELETED，允许 human:* 或 retention policy（v2 用户批准的保留策略）
RETENTION_ACTORS = {"system:retention", "cron:zero_view_alert"}

# 每状态 owner / timeout / timeout 动作（规格 §2）
STATE_META = {
    VideoState.MANAGED_SCHEDULED_DRAFT: {"owner": "intake_worker", "timeout_h": 72, "timeout_action": "QUARANTINED:stale_draft"},
    VideoState.GENERATING: {"owner": "generate_worker", "timeout_h": 6, "timeout_action": "retry_or_quarantine"},
    VideoState.READY_TO_UPLOAD: {"owner": "upload_worker", "timeout_h": 24, "timeout_action": "QUARANTINED:receipt_expired"},
    VideoState.INTENTIONAL_PRIVATE: {"owner": "exemption_owner", "timeout_h": 90 * 24, "timeout_action": "notify_owner"},
    VideoState.QUARANTINED: {"owner": "review_worker", "timeout_h": 7 * 24, "timeout_action": "review_brief"},
    VideoState.STABLE_LIVE: {"owner": "monitor", "timeout_h": None, "timeout_action": None},
    VideoState.DELETED: {"owner": None, "timeout_h": None, "timeout_action": None},
}

REJECTION_CODES = {"QUIET_WINDOW", "LEASE_HELD", "STALE_FROM_STATE",
                   "ILLEGAL_TRANSITION", "BREAKER_OPEN", "EXEMPT",
                   "RECEIPT_UNVERIFIED", "INTENT_CONFLICT"}


def _now_utc():
    return datetime.now(timezone.utc)


def _in_quiet_window(now=None):
    """MUST-9: 00:00-08:00 Asia/Shanghai 为夜间静默窗口。"""
    now = now or datetime.now(SHANGHAI)
    return QUIET_START_HOUR <= now.hour < QUIET_END_HOUR


def _actor_match(permitted: set, actor: str) -> bool:
    for p in permitted:
        if p == "human":
            if actor == "human" or actor.startswith("human:"):
                return True
        elif p == actor:
            return True
    return False


def _is_tier3_auto(actor: str) -> bool:
    return actor in TIER3_AUTO_ACTORS


def _visibility_changing(from_state, to_state) -> bool:
    if from_state is None:
        return True
    return VISIBILITY_TAG[VideoState(from_state)] != VISIBILITY_TAG[VideoState(to_state)]


@contextmanager
def _global_state_lock():
    """串行化所有 transition() 的读-改-写（跨脚本真正互斥）。"""
    GLOBAL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fp = open(GLOBAL_LOCK, "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fp, fcntl.LOCK_UN)
        except Exception:
            pass
        fp.close()


def load_state():
    return tolerant_read_json(str(STATE_FILE), {})


def save_state(state):
    atomic_write_json(str(STATE_FILE), state)


def load_index():
    return tolerant_read_json(str(INDEX_FILE), {})


def save_index(index):
    atomic_write_json(str(INDEX_FILE), index)


def load_exemptions():
    """MUST-12: 统一豁免注册表。{video_key: {exemption_id, reason, owner, expires_at}}"""
    return tolerant_read_json(str(EXEMPTION_FILE), {})


def is_exempt(video_key, now=None) -> bool:
    reg = load_exemptions()
    e = reg.get(video_key)
    if not e:
        return False
    exp = e.get("expires_at")
    if exp:
        try:
            if _now_utc() > datetime.fromisoformat(exp):
                return False
        except Exception:
            pass
    return True


def _new_record(video_key, state: VideoState, video_id=None, owner="", run_id=None):
    now = _now_utc().isoformat()
    meta = STATE_META[state]
    timeout_at = None
    if meta["timeout_h"]:
        timeout_at = (_now_utc() + timedelta(hours=meta["timeout_h"])).isoformat()
    return {
        "video_key": video_key,
        "state": state.value,
        "visibility_tag": VISIBILITY_TAG[state],
        "video_id": video_id,
        "owner": owner or meta["owner"],
        "lease": {"holder": None, "acquired_at": None, "expires_at": None},
        "run_id": run_id,
        "retry_count": 0,
        "exemption_id": None,
        "state_entered_at": now,
        "state_timeout_at": timeout_at,
        "last_transition_seq": 0,
        "artifact_receipt": None,
        "updated_at": now,
    }


def ensure_live_record(video_key, video_id=None, actor="system"):
    """为已在 YouTube 上线的视频补建 STABLE_LIVE 记录（迁移用）。"""
    with _global_state_lock():
        state = load_state()
        if video_key not in state:
            state[video_key] = _new_record(video_key, VideoState.STABLE_LIVE,
                                           video_id=video_id, owner="monitor")
            save_state(state)
        return state[video_key]


def _chained_audit(action, video_id="", old_status="", new_status="", actor="", extra=None):
    """MUST-4: audit.log 追加带 seq + prev_hash 链的记录（经 json_safe.audit_log）。"""
    from json_safe import AUDIT_LOG
    seq = 1
    prev_hash = "GENESIS"
    try:
        if AUDIT_LOG.exists():
            with open(AUDIT_LOG, "r", encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()]
            if lines:
                last = json.loads(lines[-1])
                seq = int(last.get("seq", 0)) + 1
                prev_hash = last.get("hash", prev_hash)
    except Exception:
        pass
    entry_extra = dict(extra or {})
    entry_extra["seq"] = seq
    entry_extra["prev_hash"] = prev_hash
    audit_log(action, video_id, old_status, new_status, actor, entry_extra)
    # 回填本条 hash（供下一条链）
    try:
        raw = json.dumps({"seq": seq, "action": action, "video_id": video_id,
                          "old": old_status, "new": new_status,
                          "actor": actor, "prev": prev_hash},
                         ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256(raw.encode()).hexdigest()[:16]
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if lines:
            last = json.loads(lines[-1])
            last_e = last.get("extra", {})
            last_e["hash"] = h
            last["extra"] = last_e
            lines[-1] = json.dumps(last, ensure_ascii=False) + "\n"
            with open(AUDIT_LOG, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except Exception as e:
        print(f"WARN: chained audit 回填 hash 失败: {e}", file=sys.stderr)
    return seq


def _lease_held_by_other(record, actor, now):
    lease = record.get("lease") or {}
    holder = lease.get("holder")
    if not holder or holder == actor:
        return False
    try:
        exp = datetime.fromisoformat(lease["expires_at"])
        return now < exp
    except Exception:
        return False


def _check_intent_conflict(video_key, from_state, to_state, actor):
    """R-OPPOSE-1: 6h 内同一 video_key 有来自不同 actor 的对立可见性翻转 → 冲突。

    refined：只统计"已达稳态（STABLE_LIVE/QUARANTINED/INTENTIONAL_PRIVATE）
    后被翻转"的记录；管线前向流转（GENERATING/READY_TO_UPLOAD→STABLE_LIVE）
    是正常生产进度，不算对立意图。
    """
    from json_safe import AUDIT_LOG
    if not _visibility_changing(from_state, to_state):
        return None
    STEADY = {VideoState.STABLE_LIVE, VideoState.QUARANTINED,
              VideoState.INTENTIONAL_PRIVATE}
    try:
        if not AUDIT_LOG.exists():
            return None
        cutoff = _now_utc() - timedelta(hours=INTENT_CONFLICT_WINDOW_H)
        my_tag = VISIBILITY_TAG[VideoState(to_state)]
        conflicts = []
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get("video_id") != video_key:
                    continue
                if e.get("action") != "transition":
                    continue
                if e.get("actor") == actor:
                    continue
                try:
                    ts = datetime.fromisoformat(e["ts"])
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                other_old, other_new = e.get("old_status", ""), e.get("new_status", "")
                try:
                    other_old_st = VideoState(other_old)
                    other_new_st = VideoState(other_new)
                except Exception:
                    continue
                if other_old_st not in STEADY:
                    continue  # 管线前向流转，非翻转
                other_tag = VISIBILITY_TAG[other_new_st]
                if other_tag != my_tag and \
                   {other_tag, my_tag} <= {"STABLE_LIVE", "QUARANTINED_LOW_VIEW"}:
                    conflicts.append(e)
        return conflicts or None
    except Exception:
        return None


def _verify_receipt(run_id):
    """MUST-8: GENERATING→READY_TO_UPLOAD 要求已验证的 artifact_receipt.json。"""
    if not run_id:
        return False, "no run_id"
    rp = ARTIFACTS_DIR / run_id / "artifact_receipt.json"
    if not rp.exists():
        return False, "receipt missing"
    try:
        r = json.loads(rp.read_text(encoding="utf-8"))
        lp = Path(r["local_uri"])
        if not lp.exists():
            return False, "artifact file missing"
        data = lp.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha != r.get("sha256") or len(data) != r.get("byte_size"):
            return False, "checksum mismatch"
        return True, "ok"
    except Exception as e:
        return False, str(e)[:100]


def write_artifact_receipt(run_id, local_path, remote_uri="", origin_run_id=""):
    """Commit 3: 写产物入站 receipt（原子写）。"""
    lp = Path(local_path)
    data = lp.read_bytes()
    rec = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_size": len(data),
        "origin_run_id": origin_run_id or run_id,
        "remote_uri": remote_uri,
        "local_uri": str(lp),
        "verified_at": _now_utc().isoformat(),
    }
    rp = ARTIFACTS_DIR / run_id / "artifact_receipt.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(rp), rec)
    return rec


def _breaker_open(actor):
    """CB: breaker 是否对该 actor 的动作类别打开（委托 circuit_breaker）。"""
    try:
        from circuit_breaker import is_open
        return is_open(actor)
    except Exception:
        return False


def _resolve_transition(from_state, to_state, actor):
    """返回 (rule, is_retention_delete)。"""
    # retention policy 优先：human:* 或 retention actor 可删任何非 DELETED 状态
    # （v2 用户批准的 24h 隔离后自动删除；遮蔽表中 QUARANTINED→DELETED 的 human-only）
    if to_state == VideoState.DELETED and from_state != VideoState.DELETED:
        if actor == "human" or actor.startswith("human:") or actor in RETENTION_ACTORS:
            return {"actors": {"human", "system:retention", "cron:zero_view_alert"},
                    "command": None, "tier3": actor in RETENTION_ACTORS}, True
    key = (from_state, to_state)
    if key in TRANSITIONS:
        return TRANSITIONS[key], False
    return None, False


def transition(video_key, from_state, to_state, actor, reason,
               run_id=None, idempotency_key=None, lease_ttl_seconds=300):
    """跃迁门（规格 §4，10 步执行顺序）。返回 dict。

    from_state: VideoState | None（None = intake 路径，仅允许 intake 跃迁）
    """
    to_state = VideoState(to_state)
    from_state = VideoState(from_state) if from_state is not None else None
    now = _now_utc()

    def reject(code, detail=""):
        # 冲突决议 1（approval TTL lease 暂停）：Tier-3 自动操作被
        # QUIET_WINDOW / BREAKER_OPEN 拒绝 → approval TTL 冻结计时，
        # 防止"批了但没执行、TTL 到了作废"的死循环。
        if _is_tier3_auto(actor) and code in ("QUIET_WINDOW", "BREAKER_OPEN"):
            try:
                from approval_lease import pause_lease
                pause_lease(video_key, f"gate_reject:{code}")
            except Exception as e:
                print(f"WARN: lease pause 失败: {e}", file=sys.stderr)
        # 冲突决议 2（reject-storm → CB-3）：记录 gate 拒绝供风暴检测。
        # QUIET_WINDOW / EXEMPT 是正常控制流（时间门禁/豁免跳过），不计入风暴，
        # 否则每夜静默窗口的定时重试会误触发 CB-3。
        if code not in ("QUIET_WINDOW", "EXEMPT"):
            try:
                from circuit_breaker import record_rejection
                record_rejection(code, actor)
            except Exception as e:
                print(f"WARN: reject 记录失败: {e}", file=sys.stderr)
        return {"accepted": False, "rejection_code": code, "seq": None,
                "idempotency_key": idempotency_key or "", "duplicate": False,
                "detail": detail}

    # Step 1: 夜间静默窗口（MUST-9 / CB-4）
    # 豁免（2026-10-09 Ask Studio Q4 指令 + 用户动态排期授权）：
    # cron:private_flip 的 scheduled_flip（reason 以 "scheduled_flip:" 开头）
    # 只是把白天已过全部硬门禁、预传为 private 的视频翻为 public——
    # 夜间不运行任何生成代码，只做一次 privacyStatus 变更。
    # 仅此精确路径豁免；其他 Tier-3 自动操作（zero_view_alert 等）不受影响。
    _scheduled_flip_exempt = (
        actor == "cron:private_flip"
        and to_state == VideoState.STABLE_LIVE
        and isinstance(reason, str) and reason.startswith("scheduled_flip:")
    )
    if _is_tier3_auto(actor) and _visibility_changing(from_state, to_state) \
            and _in_quiet_window(now.astimezone(SHANGHAI)) \
            and not _scheduled_flip_exempt:
        _chained_audit("transition_rejected", video_key,
                       from_state.value if from_state else "",
                       to_state.value, actor,
                       {"rejection": "QUIET_WINDOW", "reason": reason})
        return reject("QUIET_WINDOW", "00:00-08:00 Asia/Shanghai 禁止无人值守可见性变更")

    with _global_state_lock():
        state = load_state()
        index = load_index()
        rec = state.get(video_key)

        # Step 5 (提前): 幂等 — key 基于调用方声明的 from_state，保证重放可命中
        key = idempotency_key or \
            f"gate:{video_key}:{from_state.value if from_state else 'none'}:{to_state.value}:{run_id or 'manual'}"
        if key in index:
            prev = index[key]
            return {"accepted": prev.get("accepted", True),
                    "rejection_code": prev.get("rejection_code"),
                    "seq": prev.get("seq"), "idempotency_key": key,
                    "duplicate": True, "detail": "幂等重放"}

        # Step 3: from_state 校验
        if rec is None:
            if from_state is not None:
                return reject("STALE_FROM_STATE", "无记录但指定了 from_state")
        elif from_state is not None and rec.get("state") != from_state.value:
            return reject("STALE_FROM_STATE",
                          f"记录为 {rec.get('state')}，期望 {from_state.value}")

        cur = VideoState(rec["state"]) if rec else None

        # Step 4: 跃迁合法性 + actor 权限
        rule, _ = _resolve_transition(cur, to_state, actor)
        if rule is None:
            return reject("ILLEGAL_TRANSITION",
                          f"{cur} -> {to_state} 不在跃迁表")
        if not _actor_match(rule["actors"], actor):
            return reject("ILLEGAL_TRANSITION",
                          f"actor {actor} 无权执行 {cur} -> {to_state}")

        # Step 2: lease（MUST-10）
        if rec and _lease_held_by_other(rec, actor, now):
            return reject("LEASE_HELD", f"被 {rec['lease']['holder']} 持有")
        lease = {"holder": actor,
                 "acquired_at": now.isoformat(),
                 "expires_at": (now + timedelta(seconds=lease_ttl_seconds)).isoformat()}

        # Step 6: 熔断器
        if _breaker_open(actor):
            return reject("BREAKER_OPEN", "circuit breaker 打开中")

        # Step 7: 豁免（MUST-12）
        if to_state in (VideoState.QUARANTINED, VideoState.INTENTIONAL_PRIVATE) \
                and is_exempt(video_key):
            return reject("EXEMPT", "exemption_registry 豁免中")

        # Step 8: receipt（MUST-8）
        if rule.get("guard") == "receipt":
            ok, msg = _verify_receipt(run_id)
            if not ok:
                _record_incident_sink(video_key, actor, run_id, msg)
                return reject("RECEIPT_UNVERIFIED", msg)

        # Step 9: 意图冲突（R-OPPOSE-1）
        conflicts = _check_intent_conflict(video_key, cur, to_state, actor)
        if conflicts:
            _record_incident_conflict(video_key, actor, cur, to_state, conflicts,
                                     f"INTENT_CONFLICT seq pending")
            return reject("INTENT_CONFLICT",
                          f"6h 内有 {len(conflicts)} 条对立跃迁")

        # Step 10: 接受
        if rec is None:
            rec = _new_record(video_key, to_state,
                              owner=STATE_META[to_state]["owner"])
        old_state = rec.get("state", "")
        rec["state"] = to_state.value
        rec["visibility_tag"] = VISIBILITY_TAG[to_state]
        rec["lease"] = lease
        rec["state_entered_at"] = now.isoformat()
        meta = STATE_META[to_state]
        rec["state_timeout_at"] = (now + timedelta(hours=meta["timeout_h"])).isoformat() \
            if meta["timeout_h"] else None
        if run_id:
            rec["run_id"] = run_id
        rec["updated_at"] = now.isoformat()

        seq = _chained_audit("transition", video_key, old_state, to_state.value,
                            actor, {"reason": reason, "run_id": run_id,
                                    "idempotency_key": key})
        rec["last_transition_seq"] = seq
        # 释放 lease（跃迁完成）
        rec["lease"] = {"holder": None, "acquired_at": None, "expires_at": None}
        state[video_key] = rec
        save_state(state)

        # 冲突决议 1：跃迁成功 → approval TTL lease 恢复计时
        try:
            from approval_lease import resume_lease
            resume_lease(video_key, "transition_accepted")
        except Exception as e:
            print(f"WARN: lease resume 失败: {e}", file=sys.stderr)

        result = {"accepted": True, "rejection_code": None, "seq": seq,
                  "idempotency_key": key, "duplicate": False}
        index[key] = result
        save_index(index)

        # 发射执行器命令（MUST-7）
        cmd = rule.get("command")
        if cmd:
            try:
                from executor import emit_command
                emit_command(cmd, video_key,
                             cur.value if cur else "none", to_state.value,
                             key, actor, reason, run_id)
            except Exception as e:
                print(f"WARN: emit_command 失败: {e}", file=sys.stderr)

        return result


def _record_incident_sink(video_key, actor, run_id, msg):
    try:
        from judgment import append_incident
        append_incident(video_key,
                        [{"action": "INGEST_ARTIFACT", "actor": actor,
                          "at": _now_utc().isoformat(),
                          "transition": "GENERATING->READY_TO_UPLOAD"}],
                        "R-SINK-5", gate_decision=f"rejected RECEIPT_UNVERIFIED: {msg}")
    except Exception as e:
        print(f"WARN: incident 记录失败: {e}", file=sys.stderr)


def _record_incident_conflict(video_key, actor, cur, to_state, conflicts, gate_decision):
    try:
        from judgment import append_incident
        actions = [{"action": "opposing_transition", "actor": c.get("actor", ""),
                    "at": c.get("ts", ""),
                    "transition": f"{c.get('old_status','')}->{c.get('new_status','')}"}
                   for c in conflicts]
        actions.append({"action": f"attempt_{(cur.value if cur else 'none')}->{to_state.value}",
                        "actor": actor, "at": _now_utc().isoformat(),
                        "transition": f"{cur}->{to_state}"})
        append_incident(video_key, actions, "R-OPPOSE-1", gate_decision=gate_decision)
    except Exception as e:
        print(f"WARN: incident 记录失败: {e}", file=sys.stderr)


def _admin_revert(video_key, to_state, reason):
    """管理修正：do_fn 失败且正常补偿不可行时（如终态 DELETED）的记录回滚。
    审计留痕，非正常跃迁，仅用于 API 副作用失败的纠错。"""
    with _global_state_lock():
        state = load_state()
        rec = state.get(video_key)
        if not rec:
            return
        old = rec.get("state", "")
        rec["state"] = to_state.value
        rec["visibility_tag"] = VISIBILITY_TAG[to_state]
        rec["lease"] = {"holder": None, "acquired_at": None, "expires_at": None}
        rec["updated_at"] = _now_utc().isoformat()
        save_state(state)
    _chained_audit("admin_revert", video_key, old, to_state.value,
                   "system", {"reason": reason})


def gated_mutation(video_key, from_state, to_state, actor, reason, do_fn,
                   run_id=None, ensure_state=None):
    """两阶段门控变更：transition() 授权 → do_fn() 执行副作用 → 失败则补偿回滚。

    ensure_state: 若无记录，先以该状态建记录（迁移用）。
    返回 (transition_result, do_result)。
    """
    if ensure_state is not None:
        with _global_state_lock():
            state = load_state()
            if video_key not in state:
                state[video_key] = _new_record(video_key, VideoState(ensure_state),
                                               owner=STATE_META[VideoState(ensure_state)]["owner"])
                save_state(state)
    tr = transition(video_key, from_state, to_state, actor, reason, run_id=run_id)
    if not tr["accepted"]:
        return tr, None
    try:
        do_result = do_fn()
    except Exception as e:
        # 补偿：先尝试正常跃迁回去；终态等不可行时用管理修正
        try:
            back = transition(video_key, to_state, from_state, "system",
                              reason=f"compensate_api_failure:{str(e)[:80]}",
                              run_id=run_id)
            if not back["accepted"]:
                _admin_revert(video_key, from_state,
                              f"compensate_rejected:{back['rejection_code']}")
        except Exception:
            try:
                _admin_revert(video_key, from_state, "compensate_exception")
            except Exception as ce2:
                print(f"WARN: 管理回滚失败: {ce2}", file=sys.stderr)
        raise
    return tr, do_result


def check_timeouts(now=None):
    """超时扫描（供 nightly sweeper）：返回 [(video_key, timeout_action)]。"""
    now = now or _now_utc()
    out = []
    for vk, rec in load_state().items():
        ta = rec.get("state_timeout_at")
        if not ta:
            continue
        try:
            if now > datetime.fromisoformat(ta):
                meta = STATE_META[VideoState(rec["state"])]
                out.append((vk, meta["timeout_action"], rec["state"]))
        except Exception:
            continue
    return out


if __name__ == "__main__":
    # 自检：三态映射 + 跃迁表完整性
    assert set(VISIBILITY_TAG.values()) == {"MANAGED_SCHEDULED_DRAFT",
                                            "QUARANTINED_LOW_VIEW", "STABLE_LIVE"}
    for (f, t) in TRANSITIONS:
        assert t in VideoState and (f is None or f in VideoState)
    print(f"pipeline_state 自检通过：{len(TRANSITIONS)} 条跃迁，{len(VideoState)} 状态")
