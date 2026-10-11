#!/usr/bin/env python3
"""抖音适配器 v1 — v2-final spec 落地。

功能：
  tts(text, out)      Edge-TTS zh-CN-YunxiNeural 中文配音（单集≤800字硬上限850）
  opener(n)           开场白5变体严格轮询
  next_no()           全局编号 No.001 起（next_no.json）
  cover(no, part, title, bg_frame, out)  1080×1920 统一封面
  assemble(clips, audio, out)            N分镜 ffmpeg 拼接 + 配音混流 + loudnorm（时长跟随音轨）

用法见底部 __main__ 自测。
"""
import asyncio
import json
import os
import subprocess
import sys; sys.path.insert(0, "/home/hatch/data/perpetua")
from atomic_json import atomic_write

BASE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(BASE, "adapter_state.json")
TTS_VOICE = "zh-CN-YunxiNeural"
TTS_HARD_LIMIT = 850  # 含标点硬上限（spec为800不含标点，此处按含标点850卡）

OPENERS = [
    "档案管理员，调取编号No.{no}",
    "档案管理员，提取卷宗No.{no}",
    "档案管理员，开启档案No.{no}",
    "管理员，调阅案卷No.{no}",
    "档案管理员，检索编号No.{no}",
]
PARTS = {"up": "上", "mid": "中", "down": "下"}


def _load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"next_no": 1}


def _save_state(s):
    atomic_write(STATE, s)


def next_no():
    """取下一个全局编号（No.001格式），调用即+1。"""
    s = _load_state()
    n = s.get("next_no", 1)
    s["next_no"] = n + 1
    _save_state(s)
    return f"{n:03d}"


def peek_no():
    return f"{_load_state().get('next_no', 1):03d}"


def opener(episode_index_1based, no):
    """第N集（1-based）的开场白，严格轮询。"""
    v = OPENERS[(episode_index_1based - 1) % len(OPENERS)]
    return v.format(no=no)


async def _edge_tts(text, out_mp3):
    import edge_tts
    n = len(text)
    if n > TTS_HARD_LIMIT:
        raise ValueError(f"TTS文本{n}字超硬上限{TTS_HARD_LIMIT}，打回重写")
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(out_mp3)


def tts(text, out_mp3):
    """同步封装。返回 out_mp3。"""
    asyncio.run(_edge_tts(text, out_mp3))
    return out_mp3


def cover(no, part, title, out_jpg, bg_frame=None):
    """1080×1920 统一封面。bg_frame 可选（三集不同帧、同一色调）。"""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1080, 1920
    if bg_frame and os.path.exists(bg_frame):
        bg = Image.open(bg_frame).convert("RGB").resize((W, H))
        # 压暗，保证文字可读
        overlay = Image.new("RGB", (W, H), (10, 10, 12))
        bg = Image.blend(bg, overlay, 0.55)
    else:
        bg = Image.new("RGB", (W, H), (10, 10, 12))
    d = ImageDraw.Draw(bg)

    def font(sz):
        for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, sz)
                except Exception:
                    pass
        return ImageFont.load_default()

    # 馆名条
    d.rectangle([0, 0, W, 120], fill=(10, 10, 12))
    d.text((60, 28), "档案管理员", font=font(56), fill=(245, 241, 232))
    # 编号印章（左上）
    d.rounded_rectangle([60, 160, 380, 260], radius=12, fill=(176, 58, 46))
    d.text((90, 178), f"No.{no}", font=font(56), fill=(255, 255, 255))
    # 集数徽章（右下）
    badge = PARTS.get(part, part)
    d.rounded_rectangle([W - 260, H - 320, W - 60, H - 200], radius=12,
                       outline=(245, 241, 232), width=4)
    d.text((W - 210, H - 295), badge, font=font(72), fill=(245, 241, 232))
    # 标题（中部）
    d.text((60, 900), title[:12], font=font(92), fill=(245, 241, 232))
    # AI声明条（底部）
    d.rectangle([0, H - 100, W, H], fill=(10, 10, 12))
    d.text((60, H - 80), "本视频内容由AI生成", font=font(40), fill=(150, 150, 150))
    bg.save(out_jpg, quality=92)
    return out_jpg


def assemble(clips, audio_mp3, out_mp4, target_dur=None):
    """N分镜 concat + 配音混流 + loudnorm。clips 为有序路径列表（数量不限）。
    2026-10-10 修：去掉 21 硬编码；每分镜时长 = 音频实际时长 / 分镜数（均匀裁剪），
    成片时长跟随实际音轨（pilot1：up 24/mid 24/down 23，音轨约 180-186s）。
    pilot 用已有标准化音轨，不调 TTS。
    """
    n = len(clips)
    if n == 0:
        raise ValueError("分镜列表为空")
    # 音频实际时长
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_mp3],
        capture_output=True, text=True)
    audio_dur = float(r.stdout.strip())
    per = audio_dur / n
    # filter_complex：每分镜统一分辨率 → trim 到 per 秒后 concat
    # 2026-10-10 加固：分镜分辨率可能不一致（如 down-13 曾为 480x832），
    # concat 要求同分辨率，先 scale+crop 归一化到 720x1280 防炸。
    fc_parts = []
    for i in range(n):
        fc_parts.append(
            f"[{i}:v]scale=720:1280:force_original_aspect_ratio=increase,"
            f"crop=720:1280,setsar=1,trim=0:{per:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
    fc_parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]")
    fc = ";".join(fc_parts)
    # 2026-10-10 改两步法：23 输入单遍（视频编码+loudnorm 音频）曾在 down 集 2:36 处
    # 卡死失败；分两步（先拼视频，再混音）实测稳定。
    tmp_v = out_mp4 + ".tmpv.mp4"
    cmd1 = ["ffmpeg", "-y", "-v", "error"]
    for c in clips:
        cmd1 += ["-i", os.path.abspath(c)]
    cmd1 += ["-filter_complex", fc,
             "-map", "[vout]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "20",
             "-an", tmp_v]
    r = subprocess.run(cmd1, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("组装失败(视频拼接): " + r.stderr[-800:])
    cmd2 = ["ffmpeg", "-y", "-v", "error",
            "-i", os.path.abspath(tmp_v), "-i", os.path.abspath(audio_mp3),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-filter:a", "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-c:a", "aac", "-shortest", out_mp4]
    r = subprocess.run(cmd2, capture_output=True, text=True)
    try:
        os.remove(tmp_v)
    except OSError:
        pass
    if r.returncode != 0:
        raise RuntimeError("组装失败(混音): " + r.stderr[-800:])
    return out_mp4


if __name__ == "__main__":
    # 自测：编号/开场白/封面（不调TTS）
    print("peek_no:", peek_no())
    for i in range(1, 7):
        print(i, opener(i, "001"))
    c = cover("001", "up", "明亡之谜", "/tmp/cover_test.jpg")
    print("封面:", c, os.path.getsize(c), "bytes")
