#!/usr/bin/env python3
"""每日选题数据回流（2026-10-09 用户要求：昨天的数据 → 今天选题加权）。

闭环：昨天发布的视频 24h 播放/完播 → 赢家主题加权 / 输家主题降权 → 写入
topic_weights.json + dynamic_constraints.json 的 topic_directives → viral_prompt.py
注入生成 prompt（选题→prompt→生成链路的加权入口）。

- 赢家：views ≥ 基线中位数 ×1.5，或 averageViewPercentage ≥10
- 输家：views < 基线中位数 ×0.5
- 基线：近 30 天发布视频 views 中位数（Analytics 口径）
- 主题三元组：device（复用 series.json device_keywords）/ karma 动词（karma_verbs.json）/ 钩子类型
- 幂等：同一 CST 自然日只算一次（topic_weights.json 的 date 水印）
- 硬门禁不受影响：去重门（90天设备/30天动词/90天钩子）照常执行，加权只影响排序偏好

每天 09:00 由 cron 调用（选题生成前）。
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path("/home/hatch/data")
PERP = BASE / "perpetua"
sys.path.insert(0, str(BASE / "youtube"))

OUT = PERP / "topic_weights.json"
DC = PERP / "dynamic_constraints.json"

WIN_MULT = 1.5    # 赢家：≥ 基线 ×1.5
LOSE_MULT = 0.5   # 输家：< 基线 ×0.5
RETENTION_WIN_PCT = 10.0  # 完播 ≥10% 直接算赢家（与 D5 阈值对齐）


def _load_series_devices():
    try:
        d = json.loads((PERP / "series.json").read_text(encoding="utf-8"))
        devs = []
        for s in d.get("series", []):
            for kw in s.get("device_keywords", []):
                devs.append((kw.lower(), s.get("id", "unknown")))
    except Exception:
        devs = []
    # 系列之外的常见设备 + 别名（标题写法与关键词不完全一致时兜底）
    EXTRA = [
        ("smart meter", "parking-verse"), ("parking meter", "parking-verse"),
        ("drive-thru", "drive-thru"), ("drive thru", "drive-thru"),
        ("drivethru", "drive-thru"),
        ("robot waiter", "robot-waiter"), ("waiter robot", "robot-waiter"),
        ("lawn mower", "lawn-mower"), ("mower", "lawn-mower"),
        ("self-checkout", "checkout-verse"),
        ("gas station", "car-verse"), ("ev charger", "car-verse"),
        ("coffee machine", "coffee"), ("escalator", "escalator"),
        ("elevator", "elevator"), ("atm", "atm"),
    ]
    seen = {k for k, _ in devs}
    for kw, sid in EXTRA:
        if kw not in seen:
            devs.append((kw, sid))
    devs.sort(key=lambda x: -len(x[0]))
    return devs


def _load_verbs():
    try:
        d = json.loads((PERP / "karma_verbs.json").read_text(encoding="utf-8"))
        verbs = []
        for tier in ("tier_s", "tier_b"):
            for v in d.get(tier, []):
                verbs.append((v.lower(), tier))
        return verbs
    except Exception:
        return []


def extract_theme(title, devices, verbs):
    t = (title or "").lower()
    device = None
    for kw, sid in devices:
        if kw in t:
            device = kw
            break
    verb = None
    for v, tier in verbs:
        if re.search(r"\b" + re.escape(v) + r"\b", t):
            verb = v
            break
    hook = None
    if re.match(r"^[^a-zA-Z0-9]*[\U0001F300-\U0001FAFF]", title or ""):
        hook = "emoji_open"
    return {"device": device, "verb": verb, "hook": hook}


def main():
    from yt import api_call, _token

    cst = timezone(timedelta(hours=8))
    today = datetime.now(cst).date()
    yesterday = today - timedelta(days=1)

    # 幂等：今天已算过就跳过
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        if prev.get("date") == today.isoformat():
            print(f"OK: {today} 已计算，跳过")
            return
    except Exception:
        pass

    # 1. 昨天发布的视频
    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "contentDetails", "mine": "true"})
    uploads = r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r2 = api_call("GET", "/youtube/v3/playlistItems",
                  params={"part": "snippet", "playlistId": uploads,
                          "maxResults": 25})
    yday_vids = []
    for it in r2["items"]:
        pub = datetime.fromisoformat(
            it["snippet"]["publishedAt"].replace("Z", "+00:00"))
        if pub.astimezone(cst).date() == yesterday:
            yday_vids.append({
                "video_id": it["snippet"]["resourceId"]["videoId"],
                "title": it["snippet"]["title"],
            })
    if not yday_vids:
        print(f"OK: {yesterday} 无发布视频，无回流")
        _write_empty(today, yesterday, "no videos published yesterday")
        return

    # 2. 播放数据：Analytics（views + 完播率）优先，Data API viewCount 兜底
    # （Analytics 的 yt-analytics scope 间歇性 401；Data API 口径稳定。
    #  昨日发布的视频：viewCount ≈ 24h 播放量，可直接用。）
    import urllib.request, urllib.parse
    token = _token()

    def analytics(video_ids, start, end):
        params = {"ids": "channel==MINE", "startDate": start, "endDate": end,
                  "metrics": "views,averageViewPercentage",
                  "dimensions": "video", "sort": "-views",
                  "filters": "video==" + ",".join(video_ids),
                  "maxResults": "50"}
        url = ("https://youtubeanalytics.googleapis.com/v2/reports?"
               + urllib.parse.urlencode(params))
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"})
        return json.load(urllib.request.urlopen(req, timeout=30)).get("rows", [])

    def data_api_views(video_ids):
        out = {}
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            r = api_call("GET", "/youtube/v3/videos",
                         params={"part": "statistics", "id": ",".join(chunk)})
            for v in r.get("items", []):
                out[v["id"]] = int(v["statistics"].get("viewCount", "0"))
        return out

    y0 = yesterday.isoformat()
    perf = {vid: {"views": 0, "ret_pct": 0.0} for vid in
            [v["video_id"] for v in yday_vids]}
    try:
        for row in analytics(list(perf), y0, today.isoformat()):
            perf[row[0]] = {"views": int(row[1]), "ret_pct": float(row[2])}
        print(f"Analytics OK: {len(perf)} 条昨日视频")
    except Exception as e:
        print(f"WARN: Analytics 失败 ({e})，改用 Data API viewCount 兜底")
        try:
            vc = data_api_views(list(perf))
            for vid, n in vc.items():
                perf[vid]["views"] = n
        except Exception as e2:
            print(f"WARN: Data API 兜底也失败: {e2}")

    # 基线：近30天发布视频 views 中位数（Data API 口径，稳定）
    # uploads 播放列表按发布时间倒序，取前 50 条即近 30 天
    med = 0
    try:
        r = api_call("GET", "/youtube/v3/playlistItems",
                     params={"part": "snippet", "playlistId": uploads,
                             "maxResults": "50"})
        base_ids = [it["snippet"]["resourceId"]["videoId"]
                    for it in r.get("items", [])]
        if base_ids:
            vc = data_api_views(base_ids)
            vals = sorted(vc.values())
            med = vals[len(vals) // 2]
    except Exception as e:
        print(f"WARN: 基线拉取失败: {e}")

    # 3. 主题提取 + 赢家/输家判定
    devices, verbs = _load_series_devices(), _load_verbs()
    boosts, penalties, details = {}, {}, []
    for v in yday_vids:
        p = perf[v["video_id"]]
        theme = extract_theme(v["title"], devices, verbs)
        win = (med and p["views"] >= med * WIN_MULT) or \
              p["ret_pct"] >= RETENTION_WIN_PCT
        lose = med and p["views"] < med * LOSE_MULT and not win
        tag = "WIN" if win else ("LOSE" if lose else "FLAT")
        target = boosts if win else (penalties if lose else None)
        if target is not None:
            for k in ("device", "verb"):
                if theme[k]:
                    target[theme[k]] = target.get(theme[k], 0) + 1
        details.append({"video_id": v["video_id"], "title": v["title"][:60],
                        "views_24h": p["views"], "ret_pct": round(p["ret_pct"], 1),
                        "theme": theme, "verdict": tag})

    # 4. 落盘
    directives = []
    for dev, n in sorted(boosts.items(), key=lambda x: -x[1])[:3]:
        directives.append(
            f"BOOST '{dev}' topics today (yesterday's winner theme, "
            f"{n} win signal{'s' if n > 1 else ''})")
    for dev, n in sorted(penalties.items(), key=lambda x: -x[1])[:3]:
        directives.append(
            f"AVOID '{dev}' topics today (yesterday underperformed "
            f"< {LOSE_MULT}x baseline)")
    out = {"date": today.isoformat(), "for_yesterday": yesterday.isoformat(),
           "baseline_median_views": med, "n_videos": len(yday_vids),
           "boosts": boosts, "penalties": penalties,
           "directives": directives, "details": details,
           "generated_at": datetime.now(timezone.utc).isoformat()}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    # 5. 注入 dynamic_constraints.json（新字段，不碰现有 directives）
    try:
        dc = json.loads(DC.read_text(encoding="utf-8"))
    except Exception:
        dc = {}
    dc["topic_directives"] = directives
    dc["topic_feedback_date"] = today.isoformat()
    DC.write_text(json.dumps(dc, ensure_ascii=False, indent=2),
                  encoding="utf-8")

    # 5b. 自动释放：teaser_hold 等待的题材若已不在今日 AVOID 名单，解除 hold
    # （2026-10-11 用户批准"等题材回暖"机制）
    try:
        avoided = set()
        for d in directives:
            if d.startswith("AVOID '"):
                avoided.add(d.split("'")[1].lower())
        import queue_db
        _q = queue_db.pipeline_load()
        _items = _q if isinstance(_q, list) else _q.get("items", [])
        _changed = False
        for _it in _items:
            if _it.get("teaser_hold") and _it.get("teaser_hold_topic", "").lower() not in avoided:
                _it["teaser_hold"] = False
                _it["teaser_hold_released_at"] = datetime.now(timezone.utc).isoformat()
                _it["teaser_hold_released_reason"] = \
                    "题材回暖：%s 已不在 AVOID 名单，恢复自动发布" % _it.get("teaser_hold_topic")
                _changed = True
                print(f"  - teaser hold 释放: {_it.get('topic', '')[:40]}")
        if _changed:
            import teaser_validate as _tv
            _tv.save_queue(_q)
    except Exception as _e:
        print(f"  - teaser hold 释放检查跳过: {_e}")

    print(f"OK: {yesterday} {len(yday_vids)} 条视频回流，基线中位数 {med}，"
          f"boost {len(boosts)} / penalty {len(penalties)}")
    for d in directives:
        print(f"  - {d}")


def _write_empty(today, yesterday, reason):
    OUT.write_text(json.dumps(
        {"date": today.isoformat(), "for_yesterday": yesterday.isoformat(),
         "baseline_median_views": 0, "n_videos": 0, "boosts": {},
         "penalties": {}, "directives": [], "details": [],
         "note": reason,
         "generated_at": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
