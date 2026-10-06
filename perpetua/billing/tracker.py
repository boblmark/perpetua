#!/usr/bin/env python3
"""Perpetua 计费：用量追踪 + 分级定价 + 账单"""
import json, os
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"

# 定价（美元/月）
PLANS = {
    "free": {"price": 0, "videos_per_day": 3, "ask_studio_per_day": 10,
             "overage_video": 0.50},
    "pro": {"price": 49, "videos_per_day": 10, "ask_studio_per_day": 50,
            "overage_video": 0.30},
    "enterprise": {"price": 199, "videos_per_day": 50, "ask_studio_per_day": 200,
                   "overage_video": 0.15},
}

# 计费资源
RESOURCES = ["videos_per_day", "ask_studio_per_day", "urgent_push", "retitle"]

def _usage_file(tid):
    return f"{BASE}/billing/usage_{tid}.json"

def record(tid, resource, count=1, meta=None):
    """记录一次用量"""
    f = _usage_file(tid)
    u = json.load(open(f)) if os.path.exists(f) else {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day = u.setdefault(today, {})
    day[resource] = day.get(resource, 0) + count
    # 明细（最近100条）
    det = u.setdefault("_details", [])
    det.append({"ts": datetime.now(timezone.utc).isoformat()[:19] + "Z",
                "resource": resource, "count": count, "meta": meta or {}})
    u["_details"] = det[-100:]
    json.dump(u, open(f, "w"), ensure_ascii=False, indent=2)

def today_usage(tid):
    f = _usage_file(tid)
    if not os.path.exists(f):
        return {}
    u = json.load(open(f))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {k: v for k, v in u.get(today, {}).items() if not k.startswith("_")}

def monthly_bill(tid, year_month=None):
    """月账单：订阅费 + 超量费"""
    import sys
    sys.path.insert(0, BASE)
    from tenants.manager import get_tenant
    t = get_tenant(tid)
    if not t:
        return {"error": "tenant not found"}
    plan = t["plan"]
    p = PLANS[plan]
    ym = year_month or datetime.now(timezone.utc).strftime("%Y-%m")
    f = _usage_file(tid)
    u = json.load(open(f)) if os.path.exists(f) else {}
    # 汇总当月
    total = {}
    for day, vals in u.items():
        if day.startswith(ym) and not day.startswith("_"):
            for k, v in vals.items():
                total[k] = total.get(k, 0) + v
    # 超量计算（按天配额 × 天数简化）
    days_in_month = 30
    overage = 0
    overage_detail = {}
    vids = total.get("videos_per_day", 0)
    allowed = p["videos_per_day"] * days_in_month
    if vids > allowed:
        over = vids - allowed
        overage = round(over * p["overage_video"], 2)
        overage_detail["videos"] = {"over": over, "fee": overage}
    return {
        "tenant": tid, "plan": plan, "period": ym,
        "subscription": p["price"],
        "usage": total, "overage": overage,
        "overage_detail": overage_detail,
        "total": round(p["price"] + overage, 2),
    }

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1]
    if cmd == "record":
        record(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 1)
        print("recorded")
    elif cmd == "today":
        print(json.dumps(today_usage(sys.argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "bill":
        ym = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(monthly_bill(sys.argv[2], ym), ensure_ascii=False, indent=2))
    elif cmd == "plans":
        print(json.dumps(PLANS, ensure_ascii=False, indent=2))
