#!/usr/bin/env python3
"""视频美化原型：CPU 纯 ffmpeg 滤镜链（无 GPU 可用时的务实路线）。

链路（按 vidfix 实战经验）：deblock → hqdn3d 轻降噪 → unsharp（仅 luma，适度）
→ eq 对比/饱和 → vibrance 提鲜艳（保护肤色）。

用法：python3 beautify.py <input.mp4> [--preset mild|pop] [--out <path>]
输出 JSON：{out, preset, elapsed_s, size_before, size_after}
美化是可选后处理，永不 fail-closed，不进 QC 拦截逻辑。
"""
import argparse
import json
import os
import subprocess
import sys
import time

PRESETS = {
    # mild：去噪+轻锐化，色彩几乎不动——求稳
    "mild": "hqdn3d=1.2:1.2:5:5,unsharp=5:5:0.6:5:5:0.0,eq=contrast=1.03:saturation=1.08",
    # pop：短视频爆款观感——降噪+锐化+对比饱和+vibrance
    "pop": (
        "hqdn3d=1.5:1.5:6:6,"
        "unsharp=5:5:0.8:5:5:0.0,"
        "eq=contrast=1.06:saturation=1.15:brightness=0.01,"
        "vibrance=intensity=0.25"
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="输入 mp4")
    ap.add_argument("--preset", choices=list(PRESETS), default="pop")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = args.input
    if not os.path.isfile(src):
        print(json.dumps({"ok": False, "error": f"not found: {src}"}))
        return 1
    out = args.out or os.path.splitext(src)[0] + f".beautified-{args.preset}.mp4"
    vf = PRESETS[args.preset]

    t0 = time.time()
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", src,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    if r.returncode != 0:
        print(json.dumps({"ok": False, "error": r.stderr[-500:]}))
        return 1
    print(json.dumps({
        "ok": True,
        "out": out,
        "preset": args.preset,
        "filter": vf,
        "elapsed_s": round(dt, 1),
        "size_before": os.path.getsize(src),
        "size_after": os.path.getsize(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
