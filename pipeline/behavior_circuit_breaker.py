#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
behavior_circuit_breaker.py — 数字孪生 DNA v3.1 行为级熔断器

处理"在线但异常/作恶的大脑"：不是进程死了，而是行为偏离了。
监控维度：
  - 发布速率（单位时间发布量异常飙升）
  - 错误率（近 N 次操作失败占比）
  - 资源占用（CPU/内存/磁盘超限）
  - 外部调用模式（异常的 API 调用频率/目标）

规则：
  - 阈值可配置，须有基线数据支撑（baseline.json）
  - 触发后降级到 L2（暂停所有自动化），并联动进化冻结
  - 不得自动恢复：必须人工确认 + 人工执行恢复
  - 每次触发/恢复写审计日志

依赖：仅 Python stdlib（资源占用经 /proc 读取，Linux）。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional


STATE_DIR = os.environ.get("PERPETUA_STATE_DIR", "/home/hatch/data/perpetua/state")
os.makedirs(STATE_DIR, exist_ok=True)
STATE_PATH = os.path.join(STATE_DIR, "behavior_breaker.json")
BASELINE_PATH = os.path.join(STATE_DIR, "behavior_baseline.json")
AUDIT_PATH = os.path.join(STATE_DIR, "behavior_breaker_audit.jsonl")


@dataclass
class Thresholds:
    """熔断阈值（须有基线支撑，见 baseline.json）"""
    # 发布速率：滑动窗口内最大允许发布数
    publish_window_s: float = 3600.0
    publish_max: int = 200
    # 错误率：最近 N 次操作中失败占比
    error_window_n: int = 50
    error_rate_max: float = 0.20
    # 资源占用
    mem_max_mb: float = 2048.0
    disk_max_pct: float = 0.90
    # 外部调用：滑动窗口内最大调用数
    api_window_s: float = 60.0
    api_max: int = 600

    def to_dict(self) -> Dict[str, Any]:
        return {
            "publish_window_s": self.publish_window_s,
            "publish_max": self.publish_max,
            "error_window_n": self.error_window_n,
            "error_rate_max": self.error_rate_max,
            "mem_max_mb": self.mem_max_mb,
            "disk_max_pct": self.disk_max_pct,
            "api_window_s": self.api_window_s,
            "api_max": self.api_max,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Thresholds":
        t = cls()
        for k, v in d.items():
            if hasattr(t, k):
                setattr(t, k, v)
        return t


def _read_mem_mb() -> Optional[float]:
    """从 /proc/self/status 读取 RSS（MB）"""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = float(line.split()[1])
                    return kb / 1024.0
    except OSError:
        pass
    return None


def _read_disk_pct(path: str = "/") -> Optional[float]:
    """磁盘使用率 0~1"""
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total == 0:
            return None
        return 1.0 - free / total
    except OSError:
        return None


class BehaviorCircuitBreaker:
    """
    行为级熔断器。

    用法：
        bb = BehaviorCircuitBreaker()
        bb.record_publish()          # 每次发布调用
        bb.record_op(success=True)   # 每次操作调用
        bb.record_api_call()         # 每次外部 API 调用
        bb.check()                   # 定期检查，返回是否触发
    """

    def __init__(self, thresholds: Optional[Thresholds] = None,
                 state_path: str = STATE_PATH,
                 baseline_path: str = BASELINE_PATH,
                 audit_path: str = AUDIT_PATH):
        self.state_path = state_path
        self.audit_path = audit_path
        self.thresholds = thresholds or self._load_thresholds(baseline_path)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        self._lock = threading.Lock()
        self._publishes: Deque[float] = deque()
        self._ops: Deque[bool] = deque()      # True=成功
        self._api_calls: Deque[float] = deque()
        self._tripped = False
        self._trip_reason = ""
        self._trip_ts = 0.0
        self._load_state()

    # -- 配置 ------------------------------------------------------------
    def _load_thresholds(self, baseline_path: str) -> Thresholds:
        """
        从基线文件加载阈值。若无基线文件，用保守默认值并记录警告。
        基线文件格式：{"thresholds": {...}, "measured_at": ..., "note": ...}
        """
        if os.path.exists(baseline_path):
            try:
                with open(baseline_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return Thresholds.from_dict(data.get("thresholds", {}))
            except (json.JSONDecodeError, ValueError):
                pass
        self._audit("baseline_missing",
                    "使用保守默认阈值，请尽快采集基线写入 " + baseline_path)
        return Thresholds()

    def save_baseline(self, note: str = "") -> str:
        """把当前阈值写为基线文件"""
        data = {"thresholds": self.thresholds.to_dict(),
                "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "note": note}
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._audit("baseline_saved", note)
        return BASELINE_PATH

    # -- 状态持久化 --------------------------------------------------------
    def _load_state(self) -> None:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._tripped = bool(data.get("tripped", False))
                self._trip_reason = data.get("trip_reason", "")
                self._trip_ts = data.get("trip_ts", 0.0)
            except (json.JSONDecodeError, ValueError):
                pass

    def _save_state(self) -> None:
        data = {"tripped": self._tripped, "trip_reason": self._trip_reason,
                "trip_ts": self._trip_ts}
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)

    def _audit(self, action: str, detail: str = "") -> None:
        entry = {"action": action, "detail": detail, "ts": time.time(),
                 "ts_human": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- 事件记录 ----------------------------------------------------------
    def record_publish(self, ts: Optional[float] = None) -> None:
        with self._lock:
            self._publishes.append(ts or time.time())

    def record_op(self, success: bool) -> None:
        with self._lock:
            self._ops.append(success)
            while len(self._ops) > self.thresholds.error_window_n:
                self._ops.popleft()

    def record_api_call(self, ts: Optional[float] = None) -> None:
        with self._lock:
            self._api_calls.append(ts or time.time())

    # -- 检查 --------------------------------------------------------------
    def _prune(self, now: float) -> None:
        th = self.thresholds
        while self._publishes and now - self._publishes[0] > th.publish_window_s:
            self._publishes.popleft()
        while self._api_calls and now - self._api_calls[0] > th.api_window_s:
            self._api_calls.popleft()

    def check(self) -> Dict[str, Any]:
        """
        检查各维度是否超阈值。超阈值 → 触发熔断（幂等）。
        返回 {"tripped": bool, "reasons": [...], "metrics": {...}}
        """
        now = time.time()
        th = self.thresholds
        reasons: List[str] = []
        with self._lock:
            self._prune(now)
            n_publish = len(self._publishes)
            n_api = len(self._api_calls)
            ops = list(self._ops)

        metrics: Dict[str, Any] = {
            "publish_in_window": n_publish,
            "publish_max": th.publish_max,
            "api_in_window": n_api,
            "api_max": th.api_max,
        }

        if n_publish > th.publish_max:
            reasons.append(
                f"发布速率异常：{n_publish} > {th.publish_max} "
                f"（{th.publish_window_s:.0f}s 窗口）")
        if n_api > th.api_max:
            reasons.append(
                f"外部调用异常：{n_api} > {th.api_max} "
                f"（{th.api_window_s:.0f}s 窗口）")
        if len(ops) >= 10:  # 样本太少不判
            err_rate = sum(1 for s in ops if not s) / len(ops)
            metrics["error_rate"] = round(err_rate, 3)
            metrics["error_samples"] = len(ops)
            if err_rate > th.error_rate_max:
                reasons.append(
                    f"错误率异常：{err_rate:.1%} > {th.error_rate_max:.0%} "
                    f"（近 {len(ops)} 次）")

        mem = _read_mem_mb()
        if mem is not None:
            metrics["mem_mb"] = round(mem, 1)
            if mem > th.mem_max_mb:
                reasons.append(f"内存超限：{mem:.0f}MB > {th.mem_max_mb:.0f}MB")
        disk = _read_disk_pct(STATE_DIR)
        if disk is not None:
            metrics["disk_pct"] = round(disk, 3)
            if disk > th.disk_max_pct:
                reasons.append(f"磁盘超限：{disk:.1%} > {th.disk_max_pct:.0%}")

        if reasons and not self._tripped:
            self._trip("; ".join(reasons))
        return {"tripped": self._tripped, "reasons": reasons, "metrics": metrics}

    # -- 熔断 --------------------------------------------------------------
    def _trip(self, reason: str) -> None:
        with self._lock:
            if self._tripped:
                return
            self._tripped = True
            self._trip_reason = reason
            self._trip_ts = time.time()
            self._save_state()
        self._audit("tripped", reason)

        # 联动 1：降级到 L2（暂停所有自动化）
        try:
            from kill_switch import KillSwitch, KillLevel
            ks = KillSwitch()
            # 逐级加深到 L2（KillSwitch 要求逐级）
            cur = ks.level()
            if cur.value < KillLevel.L1.value:
                ks.engage(KillLevel.L1, reason=f"behavior breaker: {reason}",
                          operator="behavior_circuit_breaker")
            if ks.level().value < KillLevel.L2.value:
                ks.engage(KillLevel.L2, reason=f"behavior breaker: {reason}",
                          operator="behavior_circuit_breaker")
            self._audit("linked_kill_L2", reason)
        except Exception as e:
            self._audit("link_kill_failed", str(e))

        # 联动 2：进化冻结
        try:
            from evolution_freeze import EvolutionFreeze
            EvolutionFreeze().freeze(
                reason=f"behavior breaker tripped: {reason}")
            self._audit("linked_freeze", reason)
        except Exception as e:
            self._audit("link_freeze_failed", str(e))

    def is_tripped(self) -> bool:
        self._load_state()
        return self._tripped

    def trip_reason(self) -> str:
        self._load_state()
        return self._trip_reason

    def reset(self, operator: str = "", confirmed: bool = False) -> bool:
        """
        人工恢复。必须 confirmed=True（人工确认），不自动恢复。
        注意：只复位熔断器本身，KillSwitch L2 需另行人工释放。
        """
        if not confirmed:
            self._audit("reset_denied", "需要人工确认 confirmed=True")
            return False
        with self._lock:
            self._tripped = False
            self._trip_reason = ""
            self._trip_ts = 0.0
            self._publishes.clear()
            self._ops.clear()
            self._api_calls.clear()
            self._save_state()
        self._audit("reset", f"operator={operator}（KillSwitch L2 需另行释放）")
        return True


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _selftest() -> None:
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="bb_test_")
    sp = os.path.join(tmpd, "behavior_breaker.json")
    ap = os.path.join(tmpd, "behavior_breaker_audit.jsonl")
    bp = os.path.join(tmpd, "behavior_baseline.json")

    th = Thresholds(publish_window_s=60, publish_max=5,
                    error_window_n=10, error_rate_max=0.5,
                    api_window_s=60, api_max=1000,
                    mem_max_mb=999999, disk_max_pct=0.999)
    bb = BehaviorCircuitBreaker(thresholds=th, state_path=sp,
                                baseline_path=bp, audit_path=ap)

    # 正常情况不触发
    for _ in range(3):
        bb.record_publish()
        bb.record_op(success=True)
    res = bb.check()
    assert res["tripped"] is False, res
    print("[behavior] 正常流量不触发 OK")

    # 发布速率超限 → 触发
    for _ in range(10):
        bb.record_publish()
    res = bb.check()
    assert res["tripped"] is True, res
    assert any("发布速率" in r for r in res["reasons"])
    print(f"[behavior] 发布速率熔断 OK: {res['reasons'][0]}")

    # 触发状态持久化
    bb2 = BehaviorCircuitBreaker(thresholds=th, state_path=sp,
                                 baseline_path=bp, audit_path=ap)
    assert bb2.is_tripped() is True
    print("[behavior] 熔断状态持久化 OK")

    # 未经确认的恢复被拒绝
    assert bb2.reset(operator="x", confirmed=False) is False
    assert bb2.is_tripped() is True
    print("[behavior] 未确认恢复被拒绝 OK")

    # 人工确认恢复
    assert bb2.reset(operator="selftest", confirmed=True) is True
    assert bb2.is_tripped() is False
    print("[behavior] 人工确认恢复 OK")

    # 错误率超限 → 触发
    for _ in range(10):
        bb2.record_op(success=False)
    res = bb2.check()
    assert res["tripped"] is True and any("错误率" in r for r in res["reasons"])
    print("[behavior] 错误率熔断 OK")
    bb2.reset(operator="selftest", confirmed=True)

    # 基线保存
    p = bb2.save_baseline(note="selftest baseline")
    assert os.path.exists(p)
    print("[behavior] 基线保存 OK")

    print("[behavior] 全部自测通过 ✓")


if __name__ == "__main__":
    _selftest()
