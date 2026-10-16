#!/usr/bin/env python3
"""Perpetua 中央编排器（2026-10-09 三脑评审 Commit 2 落地）。

从只读扫描器改为真实执行分发器：
  读命令队列 → 分发 worker → 结果写回 pipeline_state

每 30 分钟由 cron 调用。命令只有跃迁门能发射（MUST-1/MUST-7）。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from json_safe import run_lock
from datetime import datetime, timezone

DATA = '/home/hatch/data/perpetua'
LOG = f'{DATA}/orchestrator.log'


def log(msg):
    ts = datetime.now(timezone.utc).isoformat()[:19]
    line = f'[{ts}] {msg}'
    print(line)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def main():
    from executor import process_queue, load_queue
    from circuit_breaker import is_enabled

    if not is_enabled("pipeline_orchestrator"):
        log("orchestrator 被熔断器禁用，本轮跳过")
        return {"skipped": True, "reason": "breaker_open"}

    pending = [c for c in load_queue() if c.get("status") == "pending"]
    if not pending:
        log("命令队列为空，无待分发")
        return {"done": 0, "failed": 0, "skipped": 0}

    log(f"分发 {len(pending)} 条 pending 命令…")
    stats = process_queue()
    log(f"分发完成：done={stats['done']} failed={stats['failed']} "
        f"skipped={stats['skipped']}")
    return stats


if __name__ == '__main__':
    import json
    with run_lock("pipeline_orchestrator"):
        result = main()
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)
