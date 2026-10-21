#!/usr/bin/env python3
"""只读拉取频道近48h发布视频（标题/描述/标签/发布时间/播放/点赞/评论）。"""
import json, urllib.request, urllib.parse, datetime, sys

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"
UPLOADS_PL = "UU" + CHANNEL_ID[2:]  # uploads playlist

def _urlopen(req, timeout=60):
    return urllib.request.urlopen(req, timeout=timeout)

with open(OAUTH_FILE) as f:
    d = json.load(f)
data = urllib.parse.urlencode({
    'client_id': d['client_id'], 'client_secret': d['client_secret'],
    'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token',
}).encode()
resp = json.load(_urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=data), 20))
token = resp['access_token']

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return json.load(_urlopen(req, 60))

now = datetime.datetime.now(datetime.timezone.utc)
cutoff = now - datetime.timedelta(hours=48)

items, page = [], None
while True:
    url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={UPLOADS_PL}&maxResults=50" + (f"&pageToken={page}" if page else "")
    r = get(url)
    for it in r.get("items", []):
        pub = datetime.datetime.fromisoformat(it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
        if pub < cutoff:
            break
        items.append(it)
    else:
        page = r.get("nextPageToken")
        if not page:
            break
        # 只查48h内：继续分页直到遇到过期条目
        continue
    break

out = []
for it in items:
    vid = it["contentDetails"]["videoId"]
    v = get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,status&id={vid}")["items"][0]
    s, st, stat = v["snippet"], v["status"], v.get("statistics", {})
    out.append({
        "video_id": vid,
        "title": s["title"],
        "published_at": it["contentDetails"]["videoPublishedAt"],
        "description_len": len(s.get("description", "")),
        "tags": s.get("tags", []),
        "privacy": st.get("privacyStatus"),
        "views": int(stat.get("viewCount", 0)),
        "likes": int(stat.get("likeCount", 0)),
        "comments": int(stat.get("commentCount", 0)),
        "url": f"https://www.youtube.com/watch?v={vid}",
    })

print(json.dumps({"checked_at": now.isoformat(), "count_48h": len(out), "videos": out}, ensure_ascii=False, indent=1))
