#!/usr/bin/env python3
"""竞品每日快照：10 家 YouTube 竞品频道近 90 天播放 top15（Data API 口径）。

输出：~/workspace/goals/karenvsai/files/competitor-snapshots/competitor-snapshot-YYYYMMDD.json（日期 Asia/Shanghai）
口径说明：与 2026-10-28 arena 人工快照同结构（每家 top15 + 订阅/视频数），但来源为 Data API——
页面显示数与 API 数同源，微差属正常刷新时差；API 无 Short/Long 标记，故只记 duration，不判类型。
配额 403 或传输失败时写 .gap.json 缺口标记、不编数，次日自动续跑。
配额成本：约 25-30 单位/天（channels 批量 1 次 + 每家 playlistItems 1 次 + videos 批量）。
"""
import json, os, sys, time, urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/hatch/data/youtube")
from yt import api_call

POOL = "/home/hatch/data/perpetua/radar/competitors_youtube.json"
OUTDIR = os.path.expanduser("~/workspace/goals/karenvsai/files/competitor-snapshots")
CST = timezone(timedelta(hours=8))


def today_cst():
    return datetime.now(CST).strftime("%Y-%m-%d")


def _parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    date_str = today_cst()
    window_start = datetime.now(timezone.utc) - timedelta(days=90)
    with open(POOL) as f:
        pool = json.load(f)
    channels = pool["channels"]
    ids = [c["channel_id"] for c in channels]
    r = api_call("GET", "/youtube/v3/channels", params={
        "part": "snippet,statistics,contentDetails", "id": ",".join(ids), "maxResults": 50})
    meta = {it["id"]: it for it in r.get("items", [])}
    out_channels = []
    failures = []
    for c in channels:
        cid = c["channel_id"]
        try:
            m = meta[cid]
            uploads = m["contentDetails"]["relatedPlaylists"]["uploads"]
            # 翻页取上传列表：高频频道 50 条首页盖不住 90 天，必须翻到窗口外才停
            items = []
            page_token = None
            truncated = False
            for _ in range(10):  # 最多 10 页（500 条），防页数失控
                params = {"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 50}
                if page_token:
                    params["pageToken"] = page_token
                r2 = api_call("GET", "/youtube/v3/playlistItems", params=params)
                page_items = r2.get("items", [])
                items.extend(page_items)
                page_token = r2.get("nextPageToken")
                if not page_items or not page_token or \
                        _parse_ts(page_items[-1]["contentDetails"]["videoPublishedAt"]) < window_start:
                    break
            else:
                truncated = True  # 10 页未翻到窗口外，窗口内视频可能未取尽
            vids = [it["contentDetails"]["videoId"] for it in items
                    if _parse_ts(it["contentDetails"]["videoPublishedAt"]) >= window_start]
            stats = {}
            for i in range(0, len(vids), 50):
                r3 = api_call("GET", "/youtube/v3/videos", params={
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(vids[i:i + 50])})
                for v in r3.get("items", []):
                    s = v.get("statistics", {})
                    stats[v["id"]] = {
                        "video_id": v["id"],
                        "title": v["snippet"]["title"],
                        "url": f"https://www.youtube.com/watch?v={v['id']}",
                        "views": int(s.get("viewCount", 0)),
                        "likes": int(s["likeCount"]) if s.get("likeCount") is not None else None,
                        "comments": int(s["commentCount"]) if s.get("commentCount") is not None else None,
                        "published": v["snippet"]["publishedAt"][:10],
                        "duration": v["contentDetails"]["duration"],
                    }
            top = sorted(stats.values(), key=lambda x: x["views"], reverse=True)[:15]
            out_channels.append({
                "channel_id": cid, "name": c["name"], "tier": c["tier"],
                "subs": m["statistics"].get("subscriberCount"),
                "video_count": m["statistics"].get("videoCount"),
                "window_video_count": len(vids), "truncated_page": truncated,
                "top15": top,
            })
        except Exception as e:
            failures.append({"channel_id": cid, "name": c["name"], "error": repr(e)})
    os.makedirs(OUTDIR, exist_ok=True)
    out_path = os.path.join(OUTDIR, f"competitor-snapshot-{date_str}.json")
    payload = {"snapshot_date": date_str, "source": "youtube-data-api",
               "window_days": 90, "channels": out_channels, "failures": failures}
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out_path)
    total_rows = sum(len(ch["top15"]) for ch in out_channels)
    print(f"OK {date_str}: {len(out_channels)}/10 channels, {total_rows} rows -> {out_path}")
    if failures:
        print(f"FAILURES: {failures}")
        return 1
    return 0


def _write_gap(reason):
    date_str = today_cst()
    os.makedirs(OUTDIR, exist_ok=True)
    gap = {"snapshot_date": date_str, "gap": True, "reason": reason}
    with open(os.path.join(OUTDIR, f"competitor-snapshot-{date_str}.gap.json"), "w") as f:
        json.dump(gap, f, ensure_ascii=False, indent=1)
    print(f"GAP {date_str}: {reason}, gap marker written, no data fabricated")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as e:
        _write_gap(f"HTTP {e.code}")
        sys.exit(3)
    except Exception:
        # 传输层异常：只重试一次，仍失败则记缺口、不编数
        try:
            time.sleep(10)
            sys.exit(main())
        except Exception as e2:
            _write_gap(repr(e2))
            sys.exit(4)
