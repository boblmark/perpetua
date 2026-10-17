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
- Battle 模式不显示模型名（生成完成后 battle 页会揭示，如 minimax-h3-max），2 条都下载由 QC 决定取舍
- 不能走 CDP 无人值守（reCAPTCHA v3 拦截合成事件）
- 需要主 agent 派发 browser 任务（参考 geminigen 的 browser 兜底流程）

编辑模式（2026-10-18 浏览器实测确认）：
- Video modality 明确标注 "Generate and edit videos"
- 两条路：(a) battle 页每条视频卡片的 Edit 按钮 → 视频以附件 chip 挂到输入框，
  prompt 框变为 "Describe how you want to edit this video…"（2500 字符上限），
  点 Send 后走正常 Battle 流程（2 个匿名模型）产出 2 条编辑版；
  (b) 输入框 "+" → "Add files" 上传外部视频文件（页面标注 Up to 10MB per file，
  未声明格式/时长限制），再描述编辑内容。注意：实测中浏览器拒绝了原生文件
  选择器的自动化点击，外部文件上传尚未端到端验证，编辑 arena 自家视频（Edit 按钮路）已验证可行。
- 用途：QC 未过的成片可直接描述修改（如换钩子/修穿帮），不用整条重生成；
  也可用于重写环：先 Battle 出 2 候选，挑优者 Edit 迭代。

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

ARENA_EDIT_TASK_TEMPLATE = """Visit {BATTLE_URL} and edit one of its videos with a text description.

Steps:
1. Load {BATTLE_URL} (session should already be logged in as bat08738@gmail.com)
2. Find the video card for model output "{CHOICE}" (the two cards are labeled arena_{JOBID}_a / arena_{JOBID}_b by download order; pick the one you downloaded as "{CHOICE}")
3. Click its "Edit" button (pencil icon, top-right of the card). The video attaches to the bottom composer as a "video.mp4" chip and the prompt box changes to "Describe how you want to edit this video…"
4. Enter this edit description:
---
{EDIT_PROMPT}
---
5. Click the "Send message" button
6. Wait until BOTH edited videos finish generating (the "Generating video..." indicators disappear, both videos are playable)
7. Download both videos. Save them to the files provided for this task.
   Name them arena_{JOBID}_edit_a.mp4 and arena_{JOBID}_edit_b.mp4
8. Report back: the new battle page URL, and confirmation that both videos were downloaded

Do NOT vote, do NOT pay, do NOT create accounts. This is a read-only edit task.
"""

ARENA_UPLOAD_EDIT_TASK_TEMPLATE = """Visit https://arena.ai/video and edit an uploaded video file with a text description.

Steps:
1. Load https://arena.ai/video (session should already be logged in as bat08738@gmail.com)
2. Click the "+" button in the composer, then "Add files", and select the video file provided for this task (must be under 10MB)
3. Once the file attaches as a chip in the composer, enter this edit description in the "Describe how you want to edit this video…" box:
---
{EDIT_PROMPT}
---
4. Click the "Send message" button
5. Wait until BOTH edited videos finish generating (the "Generating video..." indicators disappear, both videos are playable)
6. Download both videos. Save them to the files provided for this task.
   Name them arena_{JOBID}_uploadedit_a.mp4 and arena_{JOBID}_uploadedit_b.mp4
7. Report back: the battle page URL, and confirmation that both videos were downloaded

Do NOT vote, do NOT pay, do NOT create accounts. This is a read-only edit task.
"""

ARENA_URL = "https://arena.ai/video"


def get_task_spec(prompt, job_id):
    """返回 browser.browse 任务文本，主 agent 直接用"""
    return ARENA_TASK_TEMPLATE.format(PROMPT=prompt, JOBID=job_id)


def get_edit_task_spec(battle_url, choice, edit_prompt, job_id):
    """编辑 battle 页已生成视频：battle_url + 选 a/b + 编辑描述"""
    return ARENA_EDIT_TASK_TEMPLATE.format(
        BATTLE_URL=battle_url, CHOICE=choice,
        EDIT_PROMPT=edit_prompt, JOBID=job_id)


def get_upload_edit_task_spec(edit_prompt, job_id):
    """上传外部视频文件再描述编辑（文件经 browser 任务 files 授予）"""
    return ARENA_UPLOAD_EDIT_TASK_TEMPLATE.format(
        EDIT_PROMPT=edit_prompt, JOBID=job_id)


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Arena.ai video 后端：输出 browser 任务规格")
    ap.add_argument("--prompt", help="视频 prompt（生成模式）")
    ap.add_argument("--job-id", required=True, help="任务 ID")
    ap.add_argument("--print-task", action="store_true", help="只打印任务文本")
    ap.add_argument("--mode", choices=["generate", "edit", "upload-edit"],
                    default="generate", help="generate=文本生成，edit=编辑 battle 视频，upload-edit=上传外部文件再编辑")
    ap.add_argument("--battle-url", help="edit 模式：battle 页 URL")
    ap.add_argument("--choice", choices=["a", "b"], help="edit 模式：编辑 a/b 哪条")
    ap.add_argument("--edit-prompt", help="edit/upload-edit 模式：编辑描述")
    args = ap.parse_args()

    if args.mode == "generate":
        if not args.prompt:
            ap.error("--mode generate 需要 --prompt")
        task = get_task_spec(args.prompt, args.job_id)
    elif args.mode == "edit":
        if not (args.battle_url and args.choice and args.edit_prompt):
            ap.error("--mode edit 需要 --battle-url/--choice/--edit-prompt")
        task = get_edit_task_spec(args.battle_url, args.choice,
                                  args.edit_prompt, args.job_id)
    else:
        if not args.edit_prompt:
            ap.error("--mode upload-edit 需要 --edit-prompt")
        task = get_upload_edit_task_spec(args.edit_prompt, args.job_id)

    if args.print_task:
        print(task)
    else:
        print(f"Arena 后端需经 browser.browse 派发（CDP 被 reCAPTCHA 拦截）。")
        print(f"任务文本已生成（mode={args.mode}），用 --print-task 查看完整内容。")
        print(f"URL: {ARENA_URL}")


if __name__ == "__main__":
    main()
