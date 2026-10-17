"""Step 1 - discover candidate accounts (AI / 搞笑 / 反转 niches) on Bilibili."""
import json
import sys
import time
from collections import defaultdict

sys.path.insert(0, "/home/user/collector")
from bili_lib import Bili

KEYWORDS = ["AI搞笑", "AI短剧", "AI恶搞", "反转剧情", "搞笑短剧", "AI影视",
            "沙雕动画", "AI动画", "反转搞笑", "AI配音搞笑", "AI生成 搞笑", "搞笑反转"]

b = Bili()
agg = defaultdict(lambda: {"name": None, "hits": 0, "views": [], "titles": []})

for kw in KEYWORDS:
    for page in (1, 2):
        rows = b.search_videos(kw, page=page)
        for r in rows:
            mid = r.get("mid")
            if not mid:
                continue
            a = agg[mid]
            a["name"] = r.get("author")
            a["hits"] += 1
            try:
                a["views"].append(int(r.get("play") or 0))
            except Exception:
                pass
            if len(a["titles"]) < 3:
                a["titles"].append((r.get("title") or "").replace(
                    '<em class="keyword">', "").replace("</em>", "")[:40])
        print(f"  {kw} p{page}: {len(rows)} rows", flush=True)

print(f"\ncandidate mids: {len(agg)}")
ranked = sorted(agg.items(), key=lambda kv: -kv[1]["hits"])
out = []
for mid, a in ranked[:70]:
    c = b.card(mid)
    if not c:
        continue
    fans = c.get("fans") or 0
    rec = dict(mid=mid, name=c["name"], fans=fans, hits=a["hits"],
               max_play=max(a["views"]) if a["views"] else 0, sign=c["sign"])
    out.append(rec)
    print(f"{mid:>18} {c['name'][:16]:<18} fans={fans:>9,} hits={a['hits']:>2} maxplay={rec['max_play']:>9,} | {c['sign'][:34]}", flush=True)

json.dump(out, open("/home/user/collector/candidates.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved", len(out))
