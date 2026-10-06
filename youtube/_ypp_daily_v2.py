"""YPP 每日台账（v2，qualified 口径修正版）。

❗核心教训（2026-10-06）：
  v1 用 estimatedMinutesWatched 当作 YPP 进度，得出 4,023.9h —— 虚高 161 倍。
  官方 qualified watch hours 只计「public 长视频」的观看，排除 shorts / TV autoplay。
  Analytics API 不暴露 qualified 口径，只能人工从 Studio Eligibility 页读取。

本版设计：
  1. API 能拿的：订阅数、shorts vs videoOnDemand 拆分、流量来源、设备（作诊断用）
  2. API 拿不到的：qualified hours / qualified shorts views —— 从环境变量或参数传入，
     或在台账中保留 pending，由人工从 Studio 填入
  3. 绝不把 estimatedMinutesWatched 写成 hours_365d

用法：
  python3 ypp_daily.py                              # 只写 API 可得部分，qualified 标 None
  python3 ypp_daily.py <qualified_hours> <shorts90d>   # 人工从 Studio 读到的值
"""
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/hatch/data")
from youtube.yt_upload import _load, _req

LEDGER = "/home/hatch/data/youtube/ypp_daily.jsonl"
d = _load()
tok = d["token"]


def q(p):
    return json.load(_req("https://youtubeanalytics.googleapis.com/v2/reports?"
                          + urllib.parse.urlencode(p), tok))


today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
rec = {"date": today, "schema": 2}

# --- 人工传入的官方口径（唯一可信的 YPP 进度） ---
if len(sys.argv) >= 3:
    try:
        rec["qualified_watch_hours_365d"] = float(sys.argv[1])
        rec["qualified_shorts_views_90d"] = int(sys.argv[2])
        rec["qualified_source"] = "manual(Studio Eligibility)"
    except ValueError:
        print("ARG_ERR: 需为 <hours> <shorts_views>")
        raise SystemExit(2)
else:
    rec["qualified_watch_hours_365d"] = None
    rec["qualified_shorts_views_90d"] = None
    rec["qualified_source"] = "pending - 需从 Studio Eligibility 页人工读取"

# --- 订阅数 ---
try:
    ch = json.load(_req(
        "https://www.googleapis.com/youtube/v3/channels?part=statistics&mine=true", tok))
    rec["subs"] = int(ch["items"][0]["statistics"]["subscriberCount"])
except Exception as e:
    rec["subs"] = None
    print("subs ERR", type(e).__name__, e)

# --- 近 365 天长视频真实观看（诊断用，不是 YPP 进度） ---
diag = {}
try:
    r = q({"ids": "channel==MINE",
           "startDate": (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d"),
           "endDate": today,
           "metrics": "estimatedMinutesWatched", "dimensions": "creatorContentType"})
    for row in r.get("rows", []):
        diag[row[0] + "_minutes"] = int(row[1])
    vod = diag.get("videoOnDemand_minutes", 0)
    diag["videoOnDemand_hours_DIAGNOSTIC_ONLY"] = round(vod / 60, 1)
    diag["NOTE"] = ("这是总观看时长，不是 qualified。含 TV autoplay，"
                    "可能 99% 不计入 YPP。仅作趋势参考。")
except Exception as e:
    print("diag ERR", type(e).__name__, e)
rec["diagnostic"] = diag

# --- 流量来源 + 设备（判断是否又在蹭 TV autoplay） ---
# _TRAFFIC_SPLIT_FIX: API 不支持双维度，拆两次查
D90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
traffic_min, device_min = {}, {}
try:
    r = q({"ids": "channel==MINE", "startDate": D90, "endDate": today,
           "metrics": "estimatedMinutesWatched",
           "dimensions": "insightTrafficSourceType"})
    traffic_min = {x[0]: int(x[1]) for x in r.get("rows", [])}
except Exception as e:
    print("traffic ERR", type(e).__name__, str(e)[:120])
try:
    r = q({"ids": "channel==MINE", "startDate": D90, "endDate": today,
           "metrics": "estimatedMinutesWatched",
           "dimensions": "deviceType"})
    device_min = {x[0]: int(x[1]) for x in r.get("rows", [])}
except Exception as e:
    print("device ERR", type(e).__name__, str(e)[:120])

rec["traffic_90d_minutes"] = traffic_min
rec["device_90d_minutes"] = device_min
tot_t = sum(traffic_min.values()) or 1
tot_d = sum(device_min.values()) or 1
if device_min:
    rec["tv_share_pct_90d"] = round(100 * device_min.get("TV", 0) / tot_d, 1)
if traffic_min:
    rec["related_video_share_pct_90d"] = round(
        100 * traffic_min.get("RELATED_VIDEO", 0) / tot_t, 1)
rec["autoplay_risk"] = (rec.get("tv_share_pct_90d", 0) > 50
                        and rec.get("related_video_share_pct_90d", 0) > 50)

rec["ts"] = datetime.now(timezone.utc).isoformat()

# --- 幂等写入 ---
rows = []
if os.path.exists(LEDGER):
    rows = [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]
rows = [x for x in rows if x.get("date") != today]
rows.append(rec)
rows.sort(key=lambda x: x["date"])
with open(LEDGER, "w", encoding="utf-8") as f:
    for x in rows:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")

print(json.dumps(rec, ensure_ascii=False, indent=2))
print("\n台账：%s，共 %d 天" % (LEDGER, len(rows)))
