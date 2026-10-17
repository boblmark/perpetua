#!/usr/bin/env python3
"""YouTube 雷达轮询器（Phase 1，D20261017-002）：只读快照，禁自动快车道。

做法（抄 ViewStats 拆解结论）：
- 自有频道：uploads 播放列表（UC->UU 换前缀）分页拉取 videoId（playlistItems.list=1配额/页），
  再 50 个一批调 videos.list（part=snippet,statistics，1配额/批）。
  永不用 search.list 做批量发现（100配额/次，贵且无必要）。
- 竞品：competitors_youtube.json 种子（channel_id 或 video_id），默认空集。
  每个竞品频道取最近 N 条（默认 20）。

幂等：同（platform,video_id,snapshot_at 精确到秒）冲突时 UPDATE 覆盖，可重跑。
用法：python3 youtube_snapshot.py [--limit 50] [--dry-run]
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from radar_lib import (connect, track_video, insert_snapshot, thumbnail_hash, thumb_phash,
                       append_run_log, ts_str, today_str, normalize_competitors,
                       video_format, quota_guard, set_channel_archived, QUOTA_HARD_STOP)

YT = "/home/hatch/data/youtube"
sys.path.insert(0, YT)
from yt_upload import _load, _refresh, _req  # 复用现有 OAuth（含 401 自动刷新）

API = "https://www.googleapis.com/youtube/v3"
COMPETITOR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "competitors_youtube.json")
quota_units = 0


def api_get(url):
    global quota_units
    d = _load()
    try:
        quota_units += 1
        return json.load(_req(url, d["token"], "GET"))
    except PermissionError:
        d = _load()
        token = _refresh(d)
        quota_units += 1
        return json.load(_req(url, token, "GET"))


def my_uploads_playlist():
    d = api_get(f"{API}/channels?part=contentDetails&mine=true")
    ch = d["items"][0]
    return ch["id"], ch["contentDetails"]["relatedPlaylists"]["uploads"]


def playlist_video_ids(playlist_id, max_items=1000):
    ids, token = [], None
    while len(ids) < max_items:
        url = (f"{API}/playlistItems?part=contentDetails&playlistId={playlist_id}"
               f"&maxResults=50" + (f"&pageToken={token}" if token else ""))
        d = api_get(url)
        ids += [it["contentDetails"]["videoId"] for it in d.get("items", [])]
        token = d.get("nextPageToken")
        if not token:
            break
    return ids[:max_items]


def videos_details(video_ids):
    """50 个一批拉取 snippet+statistics+contentDetails。返回 {video_id: item}。"""
    out = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        d = api_get(f"{API}/videos?part=snippet,statistics,contentDetails&id={','.join(batch)}")
        for it in d.get("items", []):
            out[it["id"]] = it
    return out


def parse_duration_iso8601(s):
    """PT#H#M#S → 秒；解析失败返回 None。"""
    if not s:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s.strip())
    if not m:
        return None
    h, mi, sec = m.groups()
    return (int(h or 0) * 3600) + (int(mi or 0) * 60) + float(sec or 0)


def load_competitors():
    if not os.path.exists(COMPETITOR_FILE):
        with open(COMPETITOR_FILE, "w", encoding="utf-8") as f:
            json.dump({"channels": [], "videos": [],
                       "_how_to_add": "channels: 竞品频道ID 列表；videos: 竞品视频ID 列表。"
                       "添加后本轮询器自动跟踪其最近视频的每日快照。只读，不触发任何选题动作。"},
                      f, ensure_ascii=False, indent=2)
        return {"channels": [], "videos": []}
    with open(COMPETITOR_FILE, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多抓取自有视频数（0=全部）")
    ap.add_argument("--competitor-videos", type=int, default=20, help="每个竞品频道取最近 N 条")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要抓的数量，不写库")
    args = ap.parse_args()

    channel_id, uploads = my_uploads_playlist()
    own_ids = playlist_video_ids(uploads)
    if args.limit:
        own_ids = own_ids[:args.limit]
    comp = load_competitors()
    comp_entries = normalize_competitors(comp.get("channels"))
    comp_ids = list(comp.get("videos") or [])

    # 配额硬停（规格 v1）：先估算本轮用量，超 9500 直接中止，不碰配额
    # 估算 = 播放列表分页 + videos 批量 + 频道信息查询
    est_pages = (len(own_ids) + 49) // 50 + len(comp_entries)
    est_batches = (len(own_ids) + len(comp.get("videos") or [])
                   + len(comp_entries) * args.competitor_videos + 49) // 50
    quota_guard(2 + est_pages + est_batches + len(comp_entries), "youtube_snapshot")

    con = connect()
    gone_channels = []
    for entry in comp_entries:
        ch_id = entry["channel_id"]
        d = api_get(f"{API}/channels?part=contentDetails&id={ch_id}")
        if not d.get("items"):
            # 频道被删/停用/转私密 → 唯一自动移除路径（红队 KILL 规则 9 修订）
            set_channel_archived(con, "youtube", ch_id, "channel_not_found")
            gone_channels.append(ch_id)
            continue
        ups = d["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        vids = playlist_video_ids(ups, max_items=args.competitor_videos)
        comp_ids += vids
        for vid in vids:
            track_video(con, "youtube", vid, ch_id, "competitor")
        # tier 落到 tracked_videos（档位为筛选起点，空位不降标准）
        if entry.get("tier"):
            con.execute("UPDATE tracked_videos SET tier=? WHERE platform='youtube'"
                        " AND channel_id=? AND label='competitor'",
                        (entry["tier"], ch_id))

    if args.dry_run:
        print(json.dumps({"own": len(own_ids), "competitor": len(comp_ids),
                          "quota_units_so_far": quota_units}, ensure_ascii=False))
        return

    n_snap = 0

    def snap_one(vid, ch_id, label, it):
        nonlocal n_snap
        sn, st = it["snippet"], it.get("statistics", {})
        track_video(con, "youtube", vid, ch_id, label)
        dur = parse_duration_iso8601((it.get("contentDetails") or {}).get("duration"))
        fmt = video_format(dur)
        pub = sn.get("publishedAt")
        # 缩略图 hash 只对近 180 天视频做（老视频换图概率低，省带宽）
        pub_day = (pub or "")[:10]
        recent = (not pub_day) or (pub_day >= "2026-04-20")
        th_url = (sn.get("thumbnails") or {}).get("default", {}).get("url")
        insert_snapshot(con, "youtube", vid,
                        int(st.get("viewCount", 0)), int(st.get("likeCount", 0)),
                        int(st.get("commentCount", 0)), sn.get("title"),
                        th_url, thumbnail_hash(th_url) if recent else None,
                        published_at=pub, duration_sec=dur, fmt=fmt,
                        thumb_phash=thumb_phash(th_url) if recent else None)
        n_snap += 1

    details = videos_details(own_ids)
    for vid in own_ids:
        it = details.get(vid)
        if it:
            snap_one(vid, channel_id, "own", it)
    cdetails = videos_details(list(dict.fromkeys(comp_ids)))
    for vid, it in cdetails.items():
        ch_id = (it.get("snippet") or {}).get("channelId")
        snap_one(vid, ch_id, "competitor", it)
    con.commit()
    con.close()
    line = (f"youtube_snapshot done own={len(own_ids)} competitor={len(comp_ids)} "
            f"snapshots={n_snap} quota_units={quota_units}"
            + (f" gone_channels={gone_channels}" if gone_channels else ""))
    append_run_log("youtube_snapshot", line)
    print(line)


if __name__ == "__main__":
    main()
