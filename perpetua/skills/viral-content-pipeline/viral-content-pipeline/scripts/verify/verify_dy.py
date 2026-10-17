import json,re
from playwright.sync_api import sync_playwright
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
dy=json.load(open("dy_rows.json"))["rows"]
targets=[r for r in dy if r.get("account_secuid")][:3]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
    ctx=b.new_context(user_agent=UA,locale="zh-CN",viewport={"width":1400,"height":950})
    for r in targets:
        found={}
        pg=ctx.new_page()
        def on(rr):
            try:
                t=rr.text()
            except Exception: return
            if '"aweme_list"' not in t and '"aweme_id"' not in t: return
            for m in re.finditer(r'"aweme_id":"(\d{15,25})"',t):
                aid=m.group(1); seg=t[m.start():m.start()+4000]
                d=re.search(r'"digg_count":\s*(\d+)',seg)
                if d: found.setdefault(aid,int(d.group(1)))
        pg.on("response",on)
        try:
            pg.goto(f"https://www.douyin.com/user/{r['account_secuid']}",wait_until="domcontentloaded",timeout=45000)
            pg.wait_for_timeout(8000)
            for _ in range(3): pg.mouse.wheel(0,2600); pg.wait_for_timeout(2000)
        except Exception: pass
        aid=r["video_url"].split("/")[-1]
        hit=found.get(aid)
        print(f"  {r['account_name'][:12]:<14} 存储 likes={r['likes']:,} | 主页抓到 {len(found)} 条作品 | 目标视频实时点赞={hit if hit else '未出现在本次抓取'}")
        if hit:
            print(f"      >>> {'完全一致' if hit==r['likes'] else '差异 '+str(hit-r['likes'])}")
        pg.close()
    b.close()
