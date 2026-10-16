#!/usr/bin/env python3
"""
平台浏览器 fallback 队列看门狗（2026-10-15 用户要求自动切换）

每 5 分钟运行一次：
1. 检查 /home/hatch/data/perpetua/platform_browser_fallback/queue/ 是否有待处理任务
2. 有任务 → 输出 ALERT 信息（cron handoff 会送达主 agent Dash）
3. 主 agent 收到后开平台浏览器任务生成视频

注意：只有主 agent 能开 browser.spawn_task，所以这里只做检测和告警，不直接生成。

2026-10-16 P2-1 修（四脑议会 anti-idle）：告警去重——同一任务只告警一次，
之后每小时提醒一次；6h 未处理 → 升级并停止提醒。配额耗尽类任务标 do-not-retry
（带过期时间，红队 WEAKEN 对冲：配额每日重置，过期自动解除，不永久丢弃）。
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

QUEUE_DIR = "/home/hatch/data/perpetua/platform_browser_fallback/queue"
PROCESSING_DIR = "/home/hatch/data/perpetua/platform_browser_fallback/processing"
STATE_PATH = "/home/hatch/data/perpetua/platform_browser_fallback/watcher_state.json"

REMINDER_INTERVAL_H = 1
ESCALATE_AFTER_H = 6

# 配额耗尽类失败原因关键词 → do-not-retry（过期时间=下一个 UTC 午夜）
QUOTA_MARKERS = ("not enough credits", "额度不足", "quota", "配额")


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(st):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def _escalate(task_key, job):
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        from graded_assertions import escalate
        escalate(
            checker="platform-browser-fallback-watch",
            subject=str(job.get("job_id", task_key))[:40],
            condition="fallback_task_unprocessed_6h",
            severity="P2",
            detail="fallback 任务 %s 积压超 6h 未处理：%s" % (
                task_key, str(job.get("last_error", ""))[:160]),
        )
        return True
    except Exception as e:
        print(f"升级写入失败: {e}", file=sys.stderr)
        return False


def main():
    os.makedirs(QUEUE_DIR, exist_ok=True)
    os.makedirs(PROCESSING_DIR, exist_ok=True)

    jobs = []
    for fname in sorted(os.listdir(QUEUE_DIR)):
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
        return 0  # 静默：无任务不打扰

    now = _now()
    st = _load_state()
    tasks_st = st.setdefault("tasks", {})
    live_keys = set()
    alert_jobs = []
    escalated_jobs = []

    for job in jobs:
        key = job.get("fallback_id") or job["_file"]
        live_keys.add(key)
        ts = tasks_st.setdefault(key, {})
        created = _parse_ts(job.get("created_at", "")) or now
        age_h = (now - created).total_seconds() / 3600

        # 配额耗尽类 → do-not-retry（带过期）
        err = str(job.get("last_error", "")).lower()
        dnr_until = ts.get("do_not_retry_until")
        if any(m in err for m in QUOTA_MARKERS):
            _exp = _parse_ts(dnr_until) if dnr_until else None
            if _exp is None or _exp < now:
                nxt = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0)
                ts["do_not_retry_until"] = nxt.isoformat()
                ts["do_not_retry_reason"] = str(job.get("last_error", ""))[:120]
                print(f"NOTE: 任务 {key} 配额耗尽，do-not-retry 至 {nxt.isoformat()} "
                      f"（配额每日重置后自动解除）")
            continue  # 本轮不告警

        if ts.get("escalated"):
            continue  # 已升级过的 → 不再提醒

        # 6h 未处理 → 升级一次，停止提醒
        if age_h >= ESCALATE_AFTER_H:
            if _escalate(key, job):
                ts["escalated"] = True
                ts["escalated_at"] = now.isoformat()
                escalated_jobs.append(job)
            continue

        # 去重：首次告警；之后每小时提醒一次
        first = not ts.get("alerted_at")
        last_r = _parse_ts(ts.get("last_reminder_at", "")) or _parse_ts(ts.get("alerted_at", ""))
        due = first or (last_r is None) or ((now - last_r).total_seconds() / 3600 >= REMINDER_INTERVAL_H)
        if due:
            if first:
                ts["alerted_at"] = now.isoformat()
            else:
                ts["last_reminder_at"] = now.isoformat()
            alert_jobs.append(job)

    st["tasks"] = {k: v for k, v in tasks_st.items() if k in live_keys}
    _save_state(st)

    if escalated_jobs:
        print(f"ESCALATED: {len(escalated_jobs)} 个 fallback 任务积压超 6h，已升级，主 agent 请处理")
        for job in escalated_jobs:
            print(f"  - {job.get('fallback_id', job['_file'])}: {str(job.get('last_error', ''))[:100]}")
        return 1
    if not alert_jobs:
        return 0  # 本轮无需告警（去重/已升级/do-not-retry），静默

    print(f"ALERT: 平台浏览器 fallback 队列有 {len(alert_jobs)} 个待处理任务")
    print("=" * 60)
    for job in alert_jobs:
        print(f"\n任务: {job.get('fallback_id', job['_file'])}")
        print(f"  job_id: {job.get('job_id', '?')}")
        print(f"  创建时间: {job.get('created_at', '?')}")
        print(f"  prompt: {job.get('prompt', '')[:100]}...")
        print(f"  失败原因: {str(job.get('last_error', ''))[:200]}")
        print(f"  文件: {job['_path']}")
    print("=" * 60)
    print("\n主 agent 请开平台浏览器任务，到 geminigen.link 生成视频。")
    print("生成完成后下载到 out_dir，并在 done/ 写结果文件。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
