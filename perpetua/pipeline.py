#!/usr/bin/env python3
"""Perpetua 流水线遥测：统一记录七个阶段的真实执行情况。

阶段：
  trend    趋势抓取（脚本，无需 AI）
  select   选题（需 AI：Marvis）
  score    打分（脚本/API，无需 AI）
  generate 生成视频（需 AI：Marvis/视频模型）
  publish  发布（Marvis 直传 YouTube，机械操作）
  analyze  数据分析（脚本，无需 AI）
  optimize 发布后优化（脚本，无需 AI）

7 个阶段中只有 select 和 generate 严格需要 AI。
"""
import json, os
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"
RUNS_FILE = f"{BASE}/pipeline_runs.json"
MAX_RUNS = 500  # 只保留最近 500 条

STAGES = ["trend", "select", "score", "generate", "publish", "analyze", "optimize"]

STAGE_INFO = {
    "trend":    {"zh": "趋势抓取", "needs_ai": False},
    "select":   {"zh": "AI 选题", "needs_ai": True},
    "score":    {"zh": "爆款打分", "needs_ai": False},
    "generate": {"zh": "视频生成", "needs_ai": True},
    "publish":  {"zh": "发布", "needs_ai": False},
    "analyze":  {"zh": "数据分析", "needs_ai": False},
    "optimize": {"zh": "发布后优化", "needs_ai": False},
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def _load():
    if os.path.exists(RUNS_FILE):
        try:
            return json.load(open(RUNS_FILE))
        except Exception:
            pass
    return {"runs": []}

def _save(d):
    d["runs"] = d["runs"][-MAX_RUNS:]
    json.dump(d, open(RUNS_FILE, "w"), ensure_ascii=False, indent=2)

def log(tenant_id, stage, status="ok", detail="", count=0):
    """记录一次阶段执行。status: ok / working / error / idle"""
    if stage not in STAGES:
        raise ValueError(f"未知阶段 {stage}")
    d = _load()
    d["runs"].append({
        "tenant_id": tenant_id, "stage": stage, "status": status,
        "detail": detail, "count": count, "at": now_iso(),
    })
    _save(d)
    return True

def status(tenant_id="default"):
    """返回该租户七个阶段的最新状态"""
    d = _load()
    out = {}
    for s in STAGES:
        # 找该租户该阶段最新一条
        latest = None
        day_count = 0
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for r in reversed(d["runs"]):
            if r["tenant_id"] == tenant_id and r["stage"] == s:
                if latest is None:
                    latest = r
                if r["at"][:10] == today:
                    day_count += r.get("count", 0)
                if latest and r["at"][:10] != today:
                    # 继续往前找今日计数，但已有最新状态可跳出优化
                    pass
        info = STAGE_INFO[s]
        out[s] = {
            "label": info["zh"], "needs_ai": info["needs_ai"],
            "status": latest["status"] if latest else "idle",
            "last_run": latest["at"] if latest else None,
            "detail": latest["detail"] if latest else "暂无运行记录",
            "today_count": day_count,
        }
    return out

def status_all():
    """所有租户的状态（Dashboard 用）"""
    d = _load()
    tenants = sorted({r["tenant_id"] for r in d["runs"]}) or ["default"]
    return {t: status(t) for t in tenants}

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4:
        # pipeline.py <tenant> <stage> <status> [detail] [count]
        log(sys.argv[1], sys.argv[2], sys.argv[3],
            sys.argv[4] if len(sys.argv) > 4 else "",
            int(sys.argv[5]) if len(sys.argv) > 5 else 0)
        print("logged")
    elif len(sys.argv) == 2 and sys.argv[1] == "status":
        print(json.dumps(status_all(), ensure_ascii=False, indent=2))
    else:
        print("用法: pipeline.py <tenant> <stage> <status> [detail] [count]")
