#!/usr/bin/env python3
"""YouTube Analytics API 封装：CTR、完播率、流量来源等真实算法信号"""
import json, os, sys, urllib.request, urllib.parse
from datetime import date, timedelta

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
API = "https://youtubeanalytics.googleapis.com/v2/reports"

def _token():
    with open(OAUTH_FILE) as f:
        return json.load(f)["token"]

def _refresh():
    with open(OAUTH_FILE) as f:
        d = json.load(f)
    data = urllib.parse.urlencode({
        'client_id': d['client_id'], 'client_secret': d['client_secret'],
        'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    resp = json.load(urllib.request.urlopen(req, timeout=20))
    d['token'] = resp['access_token']
    with open(OAUTH_FILE, 'w') as f:
        json.dump(d, f)
    os.chmod(OAUTH_FILE, 0o600)
    return d['token']

def query(metrics, dimensions="", start=None, end=None, sort="", max_n=10, filters=""):
    if not end:
        end = date.today().isoformat()
    if not start:
        start = (date.today() - timedelta(days=30)).isoformat()
    params = {
        "ids": "channel==MINE",
        "startDate": start, "endDate": end,
        "metrics": metrics,
    }
    if dimensions: params["dimensions"] = dimensions
    if sort: params["sort"] = sort
    if max_n: params["maxResults"] = max_n
    if filters: params["filters"] = filters
    url = API + "?" + urllib.parse.urlencode(params)

    def call(tok):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PermissionError("expired")
            raise
    try:
        return call(_token())
    except PermissionError:
        return call(_refresh())

def traffic_sources(days=30):
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    r = query("views", "insightTrafficSourceType", start, end, "-views", 10)
    return {row[0]: row[1] for row in r.get("rows", [])}

def video_performance(days=30, top_n=10):
    """每条视频的播放量 + 平均观看时长"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    r = query("views,averageViewDuration", "video", start, end, "-views", top_n)
    return [{"video_id": row[0], "views": row[1],
             "avg_watch_secs": round(row[2], 1)}
            for row in r.get("rows", [])]

def shorts_90d():
    """过去90天 Shorts 播放总量（YPP 指标）"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=90)).isoformat()
    # 用 dimension 查再过滤，避免 filter 语法问题
    r = query("views", "insightTrafficSourceType", start, end, "-views", 10)
    for row in r.get("rows", []):
        if row[0] == "SHORTS":
            return row[1]
    return 0

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "traffic"
    if cmd == "traffic":
        print(json.dumps(traffic_sources(), ensure_ascii=False, indent=2))
    elif cmd == "videos":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(json.dumps(video_performance(top_n=n), ensure_ascii=False, indent=2))
    elif cmd == "shorts90":
        print(json.dumps({"shorts_90d_views": shorts_90d()}))
