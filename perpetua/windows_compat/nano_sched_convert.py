#!/usr/bin/env python3
"""Muse cron .md（agent 平台任务）→ nanoMuse agent 任务 JSON 翻译器。

背景：
  sched_win.py 把 118 个 cron 定义分成 21 直接命令 / 92 agent平台 / 5 未解析。
  92 个 agent 平台任务的 .md 正文是自然语言任务指令（含判断逻辑），在 Muse
  平台上由 worker agent 执行；在 nanoMuse 侧由 headless MuseAgent 执行
  （见 /home/hatch/data/nanomuse-migration/scheduler/agent_context.py
  的 hydrate_and_run）。本脚本把 .md 全文保留为 agent_prompt，而非只抽命令，
  因为判断逻辑（如 exit 码分级、静默条件）都在正文里。

用法：
  nano_sched_convert.py [--out DIR] [--dry-run]

输出：
  nano_agent_jobs.json —— nanoMuse 调度器可加载的任务列表
  （id/name/schedule/owner/mode=agent/agent_prompt/delivery/timeout_s）
  NANO_COVERAGE.txt —— 覆盖率报告
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sched_win import find_cron_files, extract_command  # noqa: E402

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
FNAME_RE = re.compile(
    r"^(?P<name>.+?)__(?P<kind>interval|daily|weekly|monthly|runonce)@(?P<spec>[^.]+)\.md$")
DOW_MAP = {"Mon": "1", "Tue": "2", "Wed": "3", "Thu": "4",
           "Fri": "5", "Sat": "6", "Sun": "0"}


def parse_schedule_nano(path):
    """文件名 → nanoMuse scheduler.parse_cron 兼容格式。

    interval:30s/10m/1h / daily:09:30 / weekly:1-09:30 / monthly:1-09:49
    runonce → ("runonce", fire_at_iso) 特殊处理（常驻调度器不直接支持）。
    """
    m = FNAME_RE.match(os.path.basename(path))
    if not m:
        return None, None
    kind, spec = m.group("kind"), m.group("spec")
    if kind == "interval":
        im = re.match(r"^(?P<n>\d+)(?P<u>[smhd])$", spec)
        if not im:
            return None, None
        n, u = im.group("n"), im.group("u")
        return f"interval:{n}{u}", None
    if kind == "daily":
        dm = re.match(r"^(?P<h>\d{2}):(?P<m>\d{2})", spec)
        if not dm:
            return None, None
        return f"daily:{dm.group('h')}:{dm.group('m')}", None
    if kind == "weekly":
        wm = re.match(r"^(?P<dow>[A-Za-z]{3})-(?P<h>\d{2}):(?P<m>\d{2})", spec)
        if not wm or wm.group("dow") not in DOW_MAP:
            return None, None
        return f"weekly:{DOW_MAP[wm.group('dow')]}-{wm.group('h')}:{wm.group('m')}", None
    if kind == "monthly":
        mm = re.match(r"^(?P<dom>\d{1,2})-(?P<h>\d{2}):(?P<m>\d{2})", spec)
        if not mm:
            return None, None
        return f"monthly:{int(mm.group('dom'))}-{mm.group('h')}:{mm.group('m')}", None
    if kind == "runonce":
        return "runonce", spec  # spec 为 ISO datetime
    return None, None


def parse_frontmatter(path):
    """返回 (fm_dict, body)。fm 用轻量解析，只取需要的键。"""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None, None
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    for key in ("id", "title", "enabled", "owner", "mode"):
        mm = re.search(rf"^{key}:\s*(.+?)\s*$", fm_text, re.M)
        if mm:
            v = mm.group(1).strip().strip("'\"")
            fm[key] = v
    # delivery chat_id（可能多行，取所有 uuid）
    fm["delivery"] = re.findall(
        r"chat_id:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        fm_text)
    return fm, body




def job_timeout_s(nano_sched):
    """按调度间隔给超时：interval 留 30s 余量封顶 900s；daily/weekly 给 900s。"""
    if nano_sched.startswith("interval:"):
        v = nano_sched[9:]
        if v.endswith("h"):
            secs = int(v[:-1]) * 3600
        else:
            secs = int(v[:-1]) * 60
        return max(180, min(900, secs - 30))
    return 900


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = find_cron_files()
    jobs, skipped = [], []
    for path in files:
        cmd, kind = extract_command(path)
        if kind != "agent-platform":
            continue  # 只处理 92 个 agent 平台任务
        fm, body = parse_frontmatter(path)
        if fm is None:
            skipped.append((path, "读文件失败"))
            continue
        if fm.get("enabled", "true").lower() not in ("true", "1", "yes"):
            skipped.append((fm.get("id", path), "disabled"))
            continue
        nano_sched, runonce_at = parse_schedule_nano(path)
        if not nano_sched:
            skipped.append((fm.get("id", path), "schedule 未解析"))
            continue
        job_id = fm.get("id") or os.path.basename(path).split("__")[0]
        job = {
            "id": job_id,
            "name": fm.get("title", job_id),
            "schedule": nano_sched,
            "owner": fm.get("owner", ""),
            "mode": "agent",
            "agent_prompt": body.strip(),
            "prompt_chars": len(body.strip()),
            "delivery": [{"chat_id": c} for c in fm.get("delivery", [])],
            "timeout_s": job_timeout_s(nano_sched),
            "source": path,
        }
        if nano_sched == "runonce":
            # 常驻调度器不直接支持 runonce：标记 fire_at，由一次性 runner 消费后删除
            job["mode"] = "runonce"
            job["fire_at"] = runonce_at
            job["timeout_s"] = 900
        jobs.append(job)

    jobs.sort(key=lambda j: j["id"])
    report_lines = [
        f"扫描 cron 文件: {len(files)}",
        f"agent 平台任务: {len(jobs) + len(skipped)}",
        f"翻译成功: {len(jobs)}",
        f"跳过: {len(skipped)}",
        "",
        "== 跳过明细 ==",
    ]
    for jid, reason in skipped:
        report_lines.append(f"  {jid}: {reason}")
    report = "\n".join(report_lines) + "\n"

    print(f"[nano-convert] agent 任务: 翻译成功 {len(jobs)} / 跳过 {len(skipped)}")
    for jid, reason in skipped:
        print(f"  SKIP {jid}: {reason}")

    if not args.dry_run:
        out_json = os.path.join(args.out, "nano_agent_jobs.json")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=1)
        # 合法性自检
        json.load(open(out_json, encoding="utf-8"))
        with open(os.path.join(args.out, "NANO_COVERAGE.txt"),
                  "w", encoding="utf-8") as f:
            f.write(report)
            f.write("\n== 任务清单 ==\n")
            for j in jobs:
                f.write(f"  {j['id']}: {j['schedule']} owner={j['owner'] or '-'} "
                        f"prompt={j['prompt_chars']}字 timeout={j['timeout_s']}s\n")
        print(f"[nano-convert] 已写 {out_json} + NANO_COVERAGE.txt")
    return jobs


if __name__ == "__main__":
    main()
