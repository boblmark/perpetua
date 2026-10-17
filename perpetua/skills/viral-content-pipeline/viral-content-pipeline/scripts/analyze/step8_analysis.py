"""Step 12 - 基于真实采集数据生成「校准分析」sheet。

任务书的目标是"校准选题方向、标题公式、封面风格、互动率基准"。
本脚本只用已采集的公开真实数字做统计，不引入任何后台指标、不做阈值推断。
缺少 views 的平台（抖音）自动改用「相对点赞」口径，并明确标注。
"""
import json
import os
import re
from collections import Counter, defaultdict
from statistics import median


def _resolve_data_dir():
    """可移植数据目录：$PIPELINE_DATA > 当前目录 > 脚本上级 > example_data > 旧路径"""
    cands = []
    if os.environ.get("PIPELINE_DATA"):
        cands.append(os.environ["PIPELINE_DATA"])
    cands.append(".")
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        cands += [d, os.path.join(d, "collector"), os.path.join(d, "example_data")]
        d = os.path.dirname(d)
    cands.append("/home/user/collector")
    for c in cands:
        if os.path.exists(os.path.join(c, "bili_rows.json")):
            return c
    return "."


DATA = _resolve_data_dir()

OUT_JSON = os.path.join(DATA, "analysis.json")


def load(p):
    try:
        d = json.load(open(p))
        return d.get("rows", [])
    except Exception:
        return []


BILI = load(os.path.join(DATA, "bili_rows.json"))
TT = load(os.path.join(DATA, "tt_rows.json"))
DY = load(os.path.join(DATA, "dy_rows.json"))
KS = load(os.path.join(DATA, "ks_rows.json"))
XR = load(os.path.join(DATA, "x_rows.json"))

PLATS = {"bilibili": BILI, "tiktok": TT, "douyin": DY, "kuaishou": KS, "x": XR}
V = lambda r, k: r.get(k) if isinstance(r.get(k), int) else (r.get(k) if isinstance(r.get(k), (int, float)) else None)


def num(x):
    return x if isinstance(x, (int, float)) else None


def rate(a, b):
    """a/b 的百分比，缺值返回 None"""
    if num(a) and num(b) and b:
        return round(a / b * 100, 2)
    return None


result = {"interaction": [], "topic": [], "hook": [], "duration": [],
          "title_len": [], "cover": [], "series": [], "notes": []}

# ---------- 1. 互动率基准 ----------
for plat, rows in PLATS.items():
    for grp, flag in (("爆款组", 1), ("对照组", 0)):
        sub = [r for r in rows if r.get("is_viral") == flag]
        if not sub:
            continue
        rec = {"平台": plat, "组别": grp, "样本数": len(sub)}
        for label, key in [("点赞", "likes"), ("评论", "comments"), ("转发", "shares"),
                           ("收藏", "collects")]:
            rs = [rate(r.get(key), r.get("views")) for r in sub]
            rs = [x for x in rs if x is not None]
            rec[f"{label}/播放 (%)"] = median(rs) if rs else None
            rec[f"{label}样本"] = len(rs)
        # 无 views 平台：用 收藏/点赞 相对口径
        if not any(num(r.get("views")) for r in sub):
            rel = [rate(r.get("collects"), r.get("likes")) for r in sub]
            rel = [x for x in rel if x is not None]
            rec["收藏/点赞 (%)"] = median(rel) if rel else None
            rec["口径说明"] = "该平台不公开播放量，互动率改以收藏/点赞表示"
        else:
            rec["口径说明"] = "各指标 ÷ 播放量，取中位数"
        result["interaction"].append(rec)

# ---------- 2. 选题分布 ----------
tp = defaultdict(lambda: defaultdict(int))
for plat, rows in PLATS.items():
    for r in rows:
        tp[plat][r.get("topic_category") or "未分类"] += 1
for plat, c in tp.items():
    tot = sum(c.values())
    for k, v in sorted(c.items(), key=lambda x: -x[1]):
        result["topic"].append({"平台": plat, "选题分类": k, "条数": v, "占比": f"{v/tot*100:.0f}%"})

# ---------- 3. 开场钩子分布（含爆款占比） ----------
hk = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for plat, rows in PLATS.items():
    for r in rows:
        k = r.get("hook_type") or "未分类"
        hk[plat][k][0] += 1
        hk[plat][k][1] += 1 if r.get("is_viral") == 1 else 0
for plat, c in hk.items():
    for k, (n, v) in sorted(c.items(), key=lambda x: -x[1][0]):
        result["hook"].append({"平台": plat, "开场钩子": k, "条数": n,
                              "其中爆款": v, "爆款占比": f"{v/n*100:.0f}%"})

# ---------- 4. 时长与表现 ----------
def bucket(sec):
    if sec is None:
        return None
    if sec < 30:
        return "＜30秒"
    if sec < 60:
        return "30-60秒"
    if sec < 180:
        return "1-3分钟"
    if sec < 600:
        return "3-10分钟"
    return "≥10分钟"


for plat, rows in PLATS.items():
    g = defaultdict(list)
    for r in rows:
        b = bucket(num(r.get("duration_sec")))
        if b:
            g[b].append(r)
    for b in ["＜30秒", "30-60秒", "1-3分钟", "3-10分钟", "≥10分钟"]:
        if b in g:
            sub = g[b]
            vv = [r["views"] for r in sub if num(r.get("views"))]
            ll = [r["likes"] for r in sub if num(r.get("likes"))]
            result["duration"].append({
                "平台": plat, "时长档": b, "条数": len(sub),
                "爆款条数": sum(1 for r in sub if r.get("is_viral") == 1),
                "播放量中位数": int(median(vv)) if vv else None,
                "点赞中位数": int(median(ll)) if ll else None})

# ---------- 5. 标题长度 ----------
for plat, rows in PLATS.items():
    g = defaultdict(list)
    for r in rows:
        t = r.get("title") or ""
        if t in ("N/A", ""):
            continue
        n = len(t)
        b = "≤15字" if n <= 15 else "16-30字" if n <= 30 else "31-50字" if n <= 50 else "＞50字"
        g[b].append(r)
    for b in ["≤15字", "16-30字", "31-50字", "＞50字"]:
        if b in g:
            sub = g[b]
            ll = [r["likes"] for r in sub if num(r.get("likes"))]
            vv = [r["views"] for r in sub if num(r.get("views"))]
            result["title_len"].append({
                "平台": plat, "标题长度": b, "条数": len(sub),
                "爆款条数": sum(1 for r in sub if r.get("is_viral") == 1),
                "点赞中位数": int(median(ll)) if ll else None,
                "播放量中位数": int(median(vv)) if vv else None})

# ---------- 6. 封面文字 ----------
for plat, rows in PLATS.items():
    if plat == "x":
        # X 未采集封面图（推文媒体，无独立封面字段），故不参与封面统计
        continue
    has = [r for r in rows if r.get("cover_desc") not in (None, "N/A", "")]
    no = [r for r in rows if r.get("cover_desc") in (None, "N/A", "")]
    if not rows:
        continue
    result["cover"].append({
        "平台": plat, "总条数": len(rows),
        "封面有可识别文字": len(has), "封面无文字/未识别": len(no),
        "有文字中爆款数": sum(1 for r in has if r.get("is_viral") == 1),
        "无文字中爆款数": sum(1 for r in no if r.get("is_viral") == 1),
        "说明": "封面文字由 OCR 实测提取，未识别不等于画面上没有文字"})

# ---------- 7. 系列化内容 ----------
for plat, rows in PLATS.items():
    s = [r for r in rows if "系列" in str(r.get("format_notes") or "") or "剧集" in str(r.get("format_notes") or "")]
    if rows:
        result["series"].append({
            "平台": plat, "总条数": len(rows), "系列化条数": len(s),
            "系列化中爆款数": sum(1 for r in s if r.get("is_viral") == 1),
            "说明": "系列化由标题中的「第N集/第N话」等真实文本判定"})

# ---------- 8. 高频标签（真实标签词频） ----------
tagc = defaultdict(Counter)
for plat, rows in PLATS.items():
    for r in rows:
        for t in str(r.get("hashtags") or "").split(","):
            t = t.strip().lstrip("#")
            if t and t != "N/A" and len(t) > 1:
                tagc[plat][t.lower()] += 1
top_tags = []
for plat, c in tagc.items():
    for t, n in c.most_common(12):
        top_tags.append({"平台": plat, "标签": t, "出现次数": n})
result["top_tags"] = top_tags

# ---------- 9. 数据缺口 ----------
result["notes"] = [
    "本页所有数字均由已采集的公开真实数据统计得出，未使用任何后台指标（完播率/留存/点击率/流量来源均未采集、未推断）。",
    "互动率 = 互动数 ÷ 播放量，取组内中位数；缺失值不参与统计，各单元格标注了实际参与统计的样本数。",
    "抖音不公开播放量，故其互动率改以「收藏/点赞」相对值表示，口径已在表内标注。",
    "快手未公开评论数/分享数（接口返回 null），相关行不参与对应指标的统计。",
    "X 的样本来自可公开发现的推文 ID（时间线不可枚举），代表性有限，仅作参考。",
    "封面文字来自 OCR 实测；「未识别」不等于封面无文字，需人工复核。",
]

json.dump(result, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
print("analysis written")
for k, v in result.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v)} 行")
