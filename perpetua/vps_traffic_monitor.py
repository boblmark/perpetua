#!/usr/bin/env python3
"""
VPS 公网流量每日监测（192.166.82.123）。

- 经 SSH 只读读取 eth0 RX/TX 计数器（/proc/net/dev），不在 VPS 上写任何文件。
- 快照追加到 vps_traffic.jsonl，每行 {ts, date, rx_bytes, tx_bytes}；同一天重复跑只更新当日行（幂等）。
- 按自然月累计计费方向流量（默认 tx 出站）；计数器重置（重启）时按重置处理并备注。
- 配额配置 vps_traffic_config.json：{monthly_quota_gb, billable, warn_pct, crit_pct}；
  monthly_quota_gb 为 null 时只记录不告警。
- quota 已知且使用率 >= warn_pct 打印 ALERT 行，>= crit_pct 打印 CRITICAL 行；
  始终打印一行 JSON 摘要到 stdout。
- get_summary() 供 console_server 导入（纯读文件，无副作用）。

运行：python3 /home/hatch/data/perpetua/vps_traffic_monitor.py
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/home/hatch/data/perpetua")
SNAP_FILE = BASE / "vps_traffic.jsonl"
CONFIG_FILE = BASE / "vps_traffic_config.json"
IFACE = "eth0"
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai

SSH_CMD = [
    "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
    "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
    "-i", str(Path.home() / ".ssh" / "id_ed25519"),
    "root@192.166.82.123",
]

DEFAULT_CONFIG = {
    "monthly_quota_gb": None,  # 未知：只记录不告警；已知后填数字（如 500）
    "billable": "tx",          # 计费方向：tx（出站，云厂商通常口径）
    "warn_pct": 80,
    "crit_pct": 95,
}

GB = 1024 ** 3


def load_config():
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n")
        return dict(DEFAULT_CONFIG)
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)
    out = dict(DEFAULT_CONFIG)
    out.update({k: v for k, v in cfg.items() if k in out})
    return out


def read_counters():
    """经 SSH 只读读取计数器，返回 (rx_bytes, tx_bytes)。"""
    r = subprocess.run(
        SSH_CMD + ["cat /proc/net/dev"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"SSH 读取 /proc/net/dev 失败: {r.stderr.strip()[:200]}")
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith(IFACE + ":"):
            parts = line.split(":")[1].split()
            rx, tx = int(parts[0]), int(parts[8])
            return rx, tx
    raise RuntimeError(f"VPS 上未找到接口 {IFACE}")


def load_snapshots():
    if not SNAP_FILE.exists():
        return []
    out = []
    for line in SNAP_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def save_snapshot(rx, tx):
    """追加或更新当日快照（幂等：同一天只保留一行）。"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    now_iso = datetime.now(TZ).isoformat()
    snaps = load_snapshots()
    row = {"ts": now_iso, "date": today, "rx_bytes": rx, "tx_bytes": tx}
    if snaps and snaps[-1].get("date") == today:
        snaps[-1] = row
    else:
        snaps.append(row)
    SNAP_FILE.write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in snaps)
    )
    return snaps


def compute_stats(snaps, cfg):
    """返回 (day_delta_gb, month_cum_gb, notes)。"""
    notes = []
    billable = cfg.get("billable", "tx")
    key = "tx_bytes" if billable == "tx" else "rx_bytes"
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    month_prefix = today[:7]

    if not snaps:
        return 0.0, 0.0, ["无历史快照"]

    # 当日增量：今日快照 - 最近一次有该键值的快照（跳过云账单等特殊行）
    prev = None
    for s in reversed(snaps[:-1]):
        if key in s:
            prev = s
            break
    cur = snaps[-1]
    if prev is None:
        day_delta = 0.0
        notes.append("首个快照，无昨日基线，日增量记0")
    else:
        d = cur[key] - prev[key]
        if d < 0:
            day_delta = cur[key] / GB
            notes.append(f"计数器重置（{key} 回落），按重置后当前值计日增量")
        else:
            day_delta = d / GB

    # 当月累计：按月内快照逐段累加，处理重置（跳过无该键值的特殊行）
    month_snaps = [s for s in snaps if s.get("date", "").startswith(month_prefix) and key in s]
    if not month_snaps:
        return day_delta, 0.0, notes + ["本月无有效快照"]
    # 月初基线：本月第一条之前最近的一条有效快照
    baseline = None
    for s in reversed(snaps[:snaps.index(month_snaps[0])]):
        if key in s:
            baseline = s[key]
            break
    cum = 0
    prev_v = baseline
    for s in month_snaps:
        v = s[key]
        if prev_v is None:
            notes.append("无月初基线，当月累计从本月首条快照开始计（可能低估）")
        elif v < prev_v:
            cum += v
            notes.append(f"{s.get('date')}: 计数器重置，已按重置处理")
        else:
            cum += v - prev_v
        prev_v = v
    return day_delta, cum / GB, notes


def build_summary():
    """纯读文件构造摘要（get_summary 与 main 共用）。"""
    cfg = load_config()
    snaps = load_snapshots()
    if not snaps:
        return {
            "rx_gb": 0.0, "tx_gb": 0.0, "month_tx_gb": 0.0,
            "quota_gb": cfg.get("monthly_quota_gb"), "pct": None,
            "status": "unknown", "notes": ["尚无快照，先跑一次监测脚本"],
        }
    day_delta, month_cum, notes = compute_stats(snaps, cfg)
    cur = snaps[-1]
    quota = cfg.get("monthly_quota_gb")
    pct = (month_cum / quota * 100) if quota else None
    if quota:
        if pct >= cfg.get("crit_pct", 95):
            status = "critical"
        elif pct >= cfg.get("warn_pct", 80):
            status = "warn"
        else:
            status = "ok"
    else:
        status = "unknown"
    return {
        "date": cur.get("date"),
        "rx_gb": round(cur["rx_bytes"] / GB, 2),
        "tx_gb": round(cur["tx_bytes"] / GB, 2),
        "day_tx_gb": round(day_delta, 3),
        "month_tx_gb": round(month_cum, 2),
        "quota_gb": quota,
        "pct": round(pct, 1) if pct is not None else None,
        "status": status,
        "notes": notes,
    }


def get_summary():
    """供 console_server 导入：{rx_gb, tx_gb, month_tx_gb, quota_gb, pct, status}。"""
    s = build_summary()
    return {
        "rx_gb": s["rx_gb"],
        "tx_gb": s["tx_gb"],
        "month_tx_gb": s["month_tx_gb"],
        "quota_gb": s["quota_gb"],
        "pct": s["pct"],
        "status": s["status"],
    }


def main():
    cfg = load_config()
    rx, tx = read_counters()
    snaps = save_snapshot(rx, tx)
    s = build_summary()

    quota = cfg.get("monthly_quota_gb")
    if quota and s["pct"] is not None:
        if s["pct"] >= cfg.get("crit_pct", 95):
            print(
                f"CRITICAL: VPS公网流量已用 {s['pct']}%"
                f"（{s['month_tx_gb']}/{quota} GB），即将耗尽，请立即充值",
                flush=True,
            )
        elif s["pct"] >= cfg.get("warn_pct", 80):
            print(
                f"ALERT: VPS公网流量已用 {s['pct']}%"
                f"（{s['month_tx_gb']}/{quota} GB），请及时充值",
                flush=True,
            )
    # 始终打印 JSON 摘要
    print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
