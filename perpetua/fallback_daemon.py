#!/usr/bin/env python3
"""muse-main → QQ box 自动降级守护（D20261028-006）。

每 5 分钟跑一次：
1. 读 backend_config.json：如果 muse_main_enabled=false，跳过
2. 跑 musemain_healthcheck：健康 → 若此前已切 QQ box 则回切 muse-main
   （状态文件 + backend_config.prefer_backend 一并写回），并记一次恢复告警
3. 不健康（且健康检查本身可信、无 error）→ 告警 + 写切换状态
   （backend_fallback_state.json，active_backend=qqbox）+ 跑
   qqbox_fallback.py --mode both，把超时任务自动切到 QQ box 生成。
   健康检查查询失败（UNKNOWN）时不切换——stale 数不可信，见 Rule 14。
   已认领任务不在切换范围内（2026-10-28 17:05 留置令）。

2026-10-28 之前本文件跑的是已下掉的 nano 桥，本轮已删除该调用。
SHADOW_MODE=true 时只 dry-run；默认（无环境变量）为真实切换，
因用户 2026-10-28 22:16 已拍板“不健康即告警并自动切 QQ box”。

S4（2026-10-29 batch A）：影子模式连续 3 轮“本应切换”（不健康且 stale
非空）时强制真实升级，不再无限影子。计数落盘
fallback_shadow_streak.json（独立于切换状态文件，避免改动状态语义）：
健康轮次清零；健康检查 UNKNOWN 时既不计数也不清零（检查本身不可信，
见 Rule 14，既不因抖动逃过强制、也不因不可靠检查误强制）；影子轮次
计数+1，满 3 轮改走真实桥接并另发一次强制升级告警；真实桥接成功后
清零，失败则保持 3 不清零（下一影子轮次再强制，不静默回影子）。
注意：本文件的影子从来不是全 dry-run——切换状态与切换告警在桥接前
就已写出，影子只影响桥接交付本身；S4 强制的正是交付这一步。
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
STATE_PATH = BASE / "backend_fallback_state.json"
SHADOW_MODE = os.environ.get("FALLBACK_SHADOW", "false").lower() == "true"
STREAK_PATH = BASE / "fallback_shadow_streak.json"
SHADOW_FORCE_AFTER = 3


def _read_shadow_streak() -> int:
    """读影子连续轮次；文件缺失/损坏按 0 计（fail-open，不阻塞降级）。"""
    try:
        d = json.loads(STREAK_PATH.read_text())
        n = int(d.get("count", 0))
        return n if n > 0 else 0
    except Exception:
        return 0


def _write_shadow_streak(count: int):
    try:
        STREAK_PATH.write_text(json.dumps(
            {"count": int(count),
             "updated_at": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False))
    except Exception as e:
        log(f"写影子计数失败（不阻塞降级）: {e}")


def _reset_shadow_streak():
    if _read_shadow_streak() != 0:
        _write_shadow_streak(0)


def _read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _write_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _set_prefer_backend(backend: str):
    """backend_config.prefer_backend 仅作当前后端声明（route 不靠它决策，
    真切换由状态文件 + route 健康检查驱动），写失败只记日志不阻塞。"""
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        cfg = {}
    cfg["prefer_backend"] = backend
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    except Exception as e:
        log(f"写 backend_config.prefer_backend 失败: {e}")


def _alert(level: str, dedup_key: str, title: str, body: str):
    try:
        sys.path.insert(0, str(BASE))
        import inbox as inbox_mod
        inbox_mod.append_notice({
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "dedup_key": dedup_key,
            "title": title,
            "body": body,
        })
        log(f"已写 inbox {level} 告警：{title}")
    except Exception as e:
        log(f"写 inbox 告警失败: {e}")


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
        # S4：健康轮次清零影子连续计数（链断了，下次影子从 1 重新计）。
        _reset_shadow_streak()
        log(f"主 Muse 健康 ({health.get('pending_count', 0)} pending)，无需降级")
        # 回切：此前已切 QQ box 且现在健康 → 写回 muse-main（仅状态跃迁时告警一次）
        state = _read_state()
        if state.get("active_backend") == "qqbox":
            _write_state({
                "active_backend": "muse-main",
                "recovered_at": datetime.now(timezone.utc).isoformat(),
                "previous_switched_at": state.get("switched_at"),
            })
            _set_prefer_backend("muse-main")
            _alert("info", "fallback_daemon:recovered_to_musemain",
                   "muse-main 已恢复，自动回切",
                   "健康检查已恢复健康，降级状态已从 QQ box 回切到 muse-main，"
                   "新任务重新走 muse-main；QQ box 在途任务按原流程继续。")
            log("已从 QQ box 回切到 muse-main")
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

    # 2. 告警 + 切换状态（仅状态跃迁或 stale 集合变化时告警，不每 5 分钟刷屏）
    state = _read_state()
    stale_ids = [j.get("job_id", "") for j in stale if j.get("job_id")]
    new_switch = state.get("active_backend") != "qqbox"
    changed = new_switch or stale_ids != state.get("stale_job_ids", [])
    _write_state({
        "active_backend": "qqbox",
        "switched_at": state.get("switched_at") or datetime.now(timezone.utc).isoformat(),
        "last_check": datetime.now(timezone.utc).isoformat(),
        "reason": _why,
        "stale_job_ids": stale_ids,
    })
    _set_prefer_backend("qqbox")
    if changed:
        _alert("warning", "fallback_daemon:switched_to_qqbox",
               "muse-main 不健康，已自动切换到 QQ box",
               f"原因：{_why}。stale 任务 {len(stale_ids)} 个："
               f"{', '.join(stale_ids[:10])}。新任务与超时任务改走 QQ box 生成，"
               "muse-main 恢复后自动回切；已认领任务不受影响。")
        log("已告警并切换到 QQ box")
    else:
        log("已处于 QQ box 切换态且 stale 集合未变，跳过重复告警")

    # 3. QQ box 桥接（shadow 模式只 dry-run；S4：连续满 3 轮强制真实桥接）
    cmd = [sys.executable, str(BASE / "qqbox_fallback.py"),
           "--mode", "both", "--timeout-min", str(threshold)]
    forced = False
    if SHADOW_MODE:
        streak = _read_shadow_streak() + 1
        _write_shadow_streak(streak)
        if streak >= SHADOW_FORCE_AFTER:
            forced = True
            _alert("warning", "fallback_daemon:shadow_forced_upgrade",
                   "影子降级连续 3 轮，强制真实升级",
                   f"影子模式下连续 {streak} 轮本应切换到 QQ box（stale "
                   f"{len(stale_ids)} 个），按 S4 规则本轮不再 dry-run，"
                   "改走真实 QQ box 桥接；成功后影子计数清零，失败则"
                   "下一影子轮次再强制。")
            log(f"SHADOW 强制升级：第 {streak} 轮连续影子，改走真实桥接")
        else:
            cmd.append("--dry-run")
            log(f"SHADOW 模式：dry-run，只列出不处理"
                f"（连续第 {streak}/{SHADOW_FORCE_AFTER} 轮，"
                f"满 {SHADOW_FORCE_AFTER} 轮强制真实升级）")
    else:
        # 真实模式下影子链已断，清零以免下次进影子时带旧计数。
        _reset_shadow_streak()
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    log(f"QQ box 桥接完成 (shadow={SHADOW_MODE} forced={forced}): {r2.stdout[-500:]}")
    if r2.returncode != 0:
        log(f"QQ box 桥接 stderr: {r2.stderr[-300:]}")
    if forced:
        if r2.returncode == 0:
            _write_shadow_streak(0)
            log("SHADOW 强制升级成功，影子计数清零")
        else:
            _write_shadow_streak(SHADOW_FORCE_AFTER)
            log("SHADOW 强制升级失败，计数保持满格，下一影子轮次再强制")
    return 0


if __name__ == "__main__":
    sys.exit(main())
