#!/usr/bin/env python3
"""Veo 半自动管线 (2026-10-08)。

免费档 Vids 无 API，只能走浏览器。流程：
  1. create: 生成 v5 prompt 包 → veo_jobs/pending/<job_id>.json
     （prompt 已按 Vids 优化，可直接复制粘贴）
  2. 人工/浏览器任务：在 Vids 里 File > Video size > 9:16 → Create AI videos
     → 粘贴 prompt → 生成 → File > Download > MP4 → 存到 veo_inbox/
     （文件名必须包含 job_id）
  3. collect: 扫描 veo_inbox/ → QC → 后处理 → 写入 awaiting_approval.json

用法：
  python3 veo_pipeline.py create --topic "smart security gate" --hook "Karen rams the gate arm, already mid-rant"
  python3 veo_pipeline.py collect
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/hatch/data")
JOBS_PENDING = BASE / "veo_jobs" / "pending"
JOBS_DONE = BASE / "veo_jobs" / "done"
INBOX = BASE / "veo_inbox"
APPROVAL = BASE / "perpetua" / "awaiting_approval.json"

for d in (JOBS_PENDING, JOBS_DONE, INBOX):
    d.mkdir(parents=True, exist_ok=True)


def create_job(topic, hook, karma_payoff=None):
    sys.path.insert(0, str(BASE / "perpetua"))
    from viral_prompt import build_viral_prompt
    pkg = build_viral_prompt(topic=topic, hook=hook, karma_payoff=karma_payoff)
    job_id = "veo_%s" % uuid.uuid4().hex[:8]
    job = {
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "generator": "veo",
        "topic": topic,
        "hook": hook,
        "vids_prompt": pkg["prompt"],
        "title": pkg["title"],
        "description": pkg["description"],
        "status": "pending_generation",
        "vids_steps": [
            "1. 打开 https://vids.google.com，新建视频项目",
            "2. File > Video size > 9:16（竖屏，必须先切）",
            "3. 点 'Create AI videos'，模型选 Omni，时长 8s",
            "4. 粘贴下方 vids_prompt，点 Generate",
            "5. File > Download > MP4，文件名保存为 {job_id}.mp4".format(job_id=job_id),
            "6. 放到 /home/hatch/data/veo_inbox/，运行 collect",
        ],
    }
    (JOBS_PENDING / f"{job_id}.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Job {job_id} 已创建")
    print(f"  标题: {pkg['title']}")
    print(f"  prompt 长度: {len(pkg['prompt'])} 字符")
    print(f"  job 文件: veo_jobs/pending/{job_id}.json")
    return job_id


def collect():
    sys.path.insert(0, str(BASE / "perpetua"))
    from pre_upload_qc import run_qc
    from postprocess_video import run_postprocess as postprocess

    collected = 0
    for mp4 in sorted(INBOX.glob("*.mp4")):
        job_id = mp4.stem
        job_file = JOBS_PENDING / f"{job_id}.json"
        if not job_file.exists():
            print(f"跳过 {mp4.name}：找不到对应 job")
            continue
        job = json.loads(job_file.read_text(encoding="utf-8"))
        print(f"处理 {job_id} ...")

        # Veo 原生音频开头常为淡入，先做后处理（去静音+标准化+包络），
        # 再对成品跑 QC——QC 验的是观众实际看到的东西。
        # 只用音频链（apply_audio_envelope），不用整套 run_postprocess
        #（后者含 loop_check/烧字幕，不适合 Veo 原生输出）。
        # 2026-10-08：如果原音频已达标（≥-18dBFS），跳过后处理，避免破坏好音频。
        from pre_upload_qc import _check_audio_first_100ms
        from postprocess_video import apply_audio_envelope
        try:
            audio_st, _ = _check_audio_first_100ms(str(mp4))
            if audio_st == "pass":
                # 原音频已达标，直接复制，不跑破坏性后处理
                tmp_fixed = BASE / "veo_jobs" / "done" / f"{job_id}_fixed.mp4"
                shutil.copy(str(mp4), str(tmp_fixed))
            else:
                ok, enveloped = apply_audio_envelope(str(mp4))
                if not ok or not enveloped:
                    raise RuntimeError("apply_audio_envelope 返回失败")
                # 移到固定位置
                tmp_fixed = BASE / "veo_jobs" / "done" / f"{job_id}_fixed.mp4"
                shutil.move(enveloped, str(tmp_fixed))
        except Exception as e:
            print(f"  后处理失败: {e}")
            job["status"] = "postprocess_failed"
            (JOBS_PENDING / f"{job_id}.json").write_text(
                json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            continue

        # QC（fail-closed，对成品）
        qc = run_qc(str(tmp_fixed))
        if not qc.get("passed"):
            print(f"  QC 未通过: {qc.get('rejects', [])[:2]}")
            job["status"] = "qc_failed"
            job["qc_rejects"] = qc.get("rejects", [])
            (JOBS_PENDING / f"{job_id}.json").write_text(
                json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
            continue

        # 成品即最终文件
        out = BASE / "veo_jobs" / "done" / f"{job_id}_final.mp4"
        tmp_fixed.rename(out)

        # 进待审批
        approval = []
        if APPROVAL.exists():
            approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
        approval.append({
            "job_id": job_id,
            "generator": "veo",
            "video_file": str(out),
            "title": job["title"],
            "description": job["description"],
            "topic": job["topic"],
            "qc_score": qc.get("experience_score"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        APPROVAL.write_text(json.dumps(approval, ensure_ascii=False, indent=1),
                            encoding="utf-8")

        job["status"] = "awaiting_approval"
        job["qc_score"] = qc.get("experience_score")
        shutil.move(str(job_file), str(JOBS_DONE / f"{job_id}.json"))
        mp4.unlink()
        collected += 1
        print(f"  ✅ QC {qc.get('experience_score')}/100，进待审批")

    print(f"收集完成：{collected} 个进待审批")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--topic", required=True)
    c.add_argument("--hook", required=True)
    c.add_argument("--karma", default=None)
    sub.add_parser("collect")
    args = ap.parse_args()
    if args.cmd == "create":
        create_job(args.topic, args.hook, args.karma)
    elif args.cmd == "collect":
        collect()
