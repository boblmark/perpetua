#!/usr/bin/env python3
"""YouTube 上传 + 数据查询工具库

网络：所有出站请求走 relay 旁路（VM:18080 -> ssh -L -> VPS:18080 -> 目标）。
原因：VM 默认 egress 代理会挂起任何携带 Authorization 头的请求（25-30s 超时，
与凭据真假无关），直连不可用。详见 /home/hatch/data/relay.py 顶部说明。
"""
import json, os, sys, urllib.request, urllib.parse
sys.path.insert(0, "/home/hatch/data")
from relay import urlopen as _urlopen

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"

def _token():
    with open(OAUTH_FILE) as f:
        d = json.load(f)
    # 简单过期检查：直接用，401 时刷新
    return d["token"], d

def _refresh(d):
    data = urllib.parse.urlencode({
        'client_id': d['client_id'], 'client_secret': d['client_secret'],
        'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token',
    }).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    resp = json.load(_urlopen(req, timeout=20))
    d['token'] = resp['access_token']
    with open(OAUTH_FILE, 'w') as f:
        json.dump(d, f)
    os.chmod(OAUTH_FILE, 0o600)
    return d['token']

def _api(method, path, token, data=None, params=None):
    url = f"https://www.googleapis.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": f"Bearer {token}"}
    body = json.dumps(data).encode() if data else None
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        return json.load(_urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PermissionError("token_expired")
        raise

def api_call(method, path, data=None, params=None):
    token, d = _token()
    try:
        return _api(method, path, token, data, params)
    except PermissionError:
        token = _refresh(d)
        return _api(method, path, token, data, params)

def channel_stats():
    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "snippet,statistics", "mine": "true"})
    i = r["items"][0]
    return {"title": i["snippet"]["title"],
            "subs": i["statistics"].get("subscriberCount"),
            "videos": i["statistics"].get("videoCount"),
            "views": i["statistics"].get("viewCount")}

def recent_videos(max_n=10):
    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "contentDetails", "mine": "true"})
    uploads = r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r2 = api_call("GET", "/youtube/v3/playlistItems",
                  params={"part": "snippet", "playlistId": uploads, "maxResults": max_n})
    vids = [it["snippet"]["resourceId"]["videoId"] for it in r2["items"]]
    if not vids:
        return []
    r3 = api_call("GET", "/youtube/v3/videos",
                  params={"part": "snippet,statistics", "id": ",".join(vids)})
    return [{"id": v["id"], "title": v["snippet"]["title"],
             "published": v["snippet"]["publishedAt"][:10],
             "views": v["statistics"].get("viewCount", "0"),
             "likes": v["statistics"].get("likeCount", "0"),
             "comments": v["statistics"].get("commentCount", "0")}
            for v in r3["items"]]

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "stats":
        print(json.dumps(channel_stats(), ensure_ascii=False, indent=2))
    elif cmd == "recent":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        print(json.dumps(recent_videos(n), ensure_ascii=False, indent=2))

