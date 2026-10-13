#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
intent_firewall.py — 数字孪生 DNA v3.1 意图防火墙（第六舱壁的独立模块）

保护"意图"，而非仅保护"生存"。

问题（Kimi 终审指出）：
  五大舱壁和 QC 熔断器保护的全部是"生存"（fail-closed 保可用性），
  没有任何一个舱壁保护"意图"。当 23:00 的 L1 自动进化日复一日对着
  P(播放>10万|72h) 这个可被 Goodhart 化的代理指标调参时，系统可以在
  全部防火墙绿灯的情况下，安静地把自己进化成一台标题党机器——
  而这正是它设计得越好越测不出来的失败模式。

机制：
  - 输入：代理指标（爆款率 viral_rate）+ 人工抽审质量评分（human_quality, 0-10）
  - 维护滑动窗口样本，计算 Pearson 相关性
  - 触发条件（二者任一）：
      1. 相关性 < corr_threshold（默认 0.3）：爆款率与人工质量脱钩
      2. 人工质量均值 < quality_floor（默认 6.0）：绝对质量下滑
  - 触发动作：
      1. 冻结 L1 进化（联动 evolution_freeze）
      2. 告警（写入告警文件，可被外部监控采集）
      3. 审计记录
  - 人工创意旁路打标：source=human_bypass 的样本同样进入因果库，
    参与同一目标函数回读（不破坏"一切皆可度量"）

依赖：仅 Python stdlib。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


STATE_DIR = os.environ.get("PERPETUA_STATE_DIR", "/home/hatch/data/perpetua/state")
os.makedirs(STATE_DIR, exist_ok=True)
DATA_PATH = os.path.join(STATE_DIR, "intent_samples.jsonl")
ALERT_PATH = os.path.join(STATE_DIR, "intent_alerts.jsonl")
AUDIT_PATH = os.path.join(STATE_DIR, "intent_firewall_audit.jsonl")


class IntentFirewall:
    """
    意图防火墙。

    用法：
        fw = IntentFirewall()
        fw.record(viral_rate=5.6, human_quality=7.5, source="auto")
        fw.record(viral_rate=8.1, human_quality=4.2, source="human_bypass")
        result = fw.check()   # {"triggered": bool, ...}
    """

    def __init__(self,
                 corr_threshold: float = 0.3,
                 quality_floor: float = 6.0,
                 window: int = 30,
                 min_samples: int = 5,
                 data_path: str = DATA_PATH,
                 alert_path: str = ALERT_PATH,
                 audit_path: str = AUDIT_PATH):
        self.corr_threshold = corr_threshold
        self.quality_floor = quality_floor
        self.window = window
        self.min_samples = min_samples
        self.data_path = data_path
        self.alert_path = alert_path
        self.audit_path = audit_path
        for p in (data_path, alert_path, audit_path):
            d = os.path.dirname(p)
            if d:
                os.makedirs(d, exist_ok=True)

    # -- 样本记录 ----------------------------------------------------------
    def record(self, viral_rate: float, human_quality: float,
               source: str = "auto", note: str = "") -> None:
        """
        记录一次（代理指标，人工质量）配对。
        source: "auto"（自动流水线）或 "human_bypass"（人工创意旁路）。
        旁路样本同样入库、同样参与回读——度量体系的一部分。
        """
        if not (0.0 <= human_quality <= 10.0):
            raise ValueError(f"human_quality 必须在 0-10 之间， got {human_quality}")
        if viral_rate < 0:
            raise ValueError(f"viral_rate 不能为负，got {viral_rate}")
        entry = {
            "viral_rate": viral_rate,
            "human_quality": human_quality,
            "source": source,
            "note": note,
            "ts": time.time(),
        }
        with open(self.data_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def samples(self) -> List[Dict[str, Any]]:
        """读取滑动窗口内样本"""
        if not os.path.exists(self.data_path):
            return []
        out = []
        with open(self.data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out[-self.window:]

    # -- 统计 --------------------------------------------------------------
    @staticmethod
    def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
        n = len(xs)
        if n < 3 or len(ys) != n:
            return None
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        if dx == 0 or dy == 0:
            return None  # 无方差，无法计算相关性
        return num / (dx * dy)

    # -- 检查 --------------------------------------------------------------
    def check(self) -> Dict[str, Any]:
        """
        检查意图偏离。返回：
          {"triggered": bool, "reason": str, "correlation": float|None,
           "avg_quality": float|None, "n": int, "n_bypass": int}
        """
        samples = self.samples()
        n = len(samples)
        if n < self.min_samples:
            return {"triggered": False, "reason": "insufficient_samples",
                    "correlation": None, "avg_quality": None, "n": n,
                    "n_bypass": 0}

        xs = [s["viral_rate"] for s in samples]
        ys = [s["human_quality"] for s in samples]
        n_bypass = sum(1 for s in samples if s.get("source") == "human_bypass")
        corr = self.pearson(xs, ys)
        avg_q = sum(ys) / n

        base = {"correlation": corr, "avg_quality": round(avg_q, 2),
                "n": n, "n_bypass": n_bypass}

        # 条件 1：相关性跌破阈值 → 代理指标与人工质量脱钩（Goodhart 信号）
        if corr is not None and corr < self.corr_threshold:
            reason = (f"意图偏离：爆款率与人工质量相关性 {corr:.2f} < "
                      f"阈值 {self.corr_threshold}（n={n}）")
            self._trigger(reason, base)
            return {"triggered": True, "reason": reason, **base}

        # 条件 2：人工质量绝对值跌破下限
        if avg_q < self.quality_floor:
            reason = (f"意图偏离：人工抽审质量均值 {avg_q:.2f} < "
                      f"下限 {self.quality_floor}（n={n}）")
            self._trigger(reason, base)
            return {"triggered": True, "reason": reason, **base}

        return {"triggered": False, "reason": "ok", **base}

    # -- 触发 --------------------------------------------------------------
    def _trigger(self, reason: str, metrics: Dict[str, Any]) -> None:
        # 1. 审计
        self._audit("intent_drift_triggered", reason)
        # 2. 告警（外部监控可采集此文件）
        alert = {"level": "CRITICAL", "firewall": "intent",
                 "reason": reason, "metrics": metrics,
                 "ts": time.time(),
                 "ts_human": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(self.alert_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")
        # 3. 联动：冻结 L1 进化（意图偏离时停止一切自我突变）
        try:
            from evolution_freeze import EvolutionFreeze
            changed = EvolutionFreeze().freeze(
                reason=f"intent firewall: {reason}",
                operator="intent_firewall")
            self._audit("linked_freeze", f"frozen_changed={changed}")
        except Exception as e:
            self._audit("link_freeze_failed", str(e))

    def _audit(self, action: str, detail: str = "") -> None:
        entry = {"action": action, "detail": detail, "ts": time.time(),
                 "ts_human": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def alerts(self, n: int = 20) -> List[Dict[str, Any]]:
        if not os.path.exists(self.alert_path):
            return []
        with open(self.alert_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        return [json.loads(l) for l in lines[-n:]]


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _selftest() -> None:
    import random
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="intent_test_")
    dp = os.path.join(tmpd, "intent_samples.jsonl")
    ap = os.path.join(tmpd, "intent_alerts.jsonl")
    up = os.path.join(tmpd, "intent_audit.jsonl")
    # 冻结状态隔离到 tmpd，避免污染生产状态
    fz_sp = os.path.join(tmpd, "evolution_freeze.json")
    fz_ap = os.path.join(tmpd, "evolution_freeze_audit.jsonl")
    import evolution_freeze as _ef
    _orig_sp, _orig_ap = _ef.STATE_PATH, _ef.AUDIT_PATH
    _ef.STATE_PATH, _ef.AUDIT_PATH = fz_sp, fz_ap

    try:
        fw = IntentFirewall(corr_threshold=0.3, quality_floor=6.0,
                            window=30, min_samples=5,
                            data_path=dp, alert_path=ap, audit_path=up)

        # 样本不足不触发
        assert fw.check()["triggered"] is False
        print("[intent] 样本不足不触发 OK")

        # 输入校验
        try:
            fw.record(viral_rate=5.0, human_quality=11.0)
            raise AssertionError("越界质量分应被拒绝")
        except ValueError:
            print("[intent] 输入校验 OK")

        # Goodhart 场景：爆款率↑但人工质量↓ → 负相关 → 触发
        random.seed(42)
        for i in range(10):
            fw.record(viral_rate=5.0 + i * 0.6 + random.uniform(-0.2, 0.2),
                      human_quality=8.0 - i * 0.45 + random.uniform(-0.2, 0.2),
                      source="auto" if i % 3 else "human_bypass")
        res = fw.check()
        assert res["triggered"] is True, f"应触发: {res}"
        assert res["correlation"] < 0.3
        assert res["n_bypass"] == 4  # 旁路样本同样计入
        print(f"[intent] Goodhart 场景触发 OK "
              f"(corr={res['correlation']:.2f}, bypass={res['n_bypass']})")

        # 联动：进化冻结应被触发
        fz = _ef.EvolutionFreeze(state_path=fz_sp, audit_path=fz_ap)
        assert fz.is_frozen() is True
        print("[intent] 联动冻结进化 OK")

        # 告警文件
        alerts = fw.alerts(5)
        assert len(alerts) == 1 and alerts[0]["level"] == "CRITICAL"
        print("[intent] 告警记录 OK")

        # 正常场景：正相关 + 高质量 → 不触发
        dp2 = os.path.join(tmpd, "s2.jsonl")
        fw2 = IntentFirewall(corr_threshold=0.3, quality_floor=6.0,
                             window=30, min_samples=5,
                             data_path=dp2,
                             alert_path=os.path.join(tmpd, "a2.jsonl"),
                             audit_path=os.path.join(tmpd, "u2.jsonl"))
        for i in range(10):
            fw2.record(viral_rate=5.0 + i * 0.3 + random.uniform(-0.1, 0.1),
                       human_quality=7.0 + i * 0.15 + random.uniform(-0.1, 0.1))
        res2 = fw2.check()
        assert res2["triggered"] is False, f"误触发: {res2}"
        print(f"[intent] 正常场景不触发 OK (corr={res2['correlation']:.2f})")

        # 质量下限场景：相关性正常但绝对质量过低 → 触发
        dp3 = os.path.join(tmpd, "s3.jsonl")
        fw3 = IntentFirewall(corr_threshold=0.3, quality_floor=6.0,
                             window=30, min_samples=5,
                             data_path=dp3,
                             alert_path=os.path.join(tmpd, "a3.jsonl"),
                             audit_path=os.path.join(tmpd, "u3.jsonl"))
        for i in range(8):
            # 正相关但整体质量低（4.x 分）
            fw3.record(viral_rate=5.0 + i * 0.2,
                       human_quality=4.0 + i * 0.1)
        res3 = fw3.check()
        assert res3["triggered"] is True and "质量均值" in res3["reason"]
        print(f"[intent] 质量下限触发 OK (avg_q={res3['avg_quality']})")
    finally:
        _ef.STATE_PATH, _ef.AUDIT_PATH = _orig_sp, _orig_ap

    print("[intent] 全部自测通过 ✓")


if __name__ == "__main__":
    _selftest()
