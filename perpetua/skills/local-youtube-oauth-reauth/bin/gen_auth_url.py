#!/usr/bin/env python3
"""生成 YouTube OAuth 授权 URL（打印出来发给用户手机打开）"""
import json
import urllib.parse

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
REDIRECT_URI = "http://localhost:8080/"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

d = json.load(open(OAUTH_FILE))
params = {
    "client_id": d["client_id"],
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": " ".join(SCOPES),
    "access_type": "offline",   # 必须：拿 refresh_token
    "prompt": "consent",        # 必须：强制重新同意，否则可能不发 refresh_token
}
url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
print(url)
