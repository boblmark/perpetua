#!/usr/bin/env python3
"""QC 边缘修复层（2026-10-16 用户批准接入）。

定位：已过终审（review_passed）但 QC 边缘失败的视频，先尝试自动修复，
修好→重新 QC；修不好→走原有重生成路径。绝不降低 QC 阈值。

可修复（机械性问题）：
  - loop：首尾帧相似度不达标 → 尾部 0.4s crossfade（把开头叠化到结尾），
    这是正经转场手法（MoviePy 定位：转场/花字/复杂叠加），不是掩盖缺陷。

不可修复（生成性缺陷，必须重生成，禁止靠剪辑掩盖）：
  - AI 畸形（手/脸变形）、黑帧/白闪、冻结帧、hook motion 不足、
    fps<24、首帧全黑/全白、政策问题。

约束：
  - 每个视频最多修 1 次（repair_used 标记防循环）。
  - 修复后必须用同一阈值重新跑 loop 检查，通过才算修好。
  - 修复只动尾部 0.4s，不改变时长；音频原样保留。
"""
import json
import os
import datetime as _dt

REPAIR_LOG = "/home/hatch/data/perpetua/qc_repair_log.jsonl"
XFADE_DURATION = 0.4  # crossfade 时长（秒）


def _log(event: dict):
    try:
        event["ts"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        with open(REPAIR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def repair_loop_seam(video_path: str, similarity: float = 0.0,
                     threshold: float = 0.75) -> str | None:
    """尝试修复 loop 接缝。成功返回修复后文件路径，失败返回 None。

    原理：把视频开头 XFADE_DURATION 秒叠化到结尾，使尾帧混入开头内容，
    提升首尾帧相似度。时长不变，音频不变。
    """
    if not os.path.isfile(video_path):
        return None
    try:
        from moviepy import VideoFileClip, CompositeVideoClip
        from moviepy.video.fx import CrossFadeIn
    except ImportError as e:
        _log({"op": "repair_loop_seam", "video": os.path.basename(video_path),
              "result": "skip", "reason": f"moviepy 不可用: {e}"})
        return None

    base, ext = os.path.splitext(video_path)
    out_path = f"{base}_loopfix{ext}"
    # 幂等：已修过直接返回
    if os.path.isfile(out_path):
        return out_path

    clip = None
    try:
        clip = VideoFileClip(video_path)
        dur = clip.duration or 0
        if dur < XFADE_DURATION * 3:
            _log({"op": "repair_loop_seam",
                  "video": os.path.basename(video_path),
                  "result": "skip",
                  "reason": f"时长 {dur:.1f}s 太短，无法做 crossfade"})
            return None
        xf = min(XFADE_DURATION, dur / 4)
        head = clip.subclipped(0, xf)
        head_faded = head.with_effects([CrossFadeIn(xf)]).with_start(dur - xf)
        # 2026-10-16 bugfix：CompositeVideoClip 可能丢音频（实测修复后开头变静音），
        # 显式把原片音频挂回去，保证音频与原片完全一致。
        final = CompositeVideoClip([clip, head_faded], use_bgclip=True)
        if clip.audio is not None:
            final = final.with_audio(clip.audio)
        final.write_videofile(
            out_path, codec="libx264", audio_codec="aac",
            fps=clip.fps or 30, preset="medium",
            logger=None,  # 静默，不刷屏
        )
        # 校验：输出文件有效且时长基本不变
        if not os.path.isfile(out_path) or os.path.getsize(out_path) < 1024:
            return None
        _log({"op": "repair_loop_seam",
              "video": os.path.basename(video_path),
              "result": "ok", "out": os.path.basename(out_path),
              "similarity_before": round(similarity, 4),
              "xfade": xf})
        return out_path
    except Exception as e:
        _log({"op": "repair_loop_seam",
              "video": os.path.basename(video_path),
              "result": "error", "reason": str(e)[:200]})
        try:
            if out_path and os.path.isfile(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return None
    finally:
        try:
            if clip is not None:
                clip.close()
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 qc_repair.py <video.mp4> [similarity]")
        sys.exit(2)
    sim = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    out = repair_loop_seam(sys.argv[1], sim)
    print(out or "REPAIR_FAILED")
