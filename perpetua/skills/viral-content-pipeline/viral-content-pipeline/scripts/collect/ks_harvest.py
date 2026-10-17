"""快手采集：滚动公开精选页/热榜，捕获其自身 graphql 与 rest 返回的真实视频数据。
viewCount / realLikeCount / collectCount 均为真实值。"""
import json,re
from playwright.sync_api import sync_playwright
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
photos={}
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
    ctx=b.new_context(user_agent=UA,locale="zh-CN",viewport={"width":1400,"height":950})
    pg=ctx.new_page()
    def harvest(o):
        if isinstance(o,dict):
            if "photo" in o and isinstance(o["photo"],dict) and o["photo"].get("id"):
                ph=o["photo"]; au=o.get("author") or {}
                photos[ph["id"]]={"photo":ph,"author":au}
            for v in o.values(): harvest(v)
        elif isinstance(o,list):
            for v in o: harvest(v)
    def on(r):
        if not any(k in r.url for k in ["graphql","/rest/"]): return
        try: t=r.text()
        except Exception: return
        if '"viewCount"' not in t and '"photoId"' not in t: return
        try: d=json.loads(t)
        except Exception: return
        harvest(d)
    pg.on("response",on)
    for url,scrolls in [("https://www.kuaishou.com/brilliant",26),("https://www.kuaishou.com/",10)]:
        try:
            pg.goto(url,wait_until="domcontentloaded",timeout=45000); pg.wait_for_timeout(7000)
            for _ in range(scrolls):
                pg.mouse.wheel(0,2600); pg.wait_for_timeout(1600)
            print(f"[{url}] photos={len(photos)}",flush=True)
        except Exception as e: print(f"[{url[:36]}] ERR {type(e).__name__}",flush=True)
        json.dump(photos,open("ks_raw.json","w"),ensure_ascii=False)
    b.close()
json.dump(photos,open("ks_raw.json","w"),ensure_ascii=False)
KW=re.compile(r"AI|ai|人工智能|搞笑|反转|沙雕|整活|段子|离谱|抽象|恶搞|短剧|剧情|打工人|职场|机器人|数字人|变声|配音")
hit=sum(1 for v in photos.values() if KW.search(v["photo"].get("caption") or ""))
print(f"\nDONE photos={len(photos)} | AI/搞笑相关={hit} -> ks_raw.json")
