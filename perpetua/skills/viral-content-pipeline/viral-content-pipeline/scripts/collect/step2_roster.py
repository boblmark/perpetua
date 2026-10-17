"""Step 2 - build a verified roster: followers 100k-5M, active in last 30 days, data reachable."""
import json, sys, time
from collections import defaultdict
sys.path.insert(0, "/home/user/collector")
from bili_lib import Bili

NOW = time.time()
D30 = NOW - 30 * 86400
D90 = NOW - 90 * 86400

EXTRA_KW = ["AI整活", "AI还原 搞笑", "AI翻车", "AI配音 短剧", "搞笑 反转 结局",
            "AI 老年人", "AI宠物 搞笑", "沙雕 反转", "剧情 反转 搞笑", "AI 网红 模仿"]

b = Bili()
mids = {}

# existing candidates
for c in json.load(open("/home/user/collector/candidates.json")):
    mids[c["mid"]] = c
print("seed candidates:", len(mids), flush=True)

# broaden discovery
for kw in EXTRA_KW:
    rows = b.search_videos(kw, page=1)
    for r in rows:
        m = r.get("mid")
        if m and m not in mids:
            mids[m] = {"mid": m, "name": r.get("author"), "fans": None, "hits": 1, "max_play": r.get("play") or 0}
    print(f"  +{kw}: total mids {len(mids)}", flush=True)

# enrich followers where missing
need = [m for m, v in mids.items() if v.get("fans") is None]
print("fetching cards for", len(need), flush=True)
for m in need:
    c = b.card(m)
    if c:
        mids[m]["fans"] = c.get("fans") or 0
        mids[m]["name"] = c.get("name") or mids[m].get("name")

print("\n--- scanning activity for 100k<=fans<=5M ---")
roster = []
CANDS = [(m, v) for m, v in mids.items() if v.get("fans") and 100_000 <= v["fans"] <= 5_000_000]
CANDS.sort(key=lambda kv: -(kv[1].get("max_play") or 0))
print("in-range candidates:", len(CANDS), flush=True)

for m, v in CANDS[:40]:
    arch = []
    for pn in (1, 2):
        a = b.recent_archives(m, pn=pn)
        arch += a
        if len(a) < 10:
            break
    if not arch:
        print(f"  {v['name'][:14]:<16} fans={v['fans']:>9,}  NO-DATA", flush=True)
        continue
    latest = max(x["pubdate"] for x in arch)
    in90 = [x for x in arch if x["pubdate"] >= D90]
    in30 = [x for x in arch if x["pubdate"] >= D30]
    mx = max((x["stat"]["view"] or 0) for x in in90) if in90 else 0
    rec = dict(mid=m, name=v["name"], fans=v["fans"], n=len(arch),
               latest=time.strftime("%Y-%m-%d", time.localtime(latest)),
               n90=len(in90), n30=len(in30), max90=mx)
    roster.append(rec)
    flag = "OK " if (latest >= D30 and len(in90) >= 5) else "no "
    print(f"  {flag}{v['name'][:14]:<16} fans={v['fans']:>9,} n={len(arch):>3} 90d={len(in90):>3} 30d={len(in30):>2} latest={rec['latest']} max90={mx:>10,}", flush=True)

json.dump(roster, open("/home/user/collector/roster_scan.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved roster_scan.json")
