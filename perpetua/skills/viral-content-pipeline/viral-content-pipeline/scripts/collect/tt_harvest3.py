"""Third pass: harvest '#<username>' variants for mid-tier AI/funny accounts,
the most reliable logged-out route to per-account depth."""
import json, re, time
from collections import defaultdict
from playwright.sync_api import sync_playwright
UA=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
items={}
for p in ["tt_raw.json","tt_raw2.json"]:
    for k,v in (json.load(open(p)).get("items") or {}).items(): items.setdefault(k,v)
print("seed pool:",len(items))

# candidate accounts: mid-tier, has AI-ish content
by=defaultdict(list)
for it in items.values():
    au=it.get("author") or {}; ast=it.get("authorStats") or {}; st=it.get("stats") or {}
    if not st.get("playCount") or not ast.get("followerCount"): continue
    by[au.get("uniqueId")].append(it)
cand=[]
for k,v in by.items():
    if not k or not v: continue
    f=(v[0].get("authorStats") or {}).get("followerCount") or 0
    if not (100_000<=f<=5_000_000): continue
    txt=" ".join(((it.get("desc") or "")+" "+" ".join(t.get("hashtagName","") for t in (it.get("textExtra") or []))).lower() for it in v)
    if re.search(r"\bai\b|aigc|ai[-_ ]?(generated|art|video|funny|humor|cat|dog|prank)",txt):
        cand.append((k,f,len(v)))
cand.sort(key=lambda x:-x[2])
print("candidate accounts:",len(cand))

def variants(u):
    base=re.sub(r"[^0-9a-zA-Z]","",u)
    out=[u, base]
    out.append(re.sub(r"\d+$","",base))
    return [t for t in dict.fromkeys(x for x in out if len(x)>4)]

plan=[]
for u,f,n in cand[:26]:
    for t in variants(u)[:2]:
        plan.append((t,u))
print("tags to try:",len(plan))

payloads={}; added=0
with sync_playwright() as p:
    b=p.chromium.launch(args=["--no-sandbox","--disable-blink-features=AutomationControlled"])
    ctx=b.new_context(user_agent=UA,locale="en-US",viewport={"width":1400,"height":950})
    pg=ctx.new_page()
    def on_resp(r):
        u=r.url
        if "/api/" not in u or not any(k in u for k in ["challenge/item_list","recommend/item_list","post/item_list"]): return
        try: t=r.text()
        except Exception: return
        if not t or '"itemList"' not in t: return
        ch=(re.search(r"challengeID=(\d+)",u) or re.search(r"challengeName=([^&]+)",u))
        cur=re.search(r"cursor=(\d+)",u)
        key=u.split("?")[0]+"|"+(ch.group(1) if ch else "x")+"|"+(cur.group(1) if cur else "0")
        if key in payloads: return
        payloads[key]=t
        try: dd=json.loads(t)
        except Exception: return
        for it in (dd.get("itemList") or []):
            if it.get("id") and it["id"] not in items:
                items[it["id"]]=it
                nonlocal_add[0]+=1
    nonlocal_add=[0]
    pg.on("response",on_resp)
    counts=defaultdict(int)
    for tag,acct in plan:
        try:
            pg.goto(f"https://www.tiktok.com/tag/{tag}",wait_until="domcontentloaded",timeout=45000)
            pg.wait_for_timeout(5000)
            for _ in range(10):
                pg.mouse.wheel(0,2800); pg.wait_for_timeout(2000)
            n=sum(1 for it in items.values() if (it.get("author") or {}).get("uniqueId")==acct)
            counts[acct]=max(counts[acct],n)
            print(f"[#{tag}] @{acct}: {n} videos in pool", flush=True)
        except Exception as e:
            print(f"[#{tag}] ERR {type(e).__name__}", flush=True)
        json.dump({"payloads":payloads,"items":items},open("tt_raw3.json","w"),ensure_ascii=False)
        time.sleep(1)
    b.close()
json.dump({"payloads":payloads,"items":items},open("tt_raw3.json","w"),ensure_ascii=False)
print(f"\nDONE pool={len(items)} (+{nonlocal_add[0]} new)")
print("per-account counts:",sorted(counts.items(),key=lambda x:-x[1])[:12])
