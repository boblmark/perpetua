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
FIRST_SUSPECT_PATH = os.path.join(BASE, "suspect_first_at.json")
# C17（2026-10-29）：每 subject 首发 SUSPECT 时钟旁路文件。台账只留最近 500 条，
# 最早条目被截断会使 suspect_forever 计龄无声重置；此文件只记首发时间，
# resolve 清零后重建，永不依赖台账长度。

# 具名 fallback 响应人（R4）：升级无人 ack 时的接手链
FALLBACK_CHAIN = ["dash_main", "user_direct"]
# SUSPECT-forever 熔断（R2）：同一 subject 持续 SUSPECT 超过此时长 → 自动 P1
SUSPECT_FOREVER_SECONDS = 6 * 3600
# 升级 SLA（R4）：T+2h 未 ack 重升级+分页，T+6h 升 P1
SLA_REESCALATE_SECONDS = 2 * 3600
SLA_P1_SECONDS = 6 * 3600
# SUSPECT 风暴限流（R4）：同一 dedup key 的升级合并，指数退避
STORM_BASE_SECONDS = 86400  # 24h：同一 subject+condition 的升级 24h 内复用同一 escalation ID，
                           # 不再每轮看门狗新建一条 P1/PAGE（2026-10-16：30min 窗口约等于看门狗周期导致慢性条件每轮建单，风暴）
                           # 2026-10-21 修：ack 不解除 24h 去重保护——此前只合并未 ack 记录，主 agent ack 后下一轮必新建 P1，
                           # 形成"ack→新P1→ack"无限循环（00:23/00:50 两轮 forever/grader P1 重复触发实证）
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
                # 方案 3（2026-10-27）：ledger 的 at 是 UTC 串，mktime 按本地时区
                # 解析会算老 8 小时，导致 dedup TTL 永不命中、同一批 SUSPECT 每轮
                # 重写入账灌满 500 上限。改按 UTC 解析。
                at_ts = datetime.strptime(
                    e.get("at", "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=timezone.utc).timestamp()
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
    # C17：首发时钟旁路——只在新条目且 verdict 为 SUSPECT 时记首发时间；
    # dedup 命中刷新证据不碰首发时间；台账截断不再重置熔断时钟。
    if verdict_rec.get("verdict") == SUSPECT:
        try:
            first_map = _load(FIRST_SUSPECT_PATH, {})
            if not isinstance(first_map, dict):
                first_map = {}
            if verdict_rec.get("subject") not in first_map:
                first_map[verdict_rec.get("subject")] = entry["at"]
                _save(FIRST_SUSPECT_PATH, first_map)
        except Exception:
            pass
    return entry["id"]


def _prune_first_suspect(subject):
    """subject 无未解决 SUSPECT 时清掉首发时钟（下次 SUSPECT 重建）。"""
    try:
        ledger = _load(LEDGER_PATH, [])
        still = any(not e.get("resolved") and e.get("verdict") == SUSPECT
                    and e.get("subject") == subject for e in ledger)
        if still:
            return
        first_map = _load(FIRST_SUSPECT_PATH, {})
        if isinstance(first_map, dict) and subject in first_map:
            del first_map[subject]
            _save(FIRST_SUSPECT_PATH, first_map)
    except Exception:
        pass


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
    _prune_first_suspect(subject)  # C17：收敛后若无未解决项则清首发时钟
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
             evidence_ts=None, ttl_key=None, checker_health=None,
             new_episode=False):
    """
    SUSPECT 升级：写 escalation inbox，24h 去重，风暴限流，SLA 计时。
    返回 escalation 记录。N9：去重命中不重置 ack SLA 计时器。

    C18（2026-10-29，审计原文复核后有据取舍）：
    审计要求“旧记录已 ack 且条件重现时新建一条升级（附 recurrence_of），
    不再合并”。但逐项复核发现：本函数是每轮定时上报的持久条件上报口
    （dispatch_health 每 10 分钟 C1、anomaly_watchdog grader/suspect_forever、
    auto_pipeline gen_timeout 等），上报方无法区分“条件从未清除”与
    “清除后复发”——若把新建改为默认行为，2026-10-21 已实证的
    “ack→新P1→ack”无限循环会原样回归（每轮上报 + 一次 ack 即再建单）。
    故新建只作 opt-in：new_episode=True 且 24h 窗口内同 key 记录全已 ack
    时，才建新单并附 recurrence_of；窗口内只要还有一条未 ack 记录，
    仍合并进该记录（不因一次 ack 就对持久条件重复建单）。
    当前无任何调用方能证明自己只在“清除后复发”时上报，故本批无调用方
    传 new_episode=True；默认行为与修前一致。合并进已 ack 记录时仍递增
    storm_merged_count 并记 last_merged_at，复发痕迹可见。
    附带两处复发必需的修正：合并目标取窗口内最新未 ack 记录（旧单条时
    即唯一记录，行为不变）；同秒同 key 建单撞 id 时加 -n 后缀，否则
    ack 会同时关掉两个 episode。
    """
    inbox = _load(ESCALATION_PATH, [])
    key = dedup_key(checker, subject, condition)
    now = time.time()
    recurrence_of = None
    window = [e for e in inbox
              if e.get("dedup_key") == key
              and now - e.get("filed_at_epoch", 0) < STORM_BASE_SECONDS]
    if new_episode and window:
        # 复发通道：窗口内同 key 记录若全已 ack，视为新 episode，建新单；
        # 只要还有未 ack 记录，仍合并进最新未 ack 记录（持久条件不重复建单）。
        live = [e for e in window if not e.get("ack_at")]
        if live:
            target = live[-1]
            target["storm_merged_count"] = target.get("storm_merged_count", 0) + 1
            target["last_merged_at"] = utcnow()
            _save(ESCALATION_PATH, inbox)
            return target
        recurrence_of = window[-1].get("escalation_id")
    # 风暴限流：同一 key 24h 内已升级过 → 合并计数，不重复分页。
    # 2026-10-21 修：ack 不解除 24h 去重保护。旧逻辑只合并未 ack 记录，
    # 主 agent ack 后下一轮必新建 P1，形成"ack→新P1→ack"无限循环
    # （suspect_forever/grader 每 30min 各新建一条 P1 实证）。
    # N9：合并已 ack 记录时绝不碰 ack_at/ack_by，不重置 SLA 计时器。
    # C18：recurrence_of 已定时不走合并循环，直接建新单。
    # C18 补：复发后窗口内可有两条同 key 记录，合并目标取最新未 ack
    # 记录（旧单条时即唯一记录，行为不变）；若全已 ack 则并入最新一条。
    if recurrence_of is None and window:
        live = [e for e in window if not e.get("ack_at")]
        target = live[-1] if live else window[-1]
        target["storm_merged_count"] = target.get("storm_merged_count", 0) + 1
        target["last_merged_at"] = utcnow()
        _save(ESCALATION_PATH, inbox)
        return target
    # escalation_id 同秒同 key 可撞（旧格式 esc-<秒>-<key>）：复发单与旧单
    # 若同秒建单会同 id，ack 会同时关掉两个 episode；撞时加 -n 后缀保唯一。
    base_id = f"esc-{int(now)}-{key}"
    eid = base_id
    if any(e.get("escalation_id") == eid for e in inbox):
        n = 2
        while any(e.get("escalation_id") == f"{base_id}-{n}" for e in inbox):
            n += 1
        eid = f"{base_id}-{n}"
    rec = {
        "escalation_id": eid,
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
        "recurrence_of": recurrence_of,
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
    """返回到期的升级（C16，2026-10-29 修，旧逻辑只发一次 PAGE 后永久静默）：

    - 未 ack 且满 6h、severity 已是 P1、fallback_stage 仍为 0 → FALLBACK
      （消费方置 fallback_stage=1 并向用户侧写 urgent；此后不再重复触发，
      升级链至此走完，不再静默丢单）。
    - 未 ack 且满 6h、severity 非 P1 → P1（升格；下一轮检查若仍未 ack
      且已是 P1，即走 FALLBACK，不再等另一个 6h）。
    - 未 ack 且满 2h → PAGE，且每满 2h 重复一次：下一次分页到期点为
      (pages_sent+1)*2h（消费方每分页一次 pages_sent+1，故 2h/4h/6h…各发一次，
      不再以 pages_sent==0 作一次性门）；已走完 FALLBACK 的记录不再自动分页，
      用户侧 urgent 即终态（人工 ack 关闭）。
    - 已 ack 的记录永不返回。
    """
    inbox = _load(ESCALATION_PATH, [])
    now = time.time()
    due = []
    for e in inbox:
        if e.get("ack_at"):
            continue
        age = now - e.get("filed_at_epoch", 0)
        pages = e.get("pages_sent", 0)
        if (age >= SLA_P1_SECONDS and e.get("severity") == "P1"
                and e.get("fallback_stage", 0) == 0):
            due.append((e, "FALLBACK"))
        elif age >= SLA_P1_SECONDS and e.get("severity") != "P1":
            due.append((e, "P1"))
        elif (e.get("fallback_stage", 0) == 0
                and age >= (pages + 1) * SLA_REESCALATE_SECONDS):
            due.append((e, "PAGE"))
    return due


def ledger_resolve(checker, subject, reason=""):
    """台账自愈：当前轮结论为 OK/CONFIRMED 时，把同一 (checker, subject) 的
    未解决 SUSPECT 条目标记 resolved——未知状态已消除。

    2026-10-21 新增（builtin 实证）：OK 结论从不写台账，导致 SUSPECT 条目
    永不 resolve，suspect_forever_check 按最早条目算龄，条件消失后仍每 24h
    新建 P1。自愈后熔断只看"当前仍未知"的 subject。
    """
    ledger = _load(LEDGER_PATH, [])
    n = 0
    for e in ledger:
        if (not e.get("resolved") and e.get("verdict") == SUSPECT
                and e.get("checker") == checker and e.get("subject") == subject):
            e["resolved"] = True
            e["resolved_at"] = utcnow()
            e["resolved_reason"] = reason or "台账自愈：结论翻转为确定态"
            n += 1
    if n:
        _save(LEDGER_PATH, ledger)
    _prune_first_suspect(subject)  # C17：自愈后若无未解决项则清首发时钟
    return n


def suspect_forever_check():
    """
    R2 SUSPECT-forever 熔断：同一 subject 持续 SUSPECT 超过 6h → 自动 P1 + 终端动作选项。
    返回需要升级的 subject 列表。

    C17（2026-10-29）：计龄首选 suspect_first_at.json 的首发时钟（台账截断
    不影响它）；旁路缺失时回落旧口径（现存最早未解决条目），并懒回填旁路，
    使部署前已 SUSPECT 的 subject 从本轮起也不再受 500 条截断影响。
    旁路有记录但台账已无该 subject 未解决条目时不触发（陈旧旁路无害，
    下次 resolve 时清掉）。
    """
    ledger = _load(LEDGER_PATH, [])
    now = time.time()
    by_subject = {}
    for e in ledger:
        if e.get("resolved") or e.get("verdict") != SUSPECT:
            continue
        by_subject.setdefault(e.get("subject"), []).append(e)
    first_map = _load(FIRST_SUSPECT_PATH, {})
    if not isinstance(first_map, dict):
        first_map = {}
    dirty = False
    out = []
    for subject, entries in by_subject.items():
        entries.sort(key=lambda x: x.get("at", ""))
        first_at = first_map.get(subject)
        if first_at is None:
            first_at = entries[0]["at"]
            first_map[subject] = first_at
            dirty = True
        try:
            first = datetime.fromisoformat(first_at)
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
    if dirty:
        try:
            _save(FIRST_SUSPECT_PATH, first_map)
        except Exception:
            pass
    return out


if __name__ == "__main__":
    # C16（2026-10-29）：给 escalate_ack 接真实入口——主 agent 命令行 ack，
    # 不再是零调用方的摆设。用法：
    #   python3 graded_assertions.py --ack esc-<id> [--by dash_main]
    #   python3 graded_assertions.py --due
    import argparse

    _ap = argparse.ArgumentParser(description="graded_assertions 主 agent 命令入口")
    _ap.add_argument("--ack", metavar="ESCALATION_ID",
                     help="ack 指定升级，停 SLA 计时器")
    _ap.add_argument("--by", default="dash_main", help="ack 人（默认 dash_main）")
    _ap.add_argument("--due", action="store_true", help="列出当前 sla_due")
    _args = _ap.parse_args()
    if _args.ack:
        _inbox = _load(ESCALATION_PATH, [])
        _hit = [x for x in _inbox if x.get("escalation_id") == _args.ack]
        if not _hit:
            print(f"未找到升级记录：{_args.ack}")
            raise SystemExit(1)
        escalate_ack(_args.ack, by=_args.by)
        print(f"已 ack：{_args.ack}（by={_args.by}，SLA 计时停止）")
    elif _args.due:
        for _rec, _action in sla_due():
            print(f"{_action} {_rec.get('escalation_id')} "
                  f"{_rec.get('checker')}/{_rec.get('subject')} "
                  f"severity={_rec.get('severity')} "
                  f"pages_sent={_rec.get('pages_sent', 0)} "
                  f"fallback_stage={_rec.get('fallback_stage', 0)}")
    else:
        _ap.print_help()
