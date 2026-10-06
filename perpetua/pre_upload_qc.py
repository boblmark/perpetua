#!/usr/bin/env python3
"""上传前统一质检门（最后一道门）：视频生成后、YouTube 上传前。

背景：10 个发布前门禁（标题/元数据/去重/人工终审）只覆盖权重 <1% 的变量。
算法 90%+ 权重在"播放中"信号（VVSA 60-65%、完播率 25%、循环率 r=0.82）。
本模块在上传前对成片做 10 项播放中变量检查，不达标自动修复（剪辑/烧字幕）
或打回，达标才放行上传。

fail-closed：任何检查返回 fail → passed=False，不允许上传。
warning 可过，fail 必须拦。自动修复成功后重新验证。

10 项检查：
  1. resolution  分辨率 9:16 竖屏 —— 偏离不大时自动中央裁剪修复；裁不掉则拒绝
  2. duration    时长 9-11s —— 超出自动 ffmpeg 裁到 11s；不足 9s 拒绝
  3. blackframe  黑帧/白闪（抽 5 帧，抄 etch181）—— 有坏帧直接拒绝（需重生成）
  4. firstframe  首帧静音测试（v2 P0）—— 全黑/全白拒绝；低对比度/无主体 warning
  5. loop       无缝循环（调 loop_check.check_loop，阈值 0.85）
                不通过 → 若有 regen_fn 则触发重生成（最多 2 次），否则拒绝
  6. climax      高潮时机（音频能量峰值应在 6.5-7.5s）—— warning
  7. tailcut     结尾拖尾（v2 P0：最后 1s 能量应骤降）—— warning
  8. audioclip   音频削波（ffmpeg volumedetect，抄 etch181）—— warning
  9. safezone    安全区（0s/5s/8s 三帧，危险区边缘密度启发式）—— warning
 10. subtitles  字幕烧录（调 burn_subtitles.py）—— 自动修复，失败不阻塞

用法：
    from pre_upload_qc import run_qc
    r = run_qc("/home/hatch/data/xxx.mp4", title="...")
    # r = {passed, checks, warnings, rejects, output_file, regen_used,
    #      needs_regen: bool（自动修不好，需重生成）}

接入点：MCP server 的 youtube_upload（_upload_hard_gates 之后）。
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/hatch/data/perpetua")
from loop_check import check_loop  # noqa: E402  (直接调用，不重复实现)

PERPETUA = "/home/hatch/data/perpetua"
QC_LOG = os.path.join(PERPETUA, "pre_upload_qc.log")

MIN_DUR, MAX_DUR = 9.0, 11.0
LOOP_THRESHOLD = 0.85
CLIMAX_RANGE = (6.5, 7.5)


def pipeline_log(stage, status="ok", detail="", count=0):
    """写 Perpetua 流水线遥测（pipeline_runs.json），失败不阻塞。"""
    import subprocess as _sp
    try:
        _sp.run(["python3", "/home/hatch/data/perpetua/pipeline.py",
                 "default", stage, status, detail[:200], str(count)],
                capture_output=True, timeout=10)
    except Exception:
        pass


def _log(obj):
    try:
        with open(QC_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _probe(video):
    """ffprobe 拿时长/分辨率/音频。返回 dict，失败返回 {error}。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=width,height,codec_type",
             "-of", "json", video],
            capture_output=True, text=True, timeout=30)
        info = json.loads(r.stdout or "{}")
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        return {
            "duration": float(info.get("format", {}).get("duration") or 0),
            "width": int(v.get("width") or 0),
            "height": int(v.get("height") or 0),
            "has_audio": has_audio,
        }
    except Exception as e:
        return {"error": str(e)}


def _check_resolution(probe):
    w, h = probe["width"], probe["height"]
    if not w or not h:
        return False, "无法读取分辨率"
    if w >= h:
        return False, f"非竖屏（{w}x{h}），Shorts 必须 9:16 竖屏"
    ratio = w / h
    if abs(ratio - 9 / 16) > 0.06:
        return False, f"宽高比 {ratio:.3f} 偏离 9:16（{w}x{h}）"
    return True, f"{w}x{h} 竖屏通过"


def _trim_duration(video, duration):
    """超出 11s → 取前 11s。返回新路径（失败返回 None）。"""
    base, ext = os.path.splitext(video)
    out = base + ".qc.mp4"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-t", str(MAX_DUR),
             "-c", "copy", out],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.isfile(out):
            return out
        return None
    except Exception:
        return None


def _check_climax(video, duration, has_audio):
    """音频能量峰值应在 6.5-7.5s。返回 (status, detail)，status ∈ pass/warn。"""
    if not has_audio:
        return "warn", "无音轨，无法判断高潮时机"
    wav = "/tmp/_qc_climax.wav"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-ac", "1", "-ar", "16000",
             "-f", "wav", wav],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return "warn", "音频提取失败，跳过高潮检查"
        import numpy as np
        import wave
        with wave.open(wav, "rb") as w:
            n = w.getnframes()
            raw = w.readframes(n)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio) == 0:
            return "warn", "音频为空"
        sr = 16000
        win = int(sr * 0.5)  # 0.5s 窗口
        nwin = max(1, len(audio) // win)
        energy = np.array([
            np.sqrt(np.mean(audio[i * win:(i + 1) * win] ** 2))
            for i in range(nwin)])
        if energy.max() <= 1e-6:
            return "warn", "音频全静音"
        peak_t = float(energy.argmax() * 0.5 + 0.25)
        lo, hi = CLIMAX_RANGE
        if lo <= peak_t <= hi:
            return "pass", f"能量峰值在 {peak_t:.1f}s（{lo}-{hi}s 达标）"
        return "warn", (f"能量峰值在 {peak_t:.1f}s，不在 {lo}-{hi}s —— "
                        "建议高潮（报应画面）落在 6.5-7.5s")
    except Exception as e:
        return "warn", f"高潮检查异常: {e}"
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def _check_safezone(video):
    """抽 0s/5s/8s 三帧：危险区（下 25% + 右 15%）边缘密度启发式。

    危险区边缘密度 > 1.5x 整帧 → 疑似关键文字/图形被 UI 遮挡 → warning。
    纯启发式，不阻塞。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return "warn", "cv2 不可用，跳过安全区检查"
    try:
        import cv2 as _cv
        cap = _cv.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过安全区检查"
        fps = cap.get(_cv.CAP_PROP_FPS) or 30
        hits = 0
        checked = 0
        for t in (0.0, 5.0, 8.0):
            cap.set(_cv.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            checked += 1
            h, w = frame.shape[:2]
            gray = _cv.cvtColor(frame, _cv.COLOR_BGR2GRAY)
            edges = _cv.Canny(gray, 80, 160)
            # 危险区：底部 25% + 右侧 15%
            danger = np.zeros_like(edges, dtype=bool)
            danger[int(h * 0.75):, :] = True
            danger[:, int(w * 0.85):] = True
            d_dens = float(edges[danger].mean()) if danger.any() else 0.0
            all_dens = float(edges.mean())
            if all_dens > 1e-6 and d_dens > 1.5 * all_dens:
                hits += 1
        cap.release()
        if checked == 0:
            return "warn", "抽帧失败，跳过安全区检查"
        if hits:
            return "warn", (f"{hits}/{checked} 帧危险区（下 25%/右 15%）边缘密度偏高 —— "
                            "关键文字可能被 Shorts UI 遮挡，建议移到上中部")
        return "pass", f"{checked} 帧安全区检查通过"
    except Exception as e:
        return "warn", f"安全区检查异常: {e}"


def _fix_resolution(video, probe):
    """宽高比偏离 9:16 → 中央裁剪修复。返回新路径；修不了返回 None（需重生成）。

    横屏视频裁到 9:16 会丢 >60% 画面，不自动修，直接标记重生成。
    """
    w, h = probe["width"], probe["height"]
    target = 9 / 16
    cur_ratio = w / h
    if abs(cur_ratio - target) <= 0.06:
        return None  # 已达标
    if cur_ratio > target:
        new_w, new_h = int(h * target), h      # 太宽 → 裁左右
    else:
        new_w, new_h = w, int(w / target)      # 太高 → 裁上下
    new_w -= new_w % 2
    new_h -= new_h % 2
    if (new_w * new_h) / (w * h) < 0.6:
        return None  # 裁掉太多，不自动修
    base, _ext = os.path.splitext(video)
    out = base + ".qc-crop.mp4"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-vf", f"crop={new_w}:{new_h}",
             "-c:a", "copy", out],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.isfile(out):
            return out
        return None
    except Exception:
        return None


def _check_black_frames(video, duration):
    """黑帧/白闪检测（v2 P0，抄 etch181）：抽 5 帧查全黑/全白 → fail。"""
    try:
        import cv2
    except ImportError:
        return "warn", "cv2 不可用，跳过黑帧检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过黑帧检查"
        bad = []
        for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
            t = duration * frac
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            import cv2 as _c
            gray = _c.cvtColor(frame, _c.COLOR_BGR2GRAY)
            m = float(gray.mean())
            if m < 5:
                bad.append(f"{t:.1f}s 全黑")
            elif m > 250:
                bad.append(f"{t:.1f}s 全白")
        cap.release()
        if bad:
            return "fail", "黑帧/白闪: " + "；".join(bad) + " —— 有坏帧，需重生成"
        return "pass", "5 帧亮度检查通过，无黑帧/白闪"
    except Exception as e:
        return "warn", f"黑帧检查异常: {e}"


def _check_first_frame(video):
    """首帧静音测试（v2 P0）：第一帧必须讲清概念。

    全黑/全白 → fail；中央 1/3 无主体或对比度过低 → warn。
    """
    try:
        import cv2
    except ImportError:
        return "warn", "cv2 不可用，跳过首帧检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过首帧检查"
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return "fail", "无法读取首帧，视频可能损坏"
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        bright = float(gray.mean())
        contrast = float(gray.std())
        if bright < 5:
            return "fail", f"首帧全黑（亮度 {bright:.1f}），渲染失败，需重生成"
        if bright > 250:
            return "fail", f"首帧全白（亮度 {bright:.1f}），渲染失败，需重生成"
        # 中央 1/3 主体：边缘密度启发式
        cx0, cx1, cy0, cy1 = w // 3, 2 * w // 3, h // 3, 2 * h // 3
        center = gray[cy0:cy1, cx0:cx1]
        edges = cv2.Canny(center, 80, 160)
        edge_dens = float(edges.mean())
        if contrast < 15:
            return "warn", f"首帧对比度低（{contrast:.1f}），画面可能平淡，钩子弱"
        if edge_dens < 2.0:
            return "warn", f"首帧中央缺乏明确主体（边缘密度 {edge_dens:.1f}），钩子可能弱"
        return "pass", (f"首帧通过（亮度 {bright:.0f}，对比度 {contrast:.0f}，"
                        f"中央边缘密度 {edge_dens:.1f}）")
    except Exception as e:
        return "warn", f"首帧检查异常: {e}"


def _check_audio_clip(video, has_audio):
    """音频削波检测（v2 P0，抄 etch181）：ffmpeg volumedetect → warn。"""
    if not has_audio:
        return "warn", "无音轨，跳过削波检查"
    try:
        import re
        r = subprocess.run(
            ["ffmpeg", "-i", video, "-af", "volumedetect",
             "-vn", "-sn", "-dn", "-f", "null", "/dev/null"],
            capture_output=True, text=True, timeout=60)
        err = r.stderr or ""
        m_max = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", err)
        m_clip = re.search(r"n_clipped:\s*(\d+)", err)
        max_vol = float(m_max.group(1)) if m_max else None
        n_clipped = int(m_clip.group(1)) if m_clip else 0
        if n_clipped > 100:
            return "warn", f"音频削波 {n_clipped} 个采样，音质受损（建议降增益重混）"
        if max_vol is not None and max_vol > -1.0 and n_clipped > 0:
            return "warn", f"音频接近削波（峰值 {max_vol:.1f}dB，{n_clipped} 削波采样）"
        detail = f"峰值 {max_vol:.1f}dB" if max_vol is not None else "无明显削波"
        return "pass", f"音频削波检查通过（{detail}）"
    except Exception as e:
        return "warn", f"削波检查异常: {e}"


def _check_tail_cut(video, duration, has_audio):
    """结尾拖尾检测（v2 P0）：最后 1s 音频能量应骤降（高潮后立即切断）→ warn。"""
    if not has_audio:
        return "warn", "无音轨，跳过拖尾检查"
    if duration < 2:
        return "warn", "时长过短，跳过拖尾检查"
    wav = "/tmp/_qc_tail.wav"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-ac", "1", "-ar", "16000",
             "-f", "wav", wav],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return "warn", "音频提取失败，跳过拖尾检查"
        import numpy as np
        import wave
        with wave.open(wav, "rb") as w:
            n = w.getnframes()
            raw = w.readframes(n)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        sr = 16000
        last_1s = audio[-sr:] if len(audio) >= sr else audio
        prev = audio[-3 * sr:-sr] if len(audio) >= 3 * sr else audio[:-sr]
        e_last = float(np.sqrt(np.mean(last_1s ** 2))) if len(last_1s) else 0.0
        e_prev = float(np.sqrt(np.mean(prev ** 2))) if len(prev) else 0.0
        if e_prev < 1e-6:
            return "warn", "音频过静，无法判断拖尾"
        ratio = e_last / e_prev
        if ratio > 0.7:
            return "warn", (f"结尾 1s 能量未骤降（{ratio:.0%}），疑似拖尾音乐/outro —— "
                            "建议高潮后立即切断，保护完播率")
        return "pass", f"结尾干净（最后 1s 能量 {ratio:.0%}）"
    except Exception as e:
        return "warn", f"拖尾检查异常: {e}"
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def _burn_subtitles(video):
    """调 burn_subtitles.py（不重复实现）。返回 (output_path, note)。

    成功 → 新文件路径；合规跳过/失败 → (原路径, warning 文本)。
    """
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(PERPETUA, "burn_subtitles.py"), video],
            capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            # 成功时 stdout 最后一行是 JSON {"input","output","srt"}
            for line in reversed(r.stdout.strip().splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        info = json.loads(line)
                        out = info.get("output")
                        if out and os.path.isfile(out):
                            return out, "字幕已烧录"
                    except (json.JSONDecodeError, ValueError):
                        pass
            # exit 0 但无新文件 = 合规跳过（whisper 缺失等，原因在 subtitle_burn.log）
            return video, "字幕烧录跳过（whisper 未安装或无语音），不阻塞"
        return video, f"字幕烧录失败（exit {r.returncode}），不阻塞"
    except subprocess.TimeoutExpired:
        return video, "字幕烧录超时（300s），不阻塞"
    except Exception as e:
        return video, f"字幕烧录异常: {e}，不阻塞"


def run_qc(video_path, title="", prompt_meta=None, regen_fn=None, max_regen=2):
    """执行 10 项质检（fail-closed）。

    video_path: 绝对路径。
    regen_fn:   可选，循环验证失败时的重生成回调 fn(attempt)->新视频路径|None。
    返回 {"passed": bool, "checks": [...], "warnings": [...],
          "rejects": [...], "output_file": 最终视频绝对路径, "regen_used": int,
          "needs_regen": bool（自动修不好，需重生成）}

    fail-closed：任何检查返回 fail → passed=False。自动修复（裁剪时长/
    分辨率/烧字幕）成功后会重新验证；修不好则 needs_regen=True。
    """
    checks, warnings, rejects = [], [], []
    cur = os.path.abspath(video_path)
    regen_used = 0
    needs_regen = False

    def _rec(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})
        if status == "warn":
            warnings.append(f"[{name}] {detail}")
        elif status == "fail":
            rejects.append(f"[{name}] {detail}")

    def _fail_closed():
        _log({"video": video_path, "passed": False, "rejects": rejects,
              "needs_regen": needs_regen})
        return {"passed": False, "checks": checks, "warnings": warnings,
                "rejects": rejects, "output_file": cur,
                "regen_used": regen_used, "needs_regen": needs_regen}

    if not os.path.isfile(cur):
        _rec("probe", "fail", f"文件不存在: {cur}")
        return _fail_closed()

    # ---- 1. 分辨率（偏离不大自动中央裁剪；裁不掉 → 需重生成）----
    probe = _probe(cur)
    if "error" in probe:
        _rec("probe", "fail", f"ffprobe 失败: {probe['error']}")
        return _fail_closed()
    ok, msg = _check_resolution(probe)
    if ok:
        _rec("resolution", "pass", msg)
    else:
        fixed = _fix_resolution(cur, probe)
        if fixed:
            _rec("resolution", "pass",
                 f"{msg} → 自动中央裁剪修复: {os.path.basename(fixed)}")
            cur = fixed
            probe = _probe(cur)
        else:
            _rec("resolution", "fail", msg + " —— 自动裁剪不可行，需重生成竖屏版本")
            needs_regen = True
            return _fail_closed()

    # ---- 2. 时长（超 11s 自动裁到前 11s；不足 9s 拒）----
    dur = probe["duration"]
    if dur < MIN_DUR:
        _rec("duration", "fail", f"时长 {dur:.1f}s < {MIN_DUR}s，无法修复，需重生成")
        needs_regen = True
        return _fail_closed()
    if dur > MAX_DUR:
        trimmed = _trim_duration(cur, dur)
        if trimmed:
            _rec("duration", "pass",
                 f"时长 {dur:.1f}s → 自动裁剪到 {MAX_DUR}s（取前 {MAX_DUR}s，保留开头钩子）")
            cur = trimmed
            probe = _probe(cur)
            dur = probe.get("duration", dur)
        else:
            _rec("duration", "fail", f"时长 {dur:.1f}s 超限且自动裁剪失败")
            return _fail_closed()
    else:
        _rec("duration", "pass", f"时长 {dur:.1f}s（{MIN_DUR}-{MAX_DUR}s 达标）")

    # ---- 3. 黑帧/白闪（有坏帧 → 拒，需重生成）----
    st, msg = _check_black_frames(cur, dur)
    _rec("blackframe", st, msg)
    if st == "fail":
        needs_regen = True
        return _fail_closed()

    # ---- 4. 首帧静音测试（全黑/全白 → 拒；低对比/无主体 → warn）----
    st, msg = _check_first_frame(cur)
    _rec("firstframe", st, msg)
    if st == "fail":
        needs_regen = True
        return _fail_closed()

    # ---- 5. 无缝循环（不通过 → 重生成最多 2 次，否则转人工）----
    attempt = 0
    while True:
        passed, detail = check_loop(cur, LOOP_THRESHOLD)
        if passed:
            _rec("loop", "pass",
                 f"首尾帧相似度 {detail.get('similarity')}（阈值 {LOOP_THRESHOLD}）")
            break
        # 失败：尝试重生成
        if regen_fn and attempt < max_regen:
            attempt += 1
            regen_used = attempt
            try:
                new_path = regen_fn(attempt)
            except Exception as e:
                new_path = None
                _rec("loop", "fail",
                     f"首尾帧相似度 {detail.get('similarity')} 不达标，重生成回调异常: {e}")
                break
            if new_path and os.path.isfile(new_path):
                cur = os.path.abspath(new_path)
                _rec("loop", "warn",
                     f"第 {attempt} 次重生成: {os.path.basename(cur)}，重新验证")
                continue
            _rec("loop", "fail",
                 f"首尾帧相似度 {detail.get('similarity')} 不达标，重生成未返回有效文件")
            break
        _rec("loop", "fail",
             f"首尾帧相似度 {detail.get('similarity')}（阈值 {LOOP_THRESHOLD}）不达标 —— "
             "请重新生成（循环率 r=0.82 是最强播放信号）")
        break
    if any(c["name"] == "loop" and c["status"] == "fail" for c in checks):
        needs_regen = True
        return _fail_closed()

    # ---- 6. 高潮时机（warning）----
    st, msg = _check_climax(cur, dur, probe.get("has_audio", False))
    _rec("climax", st, msg)

    # ---- 7. 结尾拖尾（warning）----
    st, msg = _check_tail_cut(cur, dur, probe.get("has_audio", False))
    _rec("tailcut", st, msg)

    # ---- 8. 音频削波（warning）----
    st, msg = _check_audio_clip(cur, probe.get("has_audio", False))
    _rec("audioclip", st, msg)

    # ---- 9. 安全区（warning）----
    st, msg = _check_safezone(cur)
    _rec("safezone", st, msg)

    # ---- 10. 字幕烧录（自动修复，不阻塞）----
    out, note = _burn_subtitles(cur)
    if out != cur:
        _rec("subtitles", "pass", note + f" → {os.path.basename(out)}")
        cur = out
    else:
        _rec("subtitles", "warn", note)

    # ---- fail-closed：显式从 rejects 计算 passed，不再写死 True ----
    passed = len(rejects) == 0
    result = {"passed": passed, "checks": checks, "warnings": warnings,
              "rejects": rejects, "output_file": cur, "regen_used": regen_used,
              "needs_regen": needs_regen and not passed}
    _log({"video": video_path, "passed": passed,
          "output": cur, "warnings": warnings, "rejects": rejects})
    pipeline_log("qc", "ok" if passed else "error",
                 f"{os.path.basename(video_path)}: {'通过' if passed else '拒绝'}"
                 + (f" ({len(rejects)}项reject)" if rejects else "")
                 + (f" 警告{len(warnings)}项" if warnings else ""), 1)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: pre_upload_qc.py <video.mp4>", file=sys.stderr)
        sys.exit(2)
    r = run_qc(sys.argv[1])
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["passed"] else 1)
