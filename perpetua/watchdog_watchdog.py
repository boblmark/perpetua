#!/usr/bin/env python3
"""
看门狗的看门狗：外部 heartbeat 检查
四脑议会 2026-10-15：没人看守望者，watcher 死了没人知道

原理：
- 每个关键 watcher 运行时写 heartbeat 文件（含时间戳）
- 本脚本检查 heartbeat 新鲜度，超过 2×interval 没更新就告警
- 本脚本自己由 cron 运行，如果 cron 宿主机死了，所有 heartbeat 都会过期 → 告警

Heartbeat 文件：/home/hatch/data/perpetua/heartbeats/<watcher>.json
格式：{"watcher": "name", "last_beat": "ISO", "interval_min": 30}

运行：python3 /home/hatch/data/perpetua/watchdog_watchdog.py
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HEARTBEAT_DIR = Path("/home/hatch/data/perpetua/heartbeats")

# 关键 watcher 及其期望间隔（分钟）
WATCHERS = {
    "dead-state-watchdog": 30,
    "publish-health-watch": 30,
    "dispatch-lifeline-watch": 10,
    "private-flip-scheduler": 10,
    "perpetua-pipeline-collect": 20,
    "mcp-b-queue-consumer": 5,
    "platform-matrix-sync": 60,
}

def check_heartbeat(name, interval_min):
    """检查单个 watcher 的 heartbeat"""
    f = HEARTBEAT_DIR / f"{name}.json"
    if not f.exists():
        return {
            "watcher": name,
            "status": "no_heartbeat_file",
            "alert": True,
            "msg": f"{name} 从未写过 heartbeat"
        }
    
    try:
        data = json.loads(f.read_text())
        last_beat = datetime.fromisoformat(data["last_beat"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_min = (now - last_beat).total_seconds() / 60
        threshold = interval_min * 2  # 2×间隔没更新就告警
        
        if age_min > threshold:
            return {
                "watcher": name,
                "status": "stale",
                "alert": True,
                "age_min": round(age_min, 1),
                "threshold_min": threshold,
                "msg": f"{name} 已 {age_min:.1f} 分钟没心跳（阈值 {threshold} 分钟）"
            }
        return {
            "watcher": name,
            "status": "ok",
            "alert": False,
            "age_min": round(age_min, 1)
        }
    except Exception as e:
        return {
            "watcher": name,
            "status": "error",
            "alert": True,
            "msg": f"{name} heartbeat 文件损坏: {e}"
        }

def write_heartbeat(name, interval_min):
    """给 watcher 写 heartbeat（各 watcher 调用）"""
    HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    f = HEARTBEAT_DIR / f"{name}.json"
    f.write_text(json.dumps({
        "watcher": name,
        "last_beat": datetime.now(timezone.utc).isoformat(),
        "interval_min": interval_min
    }))

def main():
    results = []
    alerts = []
    
    for name, interval in WATCHERS.items():
        r = check_heartbeat(name, interval)
        results.append(r)
        if r.get("alert"):
            alerts.append(r["msg"])
    
    # 本脚本自己的 heartbeat
    write_heartbeat("watchdog-watchdog", 15)
    
    output = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "alerts": alerts,
        "healthy": len(alerts) == 0
    }
    
    print(json.dumps(output, indent=2, ensure_ascii=False))
    sys.exit(0 if output["healthy"] else 1)

if __name__ == "__main__":
    # 如果带 --beat <name> 参数，就是写 heartbeat 模式
    if len(sys.argv) == 3 and sys.argv[1] == "--beat":
        name = sys.argv[2]
        interval = WATCHERS.get(name, 30)
        write_heartbeat(name, interval)
        print(f"Heartbeat written for {name}")
    else:
        main()
