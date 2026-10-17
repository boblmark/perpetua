"""抖音采集：滚动公开发现页，捕获其自身 feed 接口返回的真实视频数据。
views 抖音网页端不公开（play_count 恒为 0）→ 记 N/A；likes/comments/shares/collects 为真实值。
"""
import json,re,time
from playwright.sync_api import sync_playwright
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
KW=re.compile(r"AI|ai生成|AIGC|人工智能|搞笑|反转|沙雕|整活|段子|神剧情|离谱|抽象|恶搞|打工人|职场")
items={}
caps=0
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
    ctx=b.new_context(user_agent=UA,locale="zh-CN",viewport={"width":1400,"height":950})
    pg=ctx.new_page()
    def on(r):
        global caps
        if "douyin.com/aweme" not in r.url: return
        if not any(k in r.url for k in ["module/feed","channel/hotspot","hot/search"]): return
        try: t=r.text()
        except Exception: return
        if '"aweme_list"' not in t: return
        caps+=1
        try: d=json.loads(t)
        except Exception: return
        for it in (d.get("aweme_list") or []):
            aid=it.get("aweme_id")
            if aid: items.setdefault(aid,it)
    pg.on("response",on)
    for url,scrolls in [("https://www.douyin.com/discover",22),("https://www.douyin.com/hot",10),
                        ("https://www.douyin.com/channel/300203",10)]:
        try:
            pg.goto(url,wait_until="domcontentloaded",timeout=50000)
            pg.wait_for_timeout(8000)
            for i in range(scrolls):
                pg.mouse.wheel(0,2600); pg.wait_for_timeout(1800)
            print(f"[{url.split('/')[-1]}] caps={caps} items={len(items)}",flush=True)
        except Exception as e:
            print(f"[{url[:40]}] ERR {type(e).__name__}",flush=True)
        json.dump({"items":items},open("dy_raw.json","w"),ensure_ascii=False)
    b.close()
json.dump({"items":items},open("dy_raw.json","w"),ensure_ascii=False)
hit=sum(1 for it in items.values() if KW.search((it.get("desc") or "")+" "+json.dumps(it.get("text_extra") or [],ensure_ascii=False)))
print(f"\nDONE items={len(items)} | AI/搞笑相关={hit} | caps={caps} -> dy_raw.json")
