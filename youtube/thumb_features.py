#!/usr/bin/env python3
"""封面（thumbnail）特征提取 —— 零新依赖（PIL + numpy 已装）。

YouTube 封面 URL 是**确定性的**，不必重调 API：
  https://i.ytimg.com/vi/<video_id>/maxresdefault.jpg  (~70KB, 1280x720)
  https://i.ytimg.com/vi/<video_id>/hqdefault.jpg      (~10KB, 480x360)

提取的特征（分 4 组，都可解释、可复现）：

A. 亮度与对比       —— 平均亮度、对比度(std)、暗图占比、高光占比
B. 色彩活力         —— HSV 饱和度均值、色相熵（色彩丰富度）、暖色占比
C. 构图与视觉重心   —— 三分法贴合度、主体居中度、边缘能量、显著性集中度
D. 文字密度代理     —— 高频能量比（文字/线条多则高频强）、边缘密度、大色块占比

用法:
  python3 thumb_features.py extract          # 全量提取 -> thumb_features.jsonl
  python3 thumb_features.py extract --limit 20
  python3 thumb_features.py stats            # 汇总
"""
import hashlib
import io
import json
import math
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/hatch/data")
from relay import urlopen as _urlopen  # noqa

YT = Path("/home/hatch/data/youtube")
HIST = YT / "uploads_full.jsonl"
OUT = YT / "thumb_features.jsonl"
CACHE = YT / "thumb_cache"
SIZE = "maxresdefault"


def fetch_thumb(video_id):
    """下载封面（带磁盘缓存）。返回 bytes 或 None。"""
    CACHE.mkdir(exist_ok=True)
    cp = CACHE / f"{video_id}.jpg"
    if cp.exists() and cp.stat().st_size > 1000:
        return cp.read_bytes()
    for size in (SIZE, "hqdefault"):
        u = f"https://i.ytimg.com/vi/{video_id}/{size}.jpg"
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            b = _urlopen(req, timeout=25).read()
            if len(b) > 1000:
                cp.write_bytes(b)
                return b
        except Exception:
            continue
    return None


def analyze(raw):
    """封面 bytes -> 特征 dict（全部可解释）。"""
    from PIL import Image
    import numpy as np

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w0, h0 = im.size
    # 240x144 便于 12x12 分块统计（240/12=20, 144/12=12）
    im = im.resize((240, 144), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)           # (144,256,3)
    gray = a @ np.array([0.299, 0.587, 0.114], dtype=np.float32)  # (144,256)

    f = {}
    # --- A. 亮度与对比 ---
    f["lum_mean"] = round(float(gray.mean()), 2)
    f["lum_std"] = round(float(gray.std()), 2)
    f["dark_ratio"] = round(float((gray < 50).mean()), 3)
    f["bright_ratio"] = round(float((gray > 205).mean()), 3)

    # --- B. 色彩活力 ---
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    f["sat_mean"] = round(float(sat.mean()), 3)
    f["sat_high_ratio"] = round(float((sat > 0.5).mean()), 3)
    # 色相熵
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    hue = np.zeros_like(r)
    d = mx - mn
    m = d > 1e-6
    idx = (mx == r) & m
    hue[idx] = (60 * ((g[idx] - b[idx]) / d[idx]) + 360) % 360
    idx = (mx == g) & m
    hue[idx] = 60 * ((b[idx] - r[idx]) / d[idx]) + 120
    idx = (mx == b) & m
    hue[idx] = 60 * ((r[idx] - g[idx]) / d[idx]) + 240
    hist, _ = np.histogram(hue[m], bins=12, range=(0, 360))
    p = hist / max(hist.sum(), 1)
    p = p[p > 0]
    f["hue_entropy"] = round(float(-(p * np.log2(p)).sum()), 3)
    warm = ((hue < 60) | (hue > 300)) & m
    f["warm_ratio"] = round(float(warm.mean()), 3)

    # --- C. 构图与视觉重心 ---
    H, W = gray.shape
    h3, w3 = H // 3, W // 3
    # 三分法：4 个交点附近的"能量"占比（能量=与均值的绝对偏差）
    e = np.abs(gray - gray.mean())
    tot = e.sum() + 1e-6
    pts = []
    for cy in (h3, 2 * h3):
        for cx in (w3, 2 * w3):
            pts.append(e[max(0, cy - 18):cy + 18, max(0, cx - 18):cx + 18].sum())
    f["rule_of_thirds"] = round(float(sum(pts) / tot), 4)
    # 主体居中度：中心 1/3 区域的能量占比
    f["center_energy"] = round(float(
        e[h3:2 * h3, w3:2 * w3].sum() / tot), 4)
    # 显著性集中度：能量分布熵的归一化（低=有明确焦点）
    eb = e.reshape(12, 12, 20, 12).sum(axis=(1, 3)).ravel()  # 12x20 网格
    pb = eb / max(eb.sum(), 1e-6)
    pb = pb[pb > 0]
    f["salience_entropy"] = round(float(-(pb * np.log2(pb)).sum() / math.log2(240)), 3)

    # --- D. 文字密度代理 ---
    # 高频能量：与 3x3 均值模糊的差
    k = np.ones((3, 3), np.float32) / 9.0
    pad = np.pad(gray, 1, mode="edge")
    blur = np.zeros_like(gray)
    for dy in range(3):
        for dx in range(3):
            blur += k[dy, dx] * pad[dy:dy + H, dx:dx + W]
    hf = np.abs(gray - blur)
    f["highfreq_mean"] = round(float(hf.mean()), 3)
    f["highfreq_ratio"] = round(float((hf > 18).mean()), 4)
    # 边缘密度（Sobel 近似，用差分）
    gx = np.abs(np.diff(gray, axis=1)).mean()
    gy = np.abs(np.diff(gray, axis=0)).mean()
    f["edge_density"] = round(float((gx + gy) / 2), 3)
    # 大色块占比：量化到 5 级后，众数色占比
    q = (gray // 51).astype(np.int32)
    cnt = np.bincount(q.ravel(), minlength=5)
    f["dominant_band_ratio"] = round(float(cnt.max() / q.size), 3)

    f["_size"] = f"{w0}x{h0}"
    f["_bytes"] = len(raw)
    return f


def cmd_extract(limit=None):
    rows = [json.loads(l) for l in HIST.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("views", 0) > 0]
    if limit:
        rows = rows[:limit]
    print(f"# rows={len(rows)}", flush=True)

    done = {}
    if OUT.exists():
        for l in OUT.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    r = json.loads(l)
                    done[r["video_id"]] = 1
                except Exception:
                    pass
    print(f"# cached results={len(done)}", flush=True)

    n_ok = n_fail = 0
    fh = OUT.open("a", encoding="utf-8")
    for i, r in enumerate(rows):
        vid = r["video_id"]
        if vid in done:
            continue
        raw = fetch_thumb(vid)
        if not raw:
            n_fail += 1
            print(f"[{i+1}/{len(rows)}] {vid} FAIL", flush=True)
            continue
        try:
            f = analyze(raw)
        except Exception as e:
            n_fail += 1
            print(f"[{i+1}/{len(rows)}] {vid} ANALYZE-ERR {type(e).__name__}: {e}", flush=True)
            continue
        rec = {"video_id": vid, "views": r["views"], "title": r["title"][:80], **f}
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        n_ok += 1
        if (i + 1) % 20 == 0:
            print(f"[{i+1}/{len(rows)}] ok={n_ok} fail={n_fail}", flush=True)
    fh.close()
    print(f"# DONE ok={n_ok} fail={n_fail} -> {OUT}", flush=True)


def cmd_stats():
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"# rows={len(rows)}")
    keys = [k for k in rows[0] if not k.startswith("_") and k not in ("video_id", "views", "title")]
    import statistics as st
    print(f"{'feature':<22}{'min':>10}{'mean':>10}{'max':>10}")
    for k in keys:
        v = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        if v:
            print(f"{k:<22}{min(v):>10.3f}{st.mean(v):>10.3f}{max(v):>10.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "extract":
        lim = None
        if "--limit" in sys.argv:
            lim = int(sys.argv[sys.argv.index("--limit") + 1])
        cmd_extract(lim)
    else:
        cmd_stats()
