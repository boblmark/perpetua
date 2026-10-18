#!/usr/bin/env python3
"""deep-dive worker: pull 48h published videos with full metadata (read-only)."""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from yt import recent_videos, api_call
from datetime import datetime, timedelta, timezone
import json

OUT = "/home/hatch/data/perpetua/deepdive_48h.json"

def main():
    videos = recent_videos(25)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    vids = [v for v in videos if v.get("published", "")[:10] >= cutoff]
    print("48h videos: %d" % len(vids), flush=True)
    ids = [v["id"] for v in vids]
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = api_call("GET", "/youtube/v3/videos",
                     params={"part": "snippet,statistics,contentDetails",
                             "id": ",".join(chunk)})
        for v in r.get("items", []):
            sn = v.get("snippet", {})
            st = v.get("statistics", {})
            cd = v.get("contentDetails", {})
            out.append({
                "id": v["id"],
                "title": sn.get("title"),
                "description": (sn.get("description") or "")[:600],
                "tags": sn.get("tags", []),
                "category": sn.get("categoryId"),
                "publishedAt": sn.get("publishedAt"),
                "defaultAudioLanguage": sn.get("defaultAudioLanguage"),
                "views": int(st.get("viewCount", 0) or 0),
                "likes": int(st.get("likeCount", 0) or 0),
                "comments": int(st.get("commentCount", 0) or 0),
                "duration": cd.get("duration"),
            })
    for v in out:
        print("%s | %s | views=%s likes=%s comments=%s dur=%s pub=%s lang=%s tags=%d" % (
            v["id"], v["title"], v["views"], v["likes"], v["comments"],
            v["duration"], v["publishedAt"], v["defaultAudioLanguage"],
            len(v["tags"])), flush=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved %d -> %s" % (len(out), OUT), flush=True)

if __name__ == "__main__":
    main()
