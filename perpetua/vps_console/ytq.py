#!/usr/bin/env python3
"""YouTube Analytics 快捷查询（走 relay 旁路）。
用法: ytq.py <metrics> <days> [dimensions]
示例: ytq.py views 7          -> 近7天总播放
      ytq.py views 90 insightTrafficSourceType  -> 90天各流量来源播放（含SHORTS）
"""
import sys, json, urllib.request, urllib.parse
sys.path.insert(0, "/home/hatch/data")
from relay import urlopen as r_open
from datetime import date, timedelta

def main():
    metrics = sys.argv[1] if len(sys.argv) > 1 else "views"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    dimensions = sys.argv[3] if len(sys.argv) > 3 else ""

    tok = json.load(open("/home/hatch/data/youtube/.oauth.json"))["token"]
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    params = {
        "ids": "channel==MINE",
        "startDate": start, "endDate": end,
        "metrics": metrics,
    }
    if dimensions:
        params["dimensions"] = dimensions
        params["sort"] = "-views"
        params["maxResults"] = 10
    url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    d = json.load(r_open(req, timeout=30))
    print(json.dumps(d.get("rows", [])))

if __name__ == "__main__":
    main()
