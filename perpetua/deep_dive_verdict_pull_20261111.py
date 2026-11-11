#!/usr/bin/env python3
"""Read-only verdict pull: v7/v8 + 48h+ verdict queue. No writes to YouTube."""
import json, urllib.request, urllib.parse, datetime, sys

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
IDS = ["bslAlkpwu0Y", "3W44WW9PyBU", "RzEW0kTG3-k", "5WzdzWKoqKE",
       "ELrY4NH8tag", "DU2pVCyOTJw", "Jk57n_0j1ZY"]

with open(OAUTH_FILE) as f:
    d = json.load(f)
data = urllib.parse.urlencode({
    'client_id': d['client_id'], 'client_secret': d['client_secret'],
    'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token',
}).encode()
resp = json.load(urllib.request.urlopen(
    urllib.request.Request('https://oauth2.googleapis.com/token', data=data), timeout=20))
token = resp['access_token']

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req, timeout=60))

now = datetime.datetime.now(datetime.timezone.utc)
out = {"checked_at": now.isoformat(), "videos": []}
for vid in IDS:
    v = get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,status&id={vid}")["items"][0]
    s, st, stat = v["snippet"], v["status"], v.get("statistics", {})
    out["videos"].append({
        "video_id": vid, "title": s.get("title"),
        "published_at": s.get("publishedAt"),
        "privacy": st.get("privacyStatus"),
        "views": int(stat.get("viewCount", 0)),
        "likes": int(stat.get("likeCount", 0)),
        "comments": int(stat.get("commentCount", 0)),
        "description_len": len(s.get("description", "")),
        "tags": s.get("tags", []),
    })
print(json.dumps(out, ensure_ascii=False, indent=1))
