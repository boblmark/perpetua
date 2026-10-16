#!/usr/bin/env python3
"""统一视频生成调用层：主 Muse 优先，异常自动切 nanoMuse。

Perpetua 和外部程序只调这一个入口，不用自己选后端。

路由逻辑：
1. 如果 backend_config.json 里 muse_main_enabled=false → 直接走 nano（新机器零 Muse 模式）
2. 否则先查 video_quota（muse-main 500/天硬门禁），超限 → 走 nano
3. 跑 musemain_healthcheck：stale 任务超阈值 → 说明主 Muse 离线/异常 → 走 nano
4. 健康 → 提交 dispatcher（consumer=muse-main），走主 Muse

用法：
  python3 muse_or_nano.py --type generate_video --instruction "..." --count 1
  python3 muse_or_nano.py --type custom --instruction "..."
  python3 muse_or_nano.py --status   # 看当前路由状态

返回 JSON：{"backend": "muse-main"|"nano", "job_id"|"thread_id": "...", "reason": "..."}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/hatch/data/perpetua")
CONFIG_PATH = BASE / "backend_config.json"
QUOTA_PY = BASE / "video_quota.py"
HEALTHCHECK_PY = BASE / "musemain_healthcheck.py"
BRIDGE_PY = BASE / "dispatcher_nano_bridge.py"
NANO_CALL = Path.home() / "workspace/skills/nanomuse-caller/bin/nano-call"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception:
        return {"muse_main_enabled": True, "prefer_backend": "muse-main",
                "stale_threshold_min": 15, "fallback_check_interval_min": 5}


def check_quota(backend: str, cost: float = 1) -> tuple[bool, str]:
    """查额度。quota 脚本 exit 0 = 允许。"""
    r = subprocess.run(
        [sys.executable, str(QUOTA_PY), "check", "--backend", backend,
         "--cost", str(cost)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        out = json.loads(r.stdout.strip())
        return out.get("allowed", False), out.get("reason", "")
    except Exception:
        return r.returncode == 0, r.stdout.strip()[:200]


def consume_quota(backend: str, cost: float = 1, job_id: str = "") -> bool:
    r = subprocess.run(
        [sys.executable, str(QUOTA_PY), "consume", "--backend", backend,
         "--cost", str(cost), "--job-id", job_id],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0


def check_musemain_health(threshold_min: int) -> tuple[bool, str]:
    """健康检查。exit 0 = 健康，exit 1 = 有 stale，exit 2 = 检查失败。"""
    r = subprocess.run(
        [sys.executable, str(HEALTHCHECK_PY),
         "--threshold-min", str(threshold_min), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    try:
        data = json.loads(r.stdout.strip())
    except Exception:
        return False, f"健康检查输出解析失败: {r.stdout[:200]}"
    if r.returncode == 0:
        return True, f"健康 ({data.get('pending_count', 0)} pending, 无 stale)"
    return False, data.get("reason", data.get("error", "未知"))


def submit_to_musemain(job_type: str, instruction: str, count: int) -> dict:
    """提交到 dispatcher，走主 Muse。复用 gen_video_musemain.py 的提交逻辑。"""
    # 直接调 dispatcher 的 submit（通过现有脚本的函数，避免重复造轮子）
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gen_video_musemain", str(BASE / "gen_video_musemain.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_video_musemain"] = mod
    spec.loader.exec_module(mod)
    job_id = f"uor-{uuid.uuid4().hex[:8]}"
    # gen_video_musemain.submit(prompt_text, job_id) 内部自行构造 payload
    # 并声明 video_count；muse_or_nano 只需透传 instruction 文本。
    muse_jid = mod.submit(instruction, job_id)
    return {"job_id": muse_jid, "raw": {"job_id": muse_jid}}


def _load_bridge():
    """加载 dispatcher_nano_bridge 模块（处理 dataclass 的 importlib 坑）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dispatcher_nano_bridge", str(BRIDGE_PY))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dispatcher_nano_bridge"] = mod
    spec.loader.exec_module(mod)
    return mod


def submit_to_nano(job_type: str, instruction: str, count: int) -> dict:
    """直接走 nanoMuse。复用 bridge 的翻译+提交逻辑。"""
    mod = _load_bridge()

    job = mod.DispatcherJob(
        job_id=f"uor-{uuid.uuid4().hex[:8]}",
        job_type=job_type, consumer="nano-direct",
        payload={"instruction": instruction, "video_count": count},
        queued_at=datetime.now(timezone.utc).isoformat(),
    )
    nano = mod.NanoMuseClient()
    thread_id = nano.create_thread(f"uor-{job.job_id}")
    nano.send(thread_id, mod.job_to_instruction(job))
    return {"thread_id": thread_id, "job_id": job.job_id}


def route(job_type: str, instruction: str, count: int = 1,
          force_backend: str = "") -> dict:
    """核心路由。返回 {"backend": ..., "reason": ..., ...}。"""
    cfg = load_config()

    # 1. 强制指定
    if force_backend in ("muse-main", "nano"):
        if force_backend == "nano":
            r = submit_to_nano(job_type, instruction, count)
            consume_quota("nano-direct", 1, r["job_id"])
            return {"backend": "nano", "reason": "强制指定", **r}
        # 强制 muse-main：跳过健康检查但仍过额度
        ok, reason = check_quota("muse-main", count)
        if not ok:
            return {"backend": "拒绝", "reason": f"muse-main 额度不足: {reason}"}
        r = submit_to_musemain(job_type, instruction, count)
        consume_quota("muse-main", count, r["job_id"])
        return {"backend": "muse-main", "reason": "强制指定", **r}

    # 2. 无 Muse 模式：新机器零依赖
    if not cfg.get("muse_main_enabled", True):
        r = submit_to_nano(job_type, instruction, count)
        return {"backend": "nano", "reason": "muse_main_enabled=false（无 Muse 模式）", **r}

    # 3. 额度硬门禁
    ok, reason = check_quota("muse-main", count)
    if not ok:
        r = submit_to_nano(job_type, instruction, count)
        return {"backend": "nano",
                "reason": f"muse-main 额度超限自动降级: {reason}", **r}

    # 4. 健康检查：主 Muse 离线/异常 → 降级
    healthy, health_reason = check_musemain_health(
        cfg.get("stale_threshold_min", 15))
    if not healthy:
        r = submit_to_nano(job_type, instruction, count)
        return {"backend": "nano",
                "reason": f"主 Muse 异常自动降级: {health_reason}", **r}

    # 5. 走主 Muse
    r = submit_to_musemain(job_type, instruction, count)
    consume_quota("muse-main", count, r["job_id"])
    return {"backend": "muse-main", "reason": f"健康: {health_reason}", **r}


def status() -> dict:
    cfg = load_config()
    out = {"config": cfg}
    out["quota"] = json.loads(subprocess.run(
        [sys.executable, str(QUOTA_PY), "status"],
        capture_output=True, text=True, timeout=30).stdout or "{}")
    healthy, reason = check_musemain_health(cfg.get("stale_threshold_min", 15))
    out["musemain_health"] = {"healthy": healthy, "reason": reason}
    # 当前有效路由
    if not cfg.get("muse_main_enabled", True):
        out["effective_backend"] = "nano（无 Muse 模式）"
    elif not healthy:
        out["effective_backend"] = "nano（降级中）"
    else:
        out["effective_backend"] = "muse-main"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="统一调用层：主 Muse 优先，异常自动切 nano")
    ap.add_argument("--type", default="generate_video",
                    choices=["generate_video", "custom"])
    ap.add_argument("--instruction", default="")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--force", default="", choices=["", "muse-main", "nano"])
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return
    if not args.instruction:
        ap.error("--instruction 必填（或用 --status 查看状态）")
    result = route(args.type, args.instruction, args.count, args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
