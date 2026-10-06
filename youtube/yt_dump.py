#!/usr/bin/env python3
"""全量拉取频道上传视频（分页），输出 JSONL 供回溯分析。

用法: python3 yt_dump.py [max_total]
输出: /home/hatch/data/youtube/uploads_full.jsonl
"""
import json
import sys
sys.path.insert(0, "/home/hatch/data/youtube")
from yt import api_call

def get_uploads_playlist():
    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "contentDetails,snippet,statistics", "mine": "true"})
    item = r["items"][0]
    return (item["contentDetails"]["relatedPlaylists"]["uploads"],
            item["snippet"]["title"],
            item["statistics"])

def list_all_video_ids(playlist_id, max_total=None):
    ids, page = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
        if page:
            params["pageToken"] = page
        r = api_call("GET", "/youtube/v3/playlistItems", params=params)
        for it in r.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
            if max_total and len(ids) >= max_total:
                return ids
        page = r.get("nextPageToken")
        if not page:
            break
    return ids

def fetch_details(ids):
    """videos.list 一次最多 50 个 id。"""
    out = []
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        r = api_call("GET", "/youtube/v3/videos",
                     params={"part": "snippet,statistics,contentDetails",
                             "id": ",".join(batch)})
        for v in r.get("items", []):
            st = v.get("statistics", {})
            sn = v.get("snippet", {})
            cd = v.get("contentDetails", {})
            out.append({
                "video_id": v["id"],
                "title": sn.get("title", ""),
                "description": (sn.get("description", "") or "")[:500],
                "tags": sn.get("tags", []),
                "published": sn.get("publishedAt", "")[:10],
                "published_at": sn.get("publishedAt", ""),
                "duration": cd.get("duration", ""),
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
                "favorites": int(st.get("favoriteCount", 0) or 0),
            })
    return out

if __name__ == "__main__":
    max_total = int(sys.argv[1]) if len(sys.argv) > 1 else None
    pid, chan_title, stats = get_uploads_playlist()
    print(f"# channel={chan_title} subs={stats.get('subscriberCount')} "
          f"videos={stats.get('videoCount')} views={stats.get('viewCount')}", flush=True)
    ids = list_all_video_ids(pid, max_total)
    print(f"# video_ids={len(ids)}", flush=True)
    details = fetch_details(ids)
    out_path = "/home/hatch/data/youtube/uploads_full.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for d in details:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"# wrote {len(details)} rows -> {out_path}", flush=True)
