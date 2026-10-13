#!/usr/bin/env python3
"""用 @karenvsai 自有频道数据重新校准爆款变量权重。
输入: /home/hatch/data/youtube/all_videos.json (496 条)
输出: 控制台报告 + /home/hatch/data/perpetua/own_data_calibration.md
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json, re, math, statistics
from datetime import datetime
from collections import Counter

DATA = "/home/hatch/data/youtube/all_videos.json"
VERBS = json.load(open("/home/hatch/data/perpetua/karma_verbs.json"))
TIER_S = set(VERBS["tier_s"])
TIER_B = set(VERBS["tier_b"])
BANNED = set(VERBS["banned"])

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u2640-\u2642\u2690-\u2699]", re.UNICODE)
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")

VOWELS = "aeiouy"

def count_syllables(word):
    word = word.lower().strip(".,!?;:'\"()[]-")
    if not word: return 0
    if len(word) <= 3: return 1
    n = 0; prev_v = False
    for ch in word:
        v = ch in VOWELS
        if v and not prev_v: n += 1
        prev_v = v
    if word.endswith("e"): n -= 1
    if word.endswith("le") and len(word) > 2 and word[-3] not in VOWELS: n += 1
    return max(1, n)

def fk_grade(text):
    """Flesch-Kincaid Grade Level, 手动实现"""
    words = re.findall(r"[A-Za-z']+", text)
    if not words: return None
    sents = max(1, len(re.split(r"[.!?…]+", text.strip())))
    syl = sum(count_syllables(w) for w in words)
    return 0.39 * (len(words) / sents) + 11.8 * (syl / len(words)) - 15.59

def parse_duration(iso):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m: return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s

def verb_tier(title):
    up = title.upper()
    if any(v in up for v in BANNED): return -1
    if any(v in up for v in TIER_S): return 2
    if any(v in up for v in TIER_B): return 1
    return 0

videos = json.load(open(DATA))
print(f"共 {len(videos)} 条视频")

rows = []
for v in videos:
    t = v.get("title") or ""
    pub = v.get("published") or ""
    try:
        dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except Exception:
        try: dt = datetime.strptime(pub[:10], "%Y-%m-%d")
        except Exception: dt = None
    dur = parse_duration(v.get("duration"))
    rows.append({
        "id": v["id"], "title": t,
        "views": int(v.get("views") or 0),
        "likes": int(v.get("likes") or 0),
        "comments": int(v.get("comments") or 0),
        "has_karen": 1 if "karen" in t.lower() else 0,
        "has_ai": 1 if re.search(r"\bai\b", t.lower()) else 0,
        "emoji_first": 1 if t and EMOJI_RE.match(t[0]) else 0,
        "has_emoji": 1 if EMOJI_RE.search(t) else 0,
        "verb_tier": verb_tier(t),
        "fk_grade": fk_grade(t),
        "title_len": len(t),
        "has_question": 1 if "?" in t else 0,
        "has_number": 1 if re.search(r"\d", t) else 0,
        "has_cjk": 1 if CJK_RE.search(t) else 0,
        "n_tags": len(v.get("tags") or []),
        "duration_s": dur,
        "is_shorts": 1 if 0 < dur <= 65 else 0,
        "hour": dt.hour if dt else -1,
        "dow": dt.weekday() if dt else -1,  # 0=Mon
        "year_month": pub[:7],
    })

for r in rows:
    r["log_views"] = math.log10(r["views"] + 1)
    r["log_likes"] = math.log10(r["likes"] + 1)

# ---- 1. Top10% 集中度验证 ----
vs = sorted([r["views"] for r in rows], reverse=True)
total = sum(vs)
top10 = sum(vs[:max(1, len(vs)//10)])
print(f"\n总播放: {total}, Top10% 贡献: {top10/total*100:.1f}%")
print(f"均值: {statistics.mean(vs):.0f}, 中位: {statistics.median(vs):.0f}, max: {max(vs)}")

# ---- 2. 相关性 ----
def pearson(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs)); dy = math.sqrt(sum((y-my)**2 for y in ys))
    return num/(dx*dy) if dx and dy else 0.0

def spearman(xs, ys):
    n = len(xs)
    rx = _rank(xs); ry = _rank(ys)
    return pearson(rx, ry)

def _rank(xs):
    s = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0]*len(xs); i = 0
    while i < len(s):
        j = i
        while j+1 < len(s) and xs[s[j+1]] == xs[s[i]]: j += 1
        avg = (i+j)/2 + 1
        for k in range(i, j+1): r[s[k]] = avg
        i = j+1
    return r

num_vars = ["has_karen","has_ai","emoji_first","has_emoji","verb_tier","fk_grade",
            "title_len","has_question","has_number","has_cjk","n_tags",
            "duration_s","is_shorts","hour","dow"]
print("\n=== 变量 vs log10(views+1) 相关性 ===")
print(f"{'变量':<14} {'Pearson':>8} {'Spearman':>8} {'n':>6}  备注")
results = []
for var in num_vars:
    pairs = [(r[var], r["log_views"]) for r in rows if r[var] is not None and r[var] != -1]
    if len(pairs) < 10: continue
    xs, ys = zip(*pairs)
    p, s = pearson(xs, ys), spearman(xs, ys)
    results.append((var, p, s, len(pairs)))
    print(f"{var:<14} {p:>8.3f} {s:>8.3f} {len(pairs):>6}")

# ---- 3. 分组对比 ----
def grp(name, cond):
    g1 = [r["log_views"] for r in rows if cond(r)]
    g0 = [r["log_views"] for r in rows if not cond(r)]
    if not g1 or not g0: return
    # 转回几何均值播放量
    gm1 = 10**statistics.mean(g1)-1; gm0 = 10**statistics.mean(g0)-1
    print(f"{name}: 是 n={len(g1)} 几何均值播放 {gm1:.0f} | 否 n={len(g0)} 几何均值播放 {gm0:.0f} | 倍数 {gm1/max(gm0,1):.2f}x")

print("\n=== 分组对比（几何均值播放量） ===")
grp("标题含Karen      ", lambda r: r["has_karen"])
grp("标题含AI         ", lambda r: r["has_ai"])
grp("emoji开头        ", lambda r: r["emoji_first"])
grp("含emoji(任意位置)", lambda r: r["has_emoji"])
grp("S级动词          ", lambda r: r["verb_tier"] == 2)
grp("B级动词          ", lambda r: r["verb_tier"] == 1)
grp("禁用动词         ", lambda r: r["verb_tier"] == -1)
grp("含CJK            ", lambda r: r["has_cjk"])
grp("含问号           ", lambda r: r["has_question"])
grp("含数字           ", lambda r: r["has_number"])
grp("Shorts(<=65s)    ", lambda r: r["is_shorts"])
grp("有标签(>=3)      ", lambda r: r["n_tags"] >= 3)

# ---- 4. 发布时间分析 ----
print("\n=== 星期几 vs 几何均值播放 ===")
dows = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
for d in range(7):
    g = [r["log_views"] for r in rows if r["dow"] == d]
    if g: print(f"  {dows[d]}: n={len(g):>3} 几何均值 {10**statistics.mean(g)-1:.0f}")
print("\n=== 小时段 vs 几何均值播放（Top 6） ===")
buckets = {}
for r in rows:
    if r["hour"] >= 0:
        b = f"{r['hour']:02d}:00"
        buckets.setdefault(b, []).append(r["log_views"])
hb = sorted([(b, 10**statistics.mean(v)-1, len(v)) for b, v in buckets.items() if len(v) >= 5],
            key=lambda x: -x[1])[:6]
for b, gm, n in hb: print(f"  {b}: n={n:>3} 几何均值 {gm:.0f}")

# ---- 5. FK 可读性分桶 ----
print("\n=== 可读性(FK年级)分桶 vs 几何均值播放 ===")
fkb = {"<=3": [], "3-5": [], "5-8": [], ">8": [], "无英文": []}
for r in rows:
    g = r["fk_grade"]
    v = r["log_views"]
    if g is None: fkb["无英文"].append(v)
    elif g <= 3: fkb["<=3"].append(v)
    elif g <= 5: fkb["3-5"].append(v)
    elif g <= 8: fkb["5-8"].append(v)
    else: fkb[">8"].append(v)
for k, v in fkb.items():
    if v: print(f"  FK {k}: n={len(v):>3} 几何均值 {10**statistics.mean(v)-1:.0f}")

# ---- 6. 时长分桶 ----
print("\n=== 时长分桶 vs 几何均值播放 ===")
db = {"<=15s": [], "15-30s": [], "30-60s": [], ">60s": []}
for r in rows:
    d, v = r["duration_s"], r["log_views"]
    if d <= 15: db["<=15s"].append(v)
    elif d <= 30: db["15-30s"].append(v)
    elif d <= 60: db["30-60s"].append(v)
    else: db[">60s"].append(v)
for k, v in db.items():
    if v: print(f"  {k}: n={len(v):>3} 几何均值 {10**statistics.mean(v)-1:.0f}")

atomic_write_json("/home/hatch/data/perpetua/calibration_results.json",
                  {"n": len(rows), "correlations": [
                      {"var": v, "pearson": round(p, 4), "spearman": round(s, 4), "n": n}
                      for v, p, s, n in results],
                   "top10_pct": round(top10/total*100, 1)})
print("\n结果已存 calibration_results.json")
