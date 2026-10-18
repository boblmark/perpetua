#!/usr/bin/env python3
"""
分级断言底座（2026-10-15 四脑议会 D20261015-006/007/008，红队 R1-R5 修订后实施）

模式根治：检查器自身故障 → 被检查对象背锅 → fail-closed 饿死管线。
每个看门狗结论分三级：
  OK        — 检查器健康 + 新鲜 TTL 内证据 + 条件验证正常
  SUSPECT   — 检查器自身可能坏了（登录页/SSH 超时/空队列口径/证据过期/无佐证）
              → 永不触发状态机跃迁，只写结构化日志 + anomaly ledger + 升级主 agent
  CONFIRMED — 检查器健康 + 新鲜证据 + 口径对当前状态有效 → 唯一允许翻转状态/写分数

发布门（D20261015-008 用户拍板）："CONFIRMED 通过才发布"。
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))

OK = "OK"
SUSPECT = "SUSPECT"
CONFIRMED = "CONFIRMED"

# 证据 TTL 表（秒）— AI Studio 规格 §4
TTL = {
    "review_answer": 3600,      # 评审答案 60min
    "session_state": 900,       # 登录/会话态 15min
    "consumer_heartbeat": 1800, # 消费者心跳 30min
    "queue_snapshot": 600,      # 队列快照 10min
    "browser_handoff": 2400,    # 浏览器回传 40min
}

LEDGER_PATH = os.path.join(BASE, "anomaly_ledger.json")
LEDGER_DEDUP_TTL_S = 6 * 3600  # 同一 (checker,subject,verdict) 6h 内不重复写新条目
ESCALATION_PATH = os.path.join(BASE, "escalation_inbox.json")

# 具名 fallback 响应人（R4）：升级无人 ack 时的接手链
FALLBACK_CHAIN = ["dash_main", "user_direct"]
# SUSPECT-forever 熔断（R2）：同一 subject 持续 SUSPECT 超过此时长 → 自动 P1
SUSPECT_FOREVER_SECONDS = 6 * 3600
# 升级 SLA（R4）：T+2h 未 ack 重升级+分页，T+6h 升 P1
SLA_REESCALATE_SECONDS = 2 * 3600
SLA_P1_SECONDS = 6 * 3600
# SUSPECT 风暴限流（R4）：同一 dedup key 的升级合并，指数退避
STORM_BASE_SECONDS = 86400  # 24h：同一 subject+condition 未 ack 的升级 24h 内复用同一 escalation ID，
                           # 不再每轮看门狗新建一条 P1/PAGE（2026-10-16：30min 窗口约等于看门狗周期导致慢性条件每轮建单，风暴）
                           # N9：去重命中不重置 ack SLA 计时器，sla_due 照常对原记录 T+2h 分页/T+6h 升 P1


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def evidence_fresh(evidence_ts, ttl_seconds):
    """证据是否在 TTL 内。时间戳缺失/不可解析 → 不新鲜。"""
    if not evidence_ts:
        return False
    try:
        dt = datetime.fromisoformat(str(evidence_ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return 0 <= age <= ttl_seconds
    except Exception:
        return False


def make_verdict(verdict, detail, evidence_ts=None, ttl_key=None,
                 checker=None, subject=None, checker_health=None):
    """构造分级断言记录。M1：每个 verdict 必须带证据时间戳和 TTL。"""
    rec = {
        "verdict": verdict,
        "detail": detail,
        "evidence_timestamp": evidence_ts,
        "ttl_seconds": TTL.get(ttl_key, 0) if ttl_key else 0,
        "checker": checker,
        "subject": subject,
        "checker_health": checker_health or {},
        "at": utcnow(),
    }
    return rec


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def dedup_key(checker, subject, condition):
    """M10：去重 key 剥离易变字段（时间戳/计数/PID）后再 hash。"""
    raw = f"{checker}|{subject}|{condition}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------- anomaly ledger（R1：SUSPECT 必须留机器可读痕迹） ----------------

def ledger_append(verdict_rec):
    """SUSPECT 写入 anomaly ledger：非分数、非跃迁，但可查询。KILL#5 的修订。

    2026-10-18 dedup：同一 (checker, subject, verdict) 在 LEDGER_DEDUP_TTL_S 内
    已有未解决条目时跳过追加——同一持久状态每轮写一条会淹没台账
    （如 h3 断开数日，重复写 236 条）。首条保留作为"当前态"记录，
    状态翻转时再写新条目（resolve/新 verdict 触发）。
    """
    ledger = _load(LEDGER_PATH, [])
    c, s, v = (verdict_rec.get("checker"), verdict_rec.get("subject"),
               verdict_rec.get("verdict"))
    now = time.time()
    for e in ledger:
        if (not e.get("resolved") and e.get("checker") == c
                and e.get("subject") == s and e.get("verdict") == v):
            try:
                at_ts = time.mktime(time.strptime(e.get("at", "")[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                continue
            if now - at_ts < LEDGER_DEDUP_TTL_S:
                # 刷新证据时间戳，保持"当前态"新鲜，不写新条目
                e["evidence_timestamp"] = verdict_rec.get("evidence_timestamp")
                e["detail"] = verdict_rec.get("detail")
                _save(LEDGER_PATH, ledger[-500:])
                return e["id"]
    entry = {
        "id": f"an-{int(time.time())}-{os.getpid()}",
        "at": utcnow(),
        "checker": verdict_rec.get("checker"),
        "subject": verdict_rec.get("subject"),
        "verdict": verdict_rec.get("verdict"),
        "detail": verdict_rec.get("detail"),
        "evidence_timestamp": verdict_rec.get("evidence_timestamp"),
        "checker_health": verdict_rec.get("checker_health"),
        "resolved": False,
    }
    ledger.append(entry)
    # 只保留最近 500 条
    _save(LEDGER_PATH, ledger[-500:])
    return entry["id"]


def ledger_collapse(checker, subject):
    """把同一 (checker, subject) 的重复未解决条目收敛为最新一条，其余标记 resolved。

    用于 2026-10-18 台账清理：h3 等持久态已堆积数百条重复条目，保留最新
    一条作为当前态代表（anomaly-watchdog 的计数会随之回落到真实水平）。
    """
    ledger = _load(LEDGER_PATH, [])
    matches = [e for e in ledger if not e.get("resolved")
               and e.get("checker") == checker and e.get("subject") == subject]
    if len(matches) <= 1:
        return len(matches)
    matches.sort(key=lambda e: e.get("at", ""))
    for e in matches[:-1]:
        e["resolved"] = True
        e["resolved_at"] = utcnow()
        e["resolved_reason"] = "dedup-collapse: 同一状态重复条目收敛，保留最新一条"
    _save(LEDGER_PATH, ledger)
    return 1


def ledger_unresolved(subject=None, checker=None):
    ledger = _load(LEDGER_PATH, [])
    out = [e for e in ledger if not e.get("resolved")]
    if subject:
        out = [e for e in out if e.get("subject") == subject]
    if checker:
        out = [e for e in out if e.get("checker") == checker]
    return out


def ledger_resolve(entry_id):
    ledger = _load(LEDGER_PATH, [])
    for e in ledger:
        if e.get("id") == entry_id:
            e["resolved"] = True
            e["resolved_at"] = utcnow()
    _save(LEDGER_PATH, ledger)


# ---------------- 升级契约（R4） ----------------

def escalate(checker, subject, condition, severity="P2", detail="",
             evidence_ts=None, ttl_key=None, checker_health=None):
    """
    SUSPECT 升级：写 escalation inbox，24h 去重，风暴限流，SLA 计时。
    返回 escalation 记录。N9：去重命中不重置 ack SLA 计时器。
    """
    inbox = _load(ESCALATION_PATH, [])
    key = dedup_key(checker, subject, condition)
    now = time.time()
    # 风暴限流：同一 key 24h 内已升级过 → 合并计数，不重复分页
    for e in inbox:
        if e.get("dedup_key") == key and not e.get("ack_at"):
            age = now - e.get("filed_at_epoch", 0)
            if age < STORM_BASE_SECONDS:
                e["storm_merged_count"] = e.get("storm_merged_count", 0) + 1
                _save(ESCALATION_PATH, inbox)
                return e
    rec = {
        "escalation_id": f"esc-{int(now)}-{key}",
        "dedup_key": key,
        "checker": checker,
        "subject": subject,
        "condition": condition,
        "severity": severity,
        "detail": detail,
        "evidence_timestamp": evidence_ts,
        "checker_health": checker_health or {},
        "filed_at": utcnow(),
        "filed_at_epoch": now,
        "ack_by": None,
        "ack_at": None,
        "fallback_stage": 0,  # 0=dash_main, 1=user_direct
        "storm_merged_count": 0,
        "pages_sent": 0,
    }
    inbox.append(rec)
    _save(ESCALATION_PATH, inbox[-200:])
    return rec


def escalate_ack(escalation_id, by="dash_main"):
    """N8：只有主 agent ack 能停 SLA 计时器。"""
    inbox = _load(ESCALATION_PATH, [])
    for e in inbox:
        if e.get("escalation_id") == escalation_id:
            e["ack_by"] = by
            e["ack_at"] = utcnow()
    _save(ESCALATION_PATH, inbox)


def sla_due():
    """返回到期的升级：T+2h 未 ack 需重升级+分页；T+6h 升 P1。"""
    inbox = _load(ESCALATION_PATH, [])
    now = time.time()
    due = []
    for e in inbox:
        if e.get("ack_at"):
            continue
        age = now - e.get("filed_at_epoch", 0)
        if age >= SLA_P1_SECONDS and e.get("severity") != "P1":
            due.append((e, "P1"))
        elif age >= SLA_REESCALATE_SECONDS and e.get("pages_sent", 0) == 0:
            due.append((e, "PAGE"))
    return due


def suspect_forever_check():
    """
    R2 SUSPECT-forever 熔断：同一 subject 持续 SUSPECT 超过 6h → 自动 P1 + 终端动作选项。
    返回需要升级的 subject 列表。
    """
    ledger = _load(LEDGER_PATH, [])
    now = time.time()
    by_subject = {}
    for e in ledger:
        if e.get("resolved") or e.get("verdict") != SUSPECT:
            continue
        by_subject.setdefault(e.get("subject"), []).append(e)
    out = []
    for subject, entries in by_subject.items():
        entries.sort(key=lambda x: x.get("at", ""))
        try:
            first = datetime.fromisoformat(entries[0]["at"])
            if first.tzinfo is None:
                first = first.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - first).total_seconds()
        except Exception:
            continue
        if age >= SUSPECT_FOREVER_SECONDS:
            # 查是否已为此 subject 发过 forever 熔断
            inbox = _load(ESCALATION_PATH, [])
            key = dedup_key("suspect_forever", subject, "forever")
            if not any(x.get("dedup_key") == key and not x.get("ack_at") for x in inbox):
                out.append(subject)
    return out
