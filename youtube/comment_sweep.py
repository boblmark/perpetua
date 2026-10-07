#!/usr/bin/env python3
"""评论自动回复扫荡：每30分钟扫一次全频道未回复评论并自动回。
走 relay 旁路（标准库 urllib + relay.urlopen）。
去重：用已回复状态（totalReplyCount>0）+ 本地已回 ID 文件双保险。
"""
import sys, json, random, urllib.request, urllib.parse, os
sys.path.insert(0, "/home/hatch/data")
from relay import urlopen as r_open

OAUTH_FILE = "/home/hatch/data/youtube/.oauth.json"
CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"
DONE_FILE = "/home/hatch/data/youtube/comment_reply_done.json"
SELF_AUTHOR = "@KarenVsAI"  # 频道自己的引导评论不回复

# 2026-10-07 升级：从"礼貌回复"改成"引发讨论"话术
# 目标：每条回复都要让人想再回一条，带动评论区热度
REPLY_TEMPLATES = [
    # 站队型：制造 Team Karen vs Team AI 对立
    "Team Karen or Team AI? 👀 Be honest, whose side are you REALLY on?",
    "Karen walked in SO confident... and left SO humbled 😭 Who else saw that coming?",
    # 提问型：让观众分享自己的经历
    "Has this EVER happened to you?? 🤣 Tell us your story below!",
    "What would YOU have done in Karen's shoes? 👟 Wrong answers only!",
    # 悬念型：预告下期，留钩子
    "Wait till you see what the AI does NEXT week... 👀🔥 Any guesses?",
    "This was just the warm-up 😏 The AI has something BIGGER planned...",
    # 共鸣型：强化"即时报应"的爽感
    "The INSTANT karma in this one though!! ⚡️ Replay it, I dare you!",
    "POV: You try to scam the AI and the AI says 'nah' 🤖💅",
    # 互动型：直接要行动
    "Drop a 🔥 if Karen 100% deserved this! Let's see how many we get!",
    "Tag someone who acts like Karen 😂👇 (we all know one)",
]

def _load_oauth():
    return json.load(open(OAUTH_FILE))

def _refresh(d):
    data = urllib.parse.urlencode({
        'client_id': d['client_id'], 'client_secret': d['client_secret'],
        'refresh_token': d['refresh_token'], 'grant_type': 'refresh_token'}).encode()
    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data)
    resp = json.load(r_open(req, timeout=20))
    d['token'] = resp['access_token']
    json.dump(d, open(OAUTH_FILE, 'w'))
    os.chmod(OAUTH_FILE, 0o600)
    return d['token']

def _api(method, path, token, data=None, params=None):
    url = "https://www.googleapis.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        return json.load(r_open(req, timeout=30))
    except Exception as e:
        msg = str(e)
        if "401" in msg:
            raise PermissionError("expired")
        raise RuntimeError(msg[:200])

def _call(fn, *args):
    d = _load_oauth()
    try:
        return fn(d["token"], *args)
    except PermissionError:
        return fn(_refresh(d), *args)

def get_unreplied(max_n=20):
    def do(tok):
        return _api("GET", "/youtube/v3/commentThreads", tok, params={
            "part": "snippet", "allThreadsRelatedToChannelId": CHANNEL_ID,
            "maxResults": max_n, "order": "time", "textFormat": "plainText"})
    r = _call(do)
    out = []
    for item in r.get("items", []):
        c = item["snippet"]["topLevelComment"]
        sn = c["snippet"]
        if item["snippet"].get("totalReplyCount", 0) > 0:
            continue  # 已有回复
        if sn.get("authorDisplayName") == SELF_AUTHOR:
            continue  # 跳过频道自己的引导评论
        out.append({"id": c["id"], "author": sn.get("authorDisplayName", "?"),
                    "text": sn.get("textDisplay", "")[:80]})
    return out

def do_reply(comment_id, text):
    def fn(tok):
        return _api("POST", "/youtube/v3/comments", tok, {
            "snippet": {"parentId": comment_id, "textOriginal": text}},
            {"part": "snippet"})
    return _call(fn)

def main():
    try:
        done = set(json.load(open(DONE_FILE)) if os.path.exists(DONE_FILE) else [])
    except Exception:
        done = set()
    comments = get_unreplied(20)
    replied, skipped = [], []
    for c in comments:
        if c["id"] in done:
            skipped.append(c["id"])
            continue
        try:
            do_reply(c["id"], random.choice(REPLY_TEMPLATES))
            done.add(c["id"])
            replied.append({"author": c["author"], "text": c["text"]})
        except Exception as e:
            skipped.append(c["id"] + ":" + str(e)[:60])
    try:
        json.dump(sorted(done)[-500:], open(DONE_FILE, "w"))  # 只保留最近500
    except Exception:
        pass
    print(json.dumps({"replied": len(replied), "skipped": len(skipped),
                      "details": replied[:5]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
