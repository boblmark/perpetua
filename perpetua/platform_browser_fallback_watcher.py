#!/usr/bin/env python3
"""
平台浏览器 fallback 队列看门狗（2026-10-15 用户要求自动切换）

每 5 分钟运行一次：
1. 检查 /home/hatch/data/perpetua/platform_browser_fallback/queue/ 是否有待处理任务
2. 有任务 → 输出 ALERT 信息（cron handoff 会送达主 agent Dash）
3. 主 agent 收到后开平台浏览器任务生成视频

注意：只有主 agent 能开 browser.spawn_task，所以这里只做检测和告警，不直接生成。
"""
import json
import os
import sys
from datetime import datetime, timezone

QUEUE_DIR = "/home/hatch/data/perpetua/platform_browser_fallback/queue"
PROCESSING_DIR = "/home/hatch/data/perpetua/platform_browser_fallback/processing"

def main():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    os.makedirs(PROCESSING_DIR, exist_ok=True)
    
    jobs = []
    for fname in os.listdir(QUEUE_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(QUEUE_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                job = json.load(f)
            job["_file"] = fname
            job["_path"] = fpath
            jobs.append(job)
        except Exception as e:
            print(f"读取任务文件失败 {fname}: {e}", file=sys.stderr)
    
    if not jobs:
        # 静默：无任务不打扰
        return 0
    
    # 有任务 → 输出 ALERT，cron handoff 会送达
    print(f"ALERT: 平台浏览器 fallback 队列有 {len(jobs)} 个待处理任务")
    print("=" * 60)
    for job in jobs:
        created = job.get("created_at", "?")
        job_id = job.get("job_id", "?")
        fallback_id = job.get("fallback_id", "?")
        prompt_preview = job.get("prompt", "")[:100]
        last_error = job.get("last_error", "")[:200]
        print(f"\n任务: {fallback_id}")
        print(f"  job_id: {job_id}")
        print(f"  创建时间: {created}")
        print(f"  prompt: {prompt_preview}...")
        print(f"  失败原因: {last_error}")
        print(f"  文件: {job['_path']}")
    
    print("=" * 60)
    print("\n主 agent 请开平台浏览器任务，到 geminigen.link 生成视频。")
    print("生成完成后下载到 out_dir，并在 done/ 写结果文件。")
    
    return 1  # exit=1 表示有待处理，handoff 会报告

if __name__ == "__main__":
    sys.exit(main())
