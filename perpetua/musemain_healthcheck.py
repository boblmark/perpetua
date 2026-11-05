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
    """Run command on VPS via SSH.

    2026-10-14 补丁：cat 被 head -c 2000 按字节截断时可能把 UTF-8 字符拦腰切断，
    subprocess.run(text=True) 严格解码会抛 UnicodeDecodeError → 误报 UNKNOWN。
    改用 errors="replace" 宽容解码，被切断的字符变成 U+FFFD，不影响 JSON 解析
    （JSONDecodeError 已有 {} 兜底）。"""
    r = subprocess.run(
        SSH_BASE + [cmd],
        capture_output=True, text=True, errors="replace", timeout=timeout,
    )
    return r.stdout.strip(), r.returncode


def ssh_run_script(script: str, timeout: int = 30) -> tuple[str, int]:
    """Run a Python script on the VPS via stdin (python3 -).

    2026-11-05 新增：一次 SSH 往返批量取回全部 job 元数据，避免
    每文件一次 SSH 握手。失败时 rc != 0，调用方按查询失败处理。"""
    r = subprocess.run(
        SSH_BASE + ["python3", "-"],
        input=script,
        capture_output=True, text=True, errors="replace", timeout=timeout,
    )
    return r.stdout.strip(), r.returncode


def get_pending_jobs() -> list[dict]:
    """Get list of pending jobs with metadata.

    2026-11-05 批处理补丁：原实现每个 job 文件单独跑一次 SSH
    （探针 + 列表 + 每文件 stat+cat），pending 目录 32 个文件时
    33+ 次 SSH 握手约 100-130s，超过 fallback_daemon 的 90s 子进程
    限时，当日已 8 次误报 UNKNOWN（06:00/09:31/09:37/09:41/10:01/
    10:07/10:10/10:18 UTC），muse-main 本身健康、只是检查超时。
    改为 VPS 侧一次 python 扫描全部文件、只回传每行一个 JSON，
    本地按原口径解析：计龄/claimed 判定/负年龄 suspect 语义全不变。
    查询失败仍抛异常 → UNKNOWN，绝不静默当健康。"""
    # 2026-10-14 补洞（降级链覆盖缺口铁律：查询失败≠0 stale，必须进 UNKNOWN）：
    # 旧代码在 SSH 传输失败或目录不存在时 rc != 0 也直接 return []，
    # 上游 daemon 会把这误读为"0 pending 健康"，真故障时降级链被静默跳过。
    # 现在先跑连通性+目录存在性探针，失败即抛异常 → check_health 记 error →
    # daemon 走 _health_unknown()（inbox 告警 + exit 2），绝不静默当健康。
    probe, rc = ssh_run(
        f"test -d {JOBS_DIR} && echo PROBE_OK || echo PROBE_FAIL"
    )
    if rc != 0 or probe != "PROBE_OK":
        raise RuntimeError(
            f"VPS 队列探针失败 (rc={rc}, probe={probe!r})："
            "SSH 传输失败或 pending 目录不存在，队列查询结果不可信"
        )

    # 一次 SSH 往返：VPS 侧扫描全部 job 文件，每行回传一个 JSON
    scan_script = (
        "import json, glob, os\n"
        f"for f in sorted(glob.glob('{JOBS_DIR}/*.json')):\n"
        "    try:\n"
        "        mtime = os.path.getmtime(f)\n"
        "        d = json.load(open(f))\n"
        "    except Exception:\n"
        "        continue\n"
        "    print(json.dumps({\n"
        "        'file': os.path.basename(f),\n"
        "        'mtime': mtime,\n"
        "        'job_id': d.get('job_id', os.path.basename(f)[:-5]),\n"
        "        'consumer': d.get('consumer', ''),\n"
        "        'job_type': d.get('job_type', ''),\n"
        "        'claimed_at': d.get('claimed_at') or '',\n"
        "        'claimed_by': bool(d.get('_claimed_by')),\n"
        "    }))\n"
    )
    out, rc = ssh_run_script(scan_script)
    if rc != 0:
        raise RuntimeError(
            f"VPS 队列批量扫描失败 (rc={rc})：SSH 传输失败，队列查询结果不可信"
        )
    if not out:
        return []

    jobs = []
    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        mtime = row.get("mtime")
        if not isinstance(mtime, (int, float)):
            continue
        filename = row.get("file", "")
        _claimed_at = row.get("claimed_at") or ""

        # A3（2026-10-28）：claimed 文件早已被 *.json 通配列出（23:09
        # 实测已报 stale），审计“从未被解读”已过时；真缺口是计龄口径：
        # 认领文件以 claimed_at 计龄（mtime 会被任何重写刷新，不可靠），
        # 无 claimed_at 回落 mtime。负年龄（时钟 skew）不钳制为 0，
        # 交 check_health 列为 suspect 可疑项，不静默当健康。
        _claimed = (".claimed-" in filename
                    or bool(_claimed_at)
                    or bool(row.get("claimed_by")))
        _clock = "mtime"
        _epoch = mtime
        if _claimed_at:
            try:
                _dt = datetime.fromisoformat(
                    str(_claimed_at).replace("Z", "+00:00"))
                if _dt.tzinfo is None:
                    _dt = _dt.replace(tzinfo=timezone.utc)
                _epoch = int(_dt.timestamp())
                _clock = "claimed_at"
            except (ValueError, OverflowError):
                pass

        jobs.append({
            "file": filename,
            "job_id": row.get("job_id", filename.replace(".json", "")),
            "consumer": row.get("consumer", ""),
            "job_type": row.get("job_type", ""),
            "created_at": mtime,
            "claimed": _claimed,
            "claimed_at": _claimed_at,
            "age_clock": _clock,
            "age_minutes": (time.time() - _epoch) / 60,
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

    # Find stale jobs（负年龄永不算 stale，另列 suspect）
    stale = [j for j in musemain_jobs
             if 0 <= j["age_minutes"] and j["age_minutes"] > threshold_min]
    suspect = [j for j in musemain_jobs if j["age_minutes"] < 0]
    result["stale_count"] = len(stale)
    result["stale_jobs"] = [
        {
            "job_id": j["job_id"],
            "job_type": j["job_type"],
            "age_minutes": round(j["age_minutes"], 1),
            "claimed": bool(j.get("claimed")),
            "age_clock": j.get("age_clock", "mtime"),
        }
        for j in stale
    ]
    # A3：负年龄 = 时钟 skew 可疑项，只列出不触发降级（fail-open，
    # 不把检查器自坏当成 muse-main 故障，Rule 14）。
    result["suspect_jobs"] = [
        {
            "job_id": j["job_id"],
            "job_type": j["job_type"],
            "age_minutes": round(j["age_minutes"], 1),
            "reason": "negative_age_clock_skew",
        }
        for j in suspect
    ]

    if stale:
        result["healthy"] = False
        # A3：旧文案把所有 stale 都写成 "without claim"，对已认领未交付
        # 的任务是误述（23:11 切换告警即因此措辞失真）。分开计数表述。
        _n_claimed = sum(1 for j in stale if j.get("claimed"))
        _n_unclaimed = len(stale) - _n_claimed
        _parts = []
        if _n_unclaimed:
            _parts.append(f"{_n_unclaimed} unclaimed > {threshold_min}min")
        if _n_claimed:
            _parts.append(f"{_n_claimed} claimed but undelivered "
                          f"> {threshold_min}min")
        result["reason"] = (
            f"{len(stale)} job(s) stale ({'; '.join(_parts)}). "
            f"muse-main may be offline, out of quota, or claimed "
            f"without delivering."
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
        for j in result.get("suspect_jobs", []):
            print(f"   ? Suspect: {j['job_id']} ({j['job_type']}, "
                  f"{j['age_minutes']}min, {j['reason']})")

    sys.exit(0 if result["healthy"] else 1)


if __name__ == "__main__":
    main()
