#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L1 进化引擎 · 数字孪生 DNA v3.1

每天 23:00 运行（由 cron 触发本文件的 daily_evolution()）。
只做 L1 参数进化：Bandit 权重基于因果库数据更新。

安全设计（来自四脑终审）：
  1. 默认冻结：状态文件不存在或 frozen=true 时直接跳过（Brain 2 要求）。
  2. 漂移预算（drift budget）：单个参数值每日最大变化量，防单日剧变。
  3. 变更归因：每次变更写 causal chain（改了什么/为什么/数据依据）。
  4. 单调漂移检测：同一参数值连续 N 天同方向漂移 → 自动冻结，
     转 L3 人工批准（Kimi 评审要求）。
  5. 意图舱壁预留：代理指标 Goodhart 化检测接口（人工抽审评分跌破阈值
     时冻结），本版提供 freeze() 接口，具体评分接入待 Phase 2。

文件：
  bandit_weights.json : {feature: {value: {"weight": float, "deltas": [float...]}}}
  evolution_state.json: {"frozen": bool, "reason": str, "frozen_at": str}
  evolution_log.jsonl : 每次变更一行 JSON（WORM 式追加，不删改）
  dna_version.txt     : v3.1.x

目录：/home/hatch/data/perpetua/（环境变量 PERPETUA_DIR 可覆盖）
"""

import json
import os
from datetime import datetime, timezone

try:
    from causal_db import CausalDB
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from causal_db import CausalDB

PERPETUA_DIR = os.environ.get("PERPETUA_DIR", "/home/hatch/data/perpetua")

# ---- L1 超参数（调整需走 L3） ----
DRIFT_BUDGET = 0.05        # 单个参数值每日最大变化量
MONOTONIC_DAYS = 5         # 连续同方向漂移 N 天 → 冻结
MIN_SAMPLES = 10           # 每个特征值最少样本数才参与进化
EPSILON = 1e-9             # 视为"无变化"的阈值
MAX_DELTAS_KEPT = 30       # 每个参数值保留的 delta 历史长度

BASE_VERSION = "v3.1"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _p(name: str) -> str:
    return os.path.join(PERPETUA_DIR, name)


def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json_atomic(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class EvolutionEngine:
    def __init__(self, base_dir: "str | None" = None,
                 db: "CausalDB | None" = None):
        self.base_dir = base_dir or PERPETUA_DIR
        os.makedirs(self.base_dir, exist_ok=True)
        self.weights_path = os.path.join(self.base_dir, "bandit_weights.json")
        self.state_path = os.path.join(self.base_dir, "evolution_state.json")
        self.log_path = os.path.join(self.base_dir, "evolution_log.jsonl")
        self.version_path = os.path.join(self.base_dir, "dna_version.txt")
        self.db = db  # 允许注入（测试用）；None 则运行时按需打开

    # ---------- 状态 ----------

    def get_state(self) -> dict:
        """默认冻结：文件不存在 → frozen=true（Brain 2 要求 Week 1 默认关）。"""
        return _load_json(self.state_path,
                          {"frozen": True, "reason": "default-frozen",
                           "frozen_at": None})

    def freeze(self, reason: str) -> None:
        _save_json_atomic(self.state_path, {
            "frozen": True, "reason": reason, "frozen_at": _utcnow()})
        self._log({"ts": _utcnow(), "event": "freeze", "reason": reason})

    def unfreeze(self, reason: str = "manual") -> None:
        _save_json_atomic(self.state_path, {
            "frozen": False, "reason": reason, "frozen_at": None})
        self._log({"ts": _utcnow(), "event": "unfreeze", "reason": reason})

    def is_frozen(self) -> bool:
        return bool(self.get_state().get("frozen", True))

    # ---------- 版本 ----------

    def get_version(self) -> str:
        try:
            with open(self.version_path, "r", encoding="utf-8") as f:
                v = f.read().strip()
                return v or f"{BASE_VERSION}.0"
        except FileNotFoundError:
            return f"{BASE_VERSION}.0"

    def _bump_version(self) -> str:
        v = self.get_version()
        try:
            patch = int(v.rsplit(".", 1)[1]) + 1
        except (ValueError, IndexError):
            patch = 1
        new_v = f"{BASE_VERSION}.{patch}"
        with open(self.version_path, "w", encoding="utf-8") as f:
            f.write(new_v + "\n")
        return new_v

    # ---------- 日志（WORM 追加） ----------

    def _log(self, entry: dict) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ---------- 权重 ----------

    def get_weights(self) -> dict:
        return _load_json(self.weights_path, {})

    def _save_weights(self, w: dict) -> None:
        _save_json_atomic(self.weights_path, w)

    def get_allocation(self, feature: str) -> dict:
        """归一化后的分配比例（Bandit 读取用）。"""
        w = self.get_weights().get(feature, {})
        total = sum(v.get("weight", 0.0) for v in w.values())
        if total <= 0:
            n = len(w)
            return {k: (1.0 / n if n else 0.0) for k in w}
        return {k: v.get("weight", 0.0) / total for k, v in w.items()}

    # ---------- 每日进化 ----------

    def daily_evolution(self) -> dict:
        """L1 每日进化主入口。返回摘要 dict。"""
        if self.is_frozen():
            info = {"status": "skipped_frozen",
                    "reason": self.get_state().get("reason")}
            print(f"[evolution] 跳过：进化已冻结（{info['reason']}）")
            return info

        db = self.db or CausalDB()
        own_db = self.db is None
        try:
            weights = self.get_weights()
            changes = []
            frozen_trigger = None

            for feature, vals in list(weights.items()):
                rates = db.get_viral_rate_by_feature(feature,
                                                     min_n=MIN_SAMPLES)
                if not rates:
                    continue
                for value, entry in vals.items():
                    r = rates.get(value)
                    if r is None:
                        continue  # 样本不足，保持不动
                    old_w = float(entry.get("weight", 0.5))
                    # 目标：经验爆款率（归一化到 [0,1] 已天然成立）
                    target = r["rate"]
                    raw_delta = target - old_w
                    # 漂移预算：钳制单日变化量
                    delta = max(-DRIFT_BUDGET,
                                min(DRIFT_BUDGET, raw_delta))
                    if abs(delta) < EPSILON:
                        continue
                    new_w = old_w + delta
                    entry["weight"] = round(new_w, 6)
                    deltas = entry.setdefault("deltas", [])
                    deltas.append(round(delta, 6))
                    deltas[:] = deltas[-MAX_DELTAS_KEPT:]

                    changes.append({
                        "feature": feature, "value": value,
                        "old": old_w, "new": new_w, "delta": delta,
                        "data_basis": r,
                    })

                    # 单调漂移检测：连续 N 天同方向 → 冻结转 L3
                    recent = deltas[-MONOTONIC_DAYS:]
                    if (len(recent) == MONOTONIC_DAYS
                            and all(d > EPSILON for d in recent)
                            or len(recent) == MONOTONIC_DAYS
                            and all(d < -EPSILON for d in recent)):
                        frozen_trigger = (
                            f"单调漂移：{feature}={value} 连续 "
                            f"{MONOTONIC_DAYS} 天同向漂移，转 L3 人工批准")

            if frozen_trigger:
                self._save_weights(weights)
                self.freeze(frozen_trigger)
                print(f"[evolution] ⛔ {frozen_trigger}")
                return {"status": "frozen", "reason": frozen_trigger,
                        "changes": changes}

            if not changes:
                print("[evolution] 无变化（数据不足或已收敛）")
                return {"status": "no_change", "changes": []}

            self._save_weights(weights)
            new_version = self._bump_version()
            for c in changes:
                self._log({
                    "ts": _utcnow(),
                    "event": "l1_update",
                    "version": new_version,
                    "param": f"{c['feature']}={c['value']}",
                    "old_weight": c["old"],
                    "new_weight": c["new"],
                    "delta": round(c["delta"], 6),
                    "reason": "经验爆款率驱动的 L1 参数进化",
                    "data_basis": c["data_basis"],
                    # 变更归因链：改了什么 / 为什么 / 数据依据 / 约束
                    "attribution": [
                        "source=causal_db.get_viral_rate_by_feature",
                        f"drift_budget={DRIFT_BUDGET}",
                        f"min_samples={MIN_SAMPLES}",
                        f"monotonic_guard={MONOTONIC_DAYS}d",
                    ],
                })
            print(f"[evolution] ✓ {len(changes)} 项更新，版本 → {new_version}")
            return {"status": "evolved", "version": new_version,
                    "changes": changes}
        finally:
            if own_db:
                db.close()


def daily_evolution() -> dict:
    """cron 入口：23:00 运行。"""
    return EvolutionEngine().daily_evolution()


if __name__ == "__main__":
    import tempfile
    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "causal.db")

    def make_db(n_q_viral, n_q_total, n_s_viral, n_s_total):
        if os.path.exists(tmpdb):
            os.unlink(tmpdb)
        db = CausalDB(tmpdb)
        i = 0
        for _ in range(n_q_viral):
            db.ingest_video(f"v{i}", "t", {"title_style": "question"},
                            views_72h=200_000); i += 1
        for _ in range(n_q_total - n_q_viral):
            db.ingest_video(f"v{i}", "t", {"title_style": "question"},
                            views_72h=10_000); i += 1
        for _ in range(n_s_viral):
            db.ingest_video(f"v{i}", "t", {"title_style": "statement"},
                            views_72h=200_000); i += 1
        for _ in range(n_s_total - n_s_viral):
            db.ingest_video(f"v{i}", "t", {"title_style": "statement"},
                            views_72h=10_000); i += 1
        return db

    # 1. 默认冻结：新引擎直接跑 → 跳过
    eng = EvolutionEngine(base_dir=tmpdir, db=make_db(8, 10, 2, 10))
    r = eng.daily_evolution()
    assert r["status"] == "skipped_frozen", r
    assert eng.is_frozen() is True

    # 2. 解冻后进化：question 爆款率 0.8，权重应向 0.8 靠拢但受漂移预算限制
    eng.unfreeze("test")
    _save_json_atomic(eng.weights_path, {
        "title_style": {
            "question": {"weight": 0.5, "deltas": []},
            "statement": {"weight": 0.5, "deltas": []},
        }})
    r = eng.daily_evolution()
    assert r["status"] == "evolved", r
    w = eng.get_weights()["title_style"]
    # question: 0.5 → 0.55（预算 0.05 钳制，不是直接到 0.8）
    assert abs(w["question"]["weight"] - 0.55) < 1e-9, w
    # statement: 0.5 → 0.45（目标 0.2，预算钳制）
    assert abs(w["statement"]["weight"] - 0.45) < 1e-9, w
    assert eng.get_version() == "v3.1.1", eng.get_version()
    # 日志写了 2 行 l1_update
    logs = [json.loads(l) for l in open(eng.log_path, encoding="utf-8")]
    ups = [l for l in logs if l.get("event") == "l1_update"]
    assert len(ups) == 2 and all("attribution" in l for l in ups), logs

    # 3. 分配归一化
    alloc = eng.get_allocation("title_style")
    assert abs(sum(alloc.values()) - 1.0) < 1e-9, alloc

    # 4. 单调漂移 → 自动冻结：预置 4 天同向 delta，再跑一天同向数据
    _save_json_atomic(eng.weights_path, {
        "title_style": {
            "question": {"weight": 0.5, "deltas": [0.05, 0.05, 0.05, 0.05]},
            "statement": {"weight": 0.5, "deltas": []},
        }})
    eng.db = make_db(8, 10, 2, 10)  # question 继续推高
    r = eng.daily_evolution()
    assert r["status"] == "frozen", r
    assert eng.is_frozen() is True
    assert "单调漂移" in r["reason"]
    # 冻结后再次运行 → 跳过
    r2 = eng.daily_evolution()
    assert r2["status"] == "skipped_frozen", r2

    # 5. 样本不足 → no_change（不冻结、不报错）
    eng.unfreeze("test2")
    _save_json_atomic(eng.weights_path, {
        "title_style": {"question": {"weight": 0.5, "deltas": []}}})
    eng.db = make_db(1, 2, 0, 2)  # 每组只有 2 条 < MIN_SAMPLES=10
    r = eng.daily_evolution()
    assert r["status"] == "no_change", r

    eng.db.close()
    print("evolution_engine.py 自测全部通过 ✓")
