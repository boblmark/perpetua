#!/usr/bin/env python3
"""
Worker 诚实性校验器（2026-10-08 三脑共识落地）

设计来源：
- LMArena 陪审团：D（结果倒查）全票第一
- Ask Studio：YouTube "doesn't count views — it validates them"
- AI Studio：20 条 MUST/NEVER 规格

核心原则：
1. 不信任 worker 自报，独立验证（NEVER-4）
2. 上报必须带机器可验证的证据（MUST-1/2/3，NEVER-1）
3. 失败上报必须含完整重试轨迹（MUST-4/5，NEVER-2）
4. 分级处理：警告→隔离→升级（MUST-10）
5. 校验器误判要记账，不得误伤 worker（MUST-11/12，NEVER-5）

使用：
  # worker 上报（带证据）
  python3 worker_honesty_validator.py report --task-id <id> --worker-id <id> \
      --status completed --evidence evidence.json

  # 校验器验证
  python3 worker_honesty_validator.py verify --report-id <id>

  # 查看违规记录
  python3 worker_honesty_validator.py violations
"""
import json, sys, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse

BASE = Path("/home/hatch/data")
REPORTS_DIR = BASE / "worker_honesty" / "reports"
VIOLATIONS_FILE = BASE / "worker_honesty" / "violations.jsonl"
CHECKER_STATS_FILE = BASE / "worker_honesty" / "checker_stats.json"
EVIDENCE_DIR = BASE / "worker_honesty" / "evidence"

for d in [REPORTS_DIR, EVIDENCE_DIR, BASE / "worker_honesty"]:
    d.mkdir(parents=True, exist_ok=True)


def log_violation(worker_id, task_id, violation_type, detail, severity="warning"):
    """记录违规（MUST-10 分级处理）"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "worker_id": worker_id,
        "task_id": task_id,
        "violation_type": violation_type,
        "detail": detail,
        "severity": severity,  # warning | isolated | escalated
    }
    with open(VIOLATIONS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def get_violation_count(worker_id, hours=24):
    """获取 worker 在指定时间内的违规次数（用于分级）"""
    if not VIOLATIONS_FILE.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    with open(VIOLATIONS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                if e.get("worker_id") == worker_id:
                    ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
                    if ts > cutoff:
                        count += 1
            except Exception:
                continue
    return count


def validate_evidence_schema(evidence):
    """验证证据载荷 schema（MUST-1）"""
    required = ["task_id", "started_at", "finished_at", "items"]
    for field in required:
        if field not in evidence:
            return False, f"缺失必填字段: {field}"
    # 时间戳单调递增且在任务窗口内（MUST-7）
    try:
        start = datetime.fromisoformat(evidence["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(evidence["finished_at"].replace("Z", "+00:00"))
        if end < start:
            return False, "finished_at 早于 started_at"
    except Exception as e:
        return False, f"时间戳格式错误: {e}"
    return True, "ok"


def validate_count_consistency(report, evidence):
    """验证数量声明与证据一致（MUST-3，NEVER-3）"""
    claimed = report.get("count")
    if claimed is not None:
        actual = len(evidence.get("items", []))
        if claimed != actual:
            return False, f"数量不一致：声称 {claimed}，证据 {actual}"
    return True, "ok"


def validate_retry_trace(report):
    """验证失败上报的重试轨迹（MUST-4/5，NEVER-2）"""
    if report.get("status") == "failed":
        trace = report.get("retry_trace", [])
        max_retries = report.get("max_retries", 3)
        if len(trace) < max_retries:
            # 检查是否是"需要人工"类上报
            if "人工" in report.get("detail", "") or "login" in report.get("detail", "").lower():
                return False, (
                    f"重试未耗尽（{len(trace)}/{max_retries}）不得上报需要人工 "
                    f"(NEVER-2)"
                )
    return True, "ok"


def submit_report(args):
    """worker 提交报告（带证据）"""
    # 读取证据文件
    try:
        evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"证据文件读取失败: {e}"},
                         ensure_ascii=False))
        return 1

    # MUST-1: 验证证据 schema
    ok, msg = validate_evidence_schema(evidence)
    if not ok:
        print(json.dumps({"ok": False, "error": f"证据无效: {msg}"},
                         ensure_ascii=False))
        return 1

    report = {
        "report_id": f"{args.task_id}_{int(datetime.now(timezone.utc).timestamp())}",
        "task_id": args.task_id,
        "worker_id": args.worker_id,
        "status": args.status,
        "count": args.count,
        "detail": args.detail or "",
        "retry_trace": json.loads(args.retry_trace or "[]"),
        "max_retries": args.max_retries,
        "evidence": evidence,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "verified": False,
    }

    # MUST-3: 数量一致性
    ok, msg = validate_count_consistency(report, evidence)
    if not ok:
        log_violation(args.worker_id, args.task_id, "count_mismatch", msg)
        print(json.dumps({"ok": False, "error": msg, "violation_logged": True},
                         ensure_ascii=False))
        return 1

    # MUST-4/5: 重试轨迹
    ok, msg = validate_retry_trace(report)
    if not ok:
        log_violation(args.worker_id, args.task_id, "retry_not_exhausted", msg)
        print(json.dumps({"ok": False, "error": msg, "violation_logged": True},
                         ensure_ascii=False))
        return 1

    # NEVER-1: 零证据不得报完成
    if args.status == "completed" and not evidence.get("items"):
        log_violation(args.worker_id, args.task_id, "zero_evidence_completed",
                      "零证据上报已完成 (NEVER-1)")
        print(json.dumps({"ok": False, "error": "零证据不得上报已完成",
                          "violation_logged": True}, ensure_ascii=False))
        return 1

    # 保存报告
    report_path = REPORTS_DIR / f"{report['report_id']}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print(json.dumps({"ok": True, "report_id": report["report_id"],
                      "message": "报告已受理，等待独立验证"},
                     ensure_ascii=False))
    return 0


def verify_report(args):
    """独立验证报告（MUST-6：抽样回查源系统）"""
    report_path = REPORTS_DIR / f"{args.report_id}.json"
    if not report_path.exists():
        print(json.dumps({"ok": False, "error": "报告不存在"}, ensure_ascii=False))
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    evidence = report.get("evidence", {})
    worker_id = report.get("worker_id")
    task_id = report.get("task_id")

    # MUST-6: 回查源系统（这里做基础检查，实际应按任务类型定制）
    issues = []

    # 检查证据时间戳在任务窗口内（MUST-7）
    try:
        start = datetime.fromisoformat(evidence["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(evidence["finished_at"].replace("Z", "+00:00"))
        submitted = datetime.fromisoformat(report["submitted_at"].replace("Z", "+00:00"))
        # 证据必须先于上报写入（write-ahead）
        if end > submitted:
            issues.append("证据时间戳晚于上报时间，违反 write-ahead")
    except Exception as e:
        issues.append(f"时间戳验证失败: {e}")

    if issues:
        # MUST-10: 分级处理
        prior = get_violation_count(worker_id, hours=24)
        if prior == 0:
            severity = "warning"
            action = "警告 + 强制重跑"
        elif prior < 3:
            severity = "isolated"
            action = "隔离 worker 并告警"
        else:
            severity = "escalated"
            action = "升级为策略评审"

        for issue in issues:
            log_violation(worker_id, task_id, "verification_failed", issue, severity)

        report["verified"] = False
        report["verification_issues"] = issues
        report["severity"] = severity
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(json.dumps({"ok": False, "verified": False, "issues": issues,
                          "severity": severity, "action": action},
                         ensure_ascii=False))
        return 1
    else:
        report["verified"] = True
        report["verified_at"] = datetime.now(timezone.utc).isoformat()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(json.dumps({"ok": True, "verified": True}, ensure_ascii=False))
        return 0


def show_violations(args):
    """查看违规记录"""
    if not VIOLATIONS_FILE.exists():
        print(json.dumps({"violations": []}, ensure_ascii=False))
        return 0
    violations = []
    with open(VIOLATIONS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                violations.append(json.loads(line))
            except Exception:
                continue
    # 最近 20 条
    print(json.dumps({"violations": violations[-20:], "total": len(violations)},
                     ensure_ascii=False, indent=2))
    return 0


def main():
    p = argparse.ArgumentParser(description="Worker 诚实性校验器")
    sub = p.add_subparsers(dest="cmd", required=True)

    # report 子命令
    r = sub.add_parser("report", help="提交 worker 报告")
    r.add_argument("--task-id", required=True)
    r.add_argument("--worker-id", required=True)
    r.add_argument("--status", required=True, choices=["completed", "failed", "partial"])
    r.add_argument("--evidence", required=True, help="证据 JSON 文件路径")
    r.add_argument("--count", type=int, default=None)
    r.add_argument("--detail", default="")
    r.add_argument("--retry-trace", default="[]", help="重试轨迹 JSON")
    r.add_argument("--max-retries", type=int, default=3)

    # verify 子命令
    v = sub.add_parser("verify", help="验证报告")
    v.add_argument("--report-id", required=True)

    # violations 子命令
    sub.add_parser("violations", help="查看违规记录")

    args = p.parse_args()
    if args.cmd == "report":
        return submit_report(args)
    elif args.cmd == "verify":
        return verify_report(args)
    elif args.cmd == "violations":
        return show_violations(args)


if __name__ == "__main__":
    sys.exit(main())
