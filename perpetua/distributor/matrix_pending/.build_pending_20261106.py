#!/usr/bin/env python3
"""Build matrix_pending JSONs for 2026-11-06 10:24 run from browser-task session logs.
Extracts the ```json blocks the browser tasks returned (verbatim, no retyping),
normalizes field names to the merge format, writes matrix_pending/<platform>.json.
Stale platforms (kuaishou/shipinhao/facebook) get {"status":"stale",...}."""
import json, os, re, glob

BASE = "/home/hatch/data/perpetua/distributor"
PEND = os.path.join(BASE, "matrix_pending")
AGENTS = "/home/hatch/agents"

TASKS = {
    "douyin": "agent-a5fb25f4-f139-44a6-917e-6d7ac094ac0a",
    "xiaohongshu": "agent-49a7fd72-2ea3-43d0-b392-b93eda5b5423",
    "bilibili": "agent-708acf5e-086c-4da3-9692-8ebb31b8df7b",
    "tiktok": "agent-6db3fc03-6c5d-4068-a503-898ea598335e",
    "x": "agent-88d90e3c-d7bb-4e20-88ed-2771eb6b4cb0",
}
STALE = ["kuaishou", "shipinhao", "facebook"]

def extract_json(agent_id):
    pat = os.path.join(AGENTS, agent_id, "sessions",
                       agent_id.removeprefix("agent-") + ".jsonl")
    blocks = []
    with open(pat, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            it = d.get("item") or {}
            if it.get("type") == "message" and it.get("role") == "assistant":
                text = it.get("text") or ""
                for m in re.finditer(r"```json\s*(.*?)\s*```", text, re.S):
                    blocks.append(m.group(1))
    if not blocks:
        raise SystemExit(f"no json block in {agent_id}")
    return json.loads(blocks[-1])

def norm_videos(raw):
    out = []
    for v in raw or []:
        out.append({
            "title": v.get("title"),
            "url": v.get("url"),
            "cover": v.get("cover") or v.get("cover_url") or v.get("cover_image_url"),
            "views": v.get("views", v.get("plays", v.get("play_count"))),
            "likes": v.get("likes", v.get("like_count")),
            "published_at": v.get("published_at"),
            "pinned": bool(v.get("pinned")),
        })
    return out

def norm_comments(raw, videos):
    title_by_url = {v["url"]: v["title"] for v in videos}
    out = []
    for c in raw or []:
        if "text" not in c:
            continue  # pseudo-entry like {"post_url":..., "comments_found": 0}
        url = c.get("video_url") or c.get("post_url") or ""
        cid = c.get("comment_id")
        if not cid:
            cu = c.get("comment_url") or ""
            m = re.search(r"/status/(\d+)", cu)
            cid = m.group(1) if m else None
        out.append({
            "comment_id": cid,
            "video_title": c.get("video_title") or title_by_url.get(url, ""),
            "video_url": url,
            "author": c.get("author"),
            "text": (c.get("text") or "")[:300],
            "likes": c.get("likes"),
            "published_at": c.get("published_at"),
            "replied": bool(c.get("replied", False)),
        })
    return out

def main():
    for key, agent_id in TASKS.items():
        raw = extract_json(agent_id)
        ch = raw.get("channel")
        if isinstance(ch, dict):
            ch = ch.get("name")
        videos = norm_videos(raw.get("videos"))
        payload = {
            "channel": ch,
            "profile_url": raw.get("profile_url"),
            "avatar": raw.get("avatar"),
            "cover": raw.get("cover"),
            "description": raw.get("description"),
            "videos": videos,
            "comments": norm_comments(raw.get("comments"), videos),
        }
        path = os.path.join(PEND, key + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"{key}: channel={ch!r} videos={len(videos)} "
              f"(pinned={sum(1 for v in videos if v['pinned'])}) "
              f"comments={len(payload['comments'])} avatar={'Y' if payload['avatar'] else 'null'} "
              f"cover={'Y' if payload['cover'] else 'null'}")
    for key in STALE:
        path = os.path.join(PEND, key + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"status": "stale", "videos": [], "comments": []}, f)
        print(f"{key}: stale payload written")

if __name__ == "__main__":
    main()
