#!/usr/bin/env python3
"""统一视频生成调用层：主 Muse 唯一后端（nano 路由已下掉）。

Perpetua 和外部程序只调这一个入口，不用自己选后端。

路由逻辑（2026-10-28 用户定：管线生成链里 nano 已不再需要，降级走 QQ box MCP）：
1. muse_main_enabled=false、额度超限、或主 Muse 离线/异常 → 返回“拒绝”，
   不再自动换后端；降级改走人工 QQ box MCP 路（laptop_mcp_generate.py），不由本模块派发。
2. 健康 → 提交 dispatcher（consumer=muse-main），走主 Muse

用法：
  python3 muse_or_nano.py --type generate_video --instruction "..." --count 1
  python3 muse_or_nano.py --type custom --instruction "..."
  python3 muse_or_nano.py --status   # 看当前路由状态

返回 JSON：{"backend": "muse-main"|"拒绝", "job_id": "...", "reason": "..."}
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


def route(job_type: str, instruction: str, count: int = 1,
          force_backend: str = "") -> dict:
    """核心路由。返回 {"backend": ..., "reason": ..., ...}。

    2026-10-28 起 nano 路由已下掉：任何原本走 nano 的情形一律返回“拒绝”，
    不再创建 nano thread；降级改走人工 QQ box MCP 路，不由本模块派发。
    """
    cfg = load_config()

    # 1. 强制指定（nano 已下掉：结构化拒绝，不提交）
    if force_backend in ("muse-main", "nano"):
        if force_backend == "nano":
            return {"backend": "拒绝",
                    "reason": "nano 路由已于 2026-10-28 下掉，无可用后端"}
        # 强制 muse-main：跳过健康检查但仍过额度
        ok, reason = check_quota("muse-main", count)
        if not ok:
            return {"backend": "拒绝", "reason": f"muse-main 额度不足: {reason}"}
        r = submit_to_musemain(job_type, instruction, count)
        consume_quota("muse-main", count, r["job_id"])
        return {"backend": "muse-main", "reason": "强制指定", **r}

    # 2. 无 Muse 模式：nano 已下掉，无可用后端
    if not cfg.get("muse_main_enabled", True):
        return {"backend": "拒绝",
                "reason": "muse_main_enabled=false 且 nano 路由已下掉，无可用后端"}

    # 3. 额度硬门禁：不再降级 nano
    ok, reason = check_quota("muse-main", count)
    if not ok:
        return {"backend": "拒绝",
                "reason": f"muse-main 额度超限且 nano 路由已下掉: {reason}"}

    # 4. 健康检查：主 Muse 离线/异常 → 拒绝，不再降级 nano
    healthy, health_reason = check_musemain_health(
        cfg.get("stale_threshold_min", 15))
    if not healthy:
        return {"backend": "拒绝",
                "reason": f"主 Muse 异常且 nano 路由已下掉: {health_reason}"}

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
    # 当前有效路由（nano 已下掉，无 muse-main 即无可用后端）
    if not cfg.get("muse_main_enabled", True):
        out["effective_backend"] = "无可用后端（nano 路由已下掉）"
    elif not healthy:
        out["effective_backend"] = "无可用后端（主 Muse 异常，nano 路由已下掉）"
    else:
        out["effective_backend"] = "muse-main"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="统一调用层：主 Muse 唯一后端（nano 路由已下掉）")
    ap.add_argument("--type", default="generate_video",
                    choices=["generate_video", "custom"])
    ap.add_argument("--instruction", default="")
    ap.add_argument("--count", type=int, default=1)
    # "nano" 保留在选项里仅为结构化拒绝（route() 返回“拒绝”，不提交），非可用后端。
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
