#!/usr/bin/env python3
"""
视频生成额度管理：硬门禁，防止超预算。

支持多后端额度跟踪：
- muse-main: 500/天（调用方自行节流 → 现改为硬门禁）
- geminigen: 按 credits（45/次），跟踪余额
- vids: 按月免费额度
- agnes-video: 按调用次数

用法：
  python3 video_quota.py check --backend geminigen --cost 45
  python3 video_quota.py consume --backend geminigen --cost 45 --job-id xxx
  python3 video_quota.py status

数据文件：/home/hatch/data/perpetua/video_quota.json
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

QUOTA_FILE = Path("/home/hatch/data/perpetua/video_quota.json")

# Default limits
DEFAULT_LIMITS = {
    "muse-main": {"daily": 500, "unit": "jobs"},
    "geminigen": {"daily": None, "unit": "credits"},  # 跟踪余额，无硬上限
    "vids": {"monthly": None, "unit": "jobs"},  # 免费额度，跟踪即可
    "agnes-video": {"daily": 100, "unit": "jobs"},
}


def load() -> dict:
    if QUOTA_FILE.exists():
        return json.loads(QUOTA_FILE.read_text())
    return {"backends": {}, "log": []}


def save(data: dict):
    QUOTA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_usage(data: dict, backend: str, period: str) -> float:
    """Get usage for backend in period (day: YYYY-MM-DD, month: YYYY-MM)."""
    b = data["backends"].get(backend, {})
    return b.get(period, 0)


def check(backend: str, cost: float = 1) -> tuple[bool, str]:
    """Check if backend has quota. Returns (allowed, reason)."""
    data = load()
    limits = DEFAULT_LIMITS.get(backend, {})

    # Daily limit
    daily_limit = limits.get("daily")
    if daily_limit is not None:
        used = get_usage(data, backend, today_key())
        if used + cost > daily_limit:
            return False, f"{backend} daily quota exceeded: {used}/{daily_limit}"

    # Monthly limit
    monthly_limit = limits.get("monthly")
    if monthly_limit is not None:
        used = get_usage(data, backend, month_key())
        if used + cost > monthly_limit:
            return False, f"{backend} monthly quota exceeded: {used}/{monthly_limit}"

    return True, "OK"


def consume(backend: str, cost: float = 1, job_id: str = "") -> bool:
    """Record usage. Returns True if recorded."""
    allowed, reason = check(backend, cost)
    if not allowed:
        print(f"❌ Quota denied: {reason}", file=sys.stderr)
        return False

    data = load()
    if backend not in data["backends"]:
        data["backends"][backend] = {}

    today = today_key()
    month = month_key()
    data["backends"][backend][today] = data["backends"][backend].get(today, 0) + cost
    data["backends"][backend][month] = data["backends"][backend].get(month, 0) + cost

    data["log"].append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "cost": cost,
        "job_id": job_id,
    })
    # Keep last 1000 entries
    data["log"] = data["log"][-1000:]

    save(data)
    return True


def status() -> dict:
    """Get quota status for all backends."""
    data = load()
    result = {}
    for backend, limits in DEFAULT_LIMITS.items():
        b = data["backends"].get(backend, {})
        result[backend] = {
            "today_used": b.get(today_key(), 0),
            "month_used": b.get(month_key(), 0),
            "daily_limit": limits.get("daily"),
            "monthly_limit": limits.get("monthly"),
            "unit": limits.get("unit"),
        }
    return result


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--backend", required=True)
    p_check.add_argument("--cost", type=float, default=1)

    p_consume = sub.add_parser("consume")
    p_consume.add_argument("--backend", required=True)
    p_consume.add_argument("--cost", type=float, default=1)
    p_consume.add_argument("--job-id", default="")

    sub.add_parser("status")

    args = ap.parse_args()

    if args.cmd == "check":
        allowed, reason = check(args.backend, args.cost)
        print(json.dumps({"allowed": allowed, "reason": reason}, ensure_ascii=False))
        sys.exit(0 if allowed else 1)
    elif args.cmd == "consume":
        ok = consume(args.backend, args.cost, args.job_id)
        sys.exit(0 if ok else 1)
    elif args.cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
