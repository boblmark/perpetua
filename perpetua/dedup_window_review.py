#!/usr/bin/env python3
"""90 天去重窗口月度数据复核（议会 D20261017-00X KILL#9 修订）。

- 每月跑一次：统计近 30 天每日去重 block 率（rejects/checks，
  数据源 formula_dedup_daily.json，由 formula_dedup._bump_dedup_counter 写入）。
- 提前触发：任意连续 3 天 block 率 >80% → 立即升级（inbox + 报告），
  不等月度轮次。
- 复核结论只给建议；窗口放宽（缩短天数/放宽规则）需议会 + 用户拍板
  （DEDUP_WINDOW_POLICY），本脚本永不自动改规则。

用法：python3 dedup_window_review.py [--json]
建议 cron：每月 1 号；W7 tripwire 由 anomaly_watchdog 每 30min 轻量复算。
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

DATA = "/home/hatch/data/perpetua"
COUNTER = os.path.join(DATA, "formula_dedup_daily.json")
REVIEW_STATE = os.path.join(DATA, "dedup_window_review_state.json")
INBOX_PATH = "/home/hatch/data/collab/inbox.json"

BLOCK_RATE_THRESHOLD = 0.80
CONSECUTIVE_DAYS = 3


def _load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _daily_rates(days=30):
    cnt = _load(COUNTER, {})
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        c = cnt.get(d, {"checks": 0, "rejects": 0})
        checks = int(c.get("checks", 0) or 0)
        rejects = int(c.get("rejects", 0) or 0)
        rate = (rejects / checks) if checks else None
        out.append({"day": d, "checks": checks, "rejects": rejects,
                    "block_rate": round(rate, 3) if rate is not None else None})
    return out


def _early_trigger(rates):
    """连续 CONSECUTIVE_DAYS 天 block 率 > 阈值 → True。"""
    run = 0
    for r in rates:
        br = r["block_rate"]
        if br is not None and br > BLOCK_RATE_THRESHOLD:
            run += 1
            if run >= CONSECUTIVE_DAYS:
                return True
        else:
            run = 0
    return False


def _inbox(msg):
    try:
        inbox = _load(INBOX_PATH, {"messages": []})
        items = inbox.get("messages", []) if isinstance(inbox, dict) else inbox
        items.append({
            "type": "dedup_window_review",
            "message": msg,
            "for": "dash_main",
            "read": False,
            "created": datetime.now(timezone.utc).isoformat(),
        })
        if isinstance(inbox, dict):
            inbox["messages"] = items
        json.dump(inbox, open(INBOX_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def main():
    rates = _daily_rates(30)
    valid = [r for r in rates if r["block_rate"] is not None]
    avg = (sum(r["block_rate"] for r in valid) / len(valid)) if valid else None
    peak = max(valid, key=lambda r: r["block_rate"]) if valid else None
    trigger = _early_trigger(rates)
    # 单日 100% block 且无复核记录 → 也触发（W7）
    state = _load(REVIEW_STATE, {})
    full_block_days = [r["day"] for r in rates
                       if r["block_rate"] == 1.0 and r["checks"] > 0]
    full_block_unreviewed = [d for d in full_block_days
                             if d not in state.get("reviewed_days", [])]

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "days_with_data": len(valid),
        "avg_block_rate_30d": round(avg, 3) if avg is not None else None,
        "peak_day": peak,
        "early_trigger_3d_gt80": trigger,
        "full_block_days_unreviewed": full_block_unreviewed,
        "policy": ("窗口放宽需议会+用户拍板（D20261017-00X KILL#9），"
                   "本脚本只报告、不改规则。"),
    }
    state["last_review"] = report["at"]
    state["last_report"] = report
    json.dump(state, open(REVIEW_STATE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    as_json = "--json" in sys.argv
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print("dedup_window_review %s: 30天有效%d天, 平均block率%s, 峰值%s" % (
            report["at"][:10], report["days_with_data"],
            report["avg_block_rate_30d"],
            (peak["day"], peak["block_rate"]) if peak else None))
        if trigger:
            print("TRIGGER: 连续3天 block 率>80% → 需提前复核去重窗口")
        if full_block_unreviewed:
            print("TRIGGER: 单日 100%% block 未复核：%s" % full_block_unreviewed)

    if trigger or full_block_unreviewed:
        _inbox("去重窗口复核触发：%s" % json.dumps({
            "early_trigger_3d_gt80": trigger,
            "full_block_days_unreviewed": full_block_unreviewed,
            "avg_30d": report["avg_block_rate_30d"],
        }, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
