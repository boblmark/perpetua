#!/usr/bin/env python3
"""Ask Studio 亲派计数守卫（议会 D20261017-00X KILL#10 修订）。

背景：worker 浏览器槽位系统性进不去 Studio，主 agent 亲派 6/6 成功。
红队 KILL：6/6 是小样本，不能作为永久 bypass 依据；亲派无上限=
单点故障 SOP。

规则：7 天内亲派超过 3 次 → 升级为"通道机制检修"
（查 worker 槽位路由问题），不再无脑亲派。

用法：
    python3 ask_studio_dispatch_guard.py record --reason "..."  # 亲派后记一笔
    python3 ask_studio_dispatch_guard.py check                  # 升级前检查
        输出 OK / NEEDS_CHANNEL_REPAIR:<7天内次数>
供 W5 监控读取同一日志。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

LOG = "/home/hatch/data/ask_studio/personal_dispatch_log.jsonl"
CAP_7D = 3


def _load():
    out = []
    try:
        with open(LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except FileNotFoundError:
        pass
    return out


def record(reason=""):
    entry = {"at": datetime.now(timezone.utc).isoformat(),
             "by": "dash_main", "reason": reason}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print("recorded personal dispatch: %s" % reason[:80])


def count_7d():
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    n = 0
    for e in _load():
        try:
            at = datetime.fromisoformat(e["at"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            if at >= cutoff:
                n += 1
        except Exception:
            continue
    return n


def check():
    n = count_7d()
    if n > CAP_7D:
        print("NEEDS_CHANNEL_REPAIR:%d" % n)
        return 1
    print("OK:%d" % n)
    return 0


# C6（2026-10-28）：通道检修状态的唯一口径，供 anomaly_watchdog
# 的 24h 重发检查复用（不另起 cron、不改动任何定时任务）。
REPAIR_STATE = "/home/hatch/data/perpetua/ask_studio_channel_repair_state.json"


def repair_status():
    """返回 {count, needs_repair, last_urgent_at}。读失败按未触发处理。"""
    st = {}
    try:
        with open(REPAIR_STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    return {
        "count": count_7d(),
        "needs_repair": count_7d() > CAP_7D,
        "last_urgent_at": st.get("last_urgent_at", ""),
        "first_urgent_at": st.get("first_urgent_at", ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record", "check", "count",
                                   "repair-status"])
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.cmd == "record":
        record(a.reason)
    elif a.cmd == "count":
        print(count_7d())
    elif a.cmd == "repair-status":
        print(json.dumps(repair_status(), ensure_ascii=False))
    else:
        return check()


if __name__ == "__main__":
    sys.exit(main() or 0)
