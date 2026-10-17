"""TikTok harvester - real public data via in-browser hashtag feeds.

Method: load public hashtag pages in a real browser, let the page paginate itself,
and capture the JSON that TikTok's own frontend receives (challenge/item_list etc).
Every number (playCount/diggCount/commentCount/shareCount/collectCount/followerCount)
comes straight from those responses - nothing is estimated.
"""
import json, re, sys, time
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TAGS = ["aifunny", "funnyai", "aihumor", "aicomedy", "aivideo", "aigenerated",
        "aimemes", "surrealai", "aicartoon", "aianimation", "aiprank", "aitroll",
        "aislop", "aifails", "aiclips", "aigags", "aijokes", "aiskit",
        "funnyaivideos", "aitrend", "aiviral", "cursedai", "weirdai", "aifunnyvideos"]

OUT = "/home/user/collector/tt_raw.json"
SCROLLS = 22


def main():
    payloads = {}          # urlkey -> body text
    items = {}             # video id -> item dict
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=UA, locale="en-US",
                            viewport={"width": 1400, "height": 950})
        pg = ctx.new_page()

        def on_resp(r):
            u = r.url
            if "/api/" not in u:
                return
            if not any(k in u for k in ["challenge/item_list", "recommend/item_list",
                                        "prefetch/explore/item_list", "post/item_list",
                                        "related/item_list"]):
                return
            try:
                t = r.text()
            except Exception:
                return
            if not t or '"itemList"' not in t:
                return
            ch = (re.search(r"challengeID=(\d+)", u) or re.search(r"challengeName=([^&]+)", u))
            cur = re.search(r"cursor=(\d+)", u)
            key = u.split("?")[0] + "|" + (ch.group(1) if ch else "x") + "|" + (cur.group(1) if cur else "0")
            if key in payloads:
                return
            payloads[key] = t
            try:
                d = json.loads(t)
            except Exception:
                return
            for it in (d.get("itemList") or []):
                vid = it.get("id")
                if vid and vid not in items:
                    items[vid] = it

        pg.on("response", on_resp)

        for tag in TAGS:
            url = f"https://www.tiktok.com/tag/{tag}"
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=50000)
                pg.wait_for_timeout(5500)
                for i in range(SCROLLS):
                    pg.mouse.wheel(0, 2800)
                    pg.wait_for_timeout(2100)
                print(f"[{tag}] payloads={len(payloads)} unique_videos={len(items)}", flush=True)
            except Exception as e:
                print(f"[{tag}] ERR {type(e).__name__} {e}", flush=True)
                continue
            # checkpoint
            json.dump({"payloads": payloads, "items": items}, open(OUT, "w"), ensure_ascii=False)
            time.sleep(1.5)
        b.close()
    json.dump({"payloads": payloads, "items": items}, open(OUT, "w"), ensure_ascii=False)
    print(f"\nDONE payloads={len(payloads)} unique_videos={len(items)} -> {OUT}")


main()
