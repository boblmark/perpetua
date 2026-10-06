#!/usr/bin/env python3
"""YouTube API 测试：验证 OAuth 凭据并获取频道信息"""
import json
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"

# 走代理
os.environ["https_proxy"] = os.environ.get("https_proxy", "http://hatch-egress-proxy:3128")
os.environ["http_proxy"] = os.environ.get("http_proxy", "http://hatch-egress-proxy:3128")

def get_service():
    with open(OAUTH_FILE) as f:
        data = json.load(f)
    creds = Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )
    if creds.expired:
        creds.refresh(Request())
        data["token"] = creds.token
        with open(OAUTH_FILE, "w") as f:
            json.dump(data, f)
        import os
        os.chmod(OAUTH_FILE, 0o600)
    return build("youtube", "v3", credentials=creds)

if __name__ == "__main__":
    yt = get_service()
    ch = yt.channels().list(part="snippet,statistics", mine=True).execute()
    item = ch["items"][0]
    print(json.dumps({
        "channel_id": item["id"],
        "title": item["snippet"]["title"],
        "subs": item["statistics"].get("subscriberCount"),
        "videos": item["statistics"].get("videoCount"),
        "views": item["statistics"].get("viewCount"),
    }, ensure_ascii=False, indent=2))
