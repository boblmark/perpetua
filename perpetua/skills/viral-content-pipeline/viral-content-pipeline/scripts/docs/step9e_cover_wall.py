# -*- coding: utf-8 -*-
"""生成 封面墙.png —— 各平台「爆款组 vs 对照组」封面并排对照图（供人工目视复核）。"""
import os, json, re, math
from PIL import Image, ImageDraw, ImageFont
OUT_DIR = os.environ.get("PIPELINE_OUT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT = os.path.join(OUT_DIR, "封面墙.png")
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONTB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

def load_rows(name):
    from kb_common import DATA as _D
    p = os.path.join(_D, name)
    if not os.path.exists(p):
        p = os.path.join(BASE, name)
    d = json.load(open(p))
    return d["rows"] if isinstance(d, dict) and "rows" in d else d

SPEC = [
    ("bilibili", "B站", "covers", 8, "bili_rows.json"),
    ("tiktok", "TikTok", "covers_tt", 8, "tt_rows.json"),
    ("douyin", "抖音", "covers_dy", 6, "dy_rows.json"),
    ("kuaishou", "快手", "covers_ks", 6, "ks_rows.json"),
]

def vid_of(plat, url):
    u = str(url)
    for pat in (r"(BV[0-9A-Za-z]+)", r"/video/(\d+)", r"short-video/([0-9a-z]+)"):
        m = re.search(pat, u)
        if m:
            return m.group(1)
    return None

def num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None

def fmt(v):
    n = num(v)
    if n is None:
        return "N/A"
    if n >= 100000000:
        return f"{n/100000000:.2f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万".replace(".0万", "万")
    return f"{int(n):,}"

CELL_W, CELL_H = 176, 132          # 封面缩略图框
PAD = 9
CAP_H = 30
LBL_H = 30
SEC_GAP = 22

f_cap = ImageFont.truetype(FONT, 13)
f_lbl = ImageFont.truetype(FONTB, 19)
f_sub = ImageFont.truetype(FONT, 13)
f_row = ImageFont.truetype(FONTB, 15)

def fit(im, w, h):
    im = im.convert("RGB")
    r = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)

def build():
    sections = []
    for plat, cn, d, n, jf in SPEC:
        rows = load_rows(jf)
        items = []
        for r in rows:
            v = vid_of(plat, r.get("video_url"))
            p = os.path.join(BASE, d, f"{v}.jpg") if v else None
            if p and os.path.exists(p):
                items.append((r, p))
        vir = sorted([x for x in items if str(x[0].get("is_viral")) == "1"],
                     key=lambda x: -(num(x[0].get("views")) or num(x[0].get("likes")) or 0))[:n]
        ctl = sorted([x for x in items if str(x[0].get("is_viral")) == "0"],
                     key=lambda x: -(num(x[0].get("views")) or num(x[0].get("likes")) or 0))
        if len(ctl) > n:
            # 取中位附近的 n 条（更贴合"对照组=中位表现"的口径）
            mid = len(ctl) // 2
            start = max(0, min(mid - n // 2, len(ctl) - n))
            ctl = ctl[start:start + n]
        sections.append((cn, plat, vir, ctl))

    cols = max(len(v) for _, _, v, _ in sections)
    cols = max(cols, max(len(c) for _, _, _, c in sections))
    W = PAD + cols * (CELL_W + PAD)
    H = 92 + sum(LBL_H + 2 * (CELL_H + CAP_H + PAD) + SEC_GAP for _ in sections) + 46

    canvas = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(canvas)

    dr.rectangle([0, 0, W, 76], fill="#1F3864")
    dr.text((PAD + 4, 12), "竞品爆款 · 封面墙", font=ImageFont.truetype(FONTB, 27), fill="white")
    dr.text((PAD + 6, 48), "上排＝各平台爆款组（按播放量取前 N）　下排＝对照组（中位表现附近）　图片均为平台公开封面原图",
            font=f_sub, fill="#C9D6EC")

    y = 92
    for cn, plat, vir, ctl in sections:
        dr.text((PAD + 2, y + 4), f"{cn}", font=f_lbl, fill="#1F3864")
        dr.text((PAD + 2 + dr.textlength(cn, font=f_lbl) + 12, y + 8),
                f"爆款组 {len(vir)} 张（上） / 对照组 {len(ctl)} 张（下）", font=f_sub, fill="#767676")
        y += LBL_H
        for label, group, color in (("爆款", vir, "#C00000"), ("对照", ctl, "#7F7F7F")):
            x = PAD
            for r, p in group:
                try:
                    im = fit(Image.open(p), CELL_W, CELL_H)
                except Exception:
                    x += CELL_W + PAD
                    continue
                bx = x + (CELL_W - im.width) // 2
                by = y + (CELL_H - im.height) // 2
                canvas.paste(im, (bx, by))
                dr.rectangle([x - 1, y - 1, x + CELL_W, y + CELL_H], outline="#C9D3E4")
                # 角标
                dr.rectangle([x - 1, y - 1, x + 40, y + 19], fill=color)
                dr.text((x + 4, y + 2), label, font=f_cap, fill="white")
                acc = str(r.get("account_name") or "")[:13]
                tv = num(r.get("views"))
                cap = f"{fmt(r.get('views'))}播放" if tv else f"点赞{fmt(r.get('likes'))}"
                dr.text((x, y + CELL_H + 4), f"{acc}", font=f_cap, fill="#333333")
                dr.text((x, y + CELL_H + 17), cap, font=f_cap, fill="#8A8A8A")
                x += CELL_W + PAD
            y += CELL_H + CAP_H + PAD
        y += SEC_GAP

    dr.text((PAD + 2, H - 34),
            "说明：本图为人工目视复核用，未对封面做任何美化或筛选（除按播放量排序选前 N）。"
            "像素统计见 爆款方法论 第六节：28 项组间检验中仅 1 项达 p<0.05，不构成稳定的封面规律。",
            font=f_sub, fill="#767676")
    canvas.save(OUT, quality=92)
    print("saved", OUT, canvas.size)
    for cn, plat, vir, ctl in sections:
        print(f"  {cn}: 爆款{len(vir)} 对照{len(ctl)}")


if __name__ == "__main__":
    build()
