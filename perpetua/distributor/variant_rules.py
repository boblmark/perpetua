#!/usr/bin/env python3
"""策略C 各平台改写规则（2026-10-10 四脑议会 D20261010-021 落地）。

输入：首发视频的 {title, desc, tags, cover_path, cluster}
输出：按平台改写后的 {title, desc, tags, cover_path}
规则来自 AI Studio MUST/NEVER 条文，逐条可审计。v1 为规则模板改写，不调 LLM。
封面变体用 PIL 生成（大字报/角标/3:4裁切），源图缺失则 cover_path=None。
"""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
VARIANT_DIR = os.path.join(BASE, "cover_variants")
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
FONT_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

os.makedirs(VARIANT_DIR, exist_ok=True)

# 平台优先级（陪审团裁决）
PRIORITY = {
    "domestic": ["shipinhao", "bilibili", "xiaohongshu", "kuaishou"],
    "overseas": ["facebook", "tiktok", "x"],
}
# distributor.py 的 PLATFORMS 键名映射（video号/快手 v1 复用 hold 备料通道）
PLATFORM_KEYMAP = {
    "shipinhao": "xiaohongshu",
    "bilibili": "bilibili",
    "xiaohongshu": "xiaohongshu",
    "kuaishou": "xiaohongshu",
    "facebook": "facebook",
    "tiktok": "tiktok",
    "x": "x",
}


def _font(size, cjk=True):
    try:
        return ImageFont.truetype(FONT_BOLD if cjk else FONT_DEJAVU, size)
    except Exception:
        return ImageFont.load_default()


def _banner_cover(src, text, tag=""):
    """顶部黑底大字报（视频号/快手）。"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    bh = int(H * 0.16)
    d.rectangle([0, 0, W, bh], fill=(8, 8, 8))
    f = _font(int(bh * 0.42))
    bbox = d.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, int(bh * 0.22)), text, font=f, fill=(255, 215, 0))
    if tag:
        f2 = _font(int(bh * 0.3), cjk=False)
        d.rounded_rectangle([14, 14, 150, 64], radius=10, fill=(180, 30, 30))
        d.text((30, 22), tag, font=f2, fill=(255, 255, 255))
    return im


def _sticker_cover(src, text="DUJIA"):
    """右上角去重角标（TikTok 防查重）。"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    f = _font(44, cjk=False)
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x0, y0 = W - tw - 60, 40
    d.rounded_rectangle([x0 - 18, y0 - 12, x0 + tw + 18, y0 + th + 12],
                        radius=14, fill=(10, 10, 10))
    d.text((x0, y0), text, font=f, fill=(255, 255, 255))
    return im


def _crop_34(src):
    """中央 3:4 裁切（小红书）。"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    target_ratio = 3 / 4
    if W / H > target_ratio:
        nw = int(H * target_ratio)
        x0 = (W - nw) // 2
        im = im.crop((x0, 0, x0 + nw, H))
    return im


def _save_variant(im, source_id, platform):
    if im is None:
        return None
    p = os.path.join(VARIANT_DIR, "%s_%s.png" % (source_id, platform))
    im.save(p)
    return p


def _load_cover(cover_path):
    if cover_path and os.path.exists(cover_path):
        return cover_path
    return None


def _rw_shipinhao(v):
    title = "历史真相：" + v["title"] + "|未解之谜大解密"
    desc = (v["desc"] + "\n【互动】这段历史您怎么看？欢迎在评论区聊聊，"
            "转发给爱看历史的朋友一起探讨。")
    cover = _load_cover(v.get("cover_path"))
    cv = _save_variant(_banner_cover(cover, v["title"][:12], "JIE MI"),
                       v["source_id"], "shipinhao") if cover else None
    return {"title": title[:64], "desc": desc,
            "tags": v["tags"] + ["历史真相", "未解之谜"], "cover_path": cv or cover}


def _rw_bilibili(v):
    title = "【硬核考据】" + v["title"] + "_大型历史解密现场"
    desc = (v["desc"] + "\n【参考资料】本期涉及史料已整理，考据党欢迎逐帧验证；"
            "一键三连支持档案馆持续解密。")
    cover = _load_cover(v.get("cover_path"))
    return {"title": title[:80], "desc": desc,
            "tags": v["tags"] + ["历史", "考据"], "cover_path": cover}


def _rw_xiaohongshu(v):
    title = "挖到一个离谱的历史真相：" + v["title"] + "，看完我沉默了"
    desc = (v["desc"] + "\n#历史 #未解之谜 #涨知识 "
            "你们觉得真相是什么？评论区蹲一个课代表")
    cover = _load_cover(v.get("cover_path"))
    cv = _save_variant(_crop_34(cover), v["source_id"], "xiaohongshu") if cover else None
    return {"title": title[:64], "desc": desc,
            "tags": v["tags"] + ["历史", "涨知识"], "cover_path": cv or cover}


def _rw_kuaishou(v):
    title = "太敢拍了！" + v["title"] + "，结局所有人没料到"
    desc = v["desc"] + "\n老铁们双击点赞，评论区说说你的看法！"
    cover = _load_cover(v.get("cover_path"))
    cv = _save_variant(_banner_cover(cover, "高潮预警", "SHI PAI"),
                       v["source_id"], "kuaishou") if cover else None
    return {"title": title[:64], "desc": desc,
            "tags": v["tags"] + ["历史"], "cover_path": cv or cover}


def _rw_facebook(v):
    title = v["title"] + " -- you won't believe what happened next"
    desc = (v["desc"] + "\nShare this with someone who loves history! "
            "Follow for more AI-restored archives.")
    cover = _load_cover(v.get("cover_path"))
    return {"title": title[:100], "desc": desc,
            "tags": v["tags"] + ["history"], "cover_path": cover}


def _rw_tiktok(v):
    title = v["title"] + " #history #mystery"
    desc = v["desc"] + "\n#history #mystery #fyp"
    cover = _load_cover(v.get("cover_path"))
    cv = _save_variant(_sticker_cover(cover), v["source_id"], "tiktok") if cover else None
    return {"title": title[:100], "desc": desc,
            "tags": v["tags"] + ["history", "fyp"], "cover_path": cv or cover}


def _rw_x(v):
    title = v["title"] + " -- the footage changes everything"
    desc = (v["desc"] + "\nWhat do YOU think really happened? "
            "Reply with your theory")
    cover = _load_cover(v.get("cover_path"))
    return {"title": title[:100], "desc": desc,
            "tags": v["tags"] + ["history"], "cover_path": cover}


REWRITERS = {
    "shipinhao": _rw_shipinhao,
    "bilibili": _rw_bilibili,
    "xiaohongshu": _rw_xiaohongshu,
    "kuaishou": _rw_kuaishou,
    "facebook": _rw_facebook,
    "tiktok": _rw_tiktok,
    "x": _rw_x,
}


def build_variant(platform, video):
    """video: {source_id,title,desc,tags,cover_path,cluster}"""
    fn = REWRITERS.get(platform)
    if not fn:
        return None
    try:
        return fn(video)
    except Exception as e:
        return {"error": str(e)}
