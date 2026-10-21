#!/usr/bin/env python3
"""保活 cron 存在性自检（2026-10-21 落地）。

起因：2026-10-21 平台侧静默丢失 semantica-keepalive（5m 保活 cron），
01:29 后 Semantica 三部分死亡无人拉起，kb.viralloopapp.com 502 约 10h，
靠用户报障才发现。教训：保活 cron 本身也要有存在性核查。

检查口径（本机可得的真相源）：
- 平台 cron：定义文件投影在 ~/workspace/cron.d、~/workspace/goals/*/crons、
  ~/workspace/system-cron.d 下（<job_id>__*.md，_archive 除外——被正常删除的
  job 文件会移入 _archive，不算丢失）。
- systemd 面：unit 文件在 /etc/systemd/system 且 timer 已 enabled。

告警分级（Rule 14）：首次发现缺失记 SUSPECT（写 anomaly ledger）；
连续 2 轮（≈2h）仍缺失 → escalate P1。恢复自动记 OK 并清状态。
状态文件：cron_existence_watch_state.json（同目录）。
"""
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"
sys.path.insert(0, BASE)
import graded_assertions as ga  # noqa: E402

CHECKER = "cron_existence_watch"
STATE_PATH = os.path.join(BASE, "cron_existence_watch_state.json")

# 平台保活 cron 预期清单（2026-10-21 研究员逐一验证存在，基线干净）。
# 注：dispatch-lifeline-watch 已于 2026-10-21 迁至 systemd（见 EXPECTED_TIMERS），
# 不再列入平台预期；dead-state-watchdog 同日迁移，一并在 systemd 面检查。
EXPECTED_PLATFORM = [
    "oa-watchdog", "mcp-watchdog", "commander-chat-processor",
    "queue-lease-reaper", "private-flip-scheduler",
    "musemain-fallback-daemon", "mcp-b-queue-consumer",
    "matrix-sync-ondemand", "tunnel-18901-keepalive",
    "tunnel-18738-keepalive", "tunnel-nano-keepalive",
    "nanomuse-mcp-tunnel-keepalive", "relay-18080-keepalive",
    "semantica-keepalive", "nanomuse-serve-keepalive",
    "perception-server-keepalive", "local-chrome-keepalive",
    "agent-browser-keepalive", "tianshu-console-keepalive",
    "browser-proxy-fwd-keepalive", "nano-webui-18737-keepalive",
]

EXPECTED_TIMERS = [
    "dash-dispatch-lifeline.timer",
    "dash-dead-state-watchdog.timer",
]

PROJECTION_ROOTS = [
    "/home/hatch/workspace/cron.d",
    "/home/hatch/workspace/goals",
    "/home/hatch/workspace/system-cron.d",
]


def platform_present(job_id):
    for root in PROJECTION_ROOTS:
        for path in glob.glob(os.path.join(root, "**", job_id + "__*.md"),
                              recursive=True):
            if "_archive" not in path:
                return True
    return False


def timer_present(unit):
    if not os.path.exists(os.path.join("/etc/systemd/system", unit)):
        return False
    r = subprocess.run(["systemctl", "is-enabled", unit],
                       capture_output=True, text=True, timeout=15)
    return r.stdout.strip() == "enabled"


def main():
    expected = [("platform", j) for j in EXPECTED_PLATFORM]
    expected += [("systemd", t) for t in EXPECTED_TIMERS]
    if os.environ.get("CRON_WATCH_SELFTEST") == "1":
        expected.append(("platform", "__selftest_missing__"))

    try:
        state = json.load(open(STATE_PATH))
    except Exception:
        state = {"missing": {}}
    missing_state = state.setdefault("missing", {})

    now = datetime.now(timezone.utc).isoformat()
    results, problems = [], []

    for plane, name in expected:
        key = f"{plane}:{name}"
        present = (platform_present(name) if plane == "platform"
                   else timer_present(name))
        if present:
            results.append(f"OK {key}")
            if key in missing_state:
                rec = ga.make_verdict(
                    ga.OK, f"{key} 已恢复存在", now, None,
                    checker=CHECKER, subject=f"cron:{name}",
                    checker_health={"probe_ok": True})
                ga.ledger_append(rec)
                del missing_state[key]
                results.append(f"RECOVERED {key}")
            continue
        # 缺失
        entry = missing_state.setdefault(
            key, {"first_seen": now, "runs": 0, "escalated": False})
        entry["runs"] += 1
        problems.append(f"{key} missing runs={entry['runs']}")
        subject = f"cron:{name}"
        if entry["runs"] == 1:
            rec = ga.make_verdict(
                ga.SUSPECT,
                f"保活调度缺失（{plane} 面未找到 {name}，首次发现）",
                now, None, checker=CHECKER, subject=subject,
                checker_health={"probe_ok": True,
                                "last_error": "definition absent"})
            ga.ledger_append(rec)
        elif entry["runs"] >= 2 and not entry["escalated"]:
            ga.escalate(CHECKER, subject, "keepalive schedule missing >=2h",
                        severity="P1",
                        detail=f"{key} 连续 {entry['runs']} 轮缺失，"
                               f"首次发现 {entry['first_seen']}")
            entry["escalated"] = True

    # 清理已不在预期清单内的状态（如自检项）
    current_keys = {f"{p}:{n}" for p, n in expected}
    for key in list(missing_state):
        if key not in current_keys:
            del missing_state[key]

    state["last_run"] = now
    state["expected_count"] = len(expected)
    json.dump(state, open(STATE_PATH, "w"), ensure_ascii=False, indent=1)

    print(json.dumps({"checked": len(expected),
                      "missing": problems,
                      "ts": now}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
