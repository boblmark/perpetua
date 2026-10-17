#!/usr/bin/env python3
"""用用户贴回的授权 code 换 token，写入 .oauth.json 并验证三个 API。

用法: exchange_code.py "<用户贴回的整串URL 或 纯code>"
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
REDIRECT_URI = "http://localhost:8080/"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

PROXY = "http://hatch-egress-proxy:3128"
os.environ.setdefault("https_proxy", PROXY)
os.environ.setdefault("http_proxy", PROXY)


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    m = re.search(r"[?&]code=([^&]+)", raw)
    code = urllib.parse.unquote(m.group(1)) if m else raw.strip()
    if not code:
        print("ERR: 没解析到 code")
        sys.exit(1)

    d = json.load(open(OAUTH_FILE))
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": d["client_id"],
        "client_secret": d["client_secret"],
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    try:
        tok = json.load(urllib.request.urlopen(
            urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
            timeout=30))
    except urllib.error.HTTPError as e:
        print("ERR token exchange:", e.code, e.read()[:300])
        sys.exit(1)

    d["token"] = tok["access_token"]
    if tok.get("refresh_token"):
        d["refresh_token"] = tok["refresh_token"]
    d["scopes"] = SCOPES
    with open(OAUTH_FILE, "w") as f:
        json.dump(d, f)
    os.chmod(OAUTH_FILE, 0o600)
    print("OK: token 已写入", "refresh_token:", "已更新" if tok.get("refresh_token") else "沿用旧值")

    # 验证 1: Data API
    def api(url):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {d['token']}"})
        return json.load(urllib.request.urlopen(req, timeout=20))

    ch = api("https://www.googleapis.com/youtube/v3/channels?"
             + urllib.parse.urlencode({"part": "snippet", "mine": "true"}))
    title = ch["items"][0]["snippet"]["title"] if ch.get("items") else "?"
    print("OK: Data API 频道 =", title)

    # 验证 2: Analytics API
    an = api("https://youtubeanalytics.googleapis.com/v2/reports?"
             + urllib.parse.urlencode({
                 "ids": "channel==MINE", "startDate": "2026-09-08", "endDate": "2026-10-08",
                 "metrics": "views,averageViewDuration,averageViewPercentage,shares"}))
    print("OK: Analytics API =", an.get("rows"))

    # 验证 3: 评论读取
    cm = api("https://www.googleapis.com/youtube/v3/commentThreads?"
             + urllib.parse.urlencode({"part": "snippet", "allThreadsRelatedToChannelId": ch["items"][0]["id"],
                                        "maxResults": "1"}))
    print("OK: 评论 API 可读")
    print("ALL GREEN")


if __name__ == "__main__":
    main()
