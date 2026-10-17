# -*- coding: utf-8 -*-
"""KB 交付物公共数据层：加载真实行数据 + 统计口径 + 样片精选逻辑。"""
import json, re, os, statistics
from collections import OrderedDict, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))

# 可移植数据目录：$PIPELINE_DATA > 当前目录 > 脚本上级 > example_data > 旧路径
def _resolve_data_dir():
    import os as _os
    cands = []
    if _os.environ.get("PIPELINE_DATA"):
        cands.append(_os.environ["PIPELINE_DATA"])
    cands.append(".")
    d = BASE
    for _ in range(4):
        cands += [d, _os.path.join(d, "collector"), _os.path.join(d, "example_data"),
                  _os.path.join(d, "..", "example_data")]
        d = _os.path.dirname(d)
    cands.append("/home/user/collector")
    for c in cands:
        if _os.path.exists(_os.path.join(c, "bili_rows.json")):
            return c
    return BASE


DATA = _resolve_data_dir()
ROOT = os.path.dirname(DATA) if os.path.basename(DATA) == "collector" else os.path.dirname(os.path.abspath(__file__))

PLAT_CN = {
    "bilibili": "B站", "tiktok": "TikTok", "douyin": "抖音",
    "kuaishou": "快手", "x": "X (Twitter)",
}


def load_rows(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        p = os.path.join(BASE, name)
    d = json.load(open(p))
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


ROWS = {
    "bilibili": load_rows("bili_rows.json"),
    "tiktok": load_rows("tt_rows.json"),
    "douyin": load_rows("dy_rows.json"),
    "kuaishou": load_rows("ks_rows.json"),
    "x": load_rows("x_rows.json"),
}
ANALYSIS = json.load(open(os.path.join(DATA, "analysis.json")))

NULLS = (None, "", "N/A")


def num(v):
    """返回真值数字，N/A 等返回 None。"""
    if v in NULLS:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def fmt(v, unit=""):
    n = num(v)
    if n is None:
        return "N/A"
    if n >= 100000000:
        return f"{n/100000000:.2f}亿{unit}"
    if n >= 10000:
        s = f"{n/10000:.1f}万"
        return s.replace(".0万", "万") + unit
    return f"{int(n):,}{unit}"


def is_viral(r):
    return str(r.get("is_viral")) == "1"


def group(plat, viral):
    return [r for r in ROWS[plat] if is_viral(r) == viral]


def median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def rate(a, b):
    a, b = num(a), num(b)
    if not a or not b:
        return None
    return a / b * 100


def duration_bucket(sec):
    s = num(sec)
    if s is None:
        return "N/A"
    if s < 30:
        return "＜30秒"
    if s <= 60:
        return "30-60秒"
    if s <= 180:
        return "1-3分钟"
    if s <= 600:
        return "3-10分钟"
    return "≥10分钟"


# ---------------------------------------------------------------- 样片精选
SAMPLE_PLAN = [
    # (平台, 账号, 选取规则说明)
    ("bilibili", "阿猫阿狗AIGC", "该账号播放最高"),
    ("bilibili", "伊介书生", "该账号播放最高"),
    ("bilibili", "王与也行", "该账号播放最高"),
    ("bilibili", "暴走黄老板", "该账号播放最高"),
    ("bilibili", "史海听风", "该账号播放最高"),
    ("bilibili", "夏眠片刻", "该账号播放最高"),
    ("bilibili", "别闹了豆刨", "该账号播放最高"),
    ("bilibili", "广告圈poor猴", "该账号播放最高"),
]


def pick_top(plat, account, key="views", viral=1):
    rs = [r for r in ROWS[plat] if r.get("account_name") == account and is_viral(r) == bool(viral)]
    rs = [r for r in rs if num(r.get(key)) is not None]
    if not rs:
        return None
    return max(rs, key=lambda r: num(r.get(key)))


def pick_median(plat, account, key="views"):
    rs = [r for r in ROWS[plat] if r.get("account_name") == account and not is_viral(r)]
    rs = [r for r in rs if num(r.get(key)) is not None]
    if not rs:
        return None
    rs.sort(key=lambda r: num(r.get(key)))
    return rs[len(rs) // 2]


def build_samples():
    """返回精选项列表（每条带真实数据 + 入选理由）。"""
    S = []

    def add(r, reason):
        if r:
            S.append({"row": r, "reason": reason})

    # --- B站 8 账号头名 ---
    for plat, acc, _ in SAMPLE_PLAN:
        r = pick_top(plat, acc)
        add(r, "该账号近90天播放量最高；爆款组头名")
    # --- B站 3 条对照组（体现"中位长什么样"）---
    for acc in ["暴走黄老板", "史海听风", "别闹了豆刨"]:
        r = pick_median("bilibili", acc)
        add(r, "对照组（同账号中位表现）——用于对比同一账号的爆款/常规落差")
    # --- B站 特殊结构案例 ---
    # 超长合集 / 短时长 / 高收藏
    b = ROWS["bilibili"]
    longest = max([r for r in b if num(r.get("duration_sec"))], key=lambda r: num(r["duration_sec"]))
    add(longest, "全样本时长最长（合集形态），单条即拿下该账号最高播放")
    shortest_v = sorted([r for r in b if is_viral(r) and num(r.get("duration_sec"))], key=lambda r: num(r["duration_sec"]))[0]
    add(shortest_v, "爆款组中时长最短，验证「短时长同样能爆」")
    best_collect = max([r for r in b if num(r.get("collects"))], key=lambda r: num(r["collects"]))
    add(best_collect, "全样本收藏量最高；收藏/播放比可作「值得反复看」的参考")

    # --- TikTok ---
    t = ROWS["tiktok"]
    for acc in ["pinkcat456", "pokko42", "orange.cat.philos", "pamelapalmer19913"]:
        r = pick_top("tiktok", acc)
        add(r, "话题池横截面中的头部样本（该账号仅1条入池）")
    for acc in ["mark450_", "maverickgpt", "samdespo", "hatimsshorts", "strangeai"]:
        r = pick_top("tiktok", acc)
        add(r, "账号级抽样（话题页可回收≥10条）账号中播放最高")
    add(pick_median("tiktok", "mark450_"), "账号级抽样对照组（该账号中位表现）")
    # 转发率最高（真实计算）
    cand = [r for r in t if num(r.get("views")) and num(r.get("shares"))]
    best_share = max(cand, key=lambda r: num(r["shares"]) / num(r["views"]))
    add(best_share, "全样本转发率最高（按 转发/播放 实测计算）")

    # --- 抖音（无播放量，按点赞排序）---
    d = ROWS["douyin"]
    for acc in ["whata-ha", "灵月动漫", "鸡腿喵", "子文又饿了", "时间捡史"]:
        r = pick_top("douyin", acc, key="likes")
        add(r, "该账号点赞量最高（抖音不公开播放量，按点赞口径）")
    cand = [r for r in d if num(r.get("collects")) and num(r.get("likes"))]
    if cand:
        best_c = max(cand, key=lambda r: num(r["collects"]) / num(r["likes"]))
        add(best_c, "收藏/点赞比最高（抖音口径下最接近「高价值内容」的公开信号）")

    # --- 快手 ---
    k = ROWS["kuaishou"]
    for acc in ["王梓陌", "噜噜酱", "小蜡笔", "冰淇淋娱乐"]:
        r = pick_top("kuaishou", acc)
        add(r, "该账号播放量最高")
    add(pick_median("kuaishou", "噜噜酱"), "对照组（同账号中位表现）")

    # --- X（只挑与 AI/搞笑/反转 切题者）---
    x = ROWS["x"]
    want = ["trendsryder", "sckbounty", "gardnerakayla", "tomwarren", "LouisAnslow", "artyfiber"]
    for acc in want:
        r = pick_top("x", acc, viral=1) or pick_top("x", acc, viral=0)
        add(r, "切题样本（AI/科技话题），X 仅能对已知推文 ID 取数")

    # 去重：同一视频只保留首次出现（避免"账号头名"与"特殊结构"重复）
    seen, uniq = set(), []
    for s in S:
        u = s["row"].get("video_url")
        if u in seen:
            continue
        seen.add(u)
        uniq.append(s)
    return uniq


def sample_reason_auto(s):
    """基于真实字段补充一条可核算的量化备注。"""
    r = s["row"]
    plat = r["platform"]
    outs = []
    v, l, c, sh, co = (num(r.get(k)) for k in ("views", "likes", "comments", "shares", "collects"))
    if v and l:
        outs.append(f"点赞/播放 {l/v*100:.2f}%")
    if v and sh:
        outs.append(f"转发/播放 {sh/v*100:.2f}%")
    if v and co:
        outs.append(f"收藏/播放 {co/v*100:.2f}%")
    if v and c:
        outs.append(f"评论/播放 {c/v*100:.3f}%")
    if not v and l and co:
        outs.append(f"收藏/点赞 {co/l*100:.2f}%（抖音口径）")
    dur = num(r.get("duration_sec"))
    if dur:
        outs.append(f"时长 {dur:.0f}s")
    return "、".join(outs)
