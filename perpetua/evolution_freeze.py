#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evolution_freeze.py — 数字孪生 DNA v3.1 进化冻结开关

与"人工接管"的区别：
  - 人工接管：人接管控制权，系统听人的
  - 进化冻结：系统继续运行，但停止一切自我突变
    （L1 参数进化、L2 知识进化、L3 策略进化、L4 代码进化全部暂停）

规则：
  - 全局、一键、即时生效
  - freeze() / unfreeze() / is_frozen()
  - 状态持久化到文件，进程重启后保持
  - 默认状态：FROZEN（frozen by default）——Week 1 用固定版本跑，
    只有人工明确解冻后才允许进化
  - 每次 freeze/unfreeze 写审计日志
  - 断路器/意图防火墙触发时可自动联动冻结（调用 freeze 即可）

依赖：仅 Python stdlib。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List


STATE_DIR = os.environ.get("PERPETUA_STATE_DIR", "/home/hatch/data/perpetua/state")
os.makedirs(STATE_DIR, exist_ok=True)
STATE_PATH = os.path.join(STATE_DIR, "evolution_freeze.json")
AUDIT_PATH = os.path.join(STATE_DIR, "evolution_freeze_audit.jsonl")


class EvolutionFreeze:
    """
    进化冻结开关。

    典型用法（在进化引擎入口处）：
        from evolution_freeze import EvolutionFreeze
        if EvolutionFreeze().is_frozen():
            return  # 跳过本轮进化
        ...执行 L1/L2/L3/L4 进化...
    """

    def __init__(self, state_path: str = STATE_PATH,
                 audit_path: str = AUDIT_PATH):
        self.state_path = state_path
        self.audit_path = audit_path
        os.makedirs(os.path.dirname(state_path), exist_ok=True)

    # -- 内部读写 ----------------------------------------------------------
    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.state_path):
            # 默认 FROZEN（frozen by default）
            return {"frozen": True, "reason": "default: frozen by default",
                    "ts": time.time(), "operator": "system"}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {"frozen": True, "reason": "corrupt state → fail-closed",
                    "ts": time.time(), "operator": "system"}

    def _write(self, frozen: bool, reason: str, operator: str) -> None:
        data = {"frozen": frozen, "reason": reason, "operator": operator,
                "ts": time.time(),
                "ts_human": time.strftime("%Y-%m-%d %H:%M:%S")}
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)  # 原子写入
        self._audit("freeze" if frozen else "unfreeze",
                    f"reason={reason} operator={operator}")

    def _audit(self, action: str, detail: str = "") -> None:
        entry = {"action": action, "detail": detail, "ts": time.time(),
                 "ts_human": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- 公开接口 ----------------------------------------------------------
    def freeze(self, reason: str = "", operator: str = "system") -> bool:
        """
        冻结进化。即时生效。幂等（已冻结时返回 False）。
        """
        cur = self._read()
        if cur.get("frozen"):
            return False
        self._write(True, reason or "manual freeze", operator)
        return True

    def unfreeze(self, reason: str = "", operator: str = "") -> bool:
        """
        解冻进化。必须提供 operator（人工），不允许匿名解冻。
        幂等（已解冻时返回 False）。
        """
        if not operator:
            self._audit("unfreeze_denied", "operator required")
            raise PermissionError("解冻必须指定 operator（人工确认）")
        cur = self._read()
        if not cur.get("frozen"):
            return False
        self._write(False, reason or "manual unfreeze", operator)
        return True

    def is_frozen(self) -> bool:
        """是否处于冻结状态（进化引擎每轮调用）"""
        return bool(self._read().get("frozen", True))

    def status(self) -> Dict[str, Any]:
        """完整状态"""
        return self._read()

    def audit_tail(self, n: int = 20) -> List[Dict[str, Any]]:
        if not os.path.exists(self.audit_path):
            return []
        with open(self.audit_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        return [json.loads(l) for l in lines[-n:]]


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _selftest() -> None:
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="fz_test_")
    sp = os.path.join(tmpd, "evolution_freeze.json")
    ap = os.path.join(tmpd, "evolution_freeze_audit.jsonl")

    fz = EvolutionFreeze(state_path=sp, audit_path=ap)

    # 默认 FROZEN
    assert fz.is_frozen() is True
    st = fz.status()
    assert st["frozen"] is True and "default" in st["reason"]
    print("[freeze] 默认 FROZEN OK")

    # freeze 幂等
    assert fz.freeze(reason="x") is False
    print("[freeze] 已冻结时 freeze 幂等 OK")

    # 匿名解冻被拒绝
    try:
        fz.unfreeze(reason="anon")
        raise AssertionError("匿名解冻应被拒绝")
    except PermissionError:
        print("[freeze] 匿名解冻拒绝 OK")

    # 人工解冻
    assert fz.unfreeze(reason="week1 done", operator="selftest") is True
    assert fz.is_frozen() is False
    print("[freeze] 人工解冻 OK")

    # 持久化：新实例读到解冻状态
    fz2 = EvolutionFreeze(state_path=sp, audit_path=ap)
    assert fz2.is_frozen() is False
    print("[freeze] 持久化 OK")

    # 重新冻结（模拟断路器联动）
    assert fz2.freeze(reason="behavior breaker tripped",
                      operator="behavior_circuit_breaker") is True
    assert fz2.is_frozen() is True
    fz3 = EvolutionFreeze(state_path=sp, audit_path=ap)
    assert fz3.is_frozen() is True
    print("[freeze] 联动冻结 + 重启保持 OK")

    # 审计
    tail = fz3.audit_tail(10)
    actions = [e["action"] for e in tail]
    assert "freeze" in actions and "unfreeze" in actions
    print(f"[freeze] 审计日志 OK（{len(tail)} 条）")

    print("[freeze] 全部自测通过 ✓")


if __name__ == "__main__":
    _selftest()
