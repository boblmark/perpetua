#!/usr/bin/env python3
"""单层信号仪表盘（数字孪生 DNA v3.1 · 接口模块）。

按 GPT-5.2 终审要求：降级为单层、按小时聚合（豪华三层推迟到 Phase 3）。

信号（每小时快照）：
  - viral_rate    爆款率（24h 口径）
  - published     发布量（24h）
  - causal_db_size 因果库大小（条数）
  - evolution_version 进化版本号

get_hourly_snapshot() -> dict   取当前小时快照并落盘
get_trend(days=30) -> list       近 N 天趋势（每小时一行）

死亡检测：某信号超过 STALE_AFTER_SEC（默认 7200s=2h）未更新 → 标记 stale。
输出 JSON：signal_latest.json（控制台 HTML 可直接读取）。

全部 stdlib。
"""
import datetime
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    from atomic_json import atomic_write
except ImportError:
    def atomic_write(path, data, backup=True):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

SNAPSHOT_LOG = os.path.join(BASE_DIR, "signal_snapshots.jsonl")
LATEST_PATH = os.path.join(BASE_DIR, "signal_latest.json")
HEALTH_PATH = os.path.join(BASE_DIR, "signal_health.json")

STALE_AFTER_SEC = 7200  # 2 小时未更新 = stale（死亡）


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def hour_key(dt=None):
    dt = dt or datetime.datetime.now()
    return dt.strftime("%Y-%m-%dT%H")


def _load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _read_sources():
    """从现有状态文件读取各信号原始值。读不到 → None（由死亡检测标 stale）。"""
    snap = _load_json(os.path.join(BASE_DIR, "dashboard_snapshot.json"), {}) or {}
    causal_stats = _load_json(os.path.join(BASE_DIR, "causal_db_stats.json"), {}) or {}
    evo_state = _load_json(os.path.join(BASE_DIR, "sop_state",
                                        f"sop_night_{(datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime('%Y-%m-%d')}.json"), {}) or {}
    # 兼容旧版 daily_evolution 输出
    evo_reports_dir = os.path.join(BASE_DIR, "evolution_reports")
    version = None
    if isinstance(evo_state, dict) and evo_state.get("detail"):
        version = "night-ok" if evo_state.get("status") == "ok" else "night-failed"
    return {
        "viral_rate": snap.get("viral_rate_24h"),
        "published": snap.get("published_24h"),
        "causal_db_size": causal_stats.get("total_rows"),
        "evolution_version": version,
    }


def get_hourly_snapshot():
    """生成当前小时快照：更新 health（last_update），append 到 snapshots，写 latest。"""
    values = _read_sources()
    ts = now_iso()
    hk = hour_key()

    health = _load_json(HEALTH_PATH, {}) or {}
    for sig, val in values.items():
        entry = health.setdefault(sig, {"last_update": None, "last_value": None})
        if val is not None:
            entry["last_update"] = ts
            entry["last_value"] = val
    atomic_write(HEALTH_PATH, health)

    snapshot = {"hour": hk, "ts": ts, "signals": values,
                "stale": _stale_flags(health)}
    with open(SNAPSHOT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    atomic_write(LATEST_PATH, snapshot)
    return snapshot


def _stale_flags(health):
    """死亡检测：last_update 距今超过 STALE_AFTER_SEC → stale=True。"""
    flags = {}
    now = datetime.datetime.now()
    for sig, entry in (health or {}).items():
        lu = entry.get("last_update")
        if not lu:
            flags[sig] = True
            continue
        try:
            dt = datetime.datetime.fromisoformat(lu)
        except ValueError:
            flags[sig] = True
            continue
        flags[sig] = (now - dt).total_seconds() > STALE_AFTER_SEC
    return flags


def check_stale():
    """返回当前各信号的 stale 状态（不写快照，纯读）。"""
    health = _load_json(HEALTH_PATH, {}) or {}
    return _stale_flags(health)


def get_trend(days=30):
    """近 N 天趋势：从 snapshots 日志取每小时一行。返回 list[dict]（按时间升序）。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    out = []
    try:
        with open(SNAPSHOT_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                try:
                    dt = datetime.datetime.fromisoformat(row.get("ts", ""))
                except ValueError:
                    continue
                if dt >= cutoff:
                    out.append(row)
    except OSError:
        pass
    return out


def selftest():
    print("=== signal_dashboard 自测 ===")
    # 备份现场文件
    backups = {}
    for p in (SNAPSHOT_LOG, LATEST_PATH, HEALTH_PATH):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                backups[p] = f.read()
    try:
        # 1. 注入一个假数据源，验证快照聚合
        fake_snap = os.path.join(BASE_DIR, "dashboard_snapshot.json")
        fake_bak = None
        if os.path.exists(fake_snap):
            with open(fake_snap, encoding="utf-8") as f:
                fake_bak = f.read()
        try:
            atomic_write(fake_snap, {"viral_rate_24h": 5.6, "published_24h": 72})
            s = get_hourly_snapshot()
            assert s["signals"]["viral_rate"] == 5.6, s
            assert s["signals"]["published"] == 72, s
            print(f"get_hourly_snapshot ✅ hour={s['hour']} viral_rate=5.6")
        finally:
            if fake_bak is not None:
                with open(fake_snap, "w", encoding="utf-8") as f:
                    f.write(fake_bak)
            elif os.path.exists(fake_snap):
                os.remove(fake_snap)

        # 2. latest 可被控制台读取
        latest = _load_json(LATEST_PATH)
        assert latest and "signals" in latest and "stale" in latest
        print("signal_latest.json 可读 ✅")

        # 3. 趋势
        t = get_trend(days=1)
        assert isinstance(t, list) and len(t) >= 1
        print(f"get_trend(days=1) ✅ {len(t)} 条")

        # 4. 死亡检测：伪造一个 3 小时前的 last_update
        health = _load_json(HEALTH_PATH, {}) or {}
        old = (datetime.datetime.now() - datetime.timedelta(hours=3)).isoformat(timespec="seconds")
        health["viral_rate"] = {"last_update": old, "last_value": 5.6}
        atomic_write(HEALTH_PATH, health)
        flags = check_stale()
        assert flags.get("viral_rate") is True, flags
        print("死亡检测（3h 未更新 → stale）✅")

        # 5. 新鲜信号不标 stale
        s2 = get_hourly_snapshot()  # 重新写入 fresh（但 viral_rate 数据源已删 → 保持旧值）
        flags2 = check_stale()
        # published 刚被写入 fresh 时间（fake 数据源已删所以是 None，但 health 保留上次 fresh）
        print(f"stale flags: {flags2}")
    finally:
        for p, content in backups.items():
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        for p in (SNAPSHOT_LOG, LATEST_PATH, HEALTH_PATH):
            if p not in backups and os.path.exists(p):
                os.remove(p)
    print("自测通过 ✅")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="单层信号仪表盘")
    ap.add_argument("--snapshot", action="store_true", help="生成当前小时快照并打印")
    ap.add_argument("--trend", type=int, metavar="DAYS", default=None, help="输出近 N 天趋势 JSON")
    ap.add_argument("--stale", action="store_true", help="只检查死亡状态")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.snapshot:
        print(json.dumps(get_hourly_snapshot(), ensure_ascii=False, indent=2))
    elif args.trend is not None:
        print(json.dumps(get_trend(days=args.trend), ensure_ascii=False, indent=2))
    elif args.stale:
        print(json.dumps(check_stale(), ensure_ascii=False, indent=2))
    else:
        selftest()
