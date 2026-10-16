#!/usr/bin/env python3
"""
竞品每周增量采集（2026-10-15）
应对红队 KILL-2：素材生命周期 6 天，数据必须每周更新

逻辑：
- 读取上次采集时间戳
- 每个平台采集上周新发布的竞品（增量）
- 去重后追加到对应 JSON
- 更新时间戳

当前为框架版本，具体平台采集函数待实现（需浏览器/登录态）
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path("/home/hatch/data/competitor_reach")
STATE_FILE = BASE_DIR / "weekly_collect_state.json"

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_collect": None, "weekly_counts": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def collect_platform(platform, since):
    """
    采集单个平台的增量数据
    TODO: 实现具体采集逻辑（浏览器/API）
    返回：新增条数
    """
    # 占位：实际实现时调用对应平台的采集函数
    print(f"[{platform}] 采集 {since} 之后的新数据...")
    # 示例：douyin_weekly(), xiaohongshu_weekly(), etc.
    return 0

def main():
    state = load_state()
    last = state.get("last_collect")
    
    if last:
        since = datetime.fromisoformat(last)
    else:
        since = datetime.now() - timedelta(days=7)
    
    print(f"上次采集：{last or '无（首次）'}")
    print(f"本次采集时间窗：{since} → {datetime.now()}")
    
    platforms = ["douyin", "kuaishou", "xiaohongshu", "shipinhao", "x"]
    total_new = 0
    results = {}
    
    for p in platforms:
        try:
            count = collect_platform(p, since)
            results[p] = count
            total_new += count
        except Exception as e:
            print(f"[{p}] 采集失败：{e}")
            results[p] = -1
    
    # 更新状态
    state["last_collect"] = datetime.now().isoformat()
    state["weekly_counts"].append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total": total_new,
        "by_platform": results
    })
    # 只保留最近 12 周
    state["weekly_counts"] = state["weekly_counts"][-12:]
    save_state(state)
    
    print(f"\n本周新增：{total_new} 条")
    for p, c in results.items():
        print(f"  {p}: {c}")
    
    return total_new

if __name__ == "__main__":
    main()
