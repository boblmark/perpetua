"""Step 8 - targeted second pass.

Technique: accounts in the pool tend to reuse a branded/consistent hashtag. Harvesting
those specific hashtags surfaces many more videos *of that account*, which is the only
logged-out route to per-account depth on TikTok. Result feeds per-account sampling.
"""
import json, re, sys, time
from collections import Counter, defaultdict
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
RAW = "/home/user/collector/tt_raw.json"
OUT = "/home/user/collector/tt_raw2.json"

d = json.load(open(RAW))
items = d["items"]
print("pool:", len(items))

# per-account hashtag frequency + mid-tier filter
by_acct = defaultdict(list)
for it in items.values():
    au = it.get("author") or {}
    ast = it.get("authorStats") or {}
    if au.get("uniqueId"):
        by_acct[au["uniqueId"]].append(it)

mid = {k: v for k, v in by_acct.items()
       if v and 100_000 <= (v[0].get("authorStats", {}).get("followerCount") or 0) <= 5_000_000}
print("mid-tier accounts in pool:", len(mid))

generic = {"fyp", "foryou", "foryoupage", "viral", "funny", "funnyvideos", "ai", "aivideo",
           "aiart", "trending", "tiktok", "shorts", "comedy", "meme", "memes", "aifunny",
           "creatorsearchinsights", "fypシ", "reels", "video"}
target_tags = {}
for acct, vids in sorted(mid.items(), key=lambda kv: -len(kv[1]))[:22]:
    tags = Counter()
    for it in vids:
        for te in (it.get("textExtra") or []):
            t = (te.get("hashtagName") or "").lower()
            if t and t not in generic and len(t) > 4:
                tags[t] += 1
    if len(vids) >= 2 and tags:
        tag, n = tags.most_common(1)[0]
        if n >= 2 or len(vids) >= 3:
            target_tags[tag] = acct
print(f"targeted hashtags derived: {len(target_tags)}")
for t, a in list(target_tags.items())[:25]:
    print(f"   #{t:<26} <- @{a}")

payloads, items2 = {}, dict(items)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1400, "height": 950})
    pg = ctx.new_page()

    def on_resp(r):
        u = r.url
        if "/api/" not in u or not any(k in u for k in ["challenge/item_list", "post/item_list", "recommend/item_list"]):
            return
        try:
            t = r.text()
        except Exception:
            return
        if not t or '"itemList"' not in t:
            return
        ch = (re.search(r"challengeID=(\d+)", u) or re.search(r"challengeName=([^&]+)", u) or re.search(r"secUid=([^&]+)", u))
        cur = re.search(r"cursor=(\d+)", u)
        key = u.split("?")[0] + "|" + (ch.group(1) if ch else "x") + "|" + (cur.group(1) if cur else "0")
        if key in payloads:
            return
        payloads[key] = t
        try:
            dd = json.loads(t)
        except Exception:
            return
        for it in (dd.get("itemList") or []):
            if it.get("id"):
                items2.setdefault(it["id"], it)

    pg.on("response", on_resp)
    for tag, acct in target_tags.items():
        try:
            pg.goto(f"https://www.tiktok.com/tag/{tag}", wait_until="domcontentloaded", timeout=50000)
            pg.wait_for_timeout(5500)
            for _ in range(14):
                pg.mouse.wheel(0, 2800); pg.wait_for_timeout(2100)
            mine = sum(1 for it in items2.values() if (it.get("author") or {}).get("uniqueId") == acct)
            print(f"[#{tag}] items_total={len(items2)} @{acct}_videos={mine}", flush=True)
        except Exception as e:
            print(f"[#{tag}] ERR {type(e).__name__}", flush=True)
        json.dump({"payloads": payloads, "items": items2}, open(OUT, "w"), ensure_ascii=False)
        time.sleep(1.2)
    b.close()

json.dump({"payloads": payloads, "items": items2}, open(OUT, "w"), ensure_ascii=False)
print(f"\nDONE pool={len(items2)} -> {OUT}")
