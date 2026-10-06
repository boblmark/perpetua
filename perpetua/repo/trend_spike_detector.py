#!/usr/bin/env python3
"""热点爆发检测：每小时扫描，发现病毒式热点立刻触发主动推送。"""
import json, os, re, urllib.request
from datetime import datetime, timezone, timedelta

DATA_DIR = "/home/hatch/data"
STATE_FILE = f"{DATA_DIR}/trend_spike_state.json"
INBOX = f"{DATA_DIR}/collab/inbox.json"

CHANNEL_KEYWORDS = ["karen", "ai", "robot", "self-checkout", "self checkout",
    "chatbot", "artificial intelligence", "automation",
    "customer service", "drive-thru", "smart home"]

def get_tenants():
    """从租户注册表取 active 租户；失败时回退单租户模式"""
    try:
        import sys
        sys.path.insert(0, f"{DATA_DIR}/perpetua/tenants")
        from manager import active_tenants
        ts = active_tenants()
        if ts:
            return ts
    except Exception:
        pass
    return [{"id": "default", "name": "Default Channel",
             "keywords": CHANNEL_KEYWORDS,
             "theme": "Karen vs AI",
             "youtube_channel_name": "Mark Bobl | Karen vs AI",
             "youtube_channel_id": "UCaVJw-mQc51X8WWssI1vjbg"}]

def tenant_state_file(tid):
    return f"{DATA_DIR}/trend_spike_state_{tid}.json"

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def load_state(tid="default"):
    f = tenant_state_file(tid) if tid != "default" else STATE_FILE
    # 兼容旧版：default 仍用原 STATE_FILE
    if tid == "default":
        f = STATE_FILE
    if os.path.exists(f):
        return json.load(open(f))
    return {"history": {}, "alerts": []}

def save_state(s, tid="default"):
    f = STATE_FILE if tid == "default" else tenant_state_file(tid)
    json.dump(s, open(f, "w"), ensure_ascii=False, indent=2)

def channel_baseline():
    """频道基线：历史视频播放中位数（缓存每天更新）"""
    import os
    from datetime import datetime
    cache = f"{DATA_DIR}/trend_spike_baseline.json"
    # 每天更新一次
    if os.path.exists(cache):
        c = json.load(open(cache))
        if c.get("date") == datetime.now().strftime("%Y-%m-%d"):
            return c["median"]
    try:
        videos = json.load(open(f"{DATA_DIR}/youtube/all_videos.json"))
        views = sorted([v["views"] for v in videos if v.get("views", 0) > 0])
        median = views[len(views) // 2] if views else 100
        json.dump({"date": datetime.now().strftime("%Y-%m-%d"),
                   "median": median, "count": len(views)},
                  open(cache, "w"))
        return median
    except Exception:
        return 100

def outlier_multiplier(item_views):
    """相对基线的倍数"""
    base = channel_baseline()
    return round(item_views / max(base, 1), 1)

def channel_relevance(text, keywords=None):
    t = text.lower()
    hits = 0
    for kw in (keywords or CHANNEL_KEYWORDS):
        # 多词短语用子串，单词用词边界
        if " " in kw:
            if kw in t:
                hits += 1
        elif re.search(r"\b" + re.escape(kw) + r"\b", t):
            hits += 1
    return min(hits / 2, 1.0)

def fetch_google_trends_daily():
    url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
        titles = re.findall(r"<title>([^<]+)</title>", data)[1:21]
        traffic = re.findall(r"ht:approx_traffic>([^<]+)", data)
        out = []
        for i, t in enumerate(titles):
            tr = traffic[i] if i < len(traffic) else ""
            out.append({"title": t.strip(), "traffic": tr})
        return out
    except Exception as e:
        return [{"error": str(e)[:100]}]

def fetch_youtube_trending():
    try:
        with open(f"{DATA_DIR}/youtube/.oauth.json") as f:
            token = json.load(f)["token"]
        url = ("https://www.googleapis.com/youtube/v3/videos"
               "?part=snippet,statistics&chart=mostPopular&regionCode=US&maxResults=25")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        d = json.load(urllib.request.urlopen(req, timeout=20))
        out = []
        for item in d.get("items", []):
            sn = item["snippet"]
            st = item.get("statistics", {})
            out.append({"title": sn["title"], "channel": sn["channelTitle"],
                        "views": int(st.get("viewCount", 0)),
                        "published": sn["publishedAt"][:10]})
        return out
    except Exception as e:
        return [{"error": str(e)[:100]}]

def fetch_google_news():
    """Google News 突发新闻（AI/robot/karen 相关）"""
    import xml.etree.ElementTree as ET
    queries = ["AI robot viral", "karen viral video", "self-checkout AI"]
    out = []
    for q in queries:
        url = ("https://news.google.com/rss/search?q=" +
               urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=15).read()
            root = ET.fromstring(data)
            for item in root.findall(".//item")[:10]:
                title = item.find("title").text or ""
                pub = item.find("pubDate").text or ""
                out.append({"title": title, "published": pub, "query": q})
        except Exception:
            continue
    return out

def detect_spikes(state, tenant):
    spikes = []
    keywords = tenant.get("keywords") or CHANNEL_KEYWORDS
    tid = tenant.get("id", "default")
    trends = fetch_google_trends_daily()
    yt = fetch_youtube_trending()
    seen = {k.lower() for k in state["history"].keys()}
    for t in trends:
        if "error" in t:
            continue
        title = t["title"]
        rel = channel_relevance(title, keywords)
        if title.lower() not in seen and rel >= 0.5:
            spikes.append({"source": "google_trends", "title": title,
                           "traffic": t.get("traffic", ""),
                           "relevance": round(rel, 2), "detected_at": now_iso()})
        state["history"][title] = now_iso()
    for v in yt:
        if "error" in v:
            continue
        rel = channel_relevance(v["title"], keywords)
        key = "yt:" + v["title"]
        if key.lower() not in seen and rel >= 0.5 and v["views"] > 100000:
            mult = outlier_multiplier(v["views"])
            spike = {"source": "youtube_trending", "title": v["title"],
                     "views": v["views"], "relevance": round(rel, 2),
                     "outlier_x": mult,  # 相对频道基线的倍数
                     "detected_at": now_iso()}
            # 离群值 3x+ 自动升级为最高优先级
            if mult >= 3:
                spike["priority_boost"] = True
            spikes.append(spike)
        state["history"][key] = now_iso()
    # Google News 突发：只收 24 小时内的新鲜事
    from email.utils import parsedate_to_datetime
    day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    for n in fetch_google_news():
        try:
            pub = parsedate_to_datetime(n["published"])
            if pub < day_ago:
                continue  # 超过24小时的不算爆发
        except Exception:
            continue
        rel = channel_relevance(n["title"], keywords)
        key = "news:" + n["title"]
        if key.lower() not in seen and rel >= 0.5:
            spikes.append({"source": "google_news", "title": n["title"],
                           "published": n["published"][:16],
                           "relevance": round(rel, 2), "detected_at": now_iso()})
        state["history"][key] = now_iso()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    state["history"] = {k: v for k, v in state["history"].items() if v > cutoff}
    return spikes

def auto_ask_studio(spikes, tenant):
    """热点爆发时自动向 Ask Studio 要选题角度（按租户主题）"""
    import subprocess
    tid = tenant.get("id", "default")
    theme = tenant.get("theme", "Karen vs AI")
    ch_name = tenant.get("youtube_channel_name") or tenant.get("name", "")
    for s in spikes:
        q = (f"A trending topic '{s['title']}' is blowing up right now. "
             f"Give me 1 specific Shorts video concept for my channel "
             f"'{ch_name}' (theme: {theme}) that rides this trend, with a hook "
             f"for the first 3 seconds.")
        subprocess.run(["python3", f"{DATA_DIR}/ask_studio/query_queue.py",
                        "ask", q, "system", "urgent", tid],
                       capture_output=True, timeout=15)

def push_urgent(spikes, tenant):
    tid = tenant.get("id", "default")
    tname = tenant.get("name", tid)
    ch_id = tenant.get("youtube_channel_id", "")
    with open(INBOX) as f:
        inbox = json.load(f)
    for s in spikes:
        outlier_info = ""
        if s.get("outlier_x"):
            outlier_info = f"，热度为频道基线 {s['outlier_x']}x"
            if s.get("priority_boost"):
                outlier_info += " 🔥【离群爆发】"
        notice = {
            "type": "urgent_trend", "priority": "URGENT", "created": now_iso(),
            "tenant_id": tid, "tenant_name": tname,
            "youtube_channel_id": ch_id,
            "title": f"🔥 热点爆发 [{tname}]：" + s["title"][:50],
            "message": (
                f"租户 {tname}（{tenant.get('theme','')}）检测到热点爆发"
                f"（来源：{s['source']}，相关度 {s['relevance']}{outlier_info}）：\n"
                f"「{s['title']}」\n\n"
                "【极速通道】跳过日常排期，立即执行：\n"
                "1. 围绕这个热点出 1 个选题（标题必须含热点关键词+该账号爆款公式）\n"
                "2. jev 判分时效性加成，60分门槛不变\n"
                "3. 生成 → 直接上传到该租户 YouTube 频道（channel_id 上方），目标 4 小时内上线"),
            "for": "marvis", "read": False, "spike": s}
        inbox.setdefault("notices", []).append(notice)
    with open(INBOX, "w") as f:
        json.dump(inbox, f, ensure_ascii=False, indent=2)
    return len(spikes)

def main():
    tenants = get_tenants()
    total = 0
    results = []
    import subprocess as _sp
    for tenant in tenants:
        tid = tenant.get("id", "default")
        state = load_state(tid)
        spikes = detect_spikes(state, tenant)
        # 遥测：记录趋势阶段执行
        _sp.run(["python3", f"{DATA_DIR}/perpetua/pipeline.py", tid, "trend",
                 "ok" if spikes else "ok",
                 f"{len(spikes)} 个热点" if spikes else "无新热点",
                 str(len(spikes))],
                capture_output=True, timeout=10)
        if spikes:
            n = push_urgent(spikes, tenant)
            auto_ask_studio(spikes, tenant)
            state["alerts"].extend([{"at": now_iso(), "title": s["title"][:60]} for s in spikes])
            total += len(spikes)
            results.append({"tenant": tid, "spikes": n,
                            "titles": [s["title"][:40] for s in spikes]})
        save_state(state, tid)
    if total:
        print(json.dumps({"spikes": total, "pushed": total,
                          "by_tenant": results}, ensure_ascii=False))
    else:
        print(json.dumps({"spikes": 0, "status": "no new spikes",
                          "tenants": len(tenants)}))

if __name__ == "__main__":
    main()
