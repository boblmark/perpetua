#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
firewalls.py — 数字孪生 DNA v3.1 六大舱壁

六大舱壁（纵深防御，保护"生存"）：
  FW1 降级自治模式   — 大脑失联时按最后已知策略继续运行
  FW2 脑外独立看门狗 — 心跳监控，不依赖大脑自身
  FW3 QC 熔断器      — QC 超时 60s 则 fail-closed（拒绝放行）
  FW4 状态存储解耦   — 状态经 WAL 独立存储接口写入
  FW5 人工终极开关   — L1/L2/L3 三档人工开关
  FW6 意图防火墙     — 代理指标 vs 人工抽审质量偏离超阈值时触发（防 Goodhart 化）

设计原则：
  - 所有舱壁 fail-closed：异常时默认拒绝/降级，不默认放行
  - 舱壁之间互不依赖：看门狗不依赖大脑，开关不依赖网络
  - 每个舱壁状态可查询、可审计

依赖：仅 Python stdlib。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 基础类型
# ---------------------------------------------------------------------------

STATE_DIR = os.environ.get("PERPETUA_STATE_DIR", "/home/hatch/data/perpetua/state")
os.makedirs(STATE_DIR, exist_ok=True)


class FirewallStatus(Enum):
    """舱壁状态"""
    NORMAL = "normal"        # 正常
    DEGRADED = "degraded"    # 降级运行中
    TRIPPED = "tripped"      # 已触发（熔断/冻结）
    DISABLED = "disabled"    # 被人工禁用（需审计）


@dataclass
class FirewallEvent:
    """舱壁事件（审计用）"""
    firewall: str
    event: str
    detail: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "firewall": self.firewall,
            "event": self.event,
            "detail": self.detail,
            "ts": self.ts,
            "ts_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts)),
        }


class AuditLog:
    """追加式审计日志（WORM 语义：只追加不修改）"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def append(self, event: FirewallEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def tail(self, n: int = 50) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


AUDIT = AuditLog(os.path.join(STATE_DIR, "firewalls_audit.jsonl"))


# ---------------------------------------------------------------------------
# FW1: 降级自治模式
# ---------------------------------------------------------------------------
class DegradedAutonomy:
    """
    大脑失联时按最后已知策略继续运行。

    机制：
      - 每次大脑下发策略时快照保存（含版本号、时间戳）
      - 心跳超时（默认 300s）未收到大脑心跳 → 进入降级自治
      - 降级期间：只执行快照策略中的"安全动作白名单"，拒绝新策略
      - 大脑恢复后需人工确认才退出降级（防脑尸复活）
    """

    HEARTBEAT_TIMEOUT_S = 300.0

    def __init__(self, state_dir: str = STATE_DIR):
        self.state_dir = state_dir
        self.snapshot_path = os.path.join(state_dir, "brain_policy_snapshot.json")
        self._last_heartbeat = 0.0
        self._degraded = False
        self._lock = threading.Lock()

    def heartbeat(self) -> None:
        """大脑心跳"""
        with self._lock:
            self._last_heartbeat = time.time()

    def save_policy_snapshot(self, policy: Dict[str, Any]) -> None:
        """保存大脑策略快照"""
        snap = {
            "policy": policy,
            "saved_ts": time.time(),
            "saved_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        tmp = self.snapshot_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.snapshot_path)  # 原子替换
        AUDIT.append(FirewallEvent("FW1", "policy_snapshot_saved",
                                   f"keys={list(policy.keys())}"))

    def load_policy_snapshot(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.snapshot_path):
            return None
        with open(self.snapshot_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check(self) -> FirewallStatus:
        """检查是否需要进入降级"""
        with self._lock:
            silent = time.time() - self._last_heartbeat
            if silent > self.HEARTBEAT_TIMEOUT_S:
                if not self._degraded:
                    self._degraded = True
                    AUDIT.append(FirewallEvent(
                        "FW1", "degraded_enter",
                        f"brain silent {silent:.0f}s > {self.HEARTBEAT_TIMEOUT_S:.0f}s"))
                return FirewallStatus.DEGRADED
            return FirewallStatus.NORMAL

    def is_degraded(self) -> bool:
        return self._degraded

    def recover(self, human_confirmed: bool = False) -> bool:
        """大脑恢复：必须人工确认才退出降级"""
        if not human_confirmed:
            return False
        with self._lock:
            self._degraded = False
            self._last_heartbeat = time.time()
        AUDIT.append(FirewallEvent("FW1", "degraded_exit", "human confirmed"))
        return True


# ---------------------------------------------------------------------------
# FW2: 脑外独立看门狗
# ---------------------------------------------------------------------------
class Watchdog:
    """
    独立于大脑的心跳监控。

    机制：
      - 被监控组件定期调用 .ping(name)
      - 看门狗在独立线程中检查各组件最后 ping 时间
      - 超时 → 记录事件 + 调用注册的回调（如触发降级/告警）
      - 看门狗自身状态可查询；看门狗不依赖大脑进程
    """

    def __init__(self, check_interval_s: float = 10.0):
        self.check_interval = check_interval_s
        self._pings: Dict[str, float] = {}
        self._timeouts: Dict[str, float] = {}
        self._callbacks: Dict[str, List[Callable[[str], None]]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def register(self, name: str, timeout_s: float,
                 on_timeout: Optional[Callable[[str], None]] = None) -> None:
        with self._lock:
            self._timeouts[name] = timeout_s
            self._pings[name] = time.time()
            if on_timeout:
                self._callbacks.setdefault(name, []).append(on_timeout)
        AUDIT.append(FirewallEvent("FW2", "registered", f"{name} timeout={timeout_s}s"))

    def ping(self, name: str) -> None:
        with self._lock:
            self._pings[name] = time.time()

    def _loop(self) -> None:
        while not self._stop.wait(self.check_interval):
            now = time.time()
            with self._lock:
                items = list(self._timeouts.items())
            for name, timeout in items:
                with self._lock:
                    last = self._pings.get(name, 0)
                if now - last > timeout:
                    AUDIT.append(FirewallEvent(
                        "FW2", "timeout", f"{name} silent {now - last:.0f}s"))
                    for cb in self._callbacks.get(name, []):
                        try:
                            cb(name)
                        except Exception as e:  # 回调异常不杀死看门狗
                            AUDIT.append(FirewallEvent(
                                "FW2", "callback_error", f"{name}: {e}"))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="fw2-watchdog")
        self._thread.start()
        AUDIT.append(FirewallEvent("FW2", "started", ""))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def status(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            return {
                name: {
                    "silent_s": round(now - self._pings.get(name, 0), 1),
                    "timeout_s": self._timeouts[name],
                    "alive": (now - self._pings.get(name, 0)) <= self._timeouts[name],
                }
                for name in self._timeouts
            }


# ---------------------------------------------------------------------------
# FW3: QC 熔断器（60s fail-closed）
# ---------------------------------------------------------------------------
class QCCircuitBreaker:
    """
    QC 决策超时熔断器。

    机制：
      - QC 评审必须在 timeout_s（默认 60s）内返回决策
      - 超时 → fail-closed：拒绝放行（视频不发布），标记待人工复核
      - 连续失败达阈值 → 熔断器打开，后续 QC 直接 fail-closed 不再等待
      - 半开试探：冷却后允许 1 个试探请求，成功则关闭熔断器
    """

    def __init__(self, timeout_s: float = 60.0, fail_threshold: int = 5,
                 cooldown_s: float = 300.0):
        self.timeout_s = timeout_s
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def decide(self, qc_fn: Callable[[], bool], video_id: str = "") -> bool:
        """
        执行 QC 决策。
        qc_fn: 返回 True=通过 / False=拒绝 的无参函数
        返回：是否放行。超时或熔断打开时返回 False（fail-closed）。
        """
        with self._lock:
            if time.time() < self._open_until:
                AUDIT.append(FirewallEvent(
                    "FW3", "reject_circuit_open", f"video={video_id}"))
                return False  # 熔断器打开：直接拒绝

        result: Optional[bool] = None
        error: Optional[str] = None

        def _run():
            nonlocal result, error
            try:
                result = qc_fn()
            except Exception as e:
                error = str(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=self.timeout_s)

        if t.is_alive() or error:
            # 超时或异常 → fail-closed
            reason = "timeout" if t.is_alive() else f"error:{error}"
            self._record_failure()
            AUDIT.append(FirewallEvent(
                "FW3", "fail_closed", f"video={video_id} reason={reason}"))
            return False

        if result:
            self._record_success()
            return True
        self._record_failure()
        AUDIT.append(FirewallEvent(
            "FW3", "qc_reject", f"video={video_id}"))
        return False

    def _record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.fail_threshold:
                self._open_until = time.time() + self.cooldown_s
                AUDIT.append(FirewallEvent(
                    "FW3", "circuit_open",
                    f"failures={self._consecutive_failures} cooldown={self.cooldown_s}s"))

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = 0.0

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "open": time.time() < self._open_until,
                "consecutive_failures": self._consecutive_failures,
                "timeout_s": self.timeout_s,
            }


# ---------------------------------------------------------------------------
# FW4: 状态存储解耦（WAL 接口）
# ---------------------------------------------------------------------------
class StateStore:
    """
    状态存储解耦：所有状态变更经 WAL（Write-Ahead Log）接口。

    机制：
      - 写操作先追加 WAL，再应用到内存状态
      - 进程重启时从 WAL 重放恢复
      - 大脑和执行器共享同一状态视图，但写入都经此接口（防状态撕裂）
    """

    def __init__(self, state_dir: str = STATE_DIR):
        self.state_dir = state_dir
        self.wal_path = os.path.join(state_dir, "state.wal.jsonl")
        self.snapshot_path = os.path.join(state_dir, "state.snapshot.json")
        self._state: Dict[str, Any] = {}
        self._lock = threading.Lock()
        os.makedirs(state_dir, exist_ok=True)
        self._replay()

    def _replay(self) -> None:
        """启动时从快照 + WAL 重放"""
        if os.path.exists(self.snapshot_path):
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        if os.path.exists(self.wal_path):
            with open(self.wal_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        self._apply_entry(entry, record=False)
                    except json.JSONDecodeError:
                        continue

    def _apply_entry(self, entry: Dict[str, Any], record: bool = True) -> None:
        op = entry.get("op")
        key = entry.get("key")
        if op == "set":
            self._state[key] = entry.get("value")
        elif op == "delete":
            self._state.pop(key, None)
        if record:
            with open(self.wal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._apply_entry({"op": "set", "key": key, "value": value,
                               "ts": time.time()})

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(key, default)

    def delete(self, key: str) -> None:
        with self._lock:
            self._apply_entry({"op": "delete", "key": key, "ts": time.time()})

    def snapshot(self) -> None:
        """定期快照（WAL 可截断，此处保留 WAL 做审计）"""
        with self._lock:
            tmp = self.snapshot_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.snapshot_path)
        AUDIT.append(FirewallEvent("FW4", "snapshot", f"keys={len(self._state)}"))


# ---------------------------------------------------------------------------
# FW5: 人工终极开关（L1/L2/L3）
# ---------------------------------------------------------------------------
# 完整实现见 kill_switch.py，此处提供轻量门面以便统一查询。
class ManualKillSwitchFacade:
    """FW5 门面：实际逻辑在 kill_switch.KillSwitch"""

    def __init__(self):
        from kill_switch import KillSwitch  # 延迟导入，防循环
        self._ks = KillSwitch()

    def level(self) -> str:
        return self._ks.level().name

    def engage(self, level: str, reason: str = "", operator: str = "") -> bool:
        from kill_switch import KillLevel
        return self._ks.engage(KillLevel[level], reason=reason, operator=operator)

    def release(self, operator: str = "") -> bool:
        return self._ks.release(operator=operator)


# ---------------------------------------------------------------------------
# FW6: 意图防火墙（防 Goodhart 化）
# ---------------------------------------------------------------------------
class IntentFirewall:
    """
    第六舱壁：保护"意图"，而非仅保护"生存"。

    问题：L1 每晚对着代理指标（爆款率）自动调参，系统可能在全部
    防火墙绿灯的情况下，安静地把自己进化成一台标题党机器
    （Goodhart 化：指标成了目标，就不再是好指标）。

    机制：
      - 输入：代理指标（爆款率）+ 人工抽审质量评分（0-10）
      - 计算两者相关性（Pearson）；相关性 < 阈值（默认 0.3）→ 触发
      - 或人工评分绝对值跌破下限 → 触发
      - 触发动作：冻结 L1 进化 + 告警 + 审计记录
    """

    def __init__(self, state_dir: str = STATE_DIR,
                 corr_threshold: float = 0.3,
                 quality_floor: float = 6.0,
                 window: int = 30):
        self.corr_threshold = corr_threshold
        self.quality_floor = quality_floor
        self.window = window
        self.data_path = os.path.join(state_dir, "intent_samples.jsonl")
        self._lock = threading.Lock()
        os.makedirs(state_dir, exist_ok=True)

    def record(self, viral_rate: float, human_quality: float) -> None:
        """记录一次（代理指标，人工质量）配对样本"""
        entry = {"viral_rate": viral_rate, "human_quality": human_quality,
                 "ts": time.time()}
        with self._lock:
            with open(self.data_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    def _samples(self) -> List[Dict[str, float]]:
        if not os.path.exists(self.data_path):
            return []
        out = []
        with open(self.data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out[-self.window:]

    @staticmethod
    def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
        n = len(xs)
        if n < 3:
            return None
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        if dx == 0 or dy == 0:
            return None
        return num / (dx * dy)

    def check(self) -> Dict[str, Any]:
        """
        检查意图偏离。
        返回 {"triggered": bool, "reason": str, "correlation": float|None, ...}
        """
        samples = self._samples()
        if len(samples) < 3:
            return {"triggered": False, "reason": "insufficient_samples",
                    "n": len(samples)}
        xs = [s["viral_rate"] for s in samples]
        ys = [s["human_quality"] for s in samples]
        corr = self._pearson(xs, ys)
        avg_q = sum(ys) / len(ys)

        if corr is not None and corr < self.corr_threshold:
            reason = (f"correlation {corr:.2f} < threshold {self.corr_threshold} "
                      f"(n={len(samples)})")
            self._trigger(reason)
            return {"triggered": True, "reason": reason,
                    "correlation": corr, "avg_quality": avg_q}
        if avg_q < self.quality_floor:
            reason = (f"avg human quality {avg_q:.2f} < floor {self.quality_floor}")
            self._trigger(reason)
            return {"triggered": True, "reason": reason,
                    "correlation": corr, "avg_quality": avg_q}
        return {"triggered": False, "reason": "ok",
                "correlation": corr, "avg_quality": avg_q, "n": len(samples)}

    def _trigger(self, reason: str) -> None:
        AUDIT.append(FirewallEvent("FW6", "intent_drift_triggered", reason))
        # 联动：冻结 L1 进化
        try:
            from evolution_freeze import EvolutionFreeze
            EvolutionFreeze().freeze(reason=f"intent firewall: {reason}")
        except Exception as e:
            AUDIT.append(FirewallEvent("FW6", "freeze_link_failed", str(e)))


# ---------------------------------------------------------------------------
# 统一查询面板
# ---------------------------------------------------------------------------
class FirewallPanel:
    """六大舱壁统一状态面板"""

    def __init__(self):
        self.fw1 = DegradedAutonomy()
        self.fw2 = Watchdog()
        self.fw3 = QCCircuitBreaker()
        self.fw4 = StateStore()
        self.fw6 = IntentFirewall()
        # FW5 通过 kill_switch 查询，避免循环导入开销

    def status(self) -> Dict[str, Any]:
        try:
            from kill_switch import KillSwitch
            fw5_level = KillSwitch().level().name
        except Exception:
            fw5_level = "unknown"
        return {
            "FW1_degraded_autonomy": self.fw1.check().value,
            "FW2_watchdog": self.fw2.status(),
            "FW3_qc_breaker": self.fw3.status(),
            "FW4_state_store_keys": len(self.fw4._state),
            "FW5_kill_switch": fw5_level,
            "FW6_intent": self.fw6.check(),
        }


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _selftest() -> None:
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="fw_test_")
    print(f"[firewalls] 自测 state_dir={tmpd}")

    # FW1
    fw1 = DegradedAutonomy(state_dir=tmpd)
    fw1.HEARTBEAT_TIMEOUT_S = 0.2
    fw1.save_policy_snapshot({"action": "publish", "whitelist": ["publish"]})
    assert fw1.load_policy_snapshot()["policy"]["action"] == "publish"
    fw1.heartbeat()
    assert fw1.check() == FirewallStatus.NORMAL
    time.sleep(0.3)
    assert fw1.check() == FirewallStatus.DEGRADED
    assert fw1.is_degraded()
    assert not fw1.recover(human_confirmed=False)
    assert fw1.recover(human_confirmed=True)
    print("[firewalls] FW1 降级自治 OK")

    # FW2
    fired = []
    wd = Watchdog(check_interval_s=0.1)
    wd.register("brain", timeout_s=0.2, on_timeout=lambda n: fired.append(n))
    wd.start()
    wd.ping("brain")
    time.sleep(0.15)
    wd.ping("brain")
    time.sleep(0.35)  # 超时
    wd.stop()
    assert "brain" in fired, f"watchdog 未触发: {fired}"
    print("[firewalls] FW2 看门狗 OK")

    # FW3
    qc = QCCircuitBreaker(timeout_s=0.3, fail_threshold=2, cooldown_s=60)
    assert qc.decide(lambda: True, video_id="v1") is True
    assert qc.decide(lambda: (_ for _ in ()).throw(RuntimeError("x")),
                     video_id="v2") is False  # 异常 → fail-closed
    def _slow():
        time.sleep(5)
        return True
    assert qc.decide(_slow, video_id="v3") is False  # 超时 → fail-closed
    st = qc.status()
    assert st["open"] is True  # 连续失败达阈值 → 熔断器打开
    assert qc.decide(lambda: True, video_id="v4") is False  # 打开时直接拒绝
    print("[firewalls] FW3 QC熔断器 OK")

    # FW4
    store = StateStore(state_dir=tmpd)
    store.set("k1", {"a": 1})
    assert store.get("k1") == {"a": 1}
    store.delete("k1")
    assert store.get("k1") is None
    store.set("k2", "v2")
    store.snapshot()
    store2 = StateStore(state_dir=tmpd)  # 重放恢复
    assert store2.get("k2") == "v2"
    print("[firewalls] FW4 状态解耦 OK")

    # FW6：构造 Goodhart 场景（爆款率高但人工评分低 → 相关性为负 → 触发）
    fw6 = IntentFirewall(state_dir=tmpd, corr_threshold=0.3,
                         quality_floor=6.0, window=30)
    assert fw6.check()["triggered"] is False  # 样本不足
    import random
    random.seed(7)
    for i in range(10):
        # 爆款率上升，人工质量下降 → 负相关
        fw6.record(viral_rate=5.0 + i * 0.5,
                   human_quality=8.0 - i * 0.4)
    res = fw6.check()
    assert res["triggered"] is True, f"FW6 应触发: {res}"
    print(f"[firewalls] FW6 意图防火墙 OK (corr={res['correlation']:.2f})")

    # 正常场景不触发
    fw6b = IntentFirewall(state_dir=tmpd + "_b", corr_threshold=0.3,
                          quality_floor=6.0, window=30)
    for i in range(10):
        fw6b.record(viral_rate=5.0 + i * 0.3 + random.uniform(-0.1, 0.1),
                    human_quality=7.0 + i * 0.2 + random.uniform(-0.1, 0.1))
    res2 = fw6b.check()
    assert res2["triggered"] is False, f"FW6 误触发: {res2}"
    print(f"[firewalls] FW6 正常场景不触发 OK (corr={res2['correlation']:.2f})")

    print("[firewalls] 全部自测通过 ✓")


if __name__ == "__main__":
    _selftest()
