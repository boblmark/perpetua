#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kill_switch.py — 数字孪生 DNA v3.1 三档 Kill Switch

三档：
  L1 PAUSE_NEW    — 暂停新任务生成（优雅）：进行中的任务继续完成，不再接受新任务
  L2 PAUSE_AUTO   — 暂停所有自动化（保留手动）：自动化流水线全停，人工操作仍可用
  L3 FULL_STOP    — 全停（含手动，需物理确认）：一切停止，需人工到场/二次确认才能恢复

规则：
  - 只能逐级加深（L1→L2→L3），不能跳级（防误触）
  - 释放（恢复）必须人工确认，且 L3 需要"物理确认"（如环境变量 + 确认文件双因子）
  - 每次 engage/release 写审计日志
  - 状态持久化到文件，进程重启后保持
"""

from __future__ import annotations

import json
import os
import time
from enum import Enum
from typing import Any, Dict, Optional


STATE_DIR = os.environ.get("PERPETUA_STATE_DIR", "/home/hatch/data/perpetua/state")
os.makedirs(STATE_DIR, exist_ok=True)
STATE_PATH = os.path.join(STATE_DIR, "kill_switch.json")
AUDIT_PATH = os.path.join(STATE_DIR, "kill_switch_audit.jsonl")

# L3 物理确认：需要同时存在确认文件 + 环境变量
L3_CONFIRM_FILE = os.path.join(STATE_DIR, "L3_PHYSICAL_CONFIRM")
L3_CONFIRM_ENV = "PERPETUA_L3_CONFIRM"  # 值为 "YES" 才算确认


class KillLevel(Enum):
    """Kill Switch 档位（数字越大越深）"""
    NORMAL = 0       # 正常运行
    L1 = 1           # 暂停新任务生成
    L2 = 2           # 暂停所有自动化（保留手动）
    L3 = 3           # 全停（含手动）


_LEVEL_DESC = {
    KillLevel.NORMAL: "正常运行",
    KillLevel.L1: "L1: 暂停新任务生成（进行中任务继续）",
    KillLevel.L2: "L2: 暂停所有自动化（保留手动操作）",
    KillLevel.L3: "L3: 全停（含手动，需物理确认恢复）",
}


class KillSwitch:
    """三档 Kill Switch（状态持久化 + 审计）"""

    def __init__(self, state_path: str = STATE_PATH,
                 audit_path: str = AUDIT_PATH):
        self.state_path = state_path
        self.audit_path = audit_path
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        self._level = KillLevel.NORMAL
        self._meta: Dict[str, Any] = {}
        self._load()

    # -- 持久化 ----------------------------------------------------------
    def _load(self) -> None:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._level = KillLevel(data.get("level", 0))
                self._meta = data.get("meta", {})
            except (json.JSONDecodeError, ValueError, KeyError):
                self._level = KillLevel.NORMAL
                self._meta = {}

    def _save(self) -> None:
        data = {"level": self._level.value, "meta": self._meta,
                "updated_ts": time.time()}
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)  # 原子写入

    def _audit(self, action: str, detail: str = "") -> None:
        entry = {
            "action": action,
            "level": self._level.name,
            "detail": detail,
            "ts": time.time(),
            "ts_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- 查询 ------------------------------------------------------------
    def level(self) -> KillLevel:
        self._load()  # 每次查询重读文件（多进程可见）
        return self._level

    def describe(self) -> str:
        return _LEVEL_DESC[self.level()]

    def allows_new_tasks(self) -> bool:
        return self.level() == KillLevel.NORMAL

    def allows_automation(self) -> bool:
        return self.level().value <= KillLevel.L1.value

    def allows_manual(self) -> bool:
        return self.level().value <= KillLevel.L2.value

    # -- 操作 ------------------------------------------------------------
    def engage(self, level: KillLevel, reason: str = "",
               operator: str = "") -> bool:
        """
        启动 Kill Switch。只能逐级加深（NORMAL→L1→L2→L3）。
        返回 True 表示档位发生变化。
        """
        if level == KillLevel.NORMAL:
            raise ValueError("engage 不能用于恢复，请用 release()")
        current = self.level()
        if level.value <= current.value:
            return False  # 已在同级或更深，不重复触发
        if level.value != current.value + 1:
            # 不允许跳级：必须逐级加深（防误触 L3）
            raise ValueError(
                f"不允许跳级：当前 {current.name}，目标 {level.name}，"
                f"请先 engage {KillLevel(current.value + 1).name}")
        self._level = level
        self._meta = {"reason": reason, "operator": operator,
                      "engaged_ts": time.time()}
        self._save()
        self._audit("engage", f"reason={reason} operator={operator}")
        return True

    def release(self, operator: str = "",
                physical_confirm: bool = False) -> bool:
        """
        释放 Kill Switch，回到 NORMAL。
        L3 释放需要物理确认：确认文件存在 + 环境变量 PERPETUA_L3_CONFIRM=YES。
        """
        current = self.level()
        if current == KillLevel.NORMAL:
            return False
        if current == KillLevel.L3:
            file_ok = os.path.exists(L3_CONFIRM_FILE)
            env_ok = os.environ.get(L3_CONFIRM_ENV) == "YES"
            if not (physical_confirm and file_ok and env_ok):
                self._audit("release_denied_L3",
                            f"physical_confirm={physical_confirm} "
                            f"file_ok={file_ok} env_ok={env_ok}")
                raise PermissionError(
                    "L3 释放需要物理确认：调用 release(physical_confirm=True) "
                    f"且确认文件 {L3_CONFIRM_FILE} 存在 "
                    f"且环境变量 {L3_CONFIRM_ENV}=YES")
            # 消耗确认文件（一次性）
            try:
                os.remove(L3_CONFIRM_FILE)
            except OSError:
                pass
        self._level = KillLevel.NORMAL
        self._meta = {"released_by": operator, "released_ts": time.time(),
                      "prev_level": current.name}
        self._save()
        self._audit("release", f"operator={operator} prev={current.name}")
        return True

    def create_l3_confirm_file(self) -> str:
        """创建 L3 物理确认文件（人工到场操作）"""
        with open(L3_CONFIRM_FILE, "w", encoding="utf-8") as f:
            f.write(f"confirmed at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self._audit("l3_confirm_file_created", L3_CONFIRM_FILE)
        return L3_CONFIRM_FILE

    def audit_tail(self, n: int = 20):
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
    tmpd = tempfile.mkdtemp(prefix="ks_test_")
    sp = os.path.join(tmpd, "kill_switch.json")
    ap = os.path.join(tmpd, "kill_switch_audit.jsonl")

    ks = KillSwitch(state_path=sp, audit_path=ap)
    assert ks.level() == KillLevel.NORMAL
    assert ks.allows_new_tasks() and ks.allows_automation() and ks.allows_manual()
    print("[kill_switch] 初始 NORMAL OK")

    # 逐级加深
    assert ks.engage(KillLevel.L1, reason="test", operator="selftest") is True
    assert ks.level() == KillLevel.L1
    assert not ks.allows_new_tasks() and ks.allows_automation()
    print("[kill_switch] L1 OK（新任务停，自动化继续）")

    # 跳级应被拒绝
    try:
        ks.engage(KillLevel.L3, reason="skip")
        raise AssertionError("跳级应被拒绝")
    except ValueError as e:
        print(f"[kill_switch] 跳级拒绝 OK: {e}")

    assert ks.engage(KillLevel.L2, reason="test2") is True
    assert ks.level() == KillLevel.L2
    assert not ks.allows_automation() and ks.allows_manual()
    print("[kill_switch] L2 OK（自动化停，手动保留）")

    assert ks.engage(KillLevel.L3, reason="test3") is True
    assert ks.level() == KillLevel.L3
    assert not ks.allows_manual()
    print("[kill_switch] L3 OK（全停）")

    # 状态持久化：新实例应读到 L3
    ks2 = KillSwitch(state_path=sp, audit_path=ap)
    assert ks2.level() == KillLevel.L3
    print("[kill_switch] 持久化 OK（重启后保持 L3）")

    # L3 无物理确认释放应被拒绝
    try:
        ks2.release(operator="selftest")
        raise AssertionError("L3 无确认释放应被拒绝")
    except PermissionError as e:
        print(f"[kill_switch] L3 无确认拒绝 OK")

    # 物理确认释放
    global L3_CONFIRM_FILE
    old_confirm = L3_CONFIRM_FILE
    L3_CONFIRM_FILE = os.path.join(tmpd, "L3_PHYSICAL_CONFIRM")
    ks2.create_l3_confirm_file()
    os.environ["PERPETUA_L3_CONFIRM"] = "YES"
    assert ks2.release(operator="selftest", physical_confirm=True) is True
    assert ks2.level() == KillLevel.NORMAL
    del os.environ["PERPETUA_L3_CONFIRM"]
    L3_CONFIRM_FILE = old_confirm
    print("[kill_switch] L3 物理确认释放 OK")

    # 审计日志
    tail = ks2.audit_tail(50)
    actions = [e["action"] for e in tail]
    assert "engage" in actions and "release" in actions
    print(f"[kill_switch] 审计日志 OK（{len(tail)} 条）")

    print("[kill_switch] 全部自测通过 ✓")


if __name__ == "__main__":
    _selftest()
