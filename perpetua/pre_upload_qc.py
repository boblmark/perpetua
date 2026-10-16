#!/usr/bin/env python3
"""上传前统一质检门（最后一道门）：视频生成后、YouTube 上传前。

2026-10-08 v3 重构（Ask Studio 底层诊断）：
  旧问题：过度优化标题/描述/标签等包装变量（权重 <1%），却没有变量化
  Shorts 前 1-3 秒的真实观看体验（算法 90%+ 权重在"播放中"信号）。
  新架构：三层门禁 ——
    Tier 1 合规硬门（能不能发）：文件损坏/非竖屏/时长/黑帧/首帧渲染失败
    Tier 2 爆款体验门（能不能爆）：前1.5秒钩子/循环/首帧可读性/音频动态/
             动作清晰度/高潮时机/结尾 —— 计 experience_score，<60 拒
    Tier 3 辅助卫生（warn only）：削波/安全区/字幕
  包装项（emoji开头/100字描述/CTA/标题换皮）已从爆款硬指标降为元数据卫生，
  在 MCP server 的 _upload_hard_gates 侧改为 warn。

fail-closed：Tier 1 任何 fail → passed=False；Tier 2 硬 fail（hookmotion/
loop）→ 拒；experience_score <60 → 拒。自动修复成功后重新验证。

12+1 项检查：
  Tier 1:
    probe        文件可读 —— 损坏直接拒绝
    resolution   9:16 竖屏 —— 偏离不大自动中央裁剪；裁不掉则拒绝
    duration     9-11s —— 超出自动裁到 11s；不足 9s 拒绝
    duration_match 实际时长 vs prompt 要求时长 —— 差 >1s 直接拒绝（2026-10-08 v5.1 十秒事故）
    blackframe   黑帧/白闪（抽 5 帧）—— 有坏帧直接拒绝（需重生成）
    firstframe_silent  首帧渲染失败（全黑/全白）—— 拒绝
    audio_first_100ms  前 100ms 音频峰值 ≥-18dBFS —— 开头静音直接拒绝（四脑 2026-10-08）
    frame0_face  首帧最大人脸 ≥30% 画面 —— 非特写直接拒绝（四脑 2026-10-08）
  Tier 2（体验分，满分 100）:
    hookmotion   前 1.5 秒运动强度 <3.0 → fail 拒；3-6 warn；≥6 pass（30 分）
    loop         首尾帧相似度 ≥0.75（20 分；不通过 → 重生成最多 2 次）
    firstframe_hook  首帧视觉可读性：对比度/中央主体（15 分）
    audiodyn     音频动态变异系数 <0.35 → warn（15 分）
    actionclarity 高潮段(6.5-7.5s) vs 升级段(2-4s) 运动强度比（10 分）
    climax       音频能量峰值 6.5-7.5s（5 分）
    tailcut      结尾 1s 能量骤降（5 分）
  Tier 3:
    audioclip    音频削波（warn only）
    safezone     安全区（warn only）
    subtitles    字幕烧录（自动修复，不阻塞）

用法：
    from pre_upload_qc import run_qc
    r = run_qc("/home/hatch/data/xxx.mp4", title="...")
    # r = {passed, experience_score, checks, warnings, rejects,
    #      output_file, regen_used, needs_regen}

接入点：MCP server 的 youtube_upload（_upload_hard_gates 之后）。
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/hatch/data/perpetua")
from loop_check import check_loop as _check_loop_impl  # noqa: E402  (直接调用，不重复实现；别名防 run_qc 的 check_loop 参数遮蔽)

PERPETUA = "/home/hatch/data/perpetua"
QC_LOG = os.path.join(PERPETUA, "pre_upload_qc.log")

MIN_DUR, MAX_DUR = 7.5, 11.0  # 2026-10-08 修正：YouTube 时长向上取整，
# Veo 原生 8s 显示为 PT9S、Sora 原生 10s 显示为 PT11S。按原生时长验收，
# 7.5 下限覆盖 Veo 8s（含导出误差），11 上限覆盖 Sora 10s。
LOOP_THRESHOLD = 0.75  # 2026-10-07 与 loop_check.py 对齐（0.85 实测不可达）
CLIMAX_RANGE = (6.5, 7.5)

# ---- 四脑会诊 2026-10-08：第一秒硬门禁（AI Studio 规格）----
# 背景：Ask Studio 诊断瓶颈在第 1 秒（viewed-vs-swiped），LMArena 2:0 否决先上 ECR。
# Check 2 人脸阈值说明：2026-10-08 实测 8 条历史视频最大人脸占比仅 10.27%，
# 全部不达标——符合预期（v5 要求特写，老视频本来就不合规）。阈值可调。
AUDIO_100MS_DBFS = -18.0   # 前 100ms 音频峰值下限（Tier 1 硬门）
FACE_AREA_RATIO = 0.30      # 首帧最大人脸占画面比下限（Tier 1 硬门）
MOTION1S_THRESHOLD = 2.50   # 前 30 帧平均光流强度下限（Tier 2：fail 扣 40 体验分）
YUNET_MODEL = os.path.join(PERPETUA, "models", "face_detection_yunet_2023mar.onnx")

# ---- Tier 2 爆款体验分（满分 100，<60 拒绝上传）----
# 权重依据 Ask Studio 2026-10-08 底层诊断：前 1-3 秒体验 > 一切包装变量
EXPERIENCE_WEIGHTS = {
    "hookmotion": 30,      # 前 1.5 秒视觉钩子：观众 1 秒内决定滑走
    "loop": 20,            # 无缝循环：循环率 r=0.82 最强播放信号
    "firstframe_hook": 15, # 首帧视觉可读性：第一帧讲清概念
    "audiodyn": 15,        # 音频动态：TTS 平淡是流失主因之一
    "actionclarity": 10,   # 动作因果清晰度：原因→动作→报应可辨认
    "climax": 5,           # 高潮时机 6.5-7.5s
    "tailcut": 5,          # 结尾干净（保护完播率）
}
EXPERIENCE_PASS = 60  # 体验分及格线

# ---- 美学下限门（2026-10-12，warn 级观察期）----
# LAION 美学分（simple-aesthetics-predictor，MIT）。warn-only：低于阈值只记
# warnings，不进 rejects、不扣分、不拦截。观察一周误报率后用户再拍板是否升级。
AESTHETIC_WARN_THRESHOLD = 4.5  # 校准见 aesthetic_calibration.json


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
             "format=duration:stream=width,height,codec_type,avg_frame_rate,r_frame_rate,duration",
             "-of", "json", video],
            capture_output=True, text=True, timeout=30)
        info = json.loads(r.stdout or "{}")
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        # P2-8: 帧率（之前只被 cv2 读去做内部计算，从未校验）
        # 2026-10-10 修：优先 r_frame_rate（标称帧率）。avg_frame_rate 会被容器
        # 时长 padding 拉低（如 768 帧/32.04s → 23.97），曾误杀正常 24fps 视频。
        fps = 0
        for k in ("r_frame_rate", "avg_frame_rate"):
            try:
                num, den = v.get(k, "0/0").split("/")
                if int(den):
                    fps = float(num) / float(den)
                    break
            except Exception:
                pass
        try:
            vdur = float(v.get("duration") or 0)
        except Exception:
            vdur = 0
        try:
            adur = float(next((s.get("duration") or 0 for s in streams
                               if s.get("codec_type") == "audio"), 0))
        except Exception:
            adur = 0
        return {
            "duration": float(info.get("format", {}).get("duration") or 0),
            "width": int(v.get("width") or 0),
            "height": int(v.get("height") or 0),
            "has_audio": has_audio,
            "fps": fps,
            # P2-9: 音视频流各自时长（2026-10-10：-c copy 拼接曾产出
            # video 32s / audio 42.7s 的错位文件并通过 QC）
            "vdur": vdur,
            "adur": adur,
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


def _trim_duration(video, duration, max_dur=None):
    """超出上限 → 取前 max_dur 秒。返回新路径（失败返回 None）。"""
    _md = max_dur if max_dur else MAX_DUR
    base, ext = os.path.splitext(video)
    out = base + ".qc.mp4"
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-t", str(_md),
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


def _check_aesthetic(video, threshold=AESTHETIC_WARN_THRESHOLD):
    """美学下限门（2026-10-12，warn 级观察期）。

    LAION 美学分，1fps 抽帧取均值。永远返回 pass/warn，不返回 fail：
    低于阈值只记 warning，不拦截、不扣分。任何异常 → warn 跳过（fail-open）。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import aesthetic_gate
        import tempfile
        dur = aesthetic_gate.ffprobe_duration(video)
        with tempfile.TemporaryDirectory() as td:
            frames = aesthetic_gate.extract_frames(video, 1.0, td)
            if not frames:
                return "warn", "美学门：抽帧为空，跳过"
            scores = aesthetic_gate.score_frames(frames)
        mean = sum(scores) / len(scores)
        lo = min(scores)
        detail = (f"美学分均值 {mean:.2f}（{len(scores)} 帧，最低 {lo:.2f}，阈值 {threshold}）")
        if mean < threshold:
            return "warn", detail + " —— 低于美学下限，观察期只记录不拦截"
        return "pass", detail
    except Exception as e:
        return "warn", f"美学门跳过: {type(e).__name__}: {str(e)[:80]}"


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


def _check_frozen_frames(video, duration):
    """P1-5 修复（2026-10-08）：冻结视频检测。
    生成器失败时常吐全片静止帧（首尾帧像素完全一致）。
    抽 3 帧两两比对，相似度 >99.5% 判冻结 → fail。
    注：完整主题匹配（帧内容 vs prompt topic）需视觉模型，待接入。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return "warn", "cv2/numpy 不可用，跳过冻结检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过冻结检查"
        frames = []
        for frac in (0.15, 0.5, 0.85):
            t = duration * frac
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if ok:
                # 缩到小图加速比对
                small = cv2.resize(frame, (64, 64))
                frames.append(small.astype(np.float32))
        cap.release()
        if len(frames) < 2:
            return "warn", "抽帧不足，跳过冻结检查"
        # 两两比对
        for i in range(len(frames)):
            for j in range(i + 1, len(frames)):
                diff = np.abs(frames[i] - frames[j]).mean()
                # 相同帧 diff≈0；正常视频 diff 通常 >3
                if diff < 1.0:
                    return "fail", (f"冻结视频：第 {i+1} 帧与第 {j+1} 帧几乎一致 "
                                    f"(diff={diff:.2f})，生成器可能吐了静止帧，需重生成")
        return "pass", "3 帧内容有差异，非冻结视频"
    except Exception as e:
        return "warn", f"冻结检查异常: {e}"


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


def _check_hook_motion(video):
    """前 1.5 秒视觉钩子：帧间运动强度（Ask Studio 2026-10-08：观众 1 秒内决定滑走）。

    采样前 1.5 秒共 12 帧，算相邻帧灰度差均值。太静止 → fail（需重生成，开场加动作）。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return "warn", "cv2/numpy 不可用，跳过钩子运动检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过钩子运动检查"
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        n = min(12, total)
        if n < 4:
            cap.release()
            return "warn", "视频帧数不足，跳过钩子运动检查"
        prev = None
        diffs = []
        for _ in range(n):
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # 降采样加速
            small = cv2.resize(gray, (160, 284))
            if prev is not None:
                diffs.append(float(np.abs(small.astype(np.int16) - prev.astype(np.int16)).mean()))
            prev = small
        cap.release()
        if not diffs:
            return "warn", "未采样到帧差，跳过"
        avg = sum(diffs) / len(diffs)
        # 阈值：实测静态 talking-head 约 <3，动作场景 >8
        if avg < 3.0:
            return "fail", (f"前 1.5 秒几乎静止（运动强度 {avg:.1f}<3.0）—— "
                            "观众 1 秒内滑走，需重生成：开场加肢体动作/镜头推进")
        if avg < 6.0:
            return "warn", f"前 1.5 秒运动偏弱（{avg:.1f}），钩子可能不够抓人"
        return "pass", f"前 1.5 秒运动强度 {avg:.1f} 达标"
    except Exception as e:
        return "warn", f"钩子运动检查异常: {e}"


def _check_audio_dynamics(video, has_audio):
    """音频动态范围（Ask Studio 2026-10-08：TTS 平淡是流失主因之一）。

    算全片 0.5s 窗口能量值的标准差/均值（变异系数）。太平 → warn。
    """
    if not has_audio:
        return "warn", "无音轨，跳过音频动态检查"
    wav = "/tmp/_qc_dyn.wav"
    try:
        import numpy as np
        import wave
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", video, "-ac", "1", "-ar", "16000",
             "-f", "wav", wav],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return "warn", "音频提取失败，跳过动态检查"
        with wave.open(wav, "rb") as w:
            n = w.getnframes()
            raw = w.readframes(n)
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio) == 0 or np.abs(audio).max() < 1e-6:
            return "warn", "音频为空/静音"
        sr = 16000
        win = int(sr * 0.5)
        nwin = max(1, len(audio) // win)
        energy = np.array([
            np.sqrt(np.mean(audio[i * win:(i + 1) * win] ** 2))
            for i in range(nwin)])
        mu = float(energy.mean())
        if mu < 1e-6:
            return "warn", "音频能量过低"
        cv = float(energy.std() / mu)
        # 变异系数：单调 TTS 约 <0.4，有起伏的 >0.6
        if cv < 0.35:
            return "warn", (f"音频动态偏平（变异系数 {cv:.2f}<0.35）—— "
                            "TTS 可能太平，喜剧节奏弱，建议重生成时加强语气起伏")
        return "pass", f"音频动态 {cv:.2f} 达标"
    except Exception as e:
        return "warn", f"音频动态检查异常: {e}"
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass


def _check_action_clarity(video, duration):
    """动作因果清晰度（Ask Studio 2026-10-08 v3 新增）。

    Slapstick 需要清楚的"原因→动作→报应"。代理指标：高潮段（6.5-7.5s）
    的运动强度应显著高于升级段（2-4s）——报应画面必须有视觉爆发力。
    全片运动太平 → 观众分不清哪是笑点 → warn。
    返回 (status, detail)，status ∈ pass/warn。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return "warn", "cv2/numpy 不可用，跳过动作清晰度检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过动作清晰度检查"
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        def _motion(t0, t1):
            """算 [t0,t1) 秒窗口内的平均帧间运动强度。"""
            cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
            prev = None
            diffs = []
            f0 = int(t0 * fps)
            f1 = int(t1 * fps)
            for _ in range(max(1, f1 - f0)):
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, (160, 284))
                if prev is not None:
                    diffs.append(float(np.abs(
                        small.astype(np.int16) - prev.astype(np.int16)).mean()))
                prev = small
            return sum(diffs) / len(diffs) if diffs else 0.0

        # 升级段 2-4s vs 高潮段 6.5-7.5s（钳制到实际时长）
        hi = min(7.5, duration)
        lo = min(6.5, hi - 0.5)
        base = _motion(2.0, min(4.0, duration))
        climax = _motion(lo, hi)
        cap.release()
        if base < 1e-6:
            return "warn", "升级段几乎静止，无法判断动作对比"
        ratio = climax / base
        if ratio >= 1.5:
            return "pass", f"高潮段运动强度是升级段的 {ratio:.1f}x，报应爆发力足"
        if ratio >= 1.2:
            return "warn", (f"高潮段仅为升级段的 {ratio:.1f}x —— "
                            "报应画面爆发力偏弱，笑点可能不够脆")
        return "warn", (f"高潮段与升级段运动强度接近（{ratio:.1f}x）—— "
                        "全片太平，观众分不清哪是笑点，建议重生成时加强报应段动作")
    except Exception as e:
        return "warn", f"动作清晰度检查异常: {e}"


def _check_deadpan_pause(video, duration):
    """面瘫停顿验证（2026-10-09 LMArena 趋势研究回流，Tier 2 warn-only 诊断项）。

    4 节拍公式的关键节拍：4.5-5.8s 机器必须面瘫静止 ~1.2s（单哔声或一句
    扁平机器音），赶过这个停顿会毁掉喜剧张力。代理指标：停顿窗口的运动
    能量应显著低于触发窗口（3.5-4.5s）和报应窗口（5.8-7.5s）——呈现
    一个可测量的"凹陷"。用相对时长定位窗口，适配 7.5-11s 各种时长。
    不计分不阻塞：AI 运动噪声大，先以诊断口径跑，积累数据后再定是否加权。
    返回 (status, detail)，status ∈ pass/warn。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return "warn", "cv2/numpy 不可用，跳过面瘫停顿检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过面瘫停顿检查"
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        def _motion(t0, t1):
            cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
            prev = None
            diffs = []
            f0 = int(t0 * fps)
            f1 = int(t1 * fps)
            for _ in range(max(1, f1 - f0)):
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, (160, 284))
                if prev is not None:
                    diffs.append(float(np.abs(
                        small.astype(np.int16) - prev.astype(np.int16)).mean()))
                prev = small
            return sum(diffs) / len(diffs) if diffs else 0.0

        # 相对窗口：触发 44%-56%，停顿 56%-72%，报应 72%-94%
        trig = _motion(duration * 0.44, duration * 0.56)
        pause = _motion(duration * 0.56, duration * 0.72)
        payback = _motion(duration * 0.72, duration * 0.94)
        cap.release()
        if trig < 1e-6 and payback < 1e-6:
            return "warn", "触发/报应窗口几乎静止，无法判断停顿凹陷"
        # 停顿应为局部最小：低于触发窗 80% 且低于报应窗 60%
        if pause < trig * 0.8 and pause < payback * 0.6:
            return "pass", (f"面瘫停顿凹陷明显（触发 {trig:.1f} → 停顿 "
                            f"{pause:.1f} → 报应 {payback:.1f}），喜剧张力节拍到位")
        return "warn", (f"未检测到明显面瘫停顿（触发 {trig:.1f} / 停顿 "
                       f"{pause:.1f} / 报应 {payback:.1f}）—— 机器少了那 "
                       "1.2s 死寂，报应笑点可能不够脆")
    except Exception as e:
        return "warn", f"面瘫停顿检查异常: {e}"


def _check_first_frame_hook(video):
    """首帧视觉可读性（Tier 2 体验分项）：第一帧必须讲清概念。

    全黑/全白由 Tier 1 的 firstframe_silent 处理；这里只评可读性：
    对比度过低 / 中央 1/3 无主体 → warn（钩子弱，扣体验分）。
    返回 (status, detail)，status ∈ pass/warn。
    """
    try:
        import cv2
    except ImportError:
        return "warn", "cv2 不可用，跳过首帧可读性检查"
    try:
        cap = cv2.VideoCapture(video)
        if not cap.isOpened():
            return "warn", "无法打开视频，跳过首帧可读性检查"
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return "warn", "无法读取首帧"
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        contrast = float(gray.std())
        cx0, cx1, cy0, cy1 = w // 3, 2 * w // 3, h // 3, 2 * h // 3
        center = gray[cy0:cy1, cx0:cx1]
        edges = cv2.Canny(center, 80, 160)
        edge_dens = float(edges.mean())
        if contrast < 15:
            return "warn", f"首帧对比度低（{contrast:.1f}），画面平淡，第一帧讲不清概念"
        if edge_dens < 2.0:
            return "warn", f"首帧中央缺乏明确主体（边缘密度 {edge_dens:.1f}），钩子弱"
        return "pass", (f"首帧可读性达标（对比度 {contrast:.0f}，"
                        f"中央边缘密度 {edge_dens:.1f}）")
    except Exception as e:
        return "warn", f"首帧可读性检查异常: {e}"


def _check_audio_first_100ms(video):
    """四脑会诊 2026-10-08 Check 1（Tier 1 硬门）：前 100ms 音频峰值 ≥ -18 dBFS。

    AI 生成常带 200-500ms 开头静音 → 观众秒划。返回 (status, detail)，
    status ∈ pass/fail。
    """
    import subprocess, json as _json
    try:
        # 抽前 0.15s 音频，用 astats 取峰值（比 volumedetect 更稳）
        # 注意：不能用 -v error，否则会屏蔽要解析的日志行
        r = subprocess.run(
            ["ffmpeg", "-i", video, "-t", "0.15",
             "-af", "astats=metadata=1:reset=1", "-vn", "-sn", "-dn",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        peak = None
        for line in r.stderr.splitlines():
            if "Peak level dB" in line:
                try:
                    peak = float(line.split(":")[-1].strip())
                    break
                except ValueError:
                    pass
        if peak is None:
            # 回退：volumedetect
            r2 = subprocess.run(
                ["ffmpeg", "-i", video, "-t", "0.15",
                 "-af", "volumedetect", "-vn", "-sn", "-dn", "-f", "null", "-"],
                capture_output=True, text=True, timeout=30)
            for line in r2.stderr.splitlines():
                if "max_volume" in line:
                    try:
                        peak = float(line.split(":")[-1].strip().split()[0])
                        break
                    except ValueError:
                        pass
        if peak is None:
            return "fail", "无法测量前 100ms 音频峰值（无音频流？）"
        if peak >= AUDIO_100MS_DBFS:
            return "pass", f"前 100ms 音频峰值 {peak:.1f} dBFS ≥ {AUDIO_100MS_DBFS}"
        return "fail", (f"前 100ms 音频峰值 {peak:.1f} dBFS < {AUDIO_100MS_DBFS} —— "
                        "开头静音/过弱，观众会秒划，需重生成")
    except Exception as e:
        return "fail", f"音频首击检查异常: {e}"


def _check_frame0_face(video):
    """四脑会诊 2026-10-08 Check 2（Tier 1 硬门）：首帧最大人脸 ≥30% 画面。

    用 YuNet（对 AI 生成脸比 Haar 可靠）。YuNet 框只覆盖五官区域，
    实际视觉头部（含头发）约为其 1.5x，因此扩展 1.5x 后计算占比。
    （2026-10-08 实测：好特写 18.8%→42.4% 通过，差中景 8.8%→19.8% 拦截）
    返回 (status, detail)。
    """
    try:
        import cv2
        import os as _os
    except ImportError:
        return "fail", "cv2 不可用，无法做首帧人脸检查", 0.5
    if not _os.path.exists(YUNET_MODEL):
        return "fail", f"人脸模型缺失: {YUNET_MODEL}", 0.5
    try:
        cap = cv2.VideoCapture(video)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return "fail", "无法读取首帧", 0.5
        h, w = frame.shape[:2]
        det = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (w, h), 0.5, 0.3, 5000)
        _, faces = det.detect(frame)
        total = h * w
        if faces is None or len(faces) == 0:
            return "fail", "首帧未检测到人脸 —— v5 要求 Karen 特写开场，需重生成", 0.5
        ratio = max(float(f[2] * f[3]) for f in faces) / total
        # YuNet 框保守，扩展 1.5x 模拟完整头部视觉占比
        f_best = max(faces, key=lambda f: f[2] * f[3])
        fx, fy, fbw, fbh = f_best[0], f_best[1], f_best[2], f_best[3]
        fcx, fcy = fx + fbw / 2, fy + fbh / 2
        few, feh = fbw * 1.5, fbh * 1.5
        fx1 = max(0, fcx - few / 2); fy1 = max(0, fcy - feh / 2)
        fx2 = min(w, fcx + few / 2); fy2 = min(h, fcy + feh / 2)
        ratio = (fx2 - fx1) * (fy2 - fy1) / total
        # 神经科学模型（2026-10-08）：人脸是乘子不是开关
        # face_mult = max(0.5, sqrt(ratio / 0.30))
        import math
        face_mult = max(0.5, math.sqrt(ratio / FACE_AREA_RATIO))
        face_mult = min(1.0, face_mult)  # 上限 1.0，不额外加分
        if ratio >= FACE_AREA_RATIO:
            return "pass", f"首帧最大人脸占比 {ratio:.1%} ≥ {FACE_AREA_RATIO:.0%}（乘子 1.0）", face_mult
        # 有脸但不够大：不硬拒，乘子惩罚（27.8%→0.96，10%→0.58，5%→0.5）
        return "warn", (f"首帧最大人脸占比 {ratio:.1%} < {FACE_AREA_RATIO:.0%} —— "
                        f"人脸乘子 {face_mult:.2f}（非硬拒）"), face_mult
    except Exception as e:
        return "fail", f"首帧人脸检查异常: {e}", 0.5


def _check_motion_1s(video):
    """四脑会诊 2026-10-08 Check 3（Tier 2）：前 30 帧平均光流 ≥2.50。

    静态开场 = 秒划。返回 (status, detail)，status ∈ pass/fail。
    AI Studio 规格：fail → 体验分扣 40 分（非硬拒）。
    """
    try:
        import cv2
        import numpy as _np
    except ImportError:
        return "fail", "cv2 不可用，无法做运动能量检查"
    try:
        cap = cv2.VideoCapture(video)
        ret, prev = cap.read()
        if not ret or prev is None:
            cap.release()
            return "fail", "无法读取视频帧"
        prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
        mags = []
        for _ in range(29):
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            mags.append(float(_np.mean(mag)))
            prev_gray = gray
        cap.release()
        if not mags:
            return "fail", "无法计算光流（视频过短？）"
        mean_e = float(_np.mean(mags))
        if mean_e >= MOTION1S_THRESHOLD:
            return "pass", f"前 30 帧平均光流 {mean_e:.2f} ≥ {MOTION1S_THRESHOLD}"
        return "fail", (f"前 30 帧平均光流 {mean_e:.2f} < {MOTION1S_THRESHOLD} —— "
                        "开场静态，观众秒划，需重生成")
    except Exception as e:
        return "fail", f"运动能量检查异常: {e}"


def run_qc(video_path, title="", prompt_meta=None, regen_fn=None, max_regen=2,
           max_duration=None, check_loop=True, repair_fn=None):
    """执行三层质检（v3, 2026-10-08）：Tier 1 合规硬门 + Tier 2 爆款体验分 + Tier 3 卫生。

    video_path: 绝对路径。
    regen_fn:   可选，循环验证失败时的重生成回调 fn(attempt)->新视频路径|None。
    repair_fn:  可选，loop 不达标时的接缝修复回调 fn(video_path, similarity)->新路径|None。
                2026-10-16 MoviePy 修复层：先修（1次）再重生成；阈值不降低。
    max_duration: 时长上限（秒），默认 MAX_DUR(11)。teaser 多段拼接（40s）传 65。
    check_loop: 是否跑无缝循环检查。v5.3.1 起多段 teaser 传 False（loop 不再是硬门）。
    返回 {"passed": bool, "experience_score": int(0-100), "checks": [...],
          "warnings": [...], "rejects": [...], "output_file": 最终视频绝对路径,
          "regen_used": int, "repair_used": int, "needs_regen": bool}

    fail-closed：
      - Tier 1 任何 fail → passed=False（合规问题，必须修/重生成）
      - Tier 2 硬 fail（hookmotion <3.0、loop 不达标）→ passed=False
      - experience_score <60 → passed=False（体验分不够，爆款概率低）
    自动修复（裁剪时长/分辨率/烧字幕）成功后重新验证；修不好则 needs_regen=True。
    """
    checks, warnings, rejects = [], [], []
    cur = os.path.abspath(video_path)
    regen_used = 0
    repair_used = 0
    needs_regen = False
    exp_score = 0
    exp_breakdown = {}

    def _rec(name, status, detail, tier=1):
        checks.append({"name": name, "status": status, "detail": detail,
                       "tier": tier})
        if status == "warn":
            warnings.append(f"[{name}] {detail}")
        elif status == "fail":
            rejects.append(f"[{name}] {detail}")

    def _rec_exp(name, status, detail):
        """Tier 2 体验分项：记录检查 + 计分（pass 满分 / warn 半分 / fail 0 分）。"""
        nonlocal exp_score
        w = EXPERIENCE_WEIGHTS[name]
        pts = w if status == "pass" else (w // 2 if status == "warn" else 0)
        exp_score += pts
        exp_breakdown[name] = pts
        _rec(name, status, f"{detail}（体验分 +{pts}/{w}）", tier=2)

    def _fail_closed():
        _log({"video": video_path, "passed": False, "rejects": rejects,
              "experience_score": exp_score, "needs_regen": needs_regen,
              "repair_used": repair_used})
        return {"passed": False, "experience_score": exp_score,
                "experience_breakdown": exp_breakdown,
                "checks": checks, "warnings": warnings,
                "rejects": rejects, "output_file": cur,
                "regen_used": regen_used, "repair_used": repair_used,
                "needs_regen": needs_regen}

    if not os.path.isfile(cur):
        _rec("probe", "fail", f"文件不存在: {cur}", tier=1)
        return _fail_closed()

    # ============ Tier 1: 合规硬门（能不能发）============
    # ---- 1. 分辨率（偏离不大自动中央裁剪；裁不掉 → 需重生成）----
    probe = _probe(cur)
    if "error" in probe:
        _rec("probe", "fail", f"ffprobe 失败: {probe['error']}", tier=1)
        return _fail_closed()
    _rec("probe", "pass", "文件可读", tier=1)
    # P2-8: 帧率检查（2026-10-08：15fps 卡顿视频之前能过全部 Tier）
    _fps = probe.get("fps", 0)
    if _fps and _fps < 24:
        _rec("fps", "fail", f"帧率 {_fps:.1f}fps < 24fps，卡顿视频需重生成", tier=1)
        needs_regen = True
        return _fail_closed()
    elif _fps:
        _rec("fps", "pass", f"帧率 {_fps:.1f}fps 达标", tier=1)
    # P2-9: 音视频时长一致性（2026-10-10：-c copy 拼接曾产出 video 32s /
    # audio 42.7s 的错位文件并通过 QC；>1s 错位直接 fail-closed）
    _vdur, _adur = probe.get("vdur", 0), probe.get("adur", 0)
    if _vdur and _adur and abs(_vdur - _adur) > 1.0:
        _rec("av_sync", "fail",
             f"音视频时长错位 video={_vdur:.1f}s audio={_adur:.1f}s，需重拼", tier=1)
        return _fail_closed()
    elif _vdur and _adur:
        _rec("av_sync", "pass",
             f"音视频对齐 video={_vdur:.1f}s audio={_adur:.1f}s", tier=1)
    ok, msg = _check_resolution(probe)
    if ok:
        _rec("resolution", "pass", msg, tier=1)
    else:
        fixed = _fix_resolution(cur, probe)
        if fixed:
            _rec("resolution", "pass",
                 f"{msg} → 自动中央裁剪修复: {os.path.basename(fixed)}", tier=1)
            cur = fixed
            probe = _probe(cur)
        else:
            _rec("resolution", "fail", msg + " —— 自动裁剪不可行，需重生成竖屏版本",
                 tier=1)
            needs_regen = True
            return _fail_closed()

    # ---- 2. 时长（超上限自动裁到上限；不足 MIN_DUR 拒）----
    _max_dur = max_duration if max_duration else MAX_DUR
    dur = probe["duration"]
    if dur < MIN_DUR:
        _rec("duration", "fail", f"时长 {dur:.1f}s < {MIN_DUR}s，无法修复，需重生成",
             tier=1)
        needs_regen = True
        return _fail_closed()
    if dur > _max_dur:
        trimmed = _trim_duration(cur, dur, _max_dur)
        if trimmed:
            _rec("duration", "pass",
                 f"时长 {dur:.1f}s → 自动裁剪到 {_max_dur}s（取前 {_max_dur}s，保留开头钩子）",
                 tier=1)
            cur = trimmed
            probe = _probe(cur)
            dur = probe.get("duration", dur)
        else:
            _rec("duration", "fail", f"时长 {dur:.1f}s 超限且自动裁剪失败", tier=1)
            return _fail_closed()
    else:
        _rec("duration", "pass", f"时长 {dur:.1f}s（{MIN_DUR}-{_max_dur}s 达标）", tier=1)

    # ---- 2b. 时长 vs prompt 要求（2026-10-08 v5.1 事故：prompt 要 8s，Veo 吐了 10s）----
    # prompt_meta 可带 expected_duration（秒）。差 >1s 直接拒，需重生成。
    exp_dur = None
    if isinstance(prompt_meta, dict):
        exp_dur = prompt_meta.get("expected_duration")
    if exp_dur:
        try:
            exp_dur = float(exp_dur)
            if abs(dur - exp_dur) > 1.0:
                _rec("duration_match", "fail",
                     f"实际时长 {dur:.1f}s vs 要求 {exp_dur:.0f}s，差 {abs(dur-exp_dur):.1f}s（>1s）—— 生成引擎未按时长要求出片，需重生成",
                     tier=1)
                needs_regen = True
                return _fail_closed()
            _rec("duration_match", "pass",
                 f"实际时长 {dur:.1f}s vs 要求 {exp_dur:.0f}s，偏差在 1s 内", tier=1)
        except (TypeError, ValueError):
            pass

    # ---- 3. 黑帧/白闪（有坏帧 → 拒，需重生成）----
    st, msg = _check_black_frames(cur, dur)
    _rec("blackframe", st, msg, tier=1)
    if st == "fail":
        needs_regen = True
        return _fail_closed()

    # ---- 3b. 冻结视频（P1-5：生成器吐静止帧 → 拒）----
    st, msg = _check_frozen_frames(cur, dur)
    _rec("frozen", st, msg, tier=1)
    if st == "fail":
        needs_regen = True
        return _fail_closed()

    # ---- 4. 首帧渲染失败（全黑/全白 → 拒；可读性问题转 Tier 2 计分）----
    st, msg = _check_first_frame(cur)
    if st == "fail":
        _rec("firstframe_silent", "fail", msg, tier=1)
        needs_regen = True
        return _fail_closed()
    _rec("firstframe_silent", "pass", "首帧渲染正常（非全黑/全白）", tier=1)

    # ---- 4b. 四脑会诊 2026-10-08：前 100ms 音频首击（Tier 1 硬门）----
    st, msg = _check_audio_first_100ms(cur)
    if st == "fail":
        _rec("audio_first_100ms", "fail", msg, tier=1)
        needs_regen = True
        return _fail_closed()
    _rec("audio_first_100ms", "pass", msg, tier=1)

    # ---- 4c. 神经科学模型 2026-10-08：首帧人脸乘子（非硬门）----
    # face_mult = max(0.5, sqrt(ratio/0.30))，无脸才硬拒
    st, msg, face_mult = _check_frame0_face(cur)
    if st == "fail" and face_mult == 0.5 and "未检测到人脸" in msg:
        _rec("frame0_face", "fail", msg, tier=1)
        needs_regen = True
        return _fail_closed()
    # 有脸：记录乘子，继续（不硬拒）
    face_mult_global = face_mult  # 供最后应用到体验分
    if st == "pass":
        _rec("frame0_face", "pass", msg, tier=1)
    else:
        _rec("frame0_face", "warn", msg, tier=1)
        warnings.append(f"[frame0_face] {msg}")

    # ============ Tier 2: 爆款体验门（能不能爆，计体验分）============
    # ---- 5. 前 1.5 秒视觉钩子（<3.0 → fail 拒，需重生成）----
    st, msg = _check_hook_motion(cur)
    _rec_exp("hookmotion", st, msg)
    if st == "fail":
        needs_regen = True
        return _fail_closed()

    # ---- 5b. 四脑会诊 2026-10-08：前 30 帧运动能量（Tier 2，AI Studio 规格：fail 扣 40 分）----
    st, msg = _check_motion_1s(cur)
    if st == "fail":
        exp_score = max(0, exp_score - 40)
        exp_breakdown["motion_1s"] = -40
        _rec("motion_1s", "fail", msg + "（体验分 -40）", tier=2)
    else:
        exp_breakdown["motion_1s"] = 0
        _rec("motion_1s", "pass", msg, tier=2)

    # ---- 6. 无缝循环（v5.3.1：多段 teaser 跳过；不通过 → 重生成最多 2 次，否则拒）----
    if not check_loop:
        _rec("loop", "skip", "多段格式跳过 loop 检查（v5.3.1）", tier=2)
        loop_status, loop_msg = "pass", "skipped"
    else:
        attempt = 0
        loop_status, loop_msg = "fail", ""
        repair_tried = False
        while True:
            passed, detail = _check_loop_impl(cur, LOOP_THRESHOLD)
            if passed:
                loop_status = "pass"
                loop_msg = (f"首尾帧相似度 {detail.get('similarity')}"
                            f"（阈值 {LOOP_THRESHOLD}）")
                break
            # 2026-10-16 MoviePy 修复层：loop 不达标先试接缝修复（限 1 次），
            # 修好（同一阈值验证通过）才继续；修不好→走原有重生成路径。阈值不降低。
            if repair_fn and not repair_tried:
                repair_tried = True
                sim_before = detail.get("similarity", 0.0)
                try:
                    repaired = repair_fn(cur, sim_before)
                except Exception as e:
                    repaired = None
                    _rec("loop", "warn", f"接缝修复回调异常: {e}", tier=2)
                if repaired and os.path.isfile(repaired):
                    ok2, d2 = _check_loop_impl(repaired, LOOP_THRESHOLD)
                    if ok2:
                        cur = os.path.abspath(repaired)
                        repair_used = 1
                        _rec("loop", "warn",
                             f"MoviePy 接缝修复: 相似度 {sim_before} → "
                             f"{d2.get('similarity')} 已达标，继续 QC",
                             tier=2)
                        continue
                    _rec("loop", "warn",
                         f"MoviePy 接缝修复未达标 "
                         f"({sim_before} → {d2.get('similarity')})，转重生成",
                         tier=2)
                    try:
                        os.remove(repaired)
                    except Exception:
                        pass
            if regen_fn and attempt < max_regen:
                attempt += 1
                regen_used = attempt
                try:
                    new_path = regen_fn(attempt)
                except Exception as e:
                    new_path = None
                    loop_msg = (f"首尾帧相似度 {detail.get('similarity')} 不达标，"
                                f"重生成回调异常: {e}")
                    break
                if new_path and os.path.isfile(new_path):
                    cur = os.path.abspath(new_path)
                    _rec("loop", "warn",
                         f"第 {attempt} 次重生成: {os.path.basename(cur)}，重新验证",
                         tier=2)
                # AI Studio 规格 #4：regen 耗尽后记 loud 日志（防无界重试占用 topic）
                if attempt >= max_regen:
                    try:
                        with open("/home/hatch/data/perpetua/qc_regen_exhausted.jsonl",
                                  "a", encoding="utf-8") as _f:
                            import json as _j, datetime as _dt
                            _f.write(_j.dumps({
                                "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                "video": os.path.basename(video_path),
                                "title": title[:50],
                                "attempts": attempt,
                            }, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                    continue
                loop_msg = (f"首尾帧相似度 {detail.get('similarity')} 不达标，"
                            "重生成未返回有效文件")
                break
            loop_msg = (f"首尾帧相似度 {detail.get('similarity')}（阈值 {LOOP_THRESHOLD}）"
                        "不达标 —— 请重新生成（循环率 r=0.82 是最强播放信号）")
            break
    _rec_exp("loop", loop_status, loop_msg)
    if loop_status == "fail":
        needs_regen = True
        return _fail_closed()

    # ---- 7. 首帧视觉可读性（对比度/中央主体）----
    st, msg = _check_first_frame_hook(cur)
    _rec_exp("firstframe_hook", st, msg)

    # ---- 8. 音频动态（TTS 太平 → warn 扣分）----
    st, msg = _check_audio_dynamics(cur, probe.get("has_audio", False))
    _rec_exp("audiodyn", st, msg)

    # ---- 9. 动作因果清晰度（高潮段 vs 升级段爆发力）----
    st, msg = _check_action_clarity(cur, dur)
    _rec_exp("actionclarity", st, msg)

    # ---- 10. 高潮时机（音频能量峰值 6.5-7.5s）----
    st, msg = _check_climax(cur, dur, probe.get("has_audio", False))
    _rec_exp("climax", st, msg)

    # ---- 10b. 面瘫停顿（2026-10-09 趋势研究回流，warn-only 诊断，不计分）----
    st, msg = _check_deadpan_pause(cur, dur)
    _rec("deadpan_pause", st if st != "fail" else "warn", msg, tier=2)

    # ---- 11. 结尾拖尾（最后 1s 能量骤降）----
    st, msg = _check_tail_cut(cur, dur, probe.get("has_audio", False))
    _rec_exp("tailcut", st, msg)

    # ============ Tier 3: 辅助卫生（warn only，不计分不阻塞）============
    # ---- 12. 音频削波 ----
    st, msg = _check_audio_clip(cur, probe.get("has_audio", False))
    _rec("audioclip", st if st != "fail" else "warn", msg, tier=3)

    # ---- 13. 安全区 ----
    st, msg = _check_safezone(cur)
    _rec("safezone", st if st != "fail" else "warn", msg, tier=3)

    # ---- 14. 字幕烧录（自动修复，不阻塞）----
    out, note = _burn_subtitles(cur)
    if out != cur:
        _rec("subtitles", "pass", note + f" → {os.path.basename(out)}", tier=3)
        cur = out
    else:
        _rec("subtitles", "warn", note, tier=3)

    # ---- 15. 美学下限门（2026-10-12，warn 级观察期：只记录不拦截）----
    st, msg = _check_aesthetic(cur)
    _rec("aesthetic", st if st != "fail" else "warn", msg, tier=3)

    # ============ 终裁：fail-closed + 体验分门槛 ============
    # 神经科学模型：人脸乘子应用到体验分（face_mult ∈ [0.5, 1.0]）
    try:
        fm = face_mult_global
    except NameError:
        fm = 1.0
    if fm < 1.0:
        exp_score = int(exp_score * fm)
        exp_breakdown["face_mult"] = round(fm, 3)
    exp_ok = exp_score >= EXPERIENCE_PASS
    if not exp_ok:
        rejects.append(
            f"[experience] 体验分 {exp_score}/100 < {EXPERIENCE_PASS} —— "
            f"分项: {json.dumps(exp_breakdown, ensure_ascii=False)}。"
            "前 3 秒体验不达标，爆款概率低，建议重生成（加强开场动作/高潮爆发力）")
    passed = len(rejects) == 0 and exp_ok
    result = {"passed": passed, "experience_score": exp_score,
              "experience_breakdown": exp_breakdown,
              "checks": checks, "warnings": warnings,
              "rejects": rejects, "output_file": cur, "regen_used": regen_used,
              "repair_used": repair_used,
              "needs_regen": needs_regen and not passed}
    _log({"video": video_path, "passed": passed, "experience_score": exp_score,
          "output": cur, "warnings": warnings, "rejects": rejects})
    pipeline_log("qc", "ok" if passed else "error",
                 f"{os.path.basename(video_path)}: {'通过' if passed else '拒绝'}"
                 f"（体验分 {exp_score}）"
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
