#!/usr/bin/env python3
"""YouTube 评论：发布后自动发一条引导互动的置顶评论"""
import json, os, sys, urllib.request, urllib.parse

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"

def _load():
    with open(OAUTH_FILE) as f:
        return json.load(f)

def _refresh(d):
    data = urllib.parse.urlencode({
        'client_id': d['client_id'], 'client_secret': d['client_secret'],
        'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token',
    }).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    resp = json.load(urllib.request.urlopen(req, timeout=20))
    d['token'] = resp['access_token']
    with open(OAUTH_FILE, 'w') as f:
        json.dump(d, f)
    os.chmod(OAUTH_FILE, 0o600)
    return d['token']

def _api(method, path, token, data=None, params=None):
    url = f"https://www.googleapis.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PermissionError("expired")
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}")

def post_comment(video_id, text):
    d = _load()
    def do(tok):
        return _api("POST", "/youtube/v3/commentThreads", tok, {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}},
            }
        }, {"part": "snippet"})
    try:
        r = do(d["token"])
    except PermissionError:
        r = do(_refresh(d))
    return {"comment_id": r["id"], "video_id": video_id}

# 引导评论模板（轮换使用，避免重复）
TEMPLATES = [
    "Which part got you? 😂 Drop a 🔥 if Karen deserved it!",
    "POV: you witnessed this live 👀 What would YOU have done?",
    "This is why we can't have nice things 🤣 Tag someone who needs to see this!",
    "Instant karma never misses 😱 Which moment was the best?",
]

if __name__ == "__main__":
    import random
    vid = sys.argv[1]
    text = sys.argv[2] if len(sys.argv) > 2 else random.choice(TEMPLATES)
    print(json.dumps(post_comment(vid, text), ensure_ascii=False, indent=2))
