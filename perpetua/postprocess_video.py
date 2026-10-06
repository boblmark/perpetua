#!/usr/bin/env python3
"""视频生成后处理链（播放中变量硬门禁）。

顺序：
  1. loop_check.py — 无缝循环验证（r=0.82 最强信号），不通过 → 打回重生成
  2. burn_subtitles.py — 烧录字幕（静音默认环境），缺依赖时合规跳过

用法：
    python3 postprocess_video.py <video.mp4> [--json] [--skip-loop] [--skip-subs]

退出码：0=全部通过（或合规跳过），1=循环验证不通过（应重生成），2=错误。

给 mcp-media-job-processor 的接线说明：
  生成 mp4 后运行此脚本；exit=1 时用同一 prompt 重生成（最多 2 次）；
  exit=0 时若输出含 "subtitled" 则用 .subtitled.mp4 作为最终交付文件。
"""

import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
LOOP_CHECK = os.path.join(BASE, "loop_check.py")
BURN_SUBS = os.path.join(BASE, "burn_subtitles.py")
LOG = os.path.join(BASE, "postprocess.log")


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def run_postprocess(video, skip_loop=False, skip_subs=False):
    """返回 (ok: bool, result: dict)。ok=False 意味着应打回重生成。"""
    result = {"video": video, "steps": {}}
    final_video = video

    if not skip_loop:
        r = subprocess.run(
            [sys.executable, LOOP_CHECK, video, "--json"],
            capture_output=True, text=True, timeout=120)
        try:
            detail = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            detail = {"error": r.stderr[-300:] or "loop_check crashed"}
        passed = bool(detail.get("passed"))
        result["steps"]["loop_check"] = detail
        _log(f"[postprocess] loop_check {video}: "
             f"{'PASS' if passed else 'FAIL'} "
             f"(similarity={detail.get('similarity')})")
        if not passed:
            result["ok"] = False
            result["reason"] = (
                "loop_check FAIL: first/last frame similarity "
                f"{detail.get('similarity')} < {detail.get('threshold', 0.85)} — "
                "regenerate with stronger loop-match prompt")
            return False, result

    if not skip_subs:
        r = subprocess.run(
            [sys.executable, BURN_SUBS, video],
            capture_output=True, text=True, timeout=600)
        out = r.stdout.strip().splitlines()
        burned = None
        for line in reversed(out):
            try:
                d = json.loads(line)
                burned = d.get("output")
                break
            except Exception:
                continue
        result["steps"]["burn_subtitles"] = {
            "exit": r.returncode,
            "burned": burned,
            "skipped": burned is None and r.returncode == 0,
        }
        if burned:
            final_video = burned
        _log(f"[postprocess] burn_subtitles {video}: "
             f"{'burned -> ' + burned if burned else 'skipped/no-op'}")

    result["ok"] = True
    result["final_video"] = final_video
    return True, result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    skip_loop = "--skip-loop" in sys.argv
    skip_subs = "--skip-subs" in sys.argv
    if not args:
        print("usage: postprocess_video.py <video.mp4> [--json] "
              "[--skip-loop] [--skip-subs]", file=sys.stderr)
        sys.exit(2)
    ok, result = run_postprocess(args[0], skip_loop, skip_subs)
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"postprocess {'PASS' if ok else 'FAIL'}: "
              f"{result.get('reason', result.get('final_video'))}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
