#!/usr/bin/env python3
"""
闭环 pacer：实时计算 published-today vs target，落后就加速
四脑议会 2026-10-15：开环 cron 靠"希望"达标，需要闭环 pacing

逻辑：
- 目标：每天 2-3 条（北京时间 00:00 为日界）
- 计算今日已发布数（YouTube API 真实数据）
- 计算剩余时间、还差几条
- 如果落后：在 inbox 发加速指令，触发紧急生成

运行：python3 /home/hatch/data/perpetua/pacer.py
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
sys.path.insert(0, "/home/hatch/data/perpetua")

TARGET_MIN = 2
TARGET_MAX = 3
# 北京时间
CST = timezone(timedelta(hours=8))

def get_today_published():
    """查今日（北京时间）已发布数"""
    from daily_reconciliation import get_recent_public_videos
    
    # 计算到今日 00:00 CST 的小时数
    now_cst = datetime.now(CST)
    midnight_cst = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_since_midnight = (now_cst - midnight_cst).total_seconds() / 3600
    
    result = get_recent_public_videos(hours=int(hours_since_midnight) + 1)
    if "error" in result:
        return {"error": result["error"]}
    
    # 过滤出今日 CST 的
    today_videos = []
    for v in result["videos"]:
        pub_dt = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        pub_cst = pub_dt.astimezone(CST)
        if pub_cst.date() == now_cst.date():
            today_videos.append(v)
    
    return {"count": len(today_videos), "videos": today_videos}

def calculate_pace(published_count):
    """计算 pacing 状态"""
    now_cst = datetime.now(CST)
    hour = now_cst.hour + now_cst.minute / 60
    
    # 一天 24 小时，目标 2-3 条
    # 期望进度 = (当前小时 / 24) * 目标
    expected_min = (hour / 24) * TARGET_MIN
    expected_max = (hour / 24) * TARGET_MAX
    
    # 还差几条
    need_min = max(0, TARGET_MIN - published_count)
    need_max = max(0, TARGET_MAX - published_count)
    
    # 是否落后
    behind = published_count < expected_min
    
    # 剩余小时
    hours_left = 24 - hour
    
    return {
        "now_cst": now_cst.isoformat(),
        "hour_of_day": round(hour, 1),
        "published": published_count,
        "target_min": TARGET_MIN,
        "target_max": TARGET_MAX,
        "expected_min": round(expected_min, 1),
        "expected_max": round(expected_max, 1),
        "behind": behind,
        "need_min": need_min,
        "need_max": need_max,
        "hours_left": round(hours_left, 1),
    }

def main():
    result = get_today_published()
    if "error" in result:
        print(json.dumps({"ok": False, "error": result["error"]}))
        sys.exit(1)
    
    pace = calculate_pace(result["count"])
    pace["videos"] = result["videos"]
    pace["ok"] = True
    pace["checked_at"] = datetime.now(timezone.utc).isoformat()
    
    # 如果落后，发加速指令
    if pace["behind"] and pace["need_min"] > 0:
        pace["action"] = "ACCELERATE"
        pace["action_detail"] = f"落后 {pace['expected_min'] - pace['published']:.1f} 条，需加速生成 {pace['need_min']} 条"
    elif pace["published"] >= TARGET_MAX:
        pace["action"] = "HOLD"
        pace["action_detail"] = "已达上限，暂停生成"
    else:
        pace["action"] = "NORMAL"
        pace["action_detail"] = "正常节奏"
    
    print(json.dumps(pace, indent=2, ensure_ascii=False))
    sys.exit(0)

if __name__ == "__main__":
    main()
