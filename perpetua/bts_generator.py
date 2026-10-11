#!/usr/bin/env python3
"""
BTS（幕后揭秘）短视频制作规格生成器 —— 骨架版。

目的：为代运营获客生产内容弹药。每条 BTS 视频回答一个问题：
    "这条爆款 Shorts 是怎么被 AI 生产出来的？"
把 Perpetua 流水线本身变成可展示、可售卖的产品证据。

输入：一条已发布视频的 video_id
输出：/home/hatch/data/perpetua/bts_specs/bts_<video_id>.json
      —— 不是视频本身，是制作规格文档（钩子文案/分镜/标题/描述/置顶评论），
         交给视频生成环节按规格生产。

用法：
    python3 bts_generator.py <video_id> [--out DIR] [--views N]

注意：
  - 只读 pipeline_queue.json，不改任何生产代码、不发布任何内容。
  - 播放量尽量从本地数据取；取不到则记为 "TBD"，由调用方用 --views 传入。
"""
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import argparse
import json
import os
import re
import sys

PERPETUA_DIR = os.path.dirname(os.path.abspath(__file__))
if PERPETUA_DIR not in sys.path:
    sys.path.insert(0, PERPETUA_DIR)
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db
QUEUE_PATH = os.path.join(PERPETUA_DIR, "pipeline_queue.json")  # 已迁 SQLite，路径仅留作注释
DEFAULT_OUT = os.path.join(PERPETUA_DIR, "bts_specs")

# 8 阶段流水线（对外展示版文案）
PIPELINE_STAGES = [
    "Trend radar", "Topic generation", "AI review gate", "Video generation",
    "3-tier QC", "Auto publish", "Post-publish ops", "Data flywheel",
]


def find_video(video_id):
    """在 pipeline_queue.json 里按 video_id 找已发布条目。"""
    # D20261011-001 P1: 已迁 SQLite
    queue = queue_db.pipeline_load()
    for item in queue:
        ur = item.get("upload_result") or ""
        m = re.search(r'"video_id":\s*"([^"]+)"', ur)
        if m and m.group(1) == video_id:
            return item
    return None


def get_views(item, override=None):
    """播放量：调用方传入优先；否则尝试本地数据源；都没有则 TBD。

    TODO(接入真实数)：接 youtube/yt.py 或 Analytics 拉取 viewCount，
    目前骨架阶段不强依赖，避免在生成规格时调外部 API。
    """
    if override is not None:
        return override
    return "TBD"


def build_spec(item, video_id, views):
    """组装 BTS 制作规格。"""
    title = item.get("title", "")
    hook = item.get("hook", "")
    topic = item.get("topic", "")
    review_score = item.get("review_score")
    review_source = item.get("review_source", "ask_studio")
    qc = item.get("qc_report") or {}
    tags = item.get("tags", [])
    url = f"https://youtu.be/{video_id}"

    # 3 秒钩子：必须在前 3 秒讲清"这条视频是 AI 做的"
    hook_copy = (
        f"This viral Short got {views} views. No camera. No actor. "
        f"100% made by AI in under 10 minutes. Here's exactly how."
        if views != "TBD" else
        "This viral Short was never filmed. No camera. No actor. "
        "100% made by AI in under 10 minutes. Here's exactly how."
    )

    storyboard = [
        {"t": "0-3s", "beat": "HOOK",
         "visual": "Split screen: LEFT = the viral Short playing, RIGHT = terminal/code scrolling. Big red caption: 'AI MADE THIS'.",
         "vo": hook_copy},
        {"t": "3-8s", "beat": "TOPIC",
         "visual": "Trend radar UI mock + topic card popping up. Highlight the hook line.",
         "vo": f"It started with one hook: '{hook}'. Our trend radar flagged it, dedup gates cleared it."},
        {"t": "8-14s", "beat": "REVIEW GATE",
         "visual": f"Score meter animating to {review_score}/100. Stamp: APPROVED.",
         "vo": f"Then our AI reviewer scored it {review_score} out of 100. Below 85? It never gets made. This one passed."},
        {"t": "14-20s", "beat": "GENERATION + QC",
         "visual": "Timelapse of video rendering → 3 checkmarks (compliance / viral-score / hygiene).",
         "vo": "AI generated the video, then 3-tier quality control checked it. Failures get auto-fixed or regenerated."},
        {"t": "20-25s", "beat": "PUBLISH + FLYWHEEL",
         "visual": "Upload animation → view counter ticking up → data flowing back into a gear icon.",
         "vo": "Auto-published at the data-driven slot. Every view feeds back into the next video. That's the flywheel."},
        {"t": "25-28s", "beat": "CTA",
         "visual": "End card: 'Want this factory for YOUR niche?' + contact.",
         "vo": "This pipeline runs 3 videos a day for our channel. Want one for your niche? Link in bio."},
    ]

    bts_title = f"🤖 How AI Made This Viral Short (No Camera, No Actor)"
    description = (
        f"Behind the scenes: this Short ({url}) was produced end-to-end by Perpetua, "
        f"our AI Shorts factory.\n\n"
        f"Original video: \"{title}\"\n"
        f"AI review score: {review_score}/100 ({review_source}) | "
        f"QC: {'passed' if qc.get('passed') else 'see report'} | Views: {views}\n\n"
        f"The 8 stages: {' → '.join(PIPELINE_STAGES)}\n\n"
        f"Want an AI Shorts pipeline for your brand? → {{CONTACT_LINK}}\n\n"
        f"#Shorts #AI #BehindTheScenes"
    )
    pinned = (
        "Which part surprised you most? 👇\n"
        "We run this factory as a service — 3 AI Shorts/day for your niche. "
        "Details: {{CONTACT_LINK}}"
    )

    return {
        "spec_version": "bts-v1",
        "video_id": video_id,
        "source_video": {
            "video_id": video_id,
            "url": url,
            "title": title,
            "topic": topic,
            "hook": hook,
            "review_score": review_score,
            "review_source": review_source,
            "qc_passed": bool(qc.get("passed")),
            "views": views,
            "tags": tags,
        },
        "bts_video": {
            "hook_copy_en": hook_copy,
            "storyboard": storyboard,
            "title": bts_title,
            "description": description,
            "pinned_comment": pinned,
            "duration_target_s": 28,
            "cta": "Link in bio → {{CONTACT_LINK}}",
        },
        "note": "规格文档，不是成片。按 storyboard 交给视频生成环节生产；{{CONTACT_LINK}} 发布前替换为真实联系方式。",
    }


def main():
    ap = argparse.ArgumentParser(description="生成 BTS 短视频制作规格（JSON）")
    ap.add_argument("video_id", help="已发布视频的 video_id")
    ap.add_argument("--out", default=DEFAULT_OUT, help="规格输出目录")
    ap.add_argument("--views", default=None, help="手动传入播放量（否则记 TBD）")
    args = ap.parse_args()

    item = find_video(args.video_id)
    if not item:
        print(f"未在 pipeline_queue.json 找到 video_id={args.video_id} 的已发布条目", file=sys.stderr)
        sys.exit(1)

    views = args.views if args.views is not None else get_views(item)
    # views 可能是纯数字字符串，转 int 方便展示
    if isinstance(views, str) and views.isdigit():
        views = int(views)

    spec = build_spec(item, args.video_id, views)
    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, f"bts_{args.video_id}.json")
    atomic_write_json(out_path, spec)
    print(f"BTS 规格已生成：{out_path}")


if __name__ == "__main__":
    main()
