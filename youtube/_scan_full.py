#!/usr/bin/env python3
"""完整版频道状态扫描（含 unlisted/private 明细 + IP 标注 + 信誉信号）。
基于 skill 里的 scan_channel_status.py 逻辑，适配本机路径。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, "/home/hatch/data/youtube")

TOK = json.load(open("/home/hatch/data/youtube/.oauth.json"))["token"]
API = "https://www.googleapis.com/youtube/v3/videos"
OUT = "/home/hatch/data/youtube/CHANNEL_STATUS_SCAN.json"

IP_WORDS = [
    "magneto", "marvel", "dc comics", "batman", "superman", "spider-man", "spiderman",
    "iron man", "thor", "hulk", "avengers", "x-men", "xmen", "deadpool", "wolverine",
    "joker", "wonder woman", "thanos", "loki",
    "disney", "pixar", "elsa", "frozen", "cinderella", "ariel", "simba", "lion king",
    "mickey", "minions", "shrek",
    "star wars", "jedi", "sith", "darth", "pokemon", "pikachu", "mario", "luigi",
    "sonic", "minecraft", "fortnite", "roblox", "harry potter", "hogwarts",
    "godzilla", "king kong", "transformers", "optimus", "bumblebee", "barbie",
    "hello kitty", "snoopy", "peanuts", "nintendo", "zelda", "kirby",
    "captain hook", "peter pan", "mumm-ra", "mummra", "vlad mourdain",
    "goku", "naruto", "one piece", "demon slayer",
]
TEST_PATTERNS = [
    (re.compile(r"stodownload", re.I), "stodownload"),
    (re.compile(r"\bE2E\b.*(Asset|Publish|Feedback)", re.I), "E2E test"),
    (re.compile(r"geminigen\s+PLAN\s+\d+", re.I), "pipeline plan probe"),
    (re.compile(r"WB\s+Verify\s+Probe", re.I), "verify probe"),
    (re.compile(r"\b(test|probe|smoke|dummy|lorem)[-_ ]?\d{3,}\b", re.I), "numbered test"),
]
INTERNAL = ["protocolguardian", "yppcompliance", "digitalforensics", "jev",
            "perpetua", "mcp", "hatch", "virality", "score_v2"]


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOK})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2 + i * 2)
    raise last


allv = json.load(open("/home/hatch/data/youtube/all_videos.json"))
ids = [v["id"] for v in allv if v.get("id")]
meta = {v["id"]: v for v in allv}
print("total ids =", len(ids))

found = {}
for i in range(0, len(ids), 50):
    chunk = ids[i:i + 50]
    url = API + "?" + urllib.parse.urlencode(
        {"part": "status,snippet,contentDetails", "id": ",".join(chunk)})
    try:
        r = get(url)
        for x in r.get("items", []):
            found[x["id"]] = x
    except Exception as e:
        print("  ERR:", str(e)[:100])
    print("  ...%d/%d found=%d" % (min(i + 50, len(ids)), len(ids), len(found)))

buckets = {"public": [], "unlisted": [], "private": [], "missing": []}
for vid in ids:
    x = found.get(vid)
    m = meta.get(vid, {})
    if not x:
        buckets["missing"].append((vid, m, None))
    else:
        p = (x.get("status") or {}).get("privacyStatus") or "other"
        buckets.setdefault(p, buckets["public"]).append((vid, m, x))

iprx = re.compile("|".join(re.escape(w) for w in IP_WORDS), re.I)
intrx = re.compile("|".join(re.escape(w) for w in INTERNAL), re.I)


def annotate(rows):
    out = []
    for vid, m, x in rows:
        blob = (m.get("title") or "")
        if x:
            blob += " " + (x.get("snippet") or {}).get("title", "")
        blob += " " + " ".join(m.get("tags") or [])
        if x:
            blob += " " + " ".join((x.get("snippet") or {}).get("tags") or [])
        out.append({
            "id": vid,
            "title": (m.get("title") or "")[:70],
            "published": (m.get("published") or "")[:10],
            "views": m.get("views"),
            "duration": m.get("duration"),
            "ip_hits": sorted(set(w.lower() for w in iprx.findall(blob))),
            "internal_hits": sorted(set(w.lower() for w in intrx.findall(blob))),
        })
    return out


def test_hits(rows):
    out = []
    for vid, m, x in rows:
        t = m.get("title") or ""
        for rx, label in TEST_PATTERNS:
            if rx.search(t):
                out.append({"id": vid, "pattern": label, "title": t[:70]})
                break
    return out


rep = []
mc = Counter((m.get("published") or "")[:7] for _, m, _ in buckets["unlisted"])
for k, v in sorted(mc.items()):
    if v >= 10:
        rep.append("单月 %s 有 %d 条转 unlisted（疑似平台 spam 判定后降级）" % (k, v))
short_unl = [m for _, m, _ in buckets["unlisted"]
             if (m.get("duration") or "").startswith(
                 ("PT4S", "PT5S", "PT8S", "PT9S", "PT11S", "PT16S"))]
if len(short_unl) >= 10:
    rep.append("%d 条 unlisted 是 4-16 秒短内容，标题模式高度雷同（批量低质特征）"
               % len(short_unl))

out = {
    "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "total": len(ids),
    "counts": {k: len(v) for k, v in buckets.items()},
    "missing": annotate(buckets["missing"]),
    "unlisted": annotate(buckets["unlisted"]),
    "private": annotate(buckets["private"]),
    "unlisted_by_month": dict(sorted(mc.items())),
    "ip_hits_public": [x for x in annotate(buckets["public"]) if x["ip_hits"]],
    "internal_leak_public": [x for x in annotate(buckets["public"]) if x["internal_hits"]],
    "internal_leak_unlisted": [x for x in annotate(buckets["unlisted"]) if x["internal_hits"]],
    "test_artifact_hits": (test_hits(buckets["missing"]) + test_hits(buckets["unlisted"])
                           + test_hits(buckets["public"])),
    "reputation_flags": rep,
}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print()
print("=" * 72)
for k, v in out["counts"].items():
    print("  %-12s %d" % (k, v))
print("  IP 命中(public)      %d" % len(out["ip_hits_public"]))
print("  内部术语泄露(public) %d" % len(out["internal_leak_public"]))
print("  测试产物命中         %d" % len(out["test_artifact_hits"]))
print("  信誉信号             %d" % len(rep))
for f in rep:
    print("    -", f)
print()
print("已落盘:", OUT)
