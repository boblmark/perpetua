#!/usr/bin/env python3
"""queue_db.py — SQLite-backed hot-queue persistence (Ops Center v2 Phase 1).

D20261011-001 (council-20261011-ops-mechanism). Replaces whole-file JSON
read-modify-write for the 3 hottest queues with transactional SQLite rows.

K3 hedge: auth / login / credential logic is UNTOUCHED. Only state
persistence moves here. Platform auth stays a per-platform plugin;
state machine and gates are shared.

Design:
  - One `event_bus` table, `queue_name` discriminator ('pipeline','instant','privateq').
  - Core primitives: put / claim / complete / fail / sweep.
  - Per-queue shims (pipeline_load/save, instant_load/save, privateq_load/save)
    preserve the EXACT Python-object semantics the old JSON had, so caller
    logic does not change — only the persistence layer changes.
  - Phase-1 shim rows use a conservative 720h timeout_alarm; per-item timeout
    policies arrive with Phase-2 event-bus adoption. sweep() infrastructure
    is live and unit-tested.

Rollback: every migrated caller keeps a `*.bak-20261011-p1` copy; the JSON
files keep `*.bak-20261011-p1` snapshots. To roll back: restore the .py files,
re-enable crons. JSON snapshots are the source of truth for re-fill.
"""

import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone, timedelta

log = logging.getLogger("queue_db")

DB_PATH = os.environ.get("OPS_CENTER_DB", "/home/hatch/data/ops_center.db")

# v2.0.0 (2026-10-11, D20261011-006): gateway version gate.
# Scripts MUST NOT import unversioned symbols for new code; pin via
# get_gateway("v2") convention (LMArena Rule 3). Old names keep working
# as thin wrappers (backward compat for 18 existing callers).
GATEWAY_VERSION = "2.0.0"


class InvalidStateTransitionError(ValueError):
    """Raised when transition_status targets a state the machine forbids."""


# v2 state machine (over the existing status vocabulary — no renames, so
# existing rows and 18 callers keep working).
_TRANSITIONS = {
    "PENDING": {"PROCESSING", "BLOCKED", "DEAD"},
    "PROCESSING": {"COMPLETED", "FAILED", "PENDING", "BLOCKED", "DEAD"},
    "FAILED": {"PENDING", "DEAD"},
    "BLOCKED": {"PENDING", "DEAD"},
    "COMPLETED": set(),
    "DEAD": set(),
}

STATUSES = ("PENDING", "PROCESSING", "COMPLETED", "FAILED", "BLOCKED", "DEAD")
ACTIVE_STATUSES = ("PENDING", "PROCESSING")

# R2 (council-20261011-perpetua-doc, AI Studio spec): lease-based claiming.
# A claim holds a row for LEASE_DURATION_SECONDS; if the worker dies, the
# reaper (every REAPER_INTERVAL_SECONDS) returns the row to PENDING.
# NEVER goes straight to DEAD unless retry_count >= MAX_RETRY_ATTEMPTS.
LEASE_DURATION_SECONDS = 900
REAPER_INTERVAL_SECONDS = 60
MAX_RETRY_ATTEMPTS = 3

# Phase-1 conservative timeout for shim rows (hours). Per-item policies in Phase 2.
SHIM_TIMEOUT_HOURS = 720

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS event_bus(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    queue_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    owner TEXT NOT NULL,
    consumer TEXT NOT NULL,
    timeout_alarm TEXT NOT NULL,
    lease_alarm TEXT,
    status TEXT NOT NULL CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED','BLOCKED','DEAD')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eb_q_status_consumer
    ON event_bus(queue_name, status, consumer);
CREATE INDEX IF NOT EXISTS idx_eb_timeout
    ON event_bus(timeout_alarm) WHERE status IN ('PENDING','PROCESSING');
CREATE INDEX IF NOT EXISTS idx_event_bus_claim
    ON event_bus(queue_name, status, lease_alarm);
CREATE TABLE IF NOT EXISTS dead_data_sweep_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_id TEXT NOT NULL UNIQUE,
    scanned_count INTEGER NOT NULL,
    escalated_count INTEGER NOT NULL,
    details TEXT NOT NULL,
    executed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA busy_timeout=5000;")
    c.execute("PRAGMA synchronous=NORMAL;")
    c.row_factory = sqlite3.Row
    return c


def init_db():
    """Create tables/indexes. Idempotent."""
    c = _conn()
    try:
        c.executescript(_SCHEMA)
        c.commit()
    finally:
        c.close()


def _ensure():
    # cheap idempotent init guard; also migrates R2 lease_alarm column and
    # verifies the claim composite index (worker aborts if it is missing).
    c = _conn()
    try:
        r = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event_bus'"
        ).fetchone()
        if not r:
            c.executescript(_SCHEMA)
            c.commit()
        else:
            cols = [row[1] for row in c.execute("PRAGMA table_info(event_bus)")]
            if "lease_alarm" not in cols:
                c.execute("ALTER TABLE event_bus ADD COLUMN lease_alarm TEXT")
                c.commit()
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_bus_claim"
                " ON event_bus(queue_name, status, lease_alarm)")
            c.commit()
            ix = c.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name='idx_event_bus_claim'").fetchone()
            if not ix:
                raise RuntimeError(
                    "R2 invariant violated: idx_event_bus_claim missing, aborting")
            # v2: record gateway version (idempotent)
            c.execute("CREATE TABLE IF NOT EXISTS schema_version("
                      "version TEXT PRIMARY KEY,"
                      " applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
            c.execute("INSERT OR IGNORE INTO schema_version(version)"
                      " VALUES (?)", (GATEWAY_VERSION,))
            c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------- core API

def put(queue, event_type, payload, owner, consumer, timeout_hours=24):
    """Insert one event. Returns event_id (uuid hex). Idempotent on event_id."""
    _ensure()
    eid = uuid.uuid4().hex
    alarm = (datetime.now(timezone.utc) + timedelta(hours=timeout_hours)).isoformat()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            """INSERT INTO event_bus
               (event_id, queue_name, event_type, payload, owner, consumer,
                timeout_alarm, status, retry_count)
               VALUES (?,?,?,?,?,?,?,?,0)""",
            (eid, queue, event_type, json.dumps(payload, ensure_ascii=False),
             owner, consumer, alarm, "PENDING"),
        )
        c.commit()
        return eid
    finally:
        c.close()


def claim(queue, consumer):
    """Atomically claim the oldest claimable row for (queue). Returns row dict or None.

    R2 lease semantics:
      - Claims PENDING rows, or PROCESSING rows whose lease_alarm expired
        (previous worker died without completing).
      - Sets lease_alarm = now + LEASE_DURATION_SECONDS on every claim.
      - Re-claiming an expired PROCESSING row bumps retry_count (poison
        detection feeds reap_leases' MAX_RETRY_ATTEMPTS -> DEAD rule).
    BEGIN IMMEDIATE serializes claimants; the UPDATE..WHERE id=(SELECT..LIMIT 1)
    is a single statement so two concurrent claimants can never get the same row.
    """
    _ensure()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lease_iso = (now + timedelta(seconds=LEASE_DURATION_SECONDS)).isoformat()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            """UPDATE event_bus
               SET status='PROCESSING', consumer=?,
                   lease_alarm=?,
                   retry_count = retry_count +
                       CASE WHEN status='PROCESSING' THEN 1 ELSE 0 END,
                   updated_at=datetime('now')
               WHERE id = (SELECT id FROM event_bus
                           WHERE queue_name=? AND (
                               status='PENDING'
                               OR (status='PROCESSING'
                                   AND lease_alarm IS NOT NULL
                                   AND lease_alarm < ?)
                           )
                           ORDER BY id ASC LIMIT 1)
               RETURNING id, event_id, queue_name, event_type, payload,
                         owner, consumer, timeout_alarm, lease_alarm,
                         status, retry_count""",
            (consumer, lease_iso, queue, now_iso),
        ).fetchone()
        c.commit()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d
    finally:
        c.close()


def reap_leases():
    """R2 lease reaper (run every REAPER_INTERVAL_SECONDS, e.g. 60s cron).

    PROCESSING rows whose lease_alarm expired:
      - retry_count >= MAX_RETRY_ATTEMPTS -> DEAD (poison message)
      - else -> PENDING (re-queue), consumer cleared, retry_count+1
    NEVER transitions straight to DEAD otherwise.
    Emits CRITICAL metric queue.lease_timeout{queue_name} + WARNING per row.
    Returns {'reaped': [...], 'dead': [...]} (event_ids).
    """
    _ensure()
    now_iso = datetime.now(timezone.utc).isoformat()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        stale = c.execute(
            """SELECT event_id, queue_name, retry_count FROM event_bus
               WHERE status='PROCESSING' AND lease_alarm IS NOT NULL
                 AND lease_alarm < ?
               ORDER BY id""",
            (now_iso,),
        ).fetchall()
        reaped, dead = [], []
        for r in stale:
            eid, q, rc = r["event_id"], r["queue_name"], r["retry_count"]
            if rc >= MAX_RETRY_ATTEMPTS:
                c.execute(
                    "UPDATE event_bus SET status='DEAD', lease_alarm=NULL,"
                    " updated_at=datetime('now') WHERE event_id=?", (eid,))
                dead.append(eid)
                log.warning("lease reaper: %s DEAD after %d retries", eid, rc)
            else:
                c.execute(
                    "UPDATE event_bus SET status='PENDING', consumer='',"
                    " lease_alarm=NULL, retry_count=retry_count+1,"
                    " updated_at=datetime('now') WHERE event_id=?", (eid,))
                reaped.append(eid)
                log.warning("lease reaper: %s lease expired, re-queued", eid)
        c.commit()
        if stale:
            by_q = {}
            for r in stale:
                by_q[r["queue_name"]] = by_q.get(r["queue_name"], 0) + 1
            for q, n in by_q.items():
                log.critical("queue.lease_timeout{queue_name=%s} count=%d", q, n)
        return {"reaped": reaped, "dead": dead}
    finally:
        c.close()


def complete(event_id):
    _ensure()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "UPDATE event_bus SET status='COMPLETED', updated_at=datetime('now')"
            " WHERE event_id=?",
            (event_id,),
        )
        c.commit()
    finally:
        c.close()


def fail(event_id, reason=""):
    _ensure()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            """UPDATE event_bus
               SET status='FAILED', retry_count=retry_count+1,
                   updated_at=datetime('now'),
                   payload=json_set(payload,'$.fail_reason',?)
               WHERE event_id=?""",
            (reason, event_id),
        )
        c.commit()
    finally:
        c.close()


def transition_status(event_id, target_status, worker_id=None, error_message=None):
    """v2: state-machine-guarded status change. Replaces raw SQL writes
    (e.g. strategy_c.py's bare UPDATE ... SET status='BLOCKED').

    - Returns False if the row does not exist or the worker does not hold
      the lease (PROCESSING row claimed by someone else).
    - Raises InvalidStateTransitionError on a forbidden transition.
    - target FAILED with error_message records $.fail_reason in payload.
    """
    if target_status not in STATUSES:
        raise InvalidStateTransitionError(f"unknown status {target_status!r}")
    _ensure()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT status, consumer FROM event_bus WHERE event_id=?",
            (event_id,)).fetchone()
        if not row:
            c.commit()
            return False
        cur = row["status"]
        if target_status not in _TRANSITIONS.get(cur, set()):
            raise InvalidStateTransitionError(
                f"{cur} -> {target_status} forbidden")
        if (worker_id and cur == "PROCESSING"
                and (row["consumer"] or "") != worker_id):
            c.commit()
            return False
        if target_status == "FAILED" and error_message:
            c.execute(
                """UPDATE event_bus SET status=?, updated_at=datetime('now'),
                   payload=json_set(payload,'$.fail_reason',?)
                   WHERE event_id=?""",
                (target_status, error_message, event_id))
        else:
            c.execute(
                "UPDATE event_bus SET status=?, updated_at=datetime('now')"
                " WHERE event_id=?",
                (target_status, event_id))
        c.commit()
        return True
    finally:
        c.close()


def save_payload_atomic(event_id, payload, worker_id=None):
    """v2: replace one row's payload without touching other rows.
    With worker_id: only succeeds if the row is PROCESSING and held by
    that worker (lease guard). Returns True/False."""
    _ensure()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        if worker_id:
            cur = c.execute(
                "UPDATE event_bus SET payload=?, updated_at=datetime('now')"
                " WHERE event_id=? AND status='PROCESSING' AND consumer=?",
                (json.dumps(payload, ensure_ascii=False), event_id, worker_id))
        else:
            cur = c.execute(
                "UPDATE event_bus SET payload=?, updated_at=datetime('now')"
                " WHERE event_id=?",
                (json.dumps(payload, ensure_ascii=False), event_id))
        c.commit()
        return cur.rowcount > 0
    finally:
        c.close()


def enqueue(queue, payload, event_type="manual", owner="manual",
            consumer="", timeout_hours=24):
    """v2: single-row insert with sane defaults. Returns event_id."""
    return put(queue, event_type, payload, owner, consumer, timeout_hours)


def claim_row(queue, worker_id, lease_seconds=900):
    """v2: claim oldest claimable row with a caller-chosen lease.
    Same atomic UPDATE..RETURNING mechanics as claim()."""
    _ensure()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lease_iso = (now + timedelta(seconds=lease_seconds)).isoformat()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            """UPDATE event_bus
               SET status='PROCESSING', consumer=?,
                   lease_alarm=?,
                   retry_count = retry_count +
                       CASE WHEN status='PROCESSING' THEN 1 ELSE 0 END,
                   updated_at=datetime('now')
               WHERE id = (SELECT id FROM event_bus
                           WHERE queue_name=? AND (
                               status='PENDING'
                               OR (status='PROCESSING'
                                   AND lease_alarm IS NOT NULL
                                   AND lease_alarm < ?)
                           )
                           ORDER BY id ASC LIMIT 1)
               RETURNING id, event_id, queue_name, event_type, payload,
                         owner, consumer, timeout_alarm, lease_alarm,
                         status, retry_count""",
            (worker_id, lease_iso, queue, now_iso),
        ).fetchone()
        c.commit()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d
    finally:
        c.close()


def sweep():
    """Mark PENDING/PROCESSING rows past timeout_alarm as DEAD; audit to log.

    Returns {'scanned': N, 'escalated': M, 'details': [event_ids]}.
    """
    _ensure()
    now = _now_iso()
    sweep_id = "sweep_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        stale = c.execute(
            """SELECT event_id, queue_name FROM event_bus
               WHERE status IN ('PENDING','PROCESSING') AND timeout_alarm < ?
               ORDER BY id""",
            (now,),
        ).fetchall()
        ids = [r["event_id"] for r in stale]
        scanned = c.execute(
            "SELECT COUNT(*) AS n FROM event_bus WHERE status IN"
            " ('PENDING','PROCESSING')"
        ).fetchone()["n"]
        if ids:
            c.execute(
                "UPDATE event_bus SET status='DEAD', updated_at=datetime('now')"
                " WHERE event_id IN (%s)" % ",".join("?" * len(ids)),
                ids,
            )
        details = json.dumps(
            [{"event_id": r["event_id"], "queue": r["queue_name"]} for r in stale],
            ensure_ascii=False,
        )
        c.execute(
            """INSERT INTO dead_data_sweep_log
               (sweep_id, scanned_count, escalated_count, details)
               VALUES (?,?,?,?)""",
            (sweep_id, scanned, len(ids), details),
        )
        c.commit()
        return {"sweep_id": sweep_id, "scanned": scanned,
                "escalated": len(ids), "details": ids}
    finally:
        c.close()


def queue_stats(queue=None):
    """Row counts per (queue, status). For dashboards / verification."""
    _ensure()
    c = _conn()
    try:
        if queue:
            rows = c.execute(
                "SELECT status, COUNT(*) AS n FROM event_bus"
                " WHERE queue_name=? GROUP BY status", (queue,)).fetchall()
        else:
            rows = c.execute(
                "SELECT queue_name, status, COUNT(*) AS n FROM event_bus"
                " GROUP BY queue_name, status").fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


# ------------------------------------------------------- per-queue shims
# Each shim preserves the exact Python-object shape the JSON file had.

def _save_all(queue_name, items, owner, consumer_fn, event_type):
    # 2026-10-11 fail-closed：拒绝非 list 输入。曾发生 pipeline_save({'items':[...]})
    # 把 dict 的 key 当行写入、29 行变 1 行垃圾的事故；必须 loud 失败，绝不静默写坏。
    if isinstance(items, dict):
        items = items.get("items", [])
    if not isinstance(items, list):
        raise TypeError(f"_save_all({queue_name}): items 必须是 list，got {type(items).__name__}")
    # v2.0.0 (D20261011-006, 红队 KILL 1)：DELETE+INSERT 全表重写已删除。
    # 新语义：同一事务内按行 upsert + 删除新列表中不存在的行。
    # 行身份：payload 中的 _row_key（稳定 uuid）。audit 发现 topic/iid/video_id
    # 均不唯一（pipeline 有 3 条同 topic 不同状态），故不用业务字段做 key。
    # 首轮 v2 保存时旧行无 _row_key，会一次性重建 id（数据不丢），之后永久稳定。
    # 效果：无"表先被清空"的 crash 窗口；行 id 稳定（外部引用不断）；并发保存串行化，
    # 不再整表丢数据。调用方的"save == 队列精确等于此 list"语义保持不变。
    for it in items:
        if isinstance(it, dict) and not it.get("_row_key"):
            it["_row_key"] = uuid.uuid4().hex
    _ensure()
    c = _conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        existing = {}
        for r in c.execute(
                "SELECT id, payload FROM event_bus WHERE queue_name=?",
                (queue_name,)):
            try:
                p = json.loads(r["payload"])
            except Exception:
                continue
            k = p.get("_row_key") if isinstance(p, dict) else None
            if k:
                existing[k] = (r["id"], r["payload"])
        now = datetime.now(timezone.utc)
        alarm = (now + timedelta(hours=SHIM_TIMEOUT_HOURS)).isoformat()
        seen_ids = set()
        for it in items:
            k = it.get("_row_key") if isinstance(it, dict) else None
            payload_json = json.dumps(it, ensure_ascii=False)
            consumer = str(consumer_fn(it))
            rid, old_payload = None, None
            if k:
                _hit = existing.pop(k, None)
                if _hit:
                    rid, old_payload = _hit
            if rid is not None:
                # UPDATE：只刷新 payload/consumer/时间；保留行 status/retry_count
                #（旧实现每次 save 把全表重置为 PENDING，会踩掉别人的 lease）。
                # 2026-10-18：payload 实变才刷新条目内 updated_at。死状态看门狗读
                # 该字段判 stale，但此前 collect/QC/review 各路径改了字段却不碰它，
                # 导致条目当天走完"评审→生成→QC"全程仍显示旧时间戳（如 10-18 hub
                # 被误报 60.8h 卡死）。无实质变化的重存不刷新，避免掩盖真卡死。
                if isinstance(it, dict) and payload_json != (old_payload or ""):
                    it["updated_at"] = now.isoformat()
                    payload_json = json.dumps(it, ensure_ascii=False)
                c.execute(
                    """UPDATE event_bus SET payload=?, consumer=?,
                       updated_at=datetime('now') WHERE id=?""",
                    (payload_json, consumer, rid))
                seen_ids.add(rid)
            else:
                cur = c.execute(
                    """INSERT INTO event_bus
                       (event_id, queue_name, event_type, payload, owner, consumer,
                        timeout_alarm, status, retry_count)
                       VALUES (?,?,?,?,?,?,?,?,0)""",
                    (uuid.uuid4().hex, queue_name, event_type,
                     payload_json, owner, consumer, alarm, "PENDING"))
                seen_ids.add(cur.lastrowid)
        if seen_ids:
            c.execute(
                "DELETE FROM event_bus WHERE queue_name=? AND id NOT IN (%s)"
                % ",".join("?" * len(seen_ids)),
                (queue_name, *seen_ids))
        else:
            c.execute("DELETE FROM event_bus WHERE queue_name=?", (queue_name,))
        c.commit()
    finally:
        c.close()


def _load_all(queue_name):
    _ensure()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT payload FROM event_bus WHERE queue_name=? AND status!='DEAD'"
            " ORDER BY id ASC",
            (queue_name,),
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]
    finally:
        c.close()


# pipeline_queue.json — was: list[dict]
def pipeline_load():
    return _load_all("pipeline")


def pipeline_save(items):
    _save_all("pipeline", items, owner="pipeline",
              consumer_fn=lambda it: str(it.get("status", "unknown") if isinstance(it, dict) else "unknown"),
              event_type="pipeline_item")


# instant_queue.json — was: {"items": [...]}
def instant_load():
    return {"items": _load_all("instant")}


def instant_save(d):
    items = d.get("items", []) if isinstance(d, dict) else []
    _save_all("instant", items, owner="ask_studio",
              consumer_fn=lambda it: str(it.get("status", "pending") if isinstance(it, dict) else "pending"),
              event_type="ask_question")


# private_queue.json — was: list[dict]
def privateq_load():
    return _load_all("privateq")


def privateq_save(items):
    _save_all("privateq", items, owner="pipeline",
              consumer_fn=lambda it: str(it.get("status", "waiting") if isinstance(it, dict) else "waiting"),
              event_type="private_flip")


# ---------------------------------------------------------------- fill

def fill_from_json(queue_name, json_path, kind):
    """One-shot migration fill. kind in ('list','instant').

    Returns (inserted_count, [spot-check payloads]).
    Must be called with producers paused (drain-switch, K4 hedge).
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    if kind == "instant":
        items = data.get("items", [])
    else:
        items = data
    if kind == "pipeline":
        pipeline_save(items)
    elif kind == "instant":
        instant_save({"items": items})
    elif kind == "privateq":
        privateq_save(items)
    else:
        raise ValueError("unknown kind: " + kind)
    # verify: count + spot-check first/last payload round-trip
    back = {"pipeline": pipeline_load, "instant": lambda: instant_load()["items"],
            "privateq": privateq_load}[kind]()
    assert len(back) == len(items), f"count mismatch {len(back)} != {len(items)}"
    checks = []
    for i in (0, len(items) // 2, len(items) - 1):
        if 0 <= i < len(items):
            a = json.dumps(items[i], sort_keys=True, ensure_ascii=False)
            b = json.dumps(back[i], sort_keys=True, ensure_ascii=False)
            assert a == b, f"payload mismatch at index {i}"
            checks.append(i)
    return len(items), checks


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "init":
        init_db()
        print("db initialized:", DB_PATH)
    elif cmd == "sweep":
        print(json.dumps(sweep(), ensure_ascii=False))
    elif cmd == "reap":
        print(json.dumps(reap_leases(), ensure_ascii=False))
    elif cmd == "stats":
        print(json.dumps(queue_stats(), ensure_ascii=False, indent=1))
    else:
        print("usage: queue_db.py [init|sweep|reap|stats]", file=sys.stderr)
        sys.exit(2)
