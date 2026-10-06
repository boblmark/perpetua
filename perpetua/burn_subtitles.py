#!/usr/bin/env python3
"""烧录字幕（播放中变量：60%+ 用户初始静音观看，无字幕=划走）。

流程：Whisper 转录 → 生成 srt → ffmpeg 烧录到画面底部安全区上方
（避开底部 25% 标题遮挡区，字幕放在 62%-72% 高度带）。

依赖检查：whisper 不可用 → 记录原因并跳过（exit 0，不阻塞）；
ffmpeg 不可用 → 同样跳过。若同目录已存在同名 .srt 则直接烧录。

用法：
    python3 burn_subtitles.py <video.mp4> [--lang en] [--force]

输出：<video>.subtitled.mp4（成功时）；跳过时原文件不动。
退出码：0=成功或合规跳过，2=错误。
"""

import json
import os
import shutil
import subprocess
import sys

LOG = "/home/hatch/data/perpetua/subtitle_burn.log"


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    print(msg)


def _have(cmd):
    return shutil.which(cmd) is not None


def _have_whisper():
    try:
        import whisper  # noqa
        return True
    except ImportError:
        return False


def _transcribe(video, lang="en"):
    """返回 srt 路径；whisper 不可用时返回 None。"""
    import whisper
    _log(f"[burn_subtitles] transcribing {video} (whisper base, lang={lang}) ...")
    model = whisper.load_model("base")
    result = model.transcribe(video, language=lang, fp16=False)
    srt_path = os.path.splitext(video)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(result.get("segments", []), 1):
            f.write(f"{i}\n{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}\n"
                    f"{seg['text'].strip()}\n\n")
    return srt_path


def _fmt_ts(sec):
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def _burn(video, srt):
    """ffmpeg 烧录字幕到 62%-72% 高度带（避开底部 25%）。返回输出路径。"""
    out = os.path.splitext(video)[0] + ".subtitled.mp4"
    # force_style: 字幕基线放在画面 68% 高度处，黄色描边黑字
    vf = (f"subtitles='{srt}':force_style="
          f"'FontSize=22,PrimaryColour=&H00FFFF&,OutlineColour=&H80000000&,"
          f"BorderStyle=1,Outline=2,Alignment=2,MarginV=120'")
    cmd = ["ffmpeg", "-y", "-i", video, "-vf", vf,
           "-c:a", "copy", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        _log(f"[burn_subtitles] ffmpeg failed: {r.stderr[-500:]}")
        return None
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lang = "en"
    for i, a in enumerate(sys.argv[1:]):
        if a == "--lang" and i + 1 < len(sys.argv[1:]):
            lang = sys.argv[1:][i + 1]
    if not args:
        print("usage: burn_subtitles.py <video.mp4> [--lang en]", file=sys.stderr)
        sys.exit(2)
    video = args[0]
    if not os.path.isfile(video):
        print(f"file not found: {video}", file=sys.stderr)
        sys.exit(2)

    # 依赖检查（任一缺失 → 记录并合规跳过，不阻塞流水线）
    if not _have("ffmpeg"):
        _log(f"[burn_subtitles] SKIP {video}: ffmpeg not available")
        sys.exit(0)
    srt = os.path.splitext(video)[0] + ".srt"
    if not os.path.isfile(srt):
        if not _have_whisper():
            _log(f"[burn_subtitles] SKIP {video}: whisper not installed "
                 f"(pip install openai-whisper to enable); no existing .srt")
            sys.exit(0)
        try:
            srt = _transcribe(video, lang)
        except Exception as e:
            _log(f"[burn_subtitles] SKIP {video}: transcribe failed: {e}")
            sys.exit(0)
    out = _burn(video, srt)
    if out:
        _log(f"[burn_subtitles] OK {video} -> {out}")
        print(json.dumps({"input": video, "output": out, "srt": srt}))
        sys.exit(0)
    sys.exit(2)


if __name__ == "__main__":
    main()
