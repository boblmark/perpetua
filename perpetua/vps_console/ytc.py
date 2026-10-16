#!/usr/bin/env python3
"""YouTube 频道评论抓取（走 relay 旁路）。
用法: ytc.py <max_comments>
示例: ytc.py 20  -> 全频道最新 20 条评论（含已回复状态）
输出 JSON: [{id, author, text, videoId, videoTitle, publishedAt, replied, likeCount}]
用 allThreadsRelatedToChannelId 一次拉全频道评论，比逐视频查更全。
"""
import sys, json, urllib.request, urllib.parse
sys.path.insert(0, "/home/hatch/data")
from relay import urlopen as r_open

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"

def _token():
    with open(OAUTH_FILE) as f:
        return json.load(f)["token"]

def _api(path, params, token):
    url = "https://www.googleapis.com" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    return json.load(r_open(req, timeout=30))

def main():
    max_n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    tok = _token()

    threads = _api("/youtube/v3/commentThreads", {
        "part": "snippet",
        "allThreadsRelatedToChannelId": CHANNEL_ID,
        "maxResults": min(max_n, 50),
        "order": "time",
        "textFormat": "plainText",
    }, tok)

    out = []
    for item in threads.get("items", []):
        c = item["snippet"]["topLevelComment"]
        sn = c["snippet"]
        out.append({
            "id": c["id"],
            "author": sn.get("authorDisplayName", "?"),
            "text": sn.get("textDisplay", "")[:300],
            "videoId": sn.get("videoId", ""),
            "videoTitle": "",  # 全频道接口不返回标题，前端按需显示 videoId
            "publishedAt": sn.get("publishedAt", ""),
            "replied": item["snippet"].get("totalReplyCount", 0) > 0,
            "likeCount": sn.get("likeCount", 0),
        })
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
