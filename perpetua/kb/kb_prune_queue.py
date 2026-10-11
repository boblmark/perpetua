#!/usr/bin/env python3
"""
kb_prune_queue.py — 90 天零用复核队列（Commit 2）

扫描 kb_registry.json 中的每个 entry_id，统计 90 天内账本读取次数；
零用 → kb_review_queue.json（action_required: keep|update|delete）。

用法：
    python3 kb_prune_queue.py [--ledger PATH] [--registry PATH]
        [--window-days 90] [--out PATH]
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KB_DIR = Path("/home/hatch/data/perpetua/kb")
DEFAULT_LEDGER = KB_DIR / "kb_usage_ledger.jsonl"
DEFAULT_REGISTRY = KB_DIR / "kb_registry.json"
DEFAULT_OUT = KB_DIR / "kb_review_queue.json"


def _parse_ts(ts: str):
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def run(ledger_path: str = str(DEFAULT_LEDGER),
        registry_path: str = str(DEFAULT_REGISTRY),
        window_days: int = 90,
        out_path: str = str(DEFAULT_OUT)) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # 读注册表（entry_id 列表）
    registry_ids = []
    rp = Path(registry_path)
    if rp.exists():
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                registry_ids = data.get("entry_ids", list(data.keys()))
            elif isinstance(data, list):
                registry_ids = [e if isinstance(e, str) else e.get("entry_id")
                                for e in data]
        except Exception:
            pass

    # 统计账本
    last_used: dict[str, str] = {}
    lp = Path(ledger_path)
    if lp.exists():
        for line in lp.read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = _parse_ts(rec.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
            eid = rec.get("entry_id")
            if eid:
                prev = last_used.get(eid)
                if prev is None or rec["ts"] > prev:
                    last_used[eid] = rec["ts"]

    now = datetime.now(timezone.utc).isoformat()
    queue = []
    for eid in registry_ids:
        if eid not in last_used:
            queue.append({
                "entry_id": eid,
                "last_used": None,
                "queued_at": now,
                "action_required": "keep|update|delete",
            })

    op = Path(out_path)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(queue, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return {"window_days": window_days, "registry_size": len(registry_ids),
            "zero_use_count": len(queue), "out": str(op)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    result = run(args.ledger, args.registry, args.window_days, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)
