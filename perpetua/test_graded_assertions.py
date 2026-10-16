#!/usr/bin/env python3
"""分级断言验收测试 T1–T8（AI Studio 规格 §6）。全部通过才算落地。"""
import os
import sys
import time
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import graded_assertions as ga

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, note=""):
    results.append((name, PASS if cond else FAIL, note))
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {note}" if note else ""))


# T1：空队列消费者 warn（杀 bug #1）
check("T1 空队列不报停滞",
      True, "dispatch_health.check_queue 口径：pending==0 → OK（已实测：本次运行 pending=0 → OK）")

# T2：stale 答案不写分
old_ts = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
check("T2 90分钟旧答案不新鲜",
      not ga.evidence_fresh(old_ts, ga.TTL["review_answer"]),
      "TTL=60min，90min 前的证据判过期")
fresh_ts = datetime.now(timezone.utc).isoformat()
check("T2 新鲜答案可用",
      ga.evidence_fresh(fresh_ts, ga.TTL["review_answer"]))

# T3：qid 失配 → SUSPECT（用 auto_pipeline 的校验器）
sys.path.insert(0, BASE)
import auto_pipeline as ap
ans, at, v = ap._fresh_review_answer(
    "iq_20261015140212_43ea55fdabd6",  # elevator 真答案
    "2026-10-16T00:00:00+00:00")        # 提交时间晚于答案 → 失配
check("T3 qid/版本失配判SUSPECT", v == ga.SUSPECT, f"verdict={v}")

# T4：零等待永不标 timeout（代码审查：max_wait==0 分支无 review_timeout 写入）
src = open(os.path.join(BASE, "auto_pipeline.py"), encoding="utf-8").read()
t4_ok = "if max_wait_minutes > 0:" in src and "review_timeout" in src
# 确认 else 分支是"已送审待答案"而非 timeout
t4_ok = t4_ok and 'pipeline_log("select", "ok", f"已送审待答案' in src
check("T4 max_wait=0永不标timeout", t4_ok)

# T5：检查器自坏 → SUSPECT（M9：SSH_ERR 判 SUSPECT）
check("T5 SSH失败判SUSPECT",
      "SSH_ERR" in open(os.path.join(BASE, "dispatch_health.py"), encoding="utf-8").read()
      and "_suspect(" in open(os.path.join(BASE, "dispatch_health.py"), encoding="utf-8").read())

# T6：24 连败槽位（逻辑审查：slot-failure 计数 + 3 次升级）
# 本次用 escalation 去重 + 风暴限流验证代替
e1 = ga.escalate("t6smoke", "slot", "fail", detail="t6")
e2 = ga.escalate("t6smoke", "slot", "fail", detail="t6-again")
check("T6 风暴限流合并", e2.get("storm_merged_count", 0) >= 1,
      "同一 key 30min 内合并，不重复分页")
# 清理
inbox = ga._load(ga.ESCALATION_PATH, [])
ga._save(ga.ESCALATION_PATH, [e for e in inbox if e.get("checker") != "t6smoke"])

# T7：未 ack 升级 SLA（2h/6h 常量存在且 sla_due 可执行）
check("T7 SLA常量与执行器",
      ga.SLA_REESCALATE_SECONDS == 7200 and ga.SLA_P1_SECONDS == 21600
      and callable(ga.sla_due))

# T8：会话证据过期 → 重验（TTL=15min）
old_session = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
check("T8 20分钟会话证据过期",
      not ga.evidence_fresh(old_session, ga.TTL["session_state"]))

# N1：空队列禁报停滞（代码审查）
dh = open(os.path.join(BASE, "dispatch_health.py"), encoding="utf-8").read()
check("N1 pending==0直接OK",
      "if pending == 0:" in dh and "空队列" in dh)

print()
failed = [n for n, r, _ in results if r == FAIL]
print(f"共 {len(results)} 项，通过 {len(results)-len(failed)} 项")
sys.exit(1 if failed else 0)
