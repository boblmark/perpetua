"""B' 节流门（2026-10-10 议会决议 D20261010-003）。

规则：
- 独立 Karen 模板短剧：FROZEN，停止自动量产。select_topics() 直接返回空。
- Shorts 只允许从《AI UNHINGED》正片剪 teaser：
  每滚动 7 天 ≤2 条；任意两条间隔 ≥72 小时；teaser ≤45 秒。
- 发布 ground truth = YouTube Data API（uploads playlist）；API 失败时降级用本地台账。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json
import os
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(BASE, "teaser_spec_bprime.json")
LEDGER_PATH = os.path.join(BASE, "shorts_throttle.json")


def load_spec():
    with open(SPEC_PATH, encoding="utf-8") as f:
        return json.load(f)


def standalone_frozen():
    """独立短剧是否被冻结（B' 默认 True）。"""
    try:
        return load_spec()["shorts_throttle"]["standalone_karen_skits"].startswith("FROZEN")
    except Exception:
        return True


def _api_recent_publishes(days=7):
    """经 YouTube API 查频道近 N 天发布的视频（video_id, publishedAt）。失败返回 None。"""
    try:
        sys_path = os.path.join(os.path.dirname(BASE), "youtube")
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from yt_upload import _load, _req
        d = _load()
        token = d.get("access_token")
        if not token:
            return None
        # 先拿 uploads playlist id
        ch = _req("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true",
                 token)
        items = (ch.get("items") or [])
        if not items:
            return None
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        out, page = [], None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        while True:
            url = ("https://www.googleapis.com/youtube/v3/playlistItems"
                   "?part=snippet,contentDetails&playlistId=%s&maxResults=50" % uploads)
            if page:
                url += "&pageToken=" + page
            r = _req(url, token)
            for it in r.get("items", []):
                pub = it["contentDetails"]["videoPublishedAt"]
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if dt < cutoff:
                    return _filter_shorts(out, token)
                out.append({"video_id": it["contentDetails"]["videoId"],
                            "published_at": pub,
                            "title": it["snippet"].get("title", "")})
            page = r.get("nextPageToken")
            if not page:
                return _filter_shorts(out, token)
    except Exception:
        return None


def _filter_shorts(videos, token):
    """只保留 Shorts（时长 ≤60s）。EP1 等长视频不占 Shorts 配额。"""
    if not videos:
        return videos
    try:
        from yt_upload import _req
        import re
        def _to_seconds(iso):
            m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
            if not m:
                return 10 ** 9
            h, mi, s = (int(x) if x else 0 for x in m.groups())
            return h * 3600 + mi * 60 + s
        ids = [v["video_id"] for v in videos]
        shorts = []
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            r = _req("https://www.googleapis.com/youtube/v3/videos?part=contentDetails&id="
                     + ",".join(chunk), token)
            dur = {it["id"]: it["contentDetails"]["duration"]
                   for it in r.get("items", [])}
            for v in videos:
                if v["video_id"] in chunk and _to_seconds(dur.get(v["video_id"])) <= 62:
                    shorts.append(v)
        return shorts
    except Exception:
        return videos  # 过滤失败时保守计入（fail-closed 偏向节流）


def _ledger_recent_publishes(days=7):
    try:
        with open(LEDGER_PATH, encoding="utf-8") as f:
            rows = json.load(f)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out = []
        for r in rows:
            try:
                dt = datetime.fromisoformat(r["published_at"].replace("Z", "+00:00"))
            except Exception:
                continue
            if dt >= cutoff:
                out.append(r)
        return out
    except Exception:
        return []


def record_publish(video_id, title=""):
    """发布成功后记一笔台账（API 为准，台账为降级备份）。"""
    rows = []
    try:
        with open(LEDGER_PATH, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        pass
    rows.append({"video_id": video_id, "title": title,
                 "published_at": datetime.now(timezone.utc).isoformat()})
    # 只保留 90 天
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    rows = [r for r in rows
            if datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) >= cutoff]
    atomic_write_json(LEDGER_PATH, rows)


def throttle_allows():
    """B' 节流门：返回 (allowed: bool, reason: str)。"""
    try:
        spec = load_spec()["shorts_throttle"]
    except Exception as e:
        return False, f"spec 读取失败，fail-closed: {e}"
    max_n = spec.get("max_per_rolling_7d", 2)
    min_h = spec.get("min_interval_hours", 72)

    pubs = _api_recent_publishes(7)
    source = "youtube-api(shorts-only)"
    if pubs is None:
        pubs = _ledger_recent_publishes(7)
        source = "local-ledger(fallback)"
    n = len(pubs)
    if n >= max_n:
        return False, f"7 天内已发 {n} 条（上限 {max_n}，来源 {source}）"
    if pubs:
        latest = max(datetime.fromisoformat(p["published_at"].replace("Z", "+00:00"))
                     for p in pubs)
        hours = (datetime.now(timezone.utc) - latest).total_seconds() / 3600
        if hours < min_h:
            return False, f"距上条仅 {hours:.1f}h（要求 ≥{min_h}h）"
    return True, f"允许（7 天内 {n}/{max_n}，来源 {source}）"
