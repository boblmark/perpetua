"""Step 3 - main Bilibili collection.

Per account: 5 viral (top views in last 90d) + 5 control (median views, published within
+/-14 days of the viral set). Every reported number comes from the live video-detail API.
cover_desc is produced by OCR of the real cover image (rapidocr), not invented.
"""
import json, os, re, sys, time
from statistics import median

import requests
sys.path.insert(0, "/home/user/collector")
from bili_lib import Bili

NOW = time.time()
D90 = NOW - 90 * 86400
COVER_DIR = "/home/user/collector/covers"
os.makedirs(COVER_DIR, exist_ok=True)

ROSTER = [
    (7960697,           "阿猫阿狗AIGC",  "AI原创动画喜剧"),
    (91790758,          "伊介书生",      "AI短片/社交观察搞笑"),
    (474213246,         "王与也行",      "AI MV恶搞/音乐整活"),
    (3546564792420361,  "暴走黄老板",    "职场反转短剧"),
    (3546856363658080,  "史海听风",      "AI美食/历史沉浸式"),
    (3546865618389421,  "夏眠片刻",      "AI剧情短剧"),
    (324188834,         "广告圈poor猴",  "创意广告/搞笑拆解"),
    (1013715215,        "别闹了豆刨",    "搞笑/反转"),
    (1391824359,        "耀祖影视电影",  "影视修复/惊悚（备选）"),
]

STOP = {"AI全民制作人", "AI", "ai"}


def clean_title(t):
    return re.sub(r'\s+', ' ', (t or "").replace('<em class="keyword">', "").replace("</em>", "")).strip()


def hashtags_of(detail):
    tags = set()
    for src in (detail.get("title") or "", detail.get("desc") or "", detail.get("dynamic") or ""):
        for m in re.findall(r"#([^#\s]{1,24})", src):
            tags.add(m.strip())
    return ",".join(sorted(tags)) if tags else "N/A"


def topic_category(title, desc, tname):
    s = (title or "") + " " + (desc or "")
    if re.search(r"AI|人工智能|生成", s, re.I):
        return "AI生成/制作"
    if tname and ("搞笑" in tname or "娱乐" in tname):
        return "搞笑/娱乐"
    return tname or "剧情/其他"


def hook_type(title, desc):
    """Heuristic label derived from the real title/desc text (documented as metadata-derived)."""
    s = (title or "") + " " + (desc or "")
    if re.search(r"反转|结局|没想到|竟然|居然|原来|最后", s):
        return "反转预期"
    if re.search(r"[?？]|猜猜|你敢|为什么|怎么", s):
        return "悬念提问"
    if re.search(r"沉浸式|一口气|全程|实拍|还原|看见", s):
        return "沉浸式/视觉奇观"
    if re.search(r"vs|对比|belike|态度", s):
        return "对比冲突"
    if re.search(r"[:：，,]", s):
        return "对话/冲突开场"
    return "陈述开场"


def format_notes(detail, title):
    """Only metadata-observable facts are written here; unobservable items stay 待人工核验."""
    notes = []
    dur = detail.get("duration") or 0
    notes.append(f"时长{dur}s")
    if re.search(r"第[一二三四五六七八九十百\d]+[集话期]", title or ""):
        m = re.search(r"[《【]?([^《【》】]{2,14})[》】]?第[一二三四五六七八九十百\d]+[集话期]", title)
        notes.append(f"系列化剧集({m.group(1) if m else '有'})")
    if "循环" in (title or ""):
        notes.append("标题含循环")
    notes.append("字幕风格/转场待人工核验")
    return "；".join(notes)


def ocr_cover(url, bvid, ocr):
    if not url:
        return "N/A", "N/A"
    p = os.path.join(COVER_DIR, f"{bvid}.jpg")
    try:
        if not os.path.exists(p):
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"}, timeout=25)
            if r.status_code != 200 or len(r.content) < 1000:
                return "N/A", "N/A"
            open(p, "wb").write(r.content)
        res, _ = ocr(p)
        if not res:
            return "N/A", "N/A"
        def _y(t):
            try:
                return (min(p[1] for p in t[0]), min(p[0] for p in t[0]))
            except Exception:
                return (0, 0)
        ordered = sorted([t for t in res if t[1] and t[1].strip()], key=_y)
        lines = [t[1].strip() for t in ordered]
        full = " / ".join(lines)[:120]
        short = "".join(lines)[:20]
        return (short or "N/A"), full
    except Exception as e:
        return "N/A", f"OCR_FAIL:{type(e).__name__}"


def main():
    b = Bili()
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    rows, accounts = [], []

    for mid, name, style in ROSTER:
        if len(accounts) >= 8:
            break
        print(f"\n=== {name} (mid={mid}) ===", flush=True)
        card = b.card(mid)
        if not card:
            print("  card failed, skip", flush=True)
            continue
        vids = []
        for pn in (1, 2, 3):
            a = b.recent_archives(mid, pn=pn)
            vids += a
            if len(a) < 10:
                break
        seen, uniq = set(), []
        for v in vids:
            if v["bvid"] not in seen:
                seen.add(v["bvid"]); uniq.append(v)
        win = [v for v in uniq if v["pubdate"] >= D90]
        if len(win) < 5:
            print(f"  only {len(win)} videos in 90d -> skip (inactive)", flush=True)
            continue
        print(f"  followers={card['fans']:,} | total={len(uniq)} | in90d={len(win)}", flush=True)

        viral = sorted(win, key=lambda v: -(v["stat"]["view"] or 0))[:5]
        vset = {v["bvid"] for v in viral}
        vdts = [v["pubdate"] for v in viral]
        pool = [v for v in win if v["bvid"] not in vset and
                any(abs(v["pubdate"] - d) <= 14 * 86400 for d in vdts)]
        if len(pool) < 5:
            pool = [v for v in win if v["bvid"] not in vset]
        med = median([v["stat"]["view"] or 0 for v in pool]) if pool else 0
        control = sorted(pool, key=lambda v: abs((v["stat"]["view"] or 0) - med))[:5]
        print(f"  viral views: {[v['stat']['view'] for v in viral]}", flush=True)
        print(f"  control median={med:.0f} -> {[v['stat']['view'] for v in control]}", flush=True)

        for v, flag in [(v, 1) for v in viral] + [(v, 0) for v in control]:
            d = b.video_stat(v["bvid"])
            if not d:
                print(f"    !! detail failed {v['bvid']}", flush=True)
                continue
            short, full = ocr_cover(d.get("pic"), v["bvid"], ocr)
            title = clean_title(d.get("title") or v.get("title"))
            rows.append({
                "platform": "bilibili",
                "account_name": d.get("owner_name") or name,
                "account_mid": d.get("owner_mid") or mid,
                "account_followers": card["fans"],
                "video_url": f"https://www.bilibili.com/video/{v['bvid']}",
                "title": title,
                "cover_desc": short,
                "cover_ocr_full": full,
                "cover_url": d.get("pic"),
                "views": d.get("view"),
                "likes": d.get("like"),
                "comments": d.get("reply"),
                "shares": d.get("share"),
                "collects": d.get("favorite"),
                "danmaku": d.get("danmaku"),
                "coins": d.get("coin"),
                "published_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.get("pubdate") or 0)),
                "duration_sec": d.get("duration"),
                "hashtags": hashtags_of(d),
                "is_viral": flag,
                "topic_category": topic_category(title, d.get("desc"), d.get("tname")),
                "hook_type": hook_type(title, d.get("desc")),
                "format_notes": format_notes(d, title),
                "account_style": style,
                "collected_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(NOW)),
            })
            print(f"    [{'V' if flag else 'c'}] {v['bvid']} views={d.get('view'):>9,} like={d.get('like'):>7,} "
                  f"cmt={d.get('reply'):>5,} fav={d.get('favorite'):>6,} | {title[:30]} | cover={short[:16]}", flush=True)

        accounts.append(dict(mid=mid, name=card["name"], fans=card["fans"],
                            style=style, n90=len(win), vids=len(uniq)))
        json.dump({"rows": rows, "accounts": accounts},
                  open("/home/user/collector/bili_rows.json", "w"), ensure_ascii=False, indent=1)
        print(f"  [saved] rows={len(rows)} accounts={len(accounts)}", flush=True)

    json.dump({"rows": rows, "accounts": accounts}, open("/home/user/collector/bili_rows.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nDONE: {len(rows)} rows across {len(accounts)} accounts -> bili_rows.json")


main()
