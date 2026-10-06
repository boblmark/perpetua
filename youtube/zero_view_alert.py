#!/usr/bin/env python3
"""
0 播放告警：扫描最近 48 小时发布的视频，
播放量为 0 且发布超过 6 小时 → 写入 inbox 告警 + 自动触发标题优化。

每小时由 zero-view-watch cron 调用。
"""
import json, sys, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path("/home/hatch/data")
sys.path.insert(0, str(BASE / "youtube"))

ALERT_HOURS = 6       # 发布超过 6 小时仍 0 播放 → 告警
SCAN_HOURS = 48       # 扫描最近 48 小时发布的视频
DEDUP_FILE = BASE / "youtube" / "zero_view_alerted.json"
INBOX = BASE / "collab" / "inbox.json"


def load_dedup():
    if DEDUP_FILE.exists():
        try:
            return set(json.loads(DEDUP_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_dedup(s):
    DEDUP_FILE.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    from yt import api_call

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=SCAN_HOURS)

    # 取最近 25 个视频，查 status + statistics
    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "contentDetails", "mine": "true"})
    uploads = r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r2 = api_call("GET", "/youtube/v3/playlistItems",
                  params={"part": "snippet", "playlistId": uploads, "maxResults": 25})
    vids = [it["snippet"]["resourceId"]["videoId"] for it in r2["items"]]
    if not vids:
        print("no videos")
        return

    r3 = api_call("GET", "/youtube/v3/videos",
                  params={"part": "snippet,status,statistics", "id": ",".join(vids)})

    alerted = load_dedup()
    new_alerts = []

    for v in r3["items"]:
        vid = v["id"]
        pub = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        if pub < cutoff:
            continue
        views = int(v["statistics"].get("viewCount", "0"))
        privacy = v["status"].get("privacyStatus", "unknown")
        age_h = (now - pub).total_seconds() / 3600

        # 情况1: private 视频 → 严重问题，立即告警
        if privacy != "public" and age_h > 1 and vid not in alerted:
            new_alerts.append({
                "video_id": vid,
                "title": v["snippet"]["title"][:60],
                "reason": f"privacy={privacy}",
                "age_hours": round(age_h, 1),
                "action": "auto_fix_privacy",
            })
            # 自动修复：转公开
            try:
                api_call("PUT", "/youtube/v3/videos", params={"part": "status"},
                         data={"id": vid, "status": {"privacyStatus": "public"}})
                new_alerts[-1]["fixed"] = "set to public"
            except Exception as e:
                new_alerts[-1]["fix_error"] = str(e)[:100]
            alerted.add(vid)

        # 情况2: 公开但 6 小时+ 0 播放 → 告警
        elif privacy == "public" and views == 0 and age_h >= ALERT_HOURS and vid not in alerted:
            new_alerts.append({
                "video_id": vid,
                "title": v["snippet"]["title"][:60],
                "reason": "0 views after 6h+",
                "age_hours": round(age_h, 1),
                "action": "trigger_title_optimization",
            })
            alerted.add(vid)

    if new_alerts:
        save_dedup(alerted)
        inbox = json.loads(INBOX.read_text(encoding="utf-8"))
        inbox.setdefault("messages", []).append({
            "type": "zero_view_alert",
            "message": f"0播放告警: {len(new_alerts)} 个视频异常 — " +
                       "; ".join(f"{a['title'][:30]}({a['reason']})" for a in new_alerts),
            "details": new_alerts,
            "from": "zero-view-watch",
            "created_at": now.isoformat(),
        })
        INBOX.write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"ALERT: {len(new_alerts)} videos")
        for a in new_alerts:
            print(f"  - {a['video_id']}: {a['reason']} | {a.get('fixed', a['action'])}")
    else:
        print("OK: no zero-view alerts")


if __name__ == "__main__":
    main()
