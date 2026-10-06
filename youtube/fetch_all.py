#!/usr/bin/env python3
"""拉取频道全部视频数据（分页），存为 JSON"""
import json, subprocess, sys

def api(path, params):
    import urllib.request, urllib.parse
    with open("/home/hatch/data/youtube/.oauth.json") as f:
        d = json.load(f)
    token = d["token"]
    # 尝试刷新
    def call(tok):
        url = f"https://www.googleapis.com{path}?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise PermissionError("expired")
            raise
    try:
        return call(token)
    except PermissionError:
        data = urllib.parse.urlencode({
            'client_id': d['client_id'], 'client_secret': d['client_secret'],
            'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token'}).encode()
        req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
        resp = json.load(urllib.request.urlopen(req, timeout=20))
        d['token'] = resp['access_token']
        with open("/home/hatch/data/youtube/.oauth.json", 'w') as f:
            json.dump(d, f)
        import os; os.chmod("/home/hatch/data/youtube/.oauth.json", 0o600)
        return call(d['token'])

import urllib.error

# 1. 拿 uploads playlist
ch = api("/youtube/v3/channels", {"part": "contentDetails", "mine": "true"})
uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

# 2. 分页拉全部 playlistItems
all_ids, page = [], None
while True:
    p = {"part": "snippet", "playlistId": uploads, "maxResults": 50}
    if page: p["pageToken"] = page
    r = api("/youtube/v3/playlistItems", p)
    for it in r["items"]:
        all_ids.append((it["snippet"]["resourceId"]["videoId"],
                        it["snippet"]["title"],
                        it["snippet"]["publishedAt"]))
    page = r.get("nextPageToken")
    print(f"已拉 {len(all_ids)} 个...", file=sys.stderr)
    if not page: break

# 3. 批量拉统计数据（50个一批）
videos = []
for i in range(0, len(all_ids), 50):
    batch = all_ids[i:i+50]
    ids = ",".join(v[0] for v in batch)
    r = api("/youtube/v3/videos",
            {"part": "snippet,statistics,contentDetails", "id": ids})
    stat = {v["id"]: v for v in r["items"]}
    for vid, title, pub in batch:
        s = stat.get(vid, {})
        st = s.get("statistics", {})
        cd = s.get("contentDetails", {})
        sn = s.get("snippet", {})
        videos.append({
            "id": vid, "title": sn.get("title", title),
            "published": pub[:10],
            "views": int(st.get("viewCount", 0)),
            "likes": int(st.get("likeCount", 0)),
            "comments": int(st.get("commentCount", 0)),
            "duration": cd.get("duration", ""),
            "tags": sn.get("tags", []),
        })
    print(f"统计 {len(videos)}/{len(all_ids)}", file=sys.stderr)

with open("/home/hatch/data/youtube/all_videos.json", "w") as f:
    json.dump(videos, f, ensure_ascii=False, indent=1)
print(f"完成，共 {len(videos)} 个视频")
