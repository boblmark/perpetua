#!/usr/bin/env python3
"""八平台分发矩阵同步器 platform_matrix_sync.py

数据文件: /home/hatch/data/perpetua/distributor/platform_matrix.json
控制台经 /api/platform_matrix 读取展示；评论回复经 /api/matrix_reply 进 reply_gate 人工门。

YouTube 走官方 Data API（relay 旁路 + /home/hatch/data/youtube/.oauth.json），直连可跑：
    python3 platform_matrix_sync.py --youtube        # 视频 + 评论一起同步

其余 7 平台走浏览器任务读公开主页（见 platform-matrix-sync cron 工单），
采集到后用 --merge 写回：
    python3 platform_matrix_sync.py --merge douyin /tmp/douyin.json
待合并 JSON 格式: {"channel": "...", "profile_url": "...",
  "avatar": "头像URL", "cover": "封面URL", "description": "频道简介",
  "videos": [{"title": "...", "url": "...", "cover": "...",
              "views": 123, "likes": 45, "published_at": "2026-10-10T..",
              "pinned": true}],
  显示规则（2026-10-11 定版）：置顶视频优先收录（pinned=true，最多 3 条，
  访客第一眼看到的就是它们），再收最新 5 条非置顶；videos 上限 8 条。
  "comments": [{"comment_id": "...", "video_title": "...", "video_url": "...",
              "author": "...", "text": "...", "likes": 12,
              "published_at": "...", "replied": false}]}
views/likes 允许为 null（页面没显示就空着，不编数字）。
"""
import json, os, sys, urllib.request, urllib.parse, datetime

BASE = "/home/hatch/data/perpetua/distributor"
MATRIX = os.path.join(BASE, "platform_matrix.json")
sys.path.insert(0, "/home/hatch/data")
sys.path.insert(0, "/home/hatch/data/youtube")
sys.path.insert(0, "/home/hatch/data/perpetua")
from atomic_json import atomic_write  # v2.0.0 KILL3: 原子写
from relay import urlopen as r_open

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
YT_CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def load():
    with open(MATRIX, encoding="utf-8") as f:
        return json.load(f)

def save(d):
    d["updated_at"] = now_iso()
    atomic_write(MATRIX, d)  # v2.0.0 KILL3: tmp+fsync+rename+锁，不再裸写

def update_platform(key, channel=None, profile_url=None, videos=None,
                    comments=None, status="ok", avatar=None, cover=None,
                    description=None):
    d = load()
    p = d["platforms"].get(key)
    if not p:
        raise SystemExit(f"unknown platform: {key}")
    if channel: p["channel"] = channel
    if profile_url: p["profile_url"] = profile_url
    if videos is not None: p["videos"] = videos[:8]
    if comments is not None:
        import hashlib as _hl
        fixed = []
        for c in comments[:10]:
            c = dict(c)
            if not c.get("comment_id"):
                h = _hl.md5(((c.get("author") or "") + (c.get("text") or "")
                              + (c.get("video_url") or "")).encode()).hexdigest()[:8]
                c["comment_id"] = f"ext-{key}-{h}"
            fixed.append(c)
        p["comments"] = fixed
    if avatar is not None: p["avatar"] = avatar
    if cover is not None: p["cover"] = cover
    if description is not None: p["description"] = description
    p["status"] = status
    p["synced_at"] = now_iso()
    save(d)
    print(f"{key}: status={status} videos={len(p['videos'])} comments={len(p['comments'])}")

# ---------- YouTube（relay + oauth） ----------
def _load_oauth():
    d = json.load(open(OAUTH_FILE))
    return d

def _refresh(d):
    data = urllib.parse.urlencode({
        'client_id': d['client_id'], 'client_secret': d['client_secret'],
        'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    resp = json.load(r_open(req, timeout=20))
    d['token'] = resp['access_token']
    # 凭据文件：tmp+fsync+rename（不断电半截），不走 atomic_write（避免 .bak 留存密钥副本）
    _tmp = OAUTH_FILE + ".tmp"
    with open(_tmp, "w", encoding="utf-8") as _f:
        json.dump(d, _f)
        _f.flush()
        os.fsync(_f.fileno())
    os.replace(_tmp, OAUTH_FILE)
    os.chmod(OAUTH_FILE, 0o600)
    return d['token']

def _api(path, token, params=None):
    url = "https://www.googleapis.com/youtube/v3/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        return json.load(r_open(req, timeout=30))
    except Exception as e:
        if "401" in str(e):
            raise PermissionError("expired")
        raise

def _call(fn, *a):
    d = _load_oauth()
    try:
        return fn(d["token"], *a)
    except PermissionError:
        return fn(_refresh(d), *a)

def sync_youtube():
    def do(tok):
        ch = _api("channels", tok, {"part": "snippet,contentDetails,brandingSettings",
                                    "id": YT_CHANNEL_ID})
        items = ch.get("items", [])
        if not items:
            return None, [], [], {}
        snip = items[0]["snippet"]
        brand = items[0].get("brandingSettings", {}).get("image", {})
        th = snip.get("thumbnails", {})
        branding = {
            "avatar": (th.get("medium") or th.get("default") or {}).get("url"),
            "cover": brand.get("bannerExternalUrl"),
            "description": (snip.get("description") or "")[:500],
        }
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = _api("playlistItems", tok, {"part": "snippet", "playlistId": uploads,
                                         "maxResults": 8})
        vids = [it["snippet"]["resourceId"]["videoId"] for it in pl.get("items", [])]
        videos = []
        if vids:
            vs = _api("videos", tok, {"part": "snippet,statistics",
                                      "id": ",".join(vids)})
            for v in vs.get("items", []):
                sn, st = v["snippet"], v.get("statistics", {})
                th = sn.get("thumbnails", {})
                cover = (th.get("medium") or th.get("default") or {}).get("url")
                videos.append({
                    "title": sn["title"],
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                    "cover": cover,
                    "views": int(st["viewCount"]) if st.get("viewCount") else None,
                    "likes": int(st["likeCount"]) if st.get("likeCount") else None,
                    "published_at": sn.get("publishedAt"),
                })
        ct = _api("commentThreads", tok, {
            "part": "snippet", "allThreadsRelatedToChannelId": YT_CHANNEL_ID,
            "maxResults": 15, "order": "time", "textFormat": "plainText"})
        comments = []
        vtitle = {v["url"].split("v=")[1]: v["title"] for v in videos}
        for it in ct.get("items", []):
            t = it["snippet"]["topLevelComment"]["snippet"]
            vid = t.get("videoId", "")
            comments.append({
                "comment_id": it["snippet"]["topLevelComment"]["id"],
                "video_title": vtitle.get(vid, ""),
                "video_url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                "author": t.get("authorDisplayName", ""),
                "text": (t.get("textDisplay", "") or "")[:300],
                "likes": t.get("likeCount"),
                "published_at": t.get("publishedAt"),
                "replied": (it["snippet"].get("totalReplyCount", 0) or 0) > 0,
            })
        return snip, videos, comments, branding
    snip, videos, comments, branding = _call(do)
    if snip is None:
        update_platform("youtube", status="error")
        print("youtube: channel not found")
        return
    update_platform("youtube", channel=snip["title"],
                    profile_url="https://www.youtube.com/@karenvsai",
                    videos=videos, comments=comments, status="ok",
                    avatar=branding.get("avatar"), cover=branding.get("cover"),
                    description=branding.get("description"))

def main():
    if "--youtube" in sys.argv:
        sync_youtube()
    elif "--merge" in sys.argv:
        i = sys.argv.index("--merge")
        key, path = sys.argv[i+1], sys.argv[i+2]
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        # stale：只标状态，不拿空数据覆盖旧的好数据（2026-10-11 修）
        if payload.get("status") == "stale":
            d = load()
            d["platforms"][key]["status"] = "stale"
            d["platforms"][key]["synced_at"] = now_iso()
            save(d)
            print(f"{key}: status=stale (keep old data)")
            return
        update_platform(key,
                        channel=payload.get("channel"),
                        profile_url=payload.get("profile_url"),
                        videos=payload.get("videos", []),
                        comments=payload.get("comments", []),
                        status=payload.get("status", "ok"),
                        avatar=payload.get("avatar"),
                        cover=payload.get("cover"),
                        description=payload.get("description"))
    elif "--show" in sys.argv:
        d = load()
        for k, p in d["platforms"].items():
            print(f"{k:12s} {p['status']:7s} {len(p['videos'])}视频 {len(p['comments'])}评论 {p.get('synced_at') or '-'}")
        # C20 batch A：--show 是每小时矩阵轮的收尾步（任务体步骤 4，
        # 无论全量/部分都必跑），轮末写 beat 即“本轮已完成”。
        # 不在 --youtube/--merge 写 beat：那两步只是轮次中段，写了会
        # 把半轮冒充整轮健康。写失败 best-effort，绝不拖垮 --show。
        try:
            from watchdog_watchdog import write_heartbeat as _ww_beat
            _ww_beat("platform-matrix-sync", 60)
        except Exception:
            pass
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
