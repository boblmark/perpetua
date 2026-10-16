#!/usr/bin/env python3
"""
anomaly 看门狗（2026-10-15 四脑议会 R1/R2/R4）
- R1：anomaly ledger 的独立看守 —— SUSPECT 必须留机器可读痕迹，这里负责盯着它们
- R2：分级器自证检测 —— 同一 checker 的 SUSPECT 率过高 → 判分级器自身不健康（禁自证）
- R4：升级 SLA 执行 —— T+2h 未 ack 分页，T+6h 升 P1；SUSPECT-forever 6h 熔断
- R5 相关：发布门 = CONFIRMED 通过才发布（D20261015-008），本脚本只看守不发布

用法：python3 anomaly_watchdog.py [--json]
建议 cron：每 30 分钟
"""
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import graded_assertions as ga

MEMORY_LOG = os.path.expanduser("~/memory/2026-10-15.md")
INBOX_PATH = "/home/hatch/data/collab/inbox.json"

# R2：分级器自证检测阈值 —— 24h 内同一 checker 的 SUSPECT 占比
GRADER_SUSPECT_RATIO = 0.8
GRADER_MIN_SAMPLES = 5


def _inbox_append(msg):
    try:
        inbox = json.load(open(INBOX_PATH, encoding="utf-8"))
    except Exception:
        inbox = {"messages": []}
    if isinstance(inbox, list):
        items = inbox
    else:
        # inbox 是 dict（keys: pending_pickup/picked_up/notices/messages/discarded），
        # 旧的 get("items", inbox) fallback 会取到 dict 本体导致 .append 崩溃
        items = inbox.get("items", inbox.get("messages"))
        if items is None:
            items = inbox.setdefault("messages", [])
    items.append({
        "type": "anomaly_watchdog",
        "message": msg,
        "for": "dash_main",
        "read": False,
        "created": ga.utcnow(),
    })
    try:
        json.dump(inbox, open(INBOX_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def check_grader_health():
    """R2：分级器自身健康必须由独立探针验证 —— SUSPECT 率过高的 checker 判为不健康。"""
    ledger = ga._load(ga.LEDGER_PATH, [])
    now = datetime.now(timezone.utc)
    by_checker = {}
    for e in ledger:
        try:
            at = datetime.fromisoformat(e.get("at", ""))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            if (now - at).total_seconds() > 24 * 3600:
                continue
        except Exception:
            continue
        c = e.get("checker") or "unknown"
        by_checker.setdefault(c, {"suspect": 0, "total": 0})
        by_checker[c]["total"] += 1
        if e.get("verdict") == ga.SUSPECT:
            by_checker[c]["suspect"] += 1
    unhealthy = []
    for checker, s in by_checker.items():
        if s["total"] >= GRADER_MIN_SAMPLES and s["suspect"] / s["total"] >= GRADER_SUSPECT_RATIO:
            unhealthy.append((checker, s["suspect"], s["total"]))
            ga.escalate("anomaly_watchdog", f"grader:{checker}",
                        "grader_suspect_ratio_high", severity="P1",
                        detail=f"分级器 {checker} 24h 内 SUSPECT 率 "
                               f"{s['suspect']}/{s['total']}，疑似自证失真，禁其 CONFIRMED 定论")
    return unhealthy


def check_sla():
    """R4：SLA 到期 → 分页/升 P1。"""
    due = ga.sla_due()
    by_id = {r["escalation_id"]: a for r, a in due}
    # 注意：ga.sla_due() 内部加载的是独立副本，必须把变异落到真正要保存的列表上，
    # 否则 reload 后 pages_sent/severity 丢失，同一升级每轮重复分页。
    inbox = ga._load(ga.ESCALATION_PATH, [])
    for rec in inbox:
        action = by_id.get(rec.get("escalation_id"))
        if action is None:
            continue
        rec["pages_sent"] = rec.get("pages_sent", 0) + 1
        if action == "P1":
            rec["severity"] = "P1"
        _inbox_append(
            f"[{'P1' if action=='P1' else 'PAGE'}] 升级未 ack：{rec['checker']}/{rec['subject']} "
            f"（{rec['condition']}），已等待超过 "
            f"{'6h' if action=='P1' else '2h'}。fallback 链：{' → '.join(ga.FALLBACK_CHAIN)}")
    if due:
        ga._save(ga.ESCALATION_PATH, inbox)
    return [(r["escalation_id"], a) for r, a in due]


def check_forever():
    """R2：SUSPECT-forever 熔断。"""
    subjects = ga.suspect_forever_check()
    for subject in subjects:
        ga.escalate("suspect_forever", subject, "forever", severity="P1",
                    detail=f"{subject} 持续 SUSPECT 超过 6h，自动升 P1。"
                           f"终端动作选项：人工介入 / 降级通道 / 保持观察")
        _inbox_append(f"[P1] SUSPECT-forever 熔断：{subject} 持续 SUSPECT 超 6h，请人工介入")
    return subjects


def main():
    report = {
        "at": ga.utcnow(),
        "unresolved_anomalies": len(ga.ledger_unresolved()),
        "grader_unhealthy": check_grader_health(),
        "sla_paged": check_sla(),
        "forever_p1": check_forever(),
    }
    as_json = "--json" in sys.argv
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"anomaly_watchdog {report['at'][:19]}: "
              f"未解决异常 {report['unresolved_anomalies']}，"
              f"不健康分级器 {len(report['grader_unhealthy'])}，"
              f"SLA 分页 {len(report['sla_paged'])}，"
              f"forever 熔断 {len(report['forever_p1'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
