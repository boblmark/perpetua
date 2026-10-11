#!/usr/bin/env python3
"""视频生成后处理链（播放中变量硬门禁）。

战略（2026-10-09 用户定）：质量关从"生成端"移到"后期端"——生成模型
只是可替换的原材料供应商（Veo / GeminiGen / H3 任意），最终达标/超标
靠本链的 QC 感知修复保证。不再依赖某个模型的生成质量。

顺序：
  0. qc_repair — QC 感知修复（新增 2026-10-09）：机械门在后期直接修好，
     不打回重生成。R1 切头尾黑帧（blackframe 门）；R2 重定起始帧到首个
     人脸≥30% 的帧（frame0_face 门）；R3 loop 不通过时搜索尾部切点找
     能通过的循环点。每步 fail-safe（失败记 warn 用原片继续），时长
     守卫：任何修剪不得使时长 <7.5s（QC 时长门）。
  1. loop_check.py — 无缝循环验证（r=0.82 最强信号），R3 修不好才打回重生成
  2. burn_subtitles.py — 烧录字幕（静音默认环境），缺依赖时合规跳过
  3. audio_envelope — v5 1.2-Second Karen Snap 音频包络：0.00s 从 70% 起步，
     2 秒内线性爬升至 100%，之后保持（ffmpeg volume 表达式强制执行，
     不依赖生成模型——Muse Video 不接受音频输入，prompt 里写也没用）

用法：
    python3 postprocess_video.py <video.mp4> [--json] [--skip-repair] [--skip-loop] [--skip-subs] [--skip-audio]

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
YUNET_MODEL = os.path.join(BASE, "models", "face_detection_yunet_2023mar.onnx")

# QC 感知修复的时长守卫：任何修剪不得使成品短于此时长（QC 时长门 7.5-11s）。
REPAIR_MIN_DURATION = 7.5


def _probe_duration(video):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _reencode_trim(video, ss, t, suffix):
    """ss 起始秒、t 时长秒，重编码修剪。返回 (ok, out_path)。"""
    base, ext = os.path.splitext(video)
    out = f"{base}.{suffix}{ext}"
    cmd = ["ffmpeg", "-y", "-ss", f"{ss:.3f}", "-i", video,
           "-t", f"{t:.3f}",
           "-c:v", "libx264", "-crf", "18", "-preset", "fast",
           "-c:a", "aac", "-b:a", "192k", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(out):
        return False, None
    if _probe_duration(out) < REPAIR_MIN_DURATION - 0.05:
        try:
            os.remove(out)
        except OSError:
            pass
        return False, None
    return True, out


def _repair_black_trim(video):
    """R1: 切除头尾黑帧（blackframe 门）。返回 (changed, out_path)。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", video,
         "-vf", "blackdetect=d=0.15:pic_th=0.98", "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    blacks = []
    for line in r.stderr.splitlines():
        if "black_start" in line:
            try:
                bs = float(line.split("black_start:")[1].split()[0])
                be = float(line.split("black_end:")[1].split()[0])
                blacks.append((bs, be))
            except (IndexError, ValueError):
                pass
    if not blacks:
        return False, video
    dur = _probe_duration(video)
    ss, end = 0.0, dur
    for bs, be in blacks:
        if bs <= 0.05:
            ss = max(ss, be)          # 头部黑帧
        if be >= dur - 0.05:
            end = min(end, bs)        # 尾部黑帧
    if ss < 0.05 and end > dur - 0.05:
        return False, video
    t = end - ss
    if t < REPAIR_MIN_DURATION:
        _log(f"[postprocess] R1 black-trim 跳过：修剪后 {t:.2f}s < {REPAIR_MIN_DURATION}s")
        return False, video
    ok, out = _reencode_trim(video, ss, t, "r1")
    if ok:
        _log(f"[postprocess] R1 black-trim: ss={ss:.2f}s t={t:.2f}s -> {out}")
        return True, out
    return False, video


def _face_ratio_yunet(det, frame):
    """与 pre_upload_qc._check_frame0_face 同口径：YuNet 框 1.5x 扩展后占比。"""
    h, w = frame.shape[:2]
    _, faces = det.detect(frame)
    if faces is None or len(faces) == 0:
        return 0.0
    f_best = max(faces, key=lambda f: f[2] * f[3])
    fx, fy, fbw, fbh = f_best[0], f_best[1], f_best[2], f_best[3]
    fcx, fcy = fx + fbw / 2, fy + fbh / 2
    few, feh = fbw * 1.5, fbh * 1.5
    fx1 = max(0, fcx - few / 2); fy1 = max(0, fcy - feh / 2)
    fx2 = min(w, fcx + few / 2); fy2 = min(h, fcy + feh / 2)
    return (fx2 - fx1) * (fy2 - fy1) / (h * w)


def _repair_face_start(video):
    """R2: 起始帧重定到首个人脸≥30% 的帧（frame0_face 门）。返回 (changed, out_path)。"""
    try:
        import cv2
    except ImportError:
        _log("[postprocess] R2 face-start 跳过：cv2 不可用")
        return False, video
    if not os.path.exists(YUNET_MODEL):
        _log("[postprocess] R2 face-start 跳过：YuNet 模型缺失")
        return False, video
    dur = _probe_duration(video)
    if dur <= 0:
        return False, video
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    try:
        det = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (w, h), 0.5, 0.3, 5000)
    except Exception as e:
        cap.release()
        _log(f"[postprocess] R2 face-start 跳过：YuNet 初始化失败 {e}")
        return False, video
    found_t = None
    # 扫描前 2.5s，每 0.1s 一帧
    t = 0.0
    while t <= min(2.5, dur - REPAIR_MIN_DURATION):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret and frame is not None:
            try:
                if _face_ratio_yunet(det, frame) >= 0.30:
                    found_t = t
                    break
            except Exception:
                pass
        t += 0.1
    cap.release()
    if found_t is None or found_t < 0.05:
        return False, video
    t_remain = dur - found_t
    if t_remain < REPAIR_MIN_DURATION:
        _log(f"[postprocess] R2 face-start 跳过：剩余 {t_remain:.2f}s < {REPAIR_MIN_DURATION}s")
        return False, video
    ok, out = _reencode_trim(video, found_t, t_remain, "r2")
    if ok:
        _log(f"[postprocess] R2 face-start: 首脸在 {found_t:.1f}s -> {out}")
        return True, out
    return False, video


def _run_loop_check(video):
    try:
        r = subprocess.run(
            [sys.executable, LOOP_CHECK, video, "--json"],
            capture_output=True, text=True, timeout=120)
        detail = json.loads(r.stdout.strip().splitlines()[-1])
        return bool(detail.get("passed")), detail
    except Exception as e:
        return False, {"error": str(e)[:200]}


def _repair_loop_point(video):
    """R3: loop 不通过时，从尾部每次多切 0.1s（最多 1.0s）找能通过的循环点。"""
    passed, detail = _run_loop_check(video)
    if passed:
        return False, video, detail
    dur = _probe_duration(video)
    _log(f"[postprocess] R3 loop-point: 原始 similarity={detail.get('similarity')}，尝试尾部切点搜索")
    cut = 0.1
    while cut <= 1.0 + 1e-6:
        t = dur - cut
        if t < REPAIR_MIN_DURATION:
            break
        ok, cand = _reencode_trim(video, 0.0, t, "r3tmp")
        if not ok:
            cut += 0.1
            continue
        p2, d2 = _run_loop_check(cand)
        if p2:
            # 落盘为正式 r3 文件
            base, ext = os.path.splitext(video)
            final = f"{base}.r3{ext}"
            os.replace(cand, final)
            _log(f"[postprocess] R3 loop-point: 切尾 {cut:.1f}s 后 similarity={d2.get('similarity')} 通过 -> {final}")
            return True, final, d2
        try:
            os.remove(cand)
        except OSError:
            pass
        cut += 0.1
    _log("[postprocess] R3 loop-point: 1.0s 内未找到通过切点，保持原片（走重生成）")
    return False, video, detail


def qc_repair(video):
    """QC 感知修复：R1 黑帧修剪 → R2 人脸起始帧 → （R3 在 loop_check 失败时触发）。

    每步 fail-safe：失败记 warn 用原片继续。返回 (ok, repaired_path, repairs[])。
    """
    repairs = []
    cur = video
    for name, fn in (("R1_black_trim", _repair_black_trim),
                     ("R2_face_start", _repair_face_start)):
        try:
            changed, cur = fn(cur)
            repairs.append({"step": name, "applied": changed, "output": cur})
        except Exception as e:
            _log(f"[postprocess] {name} 异常跳过：{e}")
            repairs.append({"step": name, "applied": False, "error": str(e)[:200]})
    return True, cur, repairs


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


# v5 1.2-Second Karen Snap 音频包络：0.00s=70%，2.00s=100%，之后保持 100%。
# 四脑会诊 2026-10-08 修正：MUST 先切开头静音再套包络（顺序反了会吃掉爬坡窗口）。
# 2026-10-08 补充：Veo 原生音频开头常为淡入（-inf），包络前加 loudnorm
# 标准化到 -16 LUFS，保证 70% 起振有实际音量。单次 ffmpeg 完成。
# 2026-10-08 实测：Veo 淡入从 -39dB 开始，-50dB 阈值切不掉，改用 -30dB。
# 2026-10-08 再补：淡入是渐进的，切完首帧仍只有 -22dB。开头 0.5s 加 2x
# 增益（+6dB）确保过 -18dBFS 门，之后接正常 70%→100% 包络。
# ffmpeg volume 表达式（eval=frame 逐帧求值）：
AUDIO_FILTER_CHAIN = (
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-30dB,"
    "loudnorm=I=-16:TP=-1.5:LRA=11,"
    "volume='if(lt(t,0.5),2.0,if(lt(t,2),0.7+0.15*t,1))':eval=frame"
)
AUDIO_ENVELOPE_EXPR = "if(lt(t,0.5),2.0,if(lt(t,2),0.7+0.15*t,1))"  # 保留供日志/校验引用


def apply_audio_envelope(video):
    """对视频音频施加 v5 包络：先切开头静音，再 70%→100% 爬坡。返回 (ok, output_path)。"""
    base, ext = os.path.splitext(video)
    out = f"{base}.envelope{ext}"
    cmd = [
        "ffmpeg", "-y", "-i", video,
        "-af", AUDIO_FILTER_CHAIN,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(out):
        _log(f"[postprocess] audio_envelope FAIL: {r.stderr[-300:]}")
        return False, None
    # 验证输出有音频流
    rp = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", out],
        capture_output=True, text=True, timeout=30)
    if not rp.stdout.strip():
        _log("[postprocess] audio_envelope FAIL: 输出无音频流")
        return False, None
    _log(f"[postprocess] audio_envelope {video} -> {out}")
    return True, out


def apply_karma_thud(video):
    """2026-10-09 议会决议 #1（Karma Drop）：在 karma 冲击点合成单次干声重击。

    - 冲击点 impact_t = min(5.8, duration*0.725)，自适应 7.5-11s 片长
    - 冲击前 0.25s 环境音压到 10%（duck），冲击点 55Hz 正弦 burst
      400ms 指数衰减，峰值 ≤-6dBFS（amplitude 0.5）
    - NEVER 电影感 bass drop；NEVER 静音对白（只 duck 环境音）
    - 失败 → (False, None)，调用方记 warn 继续，不阻塞交付
    """
    try:
        dur = _probe_duration(video)
    except Exception:
        dur = 8.0
    impact_t = min(5.8, (dur or 8.0) * 0.725)
    duck_start = max(0.0, impact_t - 0.25)
    delay_ms = int(impact_t * 1000)
    base, ext = os.path.splitext(video)
    out = f"{base}.thud{ext}"
    fc = (
        f"[0:a]volume='if(between(t,{duck_start:.2f},{impact_t:.2f}),0.1,1)'"
        f":eval=frame[a0];"
        f"aevalsrc='sin(2*PI*55*t)*exp(-6*t)':d=0.4:s=44100,"
        f"volume=0.5,adelay={delay_ms}|{delay_ms}[thud];"
        f"[a0][thud]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    cmd = ["ffmpeg", "-y", "-i", video, "-filter_complex", fc,
           "-map", "0:v", "-map", "[aout]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        _log(f"[postprocess] karma_thud 异常：{e}")
        return False, None
    if r.returncode != 0 or not os.path.exists(out):
        _log(f"[postprocess] karma_thud FAIL: {r.stderr[-300:]}")
        return False, None
    _log(f"[postprocess] karma_thud {video} -> {out} (impact@{impact_t:.2f}s)")
    return True, out


def run_postprocess(video, skip_loop=False, skip_subs=False, skip_audio=False,
                    skip_repair=False):
    """返回 (ok: bool, result: dict)。ok=False 意味着应打回重生成。"""
    result = {"video": video, "steps": {}}
    final_video = video

    # 0. QC 感知修复（2026-10-09）：机械门在后期修，不打回。fail-safe。
    if not skip_repair:
        try:
            _, repaired, repairs = qc_repair(final_video)
            result["steps"]["qc_repair"] = repairs
            final_video = repaired
            _log(f"[postprocess] qc_repair {video} -> {final_video} "
                 f"({sum(1 for r in repairs if r['applied'])} 步生效)")
        except Exception as e:
            _log(f"[postprocess] qc_repair 异常跳过：{e}")
            result["steps"]["qc_repair"] = [{"step": "qc_repair",
                                             "applied": False,
                                             "error": str(e)[:200]}]

    if not skip_loop:
        passed, detail = _run_loop_check(final_video)
        result["steps"]["loop_check"] = detail
        _log(f"[postprocess] loop_check {final_video}: "
             f"{'PASS' if passed else 'FAIL'} "
             f"(similarity={detail.get('similarity')})")
        if not passed and not skip_repair:
            # R3：loop 不通过先尝试尾部切点修复，修不好才打回重生成
            try:
                changed, repaired_lp, detail2 = _repair_loop_point(final_video)
                result["steps"]["R3_loop_point"] = {
                    "applied": changed, "detail": detail2}
                if changed:
                    final_video = repaired_lp
                    passed = True
                    result["steps"]["loop_check"] = detail2
            except Exception as e:
                _log(f"[postprocess] R3_loop_point 异常：{e}")
        if not passed:
            result["ok"] = False
            result["reason"] = (
                "loop_check FAIL: first/last frame similarity "
                f"{detail.get('similarity')} < {detail.get('threshold', 0.85)} — "
                "R3 切点修复无效，regenerate with stronger loop-match prompt")
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

    # 3. v5 音频包络（最后一步，作用于最终画面版本）
    if not skip_audio:
        ok, enveloped = apply_audio_envelope(final_video)
        result["steps"]["audio_envelope"] = {
            "ok": ok, "output": enveloped,
            "expr": AUDIO_ENVELOPE_EXPR,
        }
        if ok and enveloped:
            final_video = enveloped
        else:
            # 包络失败不打回（音频形状是优化项，不是硬门禁），记 warn 继续
            _log("[postprocess] audio_envelope 失败，继续用烧录版本交付")
            result["steps"]["audio_envelope"]["warn"] = True

    # 4. Karma Drop（2026-10-09 议会 #1）：冲击点单次干声重击。
    # 失败不打回，记 warn 继续（音频是优化项，不是硬门禁）。
    if not skip_audio:
        ok, thudded = apply_karma_thud(final_video)
        result["steps"]["karma_thud"] = {"ok": ok, "output": thudded}
        if ok and thudded:
            final_video = thudded
        else:
            _log("[postprocess] karma_thud 失败，继续用包络版本交付")
            result["steps"]["karma_thud"]["warn"] = True

    result["ok"] = True
    result["final_video"] = final_video
    return True, result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    skip_loop = "--skip-loop" in sys.argv
    skip_subs = "--skip-subs" in sys.argv
    skip_audio = "--skip-audio" in sys.argv
    skip_repair = "--skip-repair" in sys.argv
    if not args:
        print("usage: postprocess_video.py <video.mp4> [--json] "
              "[--skip-repair] [--skip-loop] [--skip-subs] [--skip-audio]",
              file=sys.stderr)
        sys.exit(2)
    ok, result = run_postprocess(args[0], skip_loop, skip_subs, skip_audio,
                                 skip_repair)
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"postprocess {'PASS' if ok else 'FAIL'}: "
              f"{result.get('reason', result.get('final_video'))}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
