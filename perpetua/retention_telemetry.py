#!/usr/bin/env python3
"""
D4 留存遥测（2026-10-08 四脑路线图 Priority #3）。

诚实说明：YouTube Analytics API 不提供逐秒留存曲线（仅 Studio 界面可见）。
本脚本采集我们能拿到的最细粒度数据：每条视频的平均观看百分比/时长/互动，
与管线元数据（topic/hook/device/verb/模板版本）做 join，供 D5 特征提取。

每 24 小时由 cron 调用一次。输出：retention_telemetry.jsonl（append）。
"""
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path("/home/hatch/data")
sys.path.insert(0, str(BASE / "youtube"))
sys.path.insert(0, str(BASE / "perpetua"))
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db
OUT = BASE / "perpetua" / "retention_telemetry.jsonl"


def _analytics_per_video(token, start, end, max_n=50):
    """Analytics API：每条视频的 views/avgViewDuration/avgViewPercentage。"""
    import urllib.request, urllib.parse
    params = {"ids": "channel==MINE", "startDate": start, "endDate": end,
              "metrics": "views,averageViewDuration,averageViewPercentage",
              "dimensions": "video", "sort": "-views",
              "maxResults": str(max_n)}
    url = ("https://youtubeanalytics.googleapis.com/v2/reports?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req, timeout=30)).get("rows", [])


def main():
    from yt import api_call, _token

    now = datetime.now(timezone.utc)
    token, _ = _token()
    start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    # Analytics：每条视频的表现（一次拉 30 天 top 50）
    perf = {}
    try:
        for row in _analytics_per_video(token, start, end):
            perf[row[0]] = {"views": row[1], "avg_dur_s": row[2],
                            "avg_view_pct": row[3]}
    except Exception as e:
        print(f"analytics failed: {e}, falling back to Data API only")

    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "contentDetails", "mine": "true"})
    uploads = r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r2 = api_call("GET", "/youtube/v3/playlistItems",
                  params={"part": "snippet", "playlistId": uploads, "maxResults": 50})
    vids = [it["snippet"]["resourceId"]["videoId"] for it in r2["items"]]
    if not vids:
        print("no videos")
        return

    # 管线元数据索引（video_id → 制作特征）
    features = {}
    for qp in [BASE / "perpetua" / "pipeline_queue.json",
               BASE / "perpetua" / "awaiting_approval.json"]:
        try:
            # D20261011-001 P1: pipeline_queue 已迁 SQLite，其余仍读 JSON
            if qp.name == "pipeline_queue.json":
                q = queue_db.pipeline_load()
            else:
                q = json.loads(qp.read_text(encoding="utf-8"))
            items = q if isinstance(q, list) else q.get("items", [])
            for it in items:
                vf = str(it.get("video_file", ""))
                # video_id 未知时用标题匹配兜底
                features[it.get("title", "")[:50]] = {
                    "topic": it.get("topic", ""),
                    "hook": it.get("hook", "")[:100],
                    "review_score": it.get("review_score", 0),
                    "tags": it.get("tags", ""),
                }
        except Exception:
            pass

    r3 = api_call("GET", "/youtube/v3/videos",
                  params={"part": "snippet,statistics,contentDetails",
                          "id": ",".join(vids)})
    n = 0
    with open(OUT, "a", encoding="utf-8") as f:
        for v in r3["items"]:
            pub = datetime.fromisoformat(
                v["snippet"]["publishedAt"].replace("Z", "+00:00"))
            age_h = (now - pub).total_seconds() / 3600
            if age_h < 24:
                continue  # 只采 >24h 的视频（数据稳定）
            st = v["statistics"]
            views = int(st.get("viewCount", "0"))
            # 平均观看百分比：Data API 不直接给，用 duration 估算
            # contentDetails.duration 是 ISO 8601（如 PT11S）
            import re
            dur_s = 0
            m = re.match(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",
                         v["contentDetails"].get("duration", ""))
            if m:
                dur_s = int(m.group(1) or 0) * 60 + float(m.group(2) or 0)
            feat = features.get(v["snippet"]["title"][:50], {})
            ap = perf.get(v["id"], {})
            rec = {
                "ts": now.isoformat(),
                "video_id": v["id"],
                "title": v["snippet"]["title"][:80],
                "age_hours": round(age_h, 1),
                "views": ap.get("views", views),
                "avg_view_pct": ap.get("avg_view_pct"),  # 核心指标：平均观看百分比
                "avg_dur_s": ap.get("avg_dur_s"),
                "likes": int(st.get("likeCount", "0")),
                "comments": int(st.get("commentCount", "0")),
                "duration_s": dur_s,
                "tags": v["snippet"].get("tags", [])[:10],
                "pipeline": feat,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"telemetry: {n} videos appended")


if __name__ == "__main__":
    main()
