# -*- coding: utf-8 -*-
"""封面视觉风格分析 —— 对本地 319 张真实封面图做像素级客观测量（非推断）。
输出 cover_visual.json：亮度/饱和度/对比度/暖冷色调/视觉复杂度/画幅比，
并对比各平台「爆款组 vs 对照组」。
"""
import os, json, glob, re, statistics
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)


def load_rows(name):
    d = json.load(open(os.path.join(BASE, name)))
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


ROWS = {"bilibili": load_rows("bili_rows.json"), "tiktok": load_rows("tt_rows.json"),
        "douyin": load_rows("dy_rows.json"), "kuaishou": load_rows("ks_rows.json")}
DIRS = {"bilibili": "covers", "tiktok": "covers_tt", "douyin": "covers_dy", "kuaishou": "covers_ks"}


def vid_of(plat, url):
    u = str(url)
    m = re.search(r"(BV[0-9A-Za-z]+)", u)
    if m:
        return m.group(1)
    m = re.search(r"/video/(\d+)", u)
    if m:
        return m.group(1)
    m = re.search(r"short-video/([0-9a-z]+)", u)
    if m:
        return m.group(1)
    return None


def metrics(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    arr = np.asarray(im.resize((160, int(160 * h / w)), Image.BILINEAR), dtype=np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    sat = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
    gy, gx = np.gradient(lum)
    edge = float(np.mean(np.sqrt(gx ** 2 + gy ** 2)))
    # 暖冷：R-B 差，正=暖
    warm = float(np.mean(r - b))
    # 高饱和像素占比（"撞色"程度）
    vivid = float(np.mean(sat > 0.5))
    return {
        "w": w, "h": h, "ratio": round(w / h, 3),
        "brightness": round(float(lum.mean()), 4),      # 0=全黑 1=全白
        "sat": round(float(sat.mean()), 4),
        "contrast": round(float(lum.std()), 4),
        "warmth": round(warm, 4),                        # >0 偏暖
        "edge": round(edge, 4),                          # 视觉复杂度代理
        "vivid_ratio": round(vivid, 4),
        "dark_ratio": round(float(np.mean(lum < 0.25)), 4),
    }


def group_stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "中位": round(statistics.median(vals), 4),
            "均值": round(statistics.mean(vals), 4)}


def main():
    out = {"rows": [], "summary": {}, "notes": []}
    by_plat = {}
    for plat, rows in ROWS.items():
        d = os.path.join(BASE, DIRS[plat])
        by_plat[plat] = {"爆款组": [], "对照组": []}
        hit = 0
        for r in rows:
            vid = vid_of(plat, r.get("video_url"))
            p = os.path.join(d, f"{vid}.jpg") if vid else None
            if not p or not os.path.exists(p):
                continue
            hit += 1
            m = metrics(p)
            m.update({"platform": plat, "account": r.get("account_name"), "url": r.get("video_url"),
                      "is_viral": str(r.get("is_viral")) == "1",
                      "views": r.get("views"), "title": r.get("title")})
            out["rows"].append(m)
            by_plat[plat]["爆款组" if m["is_viral"] else "对照组"].append(m)
        out["summary"][plat] = {"封面命中": hit, "总行": len(rows)}

    # 组间对比
    KEYS = ["brightness", "sat", "contrast", "warmth", "edge", "vivid_ratio", "dark_ratio"]
    CN = {"brightness": "亮度", "sat": "饱和度", "contrast": "对比度", "warmth": "暖色倾向",
          "edge": "视觉复杂度", "vivid_ratio": "高饱和占比", "dark_ratio": "暗部占比"}
    compare = []
    for plat in ROWS:
        for k in KEYS:
            v = group_stats([x[k] for x in by_plat[plat]["爆款组"]])
            c = group_stats([x[k] for x in by_plat[plat]["对照组"]])
            if v and c:
                diff = v["中位"] - c["中位"]
                compare.append({"平台": plat, "指标": CN[k], "爆款组中位": v["中位"], "对照组中位": c["中位"],
                                "差值": round(diff, 4), "样本(爆款/对照)": f'{v["n"]}/{c["n"]}'})
    out["compare"] = compare

    # 画幅比分布
    ratio = {}
    for plat in ROWS:
        rs = [x for x in out["rows"] if x["platform"] == plat]
        bucket = {"竖屏(9:16)": 0, "横屏(16:9)": 0, "方形/其他": 0}
        for x in rs:
            rt = x["ratio"]
            if rt < 0.85:
                bucket["竖屏(9:16)"] += 1
            elif rt > 1.4:
                bucket["横屏(16:9)"] += 1
            else:
                bucket["方形/其他"] += 1
        ratio[plat] = bucket
    out["ratio"] = ratio

    out["notes"] = [
        "所有指标均为对封面图片本身的像素级客观测量（亮度=平均相对亮度，饱和度=HSV S 均值，",
        "对比度=亮度标准差，暖色倾向=平均 R−B，视觉复杂度=Sobel 梯度均值，高饱和占比=S>0.5 像素比例）。",
        "这些是对「图长什么样」的测量，不是对「为什么爆」的解释；组间差异在小样本下可能来自噪声。",
    ]
    json.dump(out, open(os.path.join(BASE, "cover_visual.json"), "w"), ensure_ascii=False, indent=1)
    print("封面命中:", {p: v["封面命中"] for p, v in out["summary"].items()})
    print("\n=== 组间差异绝对值 top12（按 |差值| 排序）===")
    for c in sorted(compare, key=lambda x: -abs(x["差值"]))[:12]:
        print(f'  {c["平台"]:<9} {c["指标"]:<8} 爆款 {c["爆款组中位"]:>7} vs 对照 {c["对照组中位"]:>7}  Δ{c["差值"]:>+8.4f}  n={c["样本(爆款/对照)"]}')
    print("\n画幅比:", json.dumps(ratio, ensure_ascii=False))


if __name__ == "__main__":
    main()
