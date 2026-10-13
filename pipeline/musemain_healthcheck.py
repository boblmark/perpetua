#!/usr/bin/env python3
"""
muse-main 健康检查：检测任务是否长时间 pending 无人认领。

原理：muse-main 在用户设备上每 5 分钟扫队列 claim 任务。
如果任务 pending 超过阈值（默认 15 分钟）仍未被 claim，
说明 muse-main 可能离线/额度耗尽/异常。

用法：
  python3 musemain_healthcheck.py [--threshold-min 15] [--json]

返回：
  exit 0: 健康（无 stale 任务）
  exit 1: 发现 stale 任务（需要 fallback）
  exit 2: 检查失败
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

VM_HOST = "192.166.82.123"
VM_USER = "root"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
JOBS_DIR = "/opt/mcp-b/data/mcp_jobs/pending"

SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", f"ProxyCommand={PROXY}",
    "-o", "ConnectTimeout=10",
    f"{VM_USER}@{VM_HOST}",
]


def ssh_run(cmd: str, timeout: int = 30) -> tuple[str, int]:
    """Run command on VPS via SSH."""
    r = subprocess.run(
        SSH_BASE + [cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout.strip(), r.returncode


def get_pending_jobs() -> list[dict]:
    """Get list of pending jobs with metadata."""
    # List job files
    out, rc = ssh_run(f"ls -1 {JOBS_DIR}/*.json 2>/dev/null")
    if rc != 0 or not out:
        return []

    jobs = []
    for filepath in out.split("\n"):
        if not filepath.strip():
            continue
        # Get file mtime and content
        cmd = (
            f"stat -c %Y '{filepath}' 2>/dev/null; "
            f"echo '---'; "
            f"cat '{filepath}' 2>/dev/null | head -c 2000"
        )
        out2, rc2 = ssh_run(cmd)
        if rc2 != 0:
            continue

        parts = out2.split("---", 1)
        if len(parts) != 2:
            continue

        try:
            mtime = int(parts[0].strip())
        except ValueError:
            continue

        try:
            data = json.loads(parts[1].strip())
        except json.JSONDecodeError:
            data = {}

        jobs.append({
            "file": filepath.split("/")[-1],
            "job_id": data.get("job_id", filepath.split("/")[-1].replace(".json", "")),
            "consumer": data.get("consumer", ""),
            "job_type": data.get("job_type", ""),
            "created_at": mtime,
            "age_minutes": (time.time() - mtime) / 60,
        })

    return jobs


def check_health(threshold_min: int = 15) -> dict:
    """Check muse-main health. Returns status dict."""
    result = {
        "healthy": True,
        "threshold_min": threshold_min,
        "pending_count": 0,
        "stale_count": 0,
        "stale_jobs": [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        jobs = get_pending_jobs()
    except Exception as e:
        result["healthy"] = False
        result["error"] = f"Failed to query jobs: {e}"
        return result

    # Filter to muse-main consumer jobs
    musemain_jobs = [j for j in jobs if j.get("consumer") == "muse-main"]
    result["pending_count"] = len(musemain_jobs)

    # Find stale jobs
    stale = [j for j in musemain_jobs if j["age_minutes"] > threshold_min]
    result["stale_count"] = len(stale)
    result["stale_jobs"] = [
        {
            "job_id": j["job_id"],
            "job_type": j["job_type"],
            "age_minutes": round(j["age_minutes"], 1),
        }
        for j in stale
    ]

    if stale:
        result["healthy"] = False
        result["reason"] = (
            f"{len(stale)} job(s) pending > {threshold_min}min without claim. "
            f"muse-main may be offline or out of quota."
        )

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold-min", type=int, default=15,
                    help="Stale threshold in minutes (default: 15)")
    ap.add_argument("--json", action="store_true",
                    help="Output JSON")
    args = ap.parse_args()

    result = check_health(args.threshold_min)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["healthy"]:
            print(f"✅ Healthy: {result['pending_count']} pending, none stale")
        else:
            print(f"❌ Unhealthy: {result.get('reason', result.get('error', 'unknown'))}")
            for j in result.get("stale_jobs", []):
                print(f"   - {j['job_id']} ({j['job_type']}, {j['age_minutes']}min)")

    sys.exit(0 if result["healthy"] else 1)


if __name__ == "__main__":
    main()
