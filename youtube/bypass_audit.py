#!/usr/bin/env python3
"""事后审计：检测绕过 MCP youtube_upload 门禁直接发布的视频。

背景：Marvis 有独立 YouTube OAuth，可直接调 YouTube API 上传，
绕过本机 youtube_upload 的全部硬门禁（纯度/去重/错峰/emoji/元数据/动词）。
技术上无法阻止直调，只能事后审计 + 自动处置。

用法：
    python3 /home/hatch/data/youtube/bypass_audit.py [--hours 24] [--dry-run]

只读 YouTube 数据 + 写 inbox/日志，不自动删除/私享视频（处置权留给用户）。
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/hatch/data/youtube")
sys.path.insert(0, "/home/hatch/data/perpetua")

DATA = "/home/hatch/data"
INBOX = f"{DATA}/collab/inbox.json"
AUDIT_LOG = f"{DATA}/youtube/bypass_audit.log.jsonl"
AWAITING = f"{DATA}/perpetua/awaiting_approval.json"

# ---- 门禁逻辑（从 mcp_server/server.py _upload_hard_gates 复刻，适配事后审计）----

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF"
    "\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF\u231A-\u231B\u23E9-\u23F3"
    "\u23F8-\u23FA\U0001F004\U0001F0CF"
    "\u2690-\u2691\u2B05-\u2B07\u2B1B-\u2B1C\u2B50\u2B55"
    "\u2744\u2747\u274C\u274E\u2753-\u2755\u2757"
    "\u2795-\u2797\u27A1\u27B0\u27BF\u2B05]",
    flags=re.UNICODE)

KARMA_VERBS = ["TOWED", "SOAKED", "BOOTED", "TRAPPED", "DESTROYED",
               "EXPOSED", "CAUGHT", "SNAPPED", "BURNED", "FLOODED",
               "LOCKED", "SPRAYED", "DRENCHED", "EVICTED", "HIT",
               "BROKE", "CRASHED", "EXPLODED"]


def _keywords(t):
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\U0001F300-\U0001F5FF]+", "", t or "")
    words = set(re.findall(r"[a-zA-Z]{3,}", t.lower()))
    stop = {"the", "and", "for", "with", "from", "that", "this", "has", "have",
            "been", "were", "will", "would", "can", "are", "was", "she", "her",
            "his", "you", "your", "its", "after", "when"}
    return words - stop


def check_purity(title):
    """纯度：英文、无 CJK、含 Karen 或 AI。返回违规列表。"""
    v = []
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\U0001F000-\U0001FAFF]", title or ""):
        # 注意：emoji 不算 CJK，这里只查真正的 CJK 字符
        pass
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", title or ""):
        v.append(("purity_cjk", "标题含 CJK 字符（中文/日文/韩文），频道只发英文"))
    low = (title or "").lower()
    if "karen" not in low and re.search(r"\bai\b", low) is None:
        v.append(("purity_no_karen_ai", "标题不含 Karen 或 AI，偏离频道定位"))
    return v


def check_subject(title):
    """主语：报应动词前必须有 Karen；报应对象不能是机器（It）。"""
    v = []
    t_up = (title or "").upper()
    t_low = (title or "").lower()
    first_verb_pos, first_verb = None, None
    for vb in KARMA_VERBS:
        p = t_up.find(vb)
        if p >= 0 and (first_verb_pos is None or p < first_verb_pos):
            first_verb_pos, first_verb = p, vb
    if not first_verb:
        return v
    karen_pos = t_low.find("karen")
    if karen_pos < 0:
        v.append(("subject_no_karen", f"标题含报应动词 {first_verb} 但没有 Karen"))
    elif karen_pos > first_verb_pos:
        v.append(("subject_order", f"Karen 出现在报应动词 {first_verb} 之后，主语错位"))
    after = t_up[first_verb_pos + len(first_verb):first_verb_pos + len(first_verb) + 10]
    if re.search(r"^\s*IT\b", after):
        v.append(("subject_it", f"报应动词 {first_verb} 的对象是 'It'（机器），笑点反了"))
    if re.search(r"\bIT\s+(BROKE|CRASHED|SNAPPED|BROKEN)\b", t_up):
        v.append(("subject_it_broke", "标题主语是 'It'（机器坏了），不是 Karen 受罚"))
    return v


def check_emoji_first(title):
    first = (title or "")[:1]
    if not first or not EMOJI_RE.match(first):
        return [("emoji_position", f"标题首字符不是 emoji（{first!r}），Top10 70% 放开头")]
    return []


def check_metadata(description, tags):
    v = []
    # tags 可能是 list（API 返回）或逗号分隔字符串
    if isinstance(tags, list):
        tag_list = [str(t).strip() for t in tags if str(t).strip()]
    else:
        tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if len((description or "").strip()) < 20:
        v.append(("meta_desc", f"描述太短（{len((description or '').strip())} 字符，要求 ≥20）"))
    if len(tag_list) < 3:
        v.append(("meta_tags", f"标签太少（{len(tag_list)} 个，要求 ≥3）"))
    return v


def check_banned_verb(title):
    v = []
    try:
        with open(f"{DATA}/perpetua/karma_verbs.json", encoding="utf-8") as f:
            kv = json.load(f)
        banned = [x.upper() for x in kv.get("banned", [])]
        t_up = (title or "").upper()
        for bv in banned:
            if bv and bv in t_up:
                v.append(("banned_verb", f"标题含禁用抽象动词 {bv}（clickbait 感，4-5s 留存断崖）"))
    except Exception:
        pass
    return v


def check_duplicate(title, video_id, all_videos, days=90, threshold=0.6):
    """与 90 天内其他视频标题关键词重叠 >60% 判重复。"""
    v = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    new_kw = _keywords(title)
    if not new_kw:
        return v
    for other in all_videos:
        if other.get("id") == video_id:
            continue
        try:
            pub = datetime.fromisoformat(str(other.get("published", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if pub < cutoff:
            continue
        old_kw = _keywords(other.get("title", ""))
        if not old_kw:
            continue
        overlap = len(new_kw & old_kw) / max(len(new_kw), len(old_kw))
        if overlap > threshold:
            v.append(("duplicate",
                      f"与 {pub.strftime('%m-%d')}《{other.get('title','')[:40]}》重叠 {overlap:.0%}（>60%）"))
            break
    return v


def check_spacing(video_id, published_at, all_videos, window_h=1):
    """同一小时内多条发布 = 错峰违规。"""
    v = []
    try:
        me = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    except Exception:
        return v
    siblings = []
    for other in all_videos:
        if other.get("id") == video_id:
            continue
        try:
            pub = datetime.fromisoformat(str(other.get("published", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if abs((me - pub).total_seconds()) < window_h * 3600:
            siblings.append(other)
    if siblings:
        v.append(("spacing",
                  f"前后 1 小时内还有 {len(siblings)} 条发布（{siblings[0].get('title','')[:30]}…），互相抢流量"))
    return v


SEVERITY = {
    "purity_cjk": "severe", "purity_no_karen_ai": "severe",
    "duplicate": "medium", "spacing": "medium",
    "subject_no_karen": "medium", "subject_order": "medium",
    "subject_it": "medium", "subject_it_broke": "medium",
    "banned_verb": "medium",
    "emoji_position": "mild", "meta_desc": "mild", "meta_tags": "mild",
}


def audit_video(video, all_videos):
    """对单条视频跑全套门禁，返回 (violations, max_severity)。"""
    vid = video.get("id", "")
    title = video.get("title", "")
    desc = video.get("description", "")
    tags = video.get("tags", "")
    pub = video.get("published", "")
    violations = []
    violations += check_purity(title)
    violations += check_subject(title)
    violations += check_emoji_first(title)
    violations += check_metadata(desc, tags)
    violations += check_banned_verb(title)
    violations += check_duplicate(title, vid, all_videos)
    violations += check_spacing(vid, pub, all_videos)
    sev_rank = {"mild": 1, "medium": 2, "severe": 3}
    max_sev = "none"
    for code, _ in violations:
        s = SEVERITY.get(code, "mild")
        if sev_rank[s] > sev_rank.get(max_sev, 0):
            max_sev = s
    return violations, max_sev


def fetch_recent_videos(max_n=50):
    """拉取最近 N 条视频的完整 snippet（含精确发布时间、描述、标签）。"""
    from yt import api_call
    r = api_call("GET", "/youtube/v3/channels",
                 params={"part": "contentDetails", "mine": "true"})
    uploads = r["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r2 = api_call("GET", "/youtube/v3/playlistItems",
                  params={"part": "snippet", "playlistId": uploads, "maxResults": max_n})
    vids = [it["snippet"]["resourceId"]["videoId"] for it in r2["items"]]
    if not vids:
        return []
    r3 = api_call("GET", "/youtube/v3/videos",
                  params={"part": "snippet,statistics", "id": ",".join(vids)})
    out = []
    for v in r3["items"]:
        sn = v["snippet"]
        out.append({
            "id": v["id"],
            "title": sn.get("title", ""),
            "description": sn.get("description", ""),
            "tags": sn.get("tags", []),
            "published": sn.get("publishedAt", ""),
            "views": v["statistics"].get("viewCount", "0"),
        })
    return out


def log_audit(entry):
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def pipeline_log(stage, status="ok", detail="", count=0):
    """写 Perpetua 流水线遥测（pipeline_runs.json），失败不阻塞。"""
    import subprocess as _sp
    try:
        _sp.run(["python3", "/home/hatch/data/perpetua/pipeline.py",
                 "default", stage, status, detail[:200], str(count)],
                capture_output=True, timeout=10)
    except Exception:
        pass


def push_inbox_alert(video, violations):
    """严重违规 → inbox 紧急告警（建议用户手动设为私享或删除）。"""
    try:
        inbox = json.load(open(INBOX, encoding="utf-8"))
    except Exception:
        inbox = {}
    vtext = "\n".join(f"- {msg}" for _, msg in violations)
    inbox.setdefault("notices", []).append({
        "type": "bypass_audit_alert",
        "priority": "URGENT",
        "created": datetime.now(timezone.utc).isoformat(),
        "for": "user",
        "read": False,
        "title": f"🚨 绕过门禁发布：{video.get('title','')[:40]}",
        "message": (
            f"视频 https://youtu.be/{video.get('id')} 绕过 MCP 门禁直接发布，"
            f"检出 {len(violations)} 项严重违规：\n{vtext}\n\n"
            "建议：手动设为私享或删除，或按 auto_retitle 流程换标题。"),
        "video_id": video.get("id"),
        "violations": [c for c, _ in violations],
    })
    with open(INBOX, "w", encoding="utf-8") as f:
        json.dump(inbox, f, ensure_ascii=False, indent=2)


def auto_private(video_id, violations):
    """严重违规自动转私享（可恢复）。返回 True/False。"""
    import sys
    sys.path.insert(0, "/home/hatch/data/youtube")
    try:
        from yt_upload import _load, _refresh, _req
        import json as _json
        d = _load()
        try:
            token = d["access_token"]
        except (KeyError, PermissionError):
            token = _refresh(d)
        # 先 GET 现有 status
        url = f"https://www.googleapis.com/youtube/v3/videos?part=status&id={video_id}"
        cur = _json.load(_req(url, token, "GET"))
        items = cur.get("items") or []
        if not items:
            return False
        st = dict(items[0].get("status") or {})
        keep = ("privacyStatus", "selfDeclaredMadeForKids", "license",
                "embeddable", "publicStatsViewable", "containsSyntheticMedia")
        st = {k: v for k, v in st.items() if k in keep}
        st["privacyStatus"] = "private"
        body = {"id": video_id, "status": st}
        url2 = "https://www.googleapis.com/youtube/v3/videos?part=status"
        _json.load(_req(url2, token, "PUT", _json.dumps(body).encode(),
                        {"Content-Type": "application/json; charset=UTF-8"}))
        log_audit({
            "video_id": video_id,
            "action": "auto_private",
            "violations": [c for c, m in violations],
            "audited_at": datetime.now(timezone.utc).isoformat(),
        })
        return True
    except Exception as e:
        print(f"auto_private 失败 {video_id}: {e}")
        return False


def queue_retitle(video, violations):
    """轻微违规 → 加入 auto_retitle 队列。"""
    try:
        awaiting = json.load(open(AWAITING, encoding="utf-8"))
    except Exception:
        awaiting = []
    if not isinstance(awaiting, list):
        awaiting = []
    # 去重：同一视频不重复入队
    for item in awaiting:
        if item.get("video_id") == video.get("id") and item.get("type") == "auto_retitle":
            return False
    awaiting.append({
        "type": "auto_retitle",
        "video_id": video.get("id"),
        "title": video.get("title", ""),
        "reason": "bypass_audit: " + "; ".join(m for _, m in violations),
        "status": "awaiting",
        "created": datetime.now(timezone.utc).isoformat(),
    })
    with open(AWAITING, "w", encoding="utf-8") as f:
        json.dump(awaiting, f, ensure_ascii=False, indent=2)
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    videos = fetch_recent_videos(50)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    recent = []
    for v in videos:
        try:
            pub = datetime.fromisoformat(str(v.get("published", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if pub >= cutoff:
            recent.append(v)

    print(f"扫描近 {args.hours}h 视频：{len(recent)} 条")
    results = []
    for v in recent:
        violations, severity = audit_video(v, videos)
        if not violations:
            continue
        entry = {
            "video_id": v["id"],
            "title": v.get("title", ""),
            "published": v.get("published", ""),
            "views": v.get("views", "0"),
            "violations": [{"code": c, "msg": m} for c, m in violations],
            "severity": severity,
            "audited_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(entry)
        log_audit(entry)

        if args.dry_run:
            continue
        if severity == "severe":
            # 中文标题/严重偏题：自动转私享（可恢复），再告警
            codes = [c for c, m in violations]
            if "purity_cjk" in codes or "purity_offtopic" in codes:
                ok = auto_private(v["id"], violations)
                entry["auto_privated"] = ok
                print(f"  → 自动转私享: {'成功' if ok else '失败'}")
            push_inbox_alert(v, violations)
        elif severity == "mild":
            queue_retitle(v, violations)
        # medium: 只记录日志，复盘时报告

    # 输出报告
    print(f"\n检出违规视频：{len(results)} 条")
    sev_count = {"severe": 0, "medium": 0, "mild": 0}
    for r in results:
        sev_count[r["severity"]] = sev_count.get(r["severity"], 0) + 1
        print(f"\n[{r['severity']}] {r['video_id']} | {r['title'][:60]}")
        for viol in r["violations"]:
            print(f"    - [{viol['code']}] {viol['msg'][:80]}")
    print(f"\n严重: {sev_count['severe']}, 中等: {sev_count['medium']}, 轻微: {sev_count['mild']}")
    if args.dry_run:
        print("(dry-run，未写 inbox/队列)")
    else:
        st = "ok" if sev_count["severe"] == 0 else "error"
        pipeline_log("audit", st,
                     f"扫描{len(recent)}条：严重{sev_count['severe']} 中等{sev_count['medium']} 轻微{sev_count['mild']}",
                     len(results))


if __name__ == "__main__":
    main()
