#!/usr/bin/env python3
"""美学下限门（warn 级原型）：mp4 → 1fps 抽帧 → LAION 美学打分 → JSON。

用法: python3 aesthetic_gate.py <video.mp4> [--fps 1] [--threshold 4.5]
输出: {"video":..., "n_frames":N, "mean":x, "min":y, "worst_frame_t":t,
        "scores":[...], "below_threshold": bool}
退出码恒为 0（只打分不拦截；拦截决策由调用方做）。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

DEFAULT_THRESHOLD = 4.5  # 校准后可调；见 CALIBRATION.md


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=30)
    return float(out.stdout.strip())


def extract_frames(path, fps, tmpdir):
    """按 fps 抽帧为 jpg，返回按时间排序的帧文件列表。"""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", path,
         "-vf", f"fps={fps}", os.path.join(tmpdir, "f_%04d.jpg")],
        check=True, timeout=120)
    files = sorted(f for f in os.listdir(tmpdir) if f.endswith(".jpg"))
    return [os.path.join(tmpdir, f) for f in files]


_PREDICTOR = None
_PROCESSOR = None
_MODEL_ID = "shunk031/aesthetics-predictor-v1-vit-large-patch14"


def _load():
    global _PREDICTOR, _PROCESSOR
    if _PREDICTOR is None:
        import torch
        from transformers import CLIPProcessor
        from aesthetics_predictor import AestheticsPredictorV1
        _PROCESSOR = CLIPProcessor.from_pretrained(_MODEL_ID)
        _PREDICTOR = AestheticsPredictorV1.from_pretrained(_MODEL_ID)
        _PREDICTOR.eval()
    return _PREDICTOR, _PROCESSOR


def score_frames(frame_paths, batch_size=16):
    """批量推理（CPU 上 batch 比单帧快约 3 倍）。"""
    import torch
    from PIL import Image
    predictor, processor = _load()
    scores = []
    with torch.no_grad():
        for i in range(0, len(frame_paths), batch_size):
            chunk = frame_paths[i:i + batch_size]
            imgs = [Image.open(fp).convert("RGB") for fp in chunk]
            inputs = processor(images=imgs, return_tensors="pt")
            out = predictor(**inputs)
            logits = out.logits.squeeze()
            if logits.dim() == 0:
                scores.append(float(logits))
            else:
                scores.extend(float(x) for x in logits.tolist())
    return scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()

    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        print(json.dumps({"error": f"文件不存在: {video}"}), flush=True)
        return 0
    try:
        dur = ffprobe_duration(video)
    except Exception as e:
        print(json.dumps({"error": f"ffprobe 失败: {e}"}), flush=True)
        return 0

    result = {"video": video, "duration": round(dur, 2),
              "threshold": args.threshold}
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            frames = extract_frames(video, args.fps, tmpdir)
            if not frames:
                result["error"] = "抽帧为空"
            else:
                scores = score_frames(frames)
                result["n_frames"] = len(scores)
                result["mean"] = round(sum(scores) / len(scores), 3)
                result["min"] = round(min(scores), 3)
                worst_i = scores.index(min(scores))
                result["worst_frame_t"] = round(worst_i / args.fps, 2)
                result["scores"] = [round(s, 3) for s in scores]
                result["below_threshold"] = result["mean"] < args.threshold
    except Exception as e:
        result["error"] = f"打分失败: {type(e).__name__}: {e}"
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
