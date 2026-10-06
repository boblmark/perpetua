#!/usr/bin/env python3
"""发布后优化：48小时诊断 + 自动换标题 + 自动回评论（抄 toldbynova 作业）

逻辑：
1. 拉出 48-72 小时前发布的视频
2. 查每个的播放量；低于阈值（默认50，或频道中位数一半）判定为"哑火"
3. 哑火视频：用爆款公式生成 2 个备选标题，自动换上得分最高的
4. 对所有新视频：自动回复前 5 条评论（英文互动模板）
"""
import json, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

DATA_DIR = "/home/hatch/data"
OAUTH_FILE = f"{DATA_DIR}/youtube/.oauth.json"
LOG_FILE = f"{DATA_DIR}/youtube/post_optimize_log.jsonl"
VIEWS_THRESHOLD = 50  # 48h 播放低于此算哑火

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def _load_oauth():
    return json.load(open(OAUTH_FILE))

def _refresh(d):
    data = urllib.parse.urlencode({
        "client_id": d["client_id"], "client_secret": d["client_secret"],
        "refresh_token": d["refresh_token"], "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    resp = json.load(urllib.request.urlopen(req, timeout=20))
    d["token"] = resp["access_token"]
    json.dump(d, open(OAUTH_FILE, "w"))
    os.chmod(OAUTH_FILE, 0o600)
    return d["token"]

def _api(method, path, token, data=None, params=None):
    url = f"https://www.googleapis.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PermissionError("expired")
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}")

def _call(fn, *args):
    d = _load_oauth()
    try:
        return fn(d["token"], *args)
    except PermissionError:
        return fn(_refresh(d), *args)

CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"

def get_recent_videos(days=4):
    """最近 N 天发布的视频"""
    def do(tok):
        after = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()[:19] + "Z"
        return _api("GET", "/youtube/v3/search", tok, params={
            "part": "snippet", "channelId": CHANNEL_ID, "type": "video",
            "order": "date", "maxResults": 25, "publishedAfter": after})
    r = _call(do)
    out = []
    for item in r.get("items", []):
        vid = item["id"]["videoId"]
        out.append({"video_id": vid, "title": item["snippet"]["title"],
                    "published": item["snippet"]["publishedAt"]})
    return out

def get_views(video_ids):
    """批量查播放量"""
    def do(tok):
        return _api("GET", "/youtube/v3/videos", tok, params={
            "part": "statistics", "id": ",".join(video_ids)})
    r = _call(do)
    return {i["id"]: int(i["statistics"].get("viewCount", 0))
            for i in r.get("items", [])}

def get_comments(video_id, n=5):
    """取前 N 条评论"""
    def do(tok):
        return _api("GET", "/youtube/v3/commentThreads", tok, params={
            "part": "snippet", "videoId": video_id,
            "maxResults": n, "order": "time"})
    try:
        r = _call(do)
    except RuntimeError:
        return []  # 评论区可能关闭
    out = []
    for item in r.get("items", []):
        c = item["snippet"]["topLevelComment"]
        out.append({"id": c["id"], "text": c["snippet"]["textDisplay"][:80],
                    "replied": item["snippet"].get("totalReplyCount", 0) > 0})
    return out

def reply_comment(comment_id, text):
    def do(tok):
        return _api("POST", "/youtube/v3/comments", tok, {
            "snippet": {"parentId": comment_id,
                        "textOriginal": text}}, {"part": "snippet"})
    return _call(do)

def update_title(video_id, new_title, old_title):
    """换标题（保留原描述/标签）"""
    d = _load_oauth()
    def do_put(tok):
        info = _api("GET", "/youtube/v3/videos", tok, params={
            "part": "snippet", "id": video_id})["items"][0]["snippet"]
        info["title"] = new_title
        return _api("PUT", "/youtube/v3/videos", tok,
                    {"id": video_id, "snippet": info}, {"part": "snippet"})
    try:
        do_put(d["token"])
    except PermissionError:
        do_put(_refresh(d))
    return {"video_id": video_id, "old": old_title, "new": new_title}

# 备选标题生成：爆款公式 variants
def gen_alt_titles(original):
    """基于原标题生成 2 个备选（换钩子词/加emoji/调语序）"""
    alts = []
    # 策略1：加"Part 2"式悬念或强化冲突词
    hooks = ["😱", "🤯", "💥", "⚠️"]
    base = original.strip()
    # 去掉已有结尾 emoji 避免堆叠
    # 策略 A：前面加更强的 emoji + 保留核心
    alts.append(f"🤯 {base}")
    # 策略 B：加悬念后缀
    core = re.sub(r"\s*[#@].*$", "", base).strip()
    core = re.sub(r"\s+[\U0001F300-\U0001FAFF☀-➿]+\s*$", "", core).strip()
    alts.append(f"{core} — You Won't Believe What Happens Next! 😱")
    # 去重且不与原标题相同
    return [a for a in dict.fromkeys(alts) if a != original][:2]

REPLY_TEMPLATES = [
    "Thanks for watching! 🔥 Which part was your favorite?",
    "Glad you enjoyed it! 😂 More Karen vs AI coming soon!",
    "Appreciate the comment! 👀 What should the AI do next?",
]

def log(entry):
    entry["ts"] = now_iso()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def main():
    import random
    videos = get_recent_videos(4)
    if not videos:
        print(json.dumps({"status": "no recent videos"}))
        return
    views = get_views([v["video_id"] for v in videos])
    now = datetime.now(timezone.utc)
    results = {"checked": len(videos), "retitled": [], "replied": []}

    for v in videos:
        vid = v["video_id"]
        pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
        age_h = (now - pub).total_seconds() / 3600
        vc = views.get(vid, 0)

        # 48h+ 且哑火 → 换标题
        if age_h >= 48 and vc < VIEWS_THRESHOLD:
            # 2026-10-06 改：不再自动换标题，改为生成备选写入审批队列（人工批）
            try:
                sys.path.insert(0, "/home/hatch/data/perpetua")
                from auto_retitle import gen_alt_titles as _gen3
                alts = _gen3(v["title"], vid)
                if alts:
                    ap = "/home/hatch/data/perpetua/awaiting_approval.json"
                    try:
                        approvals = json.load(open(ap, encoding="utf-8"))
                    except Exception:
                        approvals = []
                    existing = {a.get("video_id") for a in approvals if isinstance(a, dict)}
                    if vid not in existing:
                        approvals.append({
                            "type": "auto_retitle",
                            "video_id": vid,
                            "old_title": v["title"],
                            "alt_titles": alts,
                            "views_at_check": vc,
                            "age_h": round(age_h, 1),
                            "status": "awaiting",
                            "created_at": now_iso(),
                            "source": "post_publish_optimizer（48h 哑火）",
                        })
                        json.dump(approvals, open(ap, "w", encoding="utf-8"),
                                  ensure_ascii=False, indent=2)
                        results["retitled"].append(
                            {"video_id": vid, "queued_for_approval": True,
                             "alts": alts})
                        log({"action": "retitle_queued", "video_id": vid,
                             "old_title": v["title"][:60], "alts": alts,
                             "views_at_48h": vc})
            except Exception as e:
                log({"action": "retitle_failed", "video_id": vid,
                     "error": str(e)[:100]})

        # 7天内新视频 → 回前5条评论
        if age_h < 168:
            for c in get_comments(vid, 5):
                if not c["replied"]:
                    try:
                        reply_comment(c["id"], random.choice(REPLY_TEMPLATES))
                        results["replied"].append({"video": vid[:8], "comment": c["text"][:40]})
                        log({"action": "reply", "video_id": vid})
                    except Exception:
                        pass

    print(json.dumps(results, ensure_ascii=False, indent=2))
    # 遥测：记录优化阶段执行
    try:
        import subprocess as _sp
        n_ret = len(results.get("retitled", []))
        n_rep = len(results.get("replied", []))
        _sp.run(["python3", "/home/hatch/data/perpetua/pipeline.py", "default",
                 "optimize", "ok",
                 f"换标题 {n_ret} 个，回评论 {n_rep} 条", str(n_ret + n_rep)],
                capture_output=True, timeout=10)
    except Exception:
        pass

if __name__ == "__main__":
    main()
