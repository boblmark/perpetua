import json,re
from playwright.sync_api import sync_playwright
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
ks=json.load(open("ks_rows.json"))["rows"]
dy=json.load(open("dy_rows.json"))["rows"]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
    ctx=b.new_context(user_agent=UA,locale="zh-CN",viewport={"width":1400,"height":950})
    print("=== 快手：定向打开存储的视频页，解析文档响应 ===")
    for r in ks[:3]:
        pid=r["video_url"].split("/")[-1]
        docs={}
        pg=ctx.new_page()
        pg.on("response",lambda rr: docs.update({rr.url:rr.text()}) if rr.request.resource_type=="document" else None)
        try:
            pg.goto(r["video_url"],wait_until="domcontentloaded",timeout=45000); pg.wait_for_timeout(7000)
        except Exception as e: pass
        txt="".join(docs.values())
        live=re.findall(r'"viewCount":\s*"?([\d\.]+万?)',txt)[:3]
        lk=re.findall(r'"realLikeCount":\s*(\d+)',txt)[:3]
        print(f"  {pid}: 存储 views={r['views']:,} likes={r['likes']:,} | 实时文档 viewCount={live} realLikeCount={lk}")
        pg.close()
    print("\n=== 抖音：定向打开存储的视频页，抓所有响应 ===")
    for r in dy[:3]:
        aid=r["video_url"].split("/")[-1]
        hits=[]
        pg2=ctx.new_page()
        def on(rr):
            try:
                t=rr.text()
                if '"digg_count"' in t:
                    seg=t[:100000]
                    v=re.findall(r'"digg_count":\s*(\d+)',seg)[:3]
                    hits.append((rr.url.split("?")[0][-46:], v))
            except Exception: pass
        pg2.on("response",on)
        try:
            pg2.goto(r["video_url"],wait_until="domcontentloaded",timeout=45000); pg2.wait_for_timeout(8000)
        except Exception: pass
        print(f"  {aid}: 存储 likes={r['likes']:,} | 实时命中 {hits[:2]}")
        pg2.close()
    b.close()
