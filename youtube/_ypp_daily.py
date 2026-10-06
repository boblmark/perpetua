"""YPP 冲刺基线台账：每日追加一行快照，供日报做日环比。

幂等：同一天重复运行只更新当天那条。
"""
import json, os, sys, urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, "/home/hatch/data")
from youtube.yt_upload import _load, _req

LEDGER = "/home/hatch/data/youtube/ypp_daily.jsonl"
d = _load(); tok = d["token"]

def q(p):
    return json.load(_req("https://youtubeanalytics.googleapis.com/v2/reports?"
                          + urllib.parse.urlencode(p), tok))

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# 订阅数
subs = None
try:
    ch = json.load(_req(
        "https://www.googleapis.com/youtube/v3/channels?part=statistics&mine=true", tok))
    subs = int(ch["items"][0]["statistics"]["subscriberCount"])
except Exception as e:
    print("subs ERR", type(e).__name__, e)

# 近 365 天观看小时（按月聚合）
hours365 = None
try:
    r = q({"ids": "channel==MINE", "startDate": "2025-10-01", "endDate": "2026-10-01",
           "metrics": "estimatedMinutesWatched", "dimensions": "month", "sort": "month"})
    hours365 = round(sum(x[1] for x in r.get("rows", [])) / 60, 1)
except Exception as e:
    print("h365 ERR", type(e).__name__, e)

# 近 90 天流量来源（判定推荐流占比）
traffic, rec_share = None, None
try:
    r = q({"ids": "channel==MINE", "startDate": "2026-07-08", "endDate": today,
           "metrics": "views", "dimensions": "insightTrafficSourceType"})
    traffic = {row[0]: row[1] for row in r.get("rows", [])}
    tot = sum(traffic.values()) or 1
    rec = traffic.get("SHORTS", 0) + traffic.get("YT_OTHER_PAGE", 0) + traffic.get("NO_LINK_OTHER", 0)
    rec_share = round(100 * rec / tot, 1)
except Exception as e:
    print("traffic ERR", type(e).__name__, e)

rec = {"date": today, "subs": subs, "hours_365d": hours365,
       "rec_feed_share_pct": rec_share, "traffic": traffic,
       "ts": datetime.now(timezone.utc).isoformat()}

# 幂等写入
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
print(f"\n台账已写入 {LEDGER}，共 {len(rows)} 天")
if len(rows) >= 2:
    prev = rows[-2]
    print(f"日环比 vs {prev['date']}: 订阅 {prev['subs']} -> {subs} "
          f"(净增 {(subs or 0) - (prev['subs'] or 0)})")
