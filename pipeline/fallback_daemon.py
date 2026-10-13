#!/usr/bin/env python3
"""muse-main → nanoMuse 自动降级守护。

每 5 分钟跑一次：
1. 读 backend_config.json：如果 muse_main_enabled=false，跳过（无 Muse 模式下统一路由已直走 nano，无需桥接）
2. 跑 musemain_healthcheck：健康 → 什么都不做
3. 不健康 → 跑 dispatcher_nano_bridge --scan，把超时的 muse-main 任务转给 nano

SHADOW_MODE=true 时只 dry-run（列出会处理的任务，不实际提交），用于验证。
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/hatch/data/perpetua")
CONFIG_PATH = BASE / "backend_config.json"
LOG_PATH = BASE / "fallback_daemon.log"
SHADOW_MODE = os.environ.get("FALLBACK_SHADOW", "true").lower() == "true"


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}Z] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def _health_unknown(err: str) -> int:
    """健康检查查询失败/超时 → 状态 UNKNOWN（绝不把"没查到"当成"0 stale"）。
    写 inbox 告警（12h 去重），返回 exit 2。"""
    log(f"健康检查查询失败（状态未知，不信任 0 stale）: {err}")
    try:
        sys.path.insert(0, str(BASE))
        import inbox as inbox_mod
        notices = inbox_mod.load().get("notices", [])
        key = "fallback_daemon:health_unknown"
        recent = [n for n in notices
                  if n.get("dedup_key") == key
                  and (datetime.now(timezone.utc)
                       - datetime.fromisoformat(n["ts"])).total_seconds() < 12 * 3600]
        if not recent:
            inbox_mod.append_notice({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": "warning",
                "dedup_key": key,
                "title": "降级守护健康检查查询失败（状态未知）",
                "body": f"muse-main 队列查询失败: {err}。"
                        "stale 任务数不可信，未触发降级扫描。"
                        "若持续出现，真故障时降级链会被跳过，需排查 SSH/dispatcher 链路。",
            })
            log("已写 inbox warning 告警（12h 去重）")
        else:
            log("inbox 告警 12h 内已发过，跳过")
    except Exception as e:
        log(f"写 inbox 告警失败: {e}")
    return 2


def main() -> int:
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {}
    if not cfg.get("muse_main_enabled", True):
        log("无 Muse 模式，跳过桥接检查")
        return 0

    threshold = cfg.get("stale_threshold_min", 15)
    # 1. 健康检查
    try:
        r = subprocess.run(
            [sys.executable, str(BASE / "musemain_healthcheck.py"),
             "--threshold-min", str(threshold), "--json"],
            capture_output=True, text=True, timeout=90,
        )
    except subprocess.TimeoutExpired:
        # 2026-10-12 修复（本轮 crash 根因）：healthcheck 子进程本身卡死超时
        # （内部 SSH 链抖动时会被 subprocess 超时杀掉）时，r 不存在——旧代码直接抛
        # TimeoutExpired 崩溃退出。按"查询失败 = UNKNOWN"铁律处理。
        return _health_unknown("musemain_healthcheck.py 子进程超过 90s 未返回（内部 SSH 链路可能抖动）")
    try:
        health = json.loads(r.stdout.strip())
    except Exception:
        log(f"健康检查输出解析失败: {r.stdout[:200]}")
        return 2

    if health.get("healthy", False):
        log(f"主 Muse 健康 ({health.get('pending_count', 0)} pending)，无需降级")
        return 0

    # 2026-10-12 修复（降级链覆盖缺口）：健康检查查询本身失败（error）
    # 时，stale_jobs 为空是"没查到"而不是"没有"。此时状态为 UNKNOWN，
    # 绝不能当成"0 stale"静默干跑——否则真故障+链路抖动叠加时，
    # 切真实降级会被跳过。改为写 inbox 告警并返回 2（未知状态）。
    if health.get("error"):
        return _health_unknown(health["error"])

    stale = health.get("stale_jobs", [])
    _why = health.get("reason") or health.get("error", "")
    log(f"主 Muse 异常: {_why}，{len(stale)} 个 stale 任务")

    # 2. 桥接（shadow 模式只 dry-run）
    cmd = [sys.executable, str(BASE / "dispatcher_nano_bridge.py"),
           "--scan", "--timeout-min", str(threshold)]
    if SHADOW_MODE:
        cmd.append("--dry-run")
        log("SHADOW 模式：dry-run，只列出不处理")
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    log(f"桥接完成 (shadow={SHADOW_MODE}): {r2.stdout[-500:]}")
    if r2.returncode != 0:
        log(f"桥接 stderr: {r2.stderr[-300:]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
