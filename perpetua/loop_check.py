#!/usr/bin/env python3
"""无缝循环验证（播放中变量，r=0.82 与播放量相关性最强信号）。

对比视频首帧与尾帧：直方图相关 + 像素均值差异。
相似度 >0.85 判为无缝循环通过。

用法：
    python3 loop_check.py <video.mp4> [--threshold 0.85] [--json]

退出码：0=通过，1=不通过，2=错误（文件不可读等）。
"""

import cv2
import json
import numpy as np
import os
import sys


def _frame_similarity(f1, f2):
    """综合相似度 0-1：直方图相关(0.6) + 归一化像素差异(0.4)。"""
    # 直方图相关（HSV，抗亮度小幅波动）
    hsv1 = cv2.cvtColor(f1, cv2.COLOR_BGR2HSV)
    hsv2 = cv2.cvtColor(f2, cv2.COLOR_BGR2HSV)
    hist1 = cv2.calcHist([hsv1], [0, 1], None, [32, 32], [0, 180, 0, 256])
    hist2 = cv2.calcHist([hsv2], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    hist_corr = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)  # -1..1
    hist_corr = max(0.0, min(1.0, (hist_corr + 1.0) / 2.0))

    # 像素均值绝对差异（下采样到 64x36 加速）
    s1 = cv2.resize(f1, (64, 36)).astype(np.float32) / 255.0
    s2 = cv2.resize(f2, (64, 36)).astype(np.float32) / 255.0
    mad = float(np.mean(np.abs(s1 - s2)))  # 0..1，越小越像
    pix_sim = max(0.0, 1.0 - mad * 3.0)  # 差异>0.33 视为完全不像

    return 0.6 * hist_corr + 0.4 * pix_sim, {
        "hist_corr": round(hist_corr, 4),
        "pixel_sim": round(pix_sim, 4),
        "mean_abs_diff": round(mad, 4),
    }


def check_loop(video_path, threshold=0.85):
    """返回 (passed: bool, detail: dict)。"""
    if not os.path.isfile(video_path):
        return False, {"error": f"file not found: {video_path}"}
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, {"error": f"cannot open video: {video_path}"}
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total < 2:
            return False, {"error": "video has fewer than 2 frames"}
        ok1, first = cap.read()
        cap.set(cv2.CAP_PROP_POS_FRAMES, total - 1)
        ok2, last = cap.read()
        if not (ok1 and ok2):
            return False, {"error": "failed to read first/last frame"}
        score, parts = _frame_similarity(first, last)
        detail = {
            "video": video_path,
            "frames": total,
            "similarity": round(score, 4),
            "threshold": threshold,
            "passed": score >= threshold,
            **parts,
        }
        return score >= threshold, detail
    finally:
        cap.release()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    threshold = 0.85
    for a in sys.argv[1:]:
        if a.startswith("--threshold"):
            threshold = float(a.split("=")[1] if "=" in a else sys.argv[sys.argv.index(a) + 1])
    if not args:
        print("usage: loop_check.py <video.mp4> [--threshold 0.85] [--json]", file=sys.stderr)
        sys.exit(2)
    passed, detail = check_loop(args[0], threshold)
    if as_json:
        print(json.dumps(detail, ensure_ascii=False))
    else:
        print(f"similarity={detail.get('similarity')} threshold={threshold} "
              f"-> {'PASS' if passed else 'FAIL'}")
        if "error" in detail:
            print(f"error: {detail['error']}", file=sys.stderr)
    sys.exit(0 if passed else (2 if "error" in detail else 1))


if __name__ == "__main__":
    main()
