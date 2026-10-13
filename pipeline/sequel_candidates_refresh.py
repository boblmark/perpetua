#!/usr/bin/env python3
"""
每天刷新爆款续集候选清单 /home/hatch/data/sequel_candidates.json。

步骤：
1. YouTube Analytics API 拉频道近 90 天每条视频播放量
2. 按播放量取 Top 10，分析：标题公式、AI 设备、笑点机制、发布时间
3. 每个爆款生成 3 个续集选题方向（换设备不换公式 / 换公式不换设备 / 同冲突升级）
4. 更新 sequel_candidates.json：不删历史记录，只更新排名/播放/续集想法
5. Top 10 新上榜视频标题 → 输出 NEW_HITS 供 cron 记入 memory 日志
"""
import json, re, sys, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, "/home/hatch/data")
sys.path.insert(0, "/home/hatch/data/youtube")
from yt import api_call, _token
# 直连（2026-10-12 起 relay→Google 中断，见 yt.py 头部说明）：Analytics API 走环境 egress 代理直连

BASE = Path("/home/hatch/data")
OUT = BASE / "sequel_candidates.json"
TODAY = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")  # 用户视角：北京时间日期

# ---------- 1. Analytics API：近 90 天每条视频播放量 ----------
def analytics_90d():
    token, _ = _token()
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    rows = []
    page = None
    while True:
        params = {"ids": "channel==MINE", "startDate": start, "endDate": end,
                  "metrics": "views,averageViewDuration", "dimensions": "video",
                  "sort": "-views", "maxResults": "200"}
        if page:
            params["pageToken"] = page
        url = ("https://youtubeanalytics.googleapis.com/v2/reports?"
               + urllib.parse.urlencode(params))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        r = json.load(urllib.request.urlopen(req, timeout=40))  # 直连，不经 relay
        rows.extend(r.get("rows", []))
        page = r.get("nextPageToken")
        if not page:
            break
    return rows  # [video_id, views, avg_dur_s] 已按 views 降序

# ---------- 2. 视频详情 ----------
def video_details(vids):
    out = {}
    for i in range(0, len(vids), 50):
        chunk = vids[i:i + 50]
        r = api_call("GET", "/youtube/v3/videos",
                     params={"part": "snippet,statistics", "id": ",".join(chunk)})
        for v in r.get("items", []):
            out[v["id"]] = {
                "title": v["snippet"]["title"],
                "published_at": v["snippet"]["publishedAt"],
                "desc": v["snippet"].get("description", "")[:200],
            }
    return out

# ---------- 3. 公式分析 ----------
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]"
    r"|\uFE0F|🅿️|🅿", re.UNICODE)

DEVICE_PATTERNS = [
    ("smart speaker", r"smart speaker|alexa|echo|google home|siri speaker"),
    ("doorbell cam", r"doorbell|ring cam|ring camera"),
    ("robot vacuum", r"robot vacuum|roomba|vacuum robot"),
    ("parking meter", r"parking meter"),
    ("self-driving car", r"self-?driv|tesla|autopilot"),
    ("drone", r"drone"),
    ("drive-thru", r"drive-?thru"),
    ("robot waiter", r"robot waiter|robot server|waiter robot"),
    ("lawn mower robot", r"lawn mow|mowing robot"),
    ("AI voice assistant", r"ai voice|chatbot|ai assistant|ai helpdesk"),
    ("security camera", r"security cam|cctv|surveillance"),
    ("dashcam", r"dashcam|dash cam"),
    ("self-checkout kiosk", r"self-?checkout|kiosk"),
    ("smart fridge", r"smart fridge"),
    ("elevator AI", r"elevator"),
]

KARMA_WORDS = ["instant", "karma", "backfire", "payback", "got owned", "caught",
               "destroy", "wreck", "humiliat", "shock", "soak", "electrocute",
               "slam", "trap", "revenge", "fired", "arrested"]
HORROR_WORDS = ["skinwalker", "creepy", "horror", "scary", "caught on camera"]

def detect_devices(title):
    t = title.lower()
    found = [name for name, pat in DEVICE_PATTERNS if re.search(pat, t)]
    return found or ["none_detected"]

def classify_formula(title):
    t = title.lower()
    has_karen = "karen" in t
    has_karma = any(w in t for w in KARMA_WORDS)
    has_horror = any(w in t for w in HORROR_WORDS)
    emoji_start = bool(EMOJI_RE.match(title.strip()))
    if has_horror:
        key, desc = "horror_creep", "诡异钩子：AI/灵异场景 + 监控视角揭秘"
    elif has_karen and has_karma:
        key, desc = "instant_karma", "Karen 挑衅 AI 设备 → 即时报应"
    elif has_karma:
        key, desc = "slapstick_chaos", "物理喜剧突发 → 连锁混乱"
    else:
        key, desc = "tech_demo", "AI 能力展示/奇观"
    return {"formula_key": key, "formula_desc": desc,
            "ai_devices": detect_devices(title),
            "starts_with_emoji": emoji_start,
            "has_karen": has_karen,
            "has_instant_karma_signal": has_karma}

# ---------- 4. 续集想法生成 ----------
SWAP_DEVICES = ["smart speaker", "doorbell cam", "robot vacuum", "parking meter",
                "drive-thru", "robot waiter", "lawn mower robot", "drone",
                "self-checkout kiosk", "security camera", "dashcam", "self-driving car"]

def title_for_idea(device, hook_words=("😱", "😭"), verb="Karen", action="messes with"):
    return f"{hook_words[0]} Karen {action} The {device.title()}… It HUMILIATED Her Instantly {hook_words[1]}"

def gen_sequel_ideas(video_id, title, breakdown):
    devices = [d for d in breakdown["ai_devices"] if d != "none_detected"]
    primary = devices[0] if devices else "AI device"
    # 换设备：选池子里和当前设备不同的
    alt_device = next((d for d in SWAP_DEVICES if d.lower() != primary.lower()),
                      SWAP_DEVICES[0])
    alt_device2 = next((d for d in SWAP_DEVICES
                        if d.lower() not in (primary.lower(), alt_device.lower())),
                       SWAP_DEVICES[1])
    cur_formula = breakdown["formula_desc"]
    ideas = [
        {
            "angle": "换设备不换公式",
            "concept": f"保留「{cur_formula}」节拍，把设备换成 {alt_device}：同样的挑衅→报应结构，场景全新。",
            "suggested_title": title_for_idea(alt_device),
        },
        {
            "angle": "换公式不换设备",
            "concept": f"同一设备（{primary}）保留，但把报应喜剧改成悬念反转：前 5 秒像灾难，最后一秒神反转（温馨/神转折）。",
            "suggested_title": f"😳 The {primary.title()} Did Something UNEXPECTED To Karen… Wait For The Ending 🤯",
        },
        {
            "angle": "同冲突升级",
            "concept": f"原场景 Part 2：Karen 不服气回来复仇/同一设备再出状况，冲突强度翻倍，报应更狠，标题直接挂 Part 2 吃原视频流量。",
            "suggested_title": f"😤 Karen Came BACK To The {primary.title()}… BIG Mistake Part 2 😭",
        },
    ]
    return ideas

# ---------- 主流程 ----------
def main():
    print("拉取 Analytics 近90天数据…", flush=True)
    rows = analytics_90d()
    print(f"拿到 {len(rows)} 条视频 90 天播放数据", flush=True)
    if not rows:
        print("ERROR: analytics 返回空，放弃本次刷新（不清空旧文件）")
        sys.exit(1)

    # 取播放量前 20（含已有的候选），再拿详情
    top_rows = rows[:20]
    details = video_details([r[0] for r in top_rows])
    # 排除拿不到详情的（已删除/私有）
    top_rows = [r for r in top_rows if r[0] in details]

    top10 = top_rows[:10]

    # 读旧文件，保留历史
    old = json.loads(OUT.read_text()) if OUT.exists() else []
    old_by_id = {e["video_id"]: e for e in old}
    old_top10_ids = {e["video_id"] for e in old if e.get("rank") and e["rank"] <= 10}

    new_entries = []
    new_hits = []
    for rank, row in enumerate(top10, start=1):
        vid, views, avg_dur = row[0], row[1], row[2]
        det = details[vid]
        old_e = old_by_id.get(vid)
        breakdown = classify_formula(det["title"])
        prev_rank = old_e.get("rank") if old_e else None
        entry = {
            "rank": rank,
            "previous_rank": prev_rank,
            "video_id": vid,
            "title": det["title"],
            "views": views,
            "avg_watch_secs": round(avg_dur, 1) if avg_dur else None,
            "published_at": det["published_at"],
            "formula_breakdown": breakdown,
            "sequel_ideas": gen_sequel_ideas(vid, det["title"], breakdown),
            "updated_at": TODAY,
        }
        if old_e and not (old_e.get("rank") and old_e["rank"] <= 10):
            new_hits.append(det["title"])
        elif not old_e:
            new_hits.append(det["title"])
        new_entries.append(entry)

    # 历史条目（不在当前 Top10 的）：保留，rank 置 null，刷新播放量
    hist = []
    views_map = {r[0]: r[1] for r in rows}
    for e in old:
        if e["video_id"] in {x["video_id"] for x in new_entries}:
            continue
        e2 = dict(e)
        e2["previous_rank"] = e2.get("rank")
        e2["rank"] = None
        e2["views"] = views_map.get(e2["video_id"], e2.get("views"))
        e2["updated_at"] = TODAY
        hist.append(e2)

    OUT.write_text(json.dumps(new_entries + hist, ensure_ascii=False, indent=2))
    print(f"已更新 {OUT}：Top10 {len(new_entries)} 条，历史保留 {len(hist)} 条")

    if new_hits:
        print("NEW_HITS:")
        for t in new_hits:
            print(f"  新爆款上榜：{t}")

if __name__ == "__main__":
    main()
