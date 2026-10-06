#!/usr/bin/env python3
"""频道关键词修复：把算法操纵术语换成正常内容描述词。
默认 DRY-RUN；要执行必须显式 --apply。
用法：python3 fix_channel_keywords.py [--apply]
"""
import json
import re
import sys
import time
import urllib.request

TOK = json.load(open("/home/hatch/data/youtube/.oauth.json"))["token"]
API = "https://www.googleapis.com/youtube/v3"
APPLY = "--apply" in sys.argv

REMOVE = [
    "Algo anomaly", "Exposure audit", "Retention score", "Cross-platform viral",
    "Remix chain", "Keyword mapping", "CTR anomaly", "Engagement logs",
    "Evidence chain", "Rec bias", "HUD metadata", "Content module",
    "Metadata audit", "Viral model", "Footprint check",
    "#ProtocolGuardian", "#AlgorithmForensics", "#HiddenSettings", "#HUDStyle",
    "#MetadataAudit", "#CTRAnalysis", "#RetentionScore", "#ViralDistribution",
    "#RemixChain", "#DigitalForensics", "#ExposureBoost",
]
NEW_KEYWORDS = [
    "AI comedy", "Karen vs AI", "instant karma", "smart device fails",
    "funny AI skit", "customer service comedy", "technology humor",
    "short comedy skit", "AI satire",
]


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


print("=" * 74)
print("当前频道关键词")
print("=" * 74)
d = get(API + "/channels?part=brandingSettings&mine=true")
it = d["items"][0]
cur = (it.get("brandingSettings", {}).get("channel", {}).get("keywords") or "")
print(cur)
print("长度:", len(cur))

new_kw = " ".join('"%s"' % k for k in NEW_KEYWORDS)
print()
print("=" * 74)
print("拟改为")
print("=" * 74)
print(new_kw)
print("长度:", len(new_kw))

print()
print("=" * 74)
print("diff")
print("=" * 74)
removed = [w for w in REMOVE if w.lower() in cur.lower()]
print("  移除 %d 个词:" % len(removed))
for w in removed:
    print("    -", w)
print("  新增 %d 个词:" % len(NEW_KEYWORDS))
for w in NEW_KEYWORDS:
    print("    + ", w)

parts = re.findall(r'"([^"]+)"|(#\w+)', cur)
flat = [a or b for a, b in parts]
keep = [p for p in flat if p not in REMOVE]
print("  保留 %d 个:" % len(keep))
for w in keep:
    print("    = ", w)

print()
print("=" * 74)
if not APPLY:
    print("DRY-RUN —— 未做任何修改。")
    print("要执行：python3 fix_channel_keywords.py --apply")
    print("=" * 74)
    raise SystemExit(0)

print("APPLY —— 提交修改")
print("=" * 74)
body = {"id": it["id"], "brandingSettings": {"channel": {"keywords": new_kw}}}
url = API + "/channels?part=brandingSettings"
req = urllib.request.Request(
    url, data=json.dumps(body).encode("utf-8"),
    headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"},
    method="PUT")
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode("utf-8"))
    got = (resp.get("brandingSettings", {}).get("channel", {}).get("keywords") or "")
    print("  HTTP OK")
    print("  回读 keywords:", got)
    print("  一致:", got.strip() == new_kw.strip())
except Exception as e:
    b = ""
    try:
        b = e.read().decode("utf-8", "replace")[:400]
    except Exception:
        pass
    print("  FAIL:", str(e)[:200])
    print("  body:", b)
    raise SystemExit(1)
