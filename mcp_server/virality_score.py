#!/usr/bin/env python3
"""爆款预判打分器：对 Short 选题/标题/脚本做规则版 virality 评分。
用法：python3 virality_score.py '{"title": "...", "hook": "...", "topic_heat": "high", "duration": 10}'
输出 JSON：{"score": 85, "grade": "A", "breakdown": {...}, "advice": [...]}
"""
import json
import sys
import re

def score(data):
    title = data.get("title", "")
    hook = data.get("hook", data.get("prompt", ""))
    heat = data.get("topic_heat", "medium")
    duration = int(data.get("duration", 10))
    text = (title + " " + hook).lower()

    breakdown = {}
    # 1. 钩子强度 (30分)：前3秒是否有强刺激词
    hook_words = ["shocking", "unbelievable", "secret", "never", "insane", "crazy",
                  "wtf", "omg", "mind-blowing", "exposed", "truth", "vs", "first",
                  "震惊", "揭秘", "首次", "真相", "对比"]
    hook_hits = sum(1 for w in hook_words if w in text)
    breakdown["hook"] = min(30, hook_hits * 10)

    # 2. 话题热度 (25分)
    heat_map = {"high": 25, "medium": 15, "low": 5}
    breakdown["heat"] = heat_map.get(heat, 15)

    # 3. 标题结构 (20分)：数字、问句、情绪词
    s = 0
    if re.search(r'\d', title): s += 7
    if '?' in title or '？' in title: s += 7
    if any(e in text for e in ["!", "🔥", "🤖", "😱", "⚡"]): s += 6
    breakdown["title"] = s

    # 4. 时长适配 (15分)：Short 最佳 7-15 秒
    if 7 <= duration <= 15: breakdown["duration"] = 15
    elif 5 <= duration <= 30: breakdown["duration"] = 10
    else: breakdown["duration"] = 5

    # 5. 视觉奇观度 (10分)：关键词暗示强视觉
    visual_words = ["robot", "transform", "explosion", "city", "face", "neon",
                    "futuristic", "ai", "cyberpunk", "hologram", "机器人", "未来", "城市"]
    v_hits = sum(1 for w in visual_words if w in text)
    breakdown["visual"] = min(10, v_hits * 3)

    total = sum(breakdown.values())
    grade = "S" if total >= 90 else "A" if total >= 75 else "B" if total >= 60 else "C"

    advice = []
    if breakdown["hook"] < 20:
        advice.append("钩子偏弱：标题/前3秒加入强刺激词（如 shocking、揭秘、vs 对比）")
    if breakdown["title"] < 12:
        advice.append("标题结构可优化：加数字、问句或情绪符号")
    if breakdown["heat"] < 20:
        advice.append("话题热度一般：建议蹭当日趋势雷达中的 high 热度话题")
    if not (7 <= duration <= 15):
        advice.append(f"时长 {duration}s 偏离最佳区间（7-15秒），建议调整")
    if not advice:
        advice.append("各项指标良好，可直接投产")

    return {"score": total, "grade": grade, "breakdown": breakdown,
            "advice": advice, "pass": total >= 60}

if __name__ == "__main__":
    data = json.loads(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read())
    print(json.dumps(score(data), ensure_ascii=False, indent=2))
