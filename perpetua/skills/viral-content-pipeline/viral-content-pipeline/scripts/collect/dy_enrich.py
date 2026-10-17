"""抖音作者粉丝数补全。

feed 接口里 author.follower_count 被打码为 0，但账号主页会调用
/aweme/v1/web/user/profile/other/ 返回真实 follower_count。
本脚本在真实浏览器里逐个作者主页拦截该接口，取真实粉丝数。
"""
import json
import os

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
OUT = "/home/user/collector/dy_followers.json"

targets = json.load(open("/home/user/collector/dy_targets.json"))
print("targets:", len(targets))

followers = json.load(open(OUT)) if os.path.exists(OUT) else {}
todo = [(s, n) for s, n in targets if s and s not in followers]
print("to fetch:", len(todo))

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA, locale="zh-CN", viewport={"width": 1400, "height": 950})
    pg = ctx.new_page()
    got = {}

    def on(r):
        if "user/profile/other" in r.url:
            try:
                d = json.loads(r.text())
            except Exception:
                return
            u = d.get("user") or {}
            if u.get("sec_uid") and u.get("follower_count"):
                got[u["sec_uid"]] = {"followers": u.get("follower_count"),
                                     "nickname": u.get("nickname"),
                                     "aweme_count": u.get("aweme_count"),
                                     "total_favorited": u.get("total_favorited"),
                                     "unique_id": u.get("unique_id") or u.get("short_id")}

    pg.on("response", on)
    for i, (sec, name) in enumerate(todo):
        got.clear()
        try:
            pg.goto(f"https://www.douyin.com/user/{sec}", wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)
        except Exception:
            pass
        if got:
            for k, v in got.items():
                followers[k] = v
            print(f"  [{i+1}/{len(todo)}] {name[:14]:<16} followers={list(got.values())[0]['followers']:,}", flush=True)
        else:
            print(f"  [{i+1}/{len(todo)}] {name[:14]:<16} NOT-FOUND", flush=True)
        json.dump(followers, open(OUT, "w"), ensure_ascii=False, indent=1)
    b.close()
print("saved", len(followers), "->", OUT)
