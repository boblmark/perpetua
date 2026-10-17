#!/usr/bin/env python3
"""
Arena.ai Video 生成后端（2026-10-17 接入）

状态：经 browser 工具验证可用，CDP 自动化被 reCAPTCHA v3 拦截。

可用性（2026-10-17 浏览器实测）：
- https://arena.ai/video 可访问，会话 bat08738@gmail.com 已登录
- Battle 模式：一次提交产出 2 条视频（2 个匿名模型）
- 无付费墙、无排队，生成约 2-5 分钟
- prompt 上限 2500 字符

调用方式（主 agent 经 browser.browse 派发）：
  任务模板见 ARENA_TASK_TEMPLATE，prompt 替换 {PROMPT} 即可。

工作流：
  1. 主 agent 用 browser.browse 打开 https://arena.ai/video
  2. 在 "Describe your video…" 输入 prompt，点 Send
  3. 等待跳转到 battle 页（https://arena.ai/c/...）
  4. 等两条视频都生成完成（"Generating video..." 消失）
  5. 下载两条视频到 /home/hatch/data/veo_inbox/arena_<jobid>_{a,b}.mp4
  6. 两条都进 QC，取优者进管线

限制：
- 模型匿名（Battle 模式不显示模型名），2 条都下载由 QC 决定取舍
- 不能走 CDP 无人值守（reCAPTCHA v3 拦截合成事件）
- 需要主 agent 派发 browser 任务（参考 geminigen 的 browser 兜底流程）

健康检查：dispatch_health.py 的 check_arena()（页面可达 + 输入框存在）
"""

ARENA_TASK_TEMPLATE = """Visit https://arena.ai/video and generate a video.

Steps:
1. Load https://arena.ai/video (session should already be logged in as bat08738@gmail.com)
2. Find the "Describe your video…" textbox, enter this prompt:
---
{PROMPT}
---
3. Click the "Send message" button
4. Wait for navigation to the battle page (URL like https://arena.ai/c/...)
5. Wait until BOTH videos finish generating (the "Generating video..." indicators disappear, both videos are playable)
6. Download both videos. Save them to the files provided for this task.
   Name them arena_{JOBID}_a.mp4 and arena_{JOBID}_b.mp4
7. Report back: the battle page URL, and confirmation that both videos were downloaded

Do NOT vote, do NOT pay, do NOT create accounts. This is a read-only generation task.
"""

ARENA_URL = "https://arena.ai/video"


def get_task_spec(prompt, job_id):
    """返回 browser.browse 任务文本，主 agent 直接用"""
    return ARENA_TASK_TEMPLATE.format(PROMPT=prompt, JOBID=job_id)


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Arena.ai video 后端：输出 browser 任务规格")
    ap.add_argument("--prompt", required=True, help="视频 prompt")
    ap.add_argument("--job-id", required=True, help="任务 ID")
    ap.add_argument("--print-task", action="store_true", help="只打印任务文本")
    args = ap.parse_args()

    task = get_task_spec(args.prompt, args.job_id)
    if args.print_task:
        print(task)
    else:
        print(f"Arena 后端需经 browser.browse 派发（CDP 被 reCAPTCHA 拦截）。")
        print(f"任务文本已生成，用 --print-task 查看完整内容。")
        print(f"URL: {ARENA_URL}")


if __name__ == "__main__":
    main()
