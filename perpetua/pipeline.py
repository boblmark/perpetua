#!/usr/bin/env python3
"""Perpetua 流水线遥测：统一记录七个阶段的真实执行情况。

阶段（2026-10-07 扩展：独立管线不再依赖 Marvis）：
  trend            趋势抓取（脚本，无需 AI）
  select           选题（旧：Marvis；新：auto_pipeline）
  score            打分（脚本/API，无需 AI）
  topic_select     独立管线选题（auto_pipeline：趋势→打分→去重）
  generate         生成视频（视频模型）
  postprocess      生成后处理（loop 检查/字幕烧录）
  qc               上传前质检（pre_upload_qc，fail-closed）
  pending_approval 待人工审批（awaiting_approval.json）
  upload           上传发布（youtube_upload，全部硬门禁）
  publish          发布（旧：Marvis 直传；保留兼容）
  audit            绕过审计（bypass_audit，每2h）
  analyze          数据分析（脚本，无需 AI）
  optimize         发布后优化（脚本，无需 AI）
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json, os
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"
RUNS_FILE = f"{BASE}/pipeline_runs.json"
MAX_RUNS = 500  # 只保留最近 500 条

STAGES = ["trend", "select", "review", "generate", "qc", "publish", "postop", "evolve",
          # A11（2026-10-28）：补 submit（提交生成）与 nowatch（看门狗存活心跳），
          # 此前两类心跳因非法阶段抛错而静默丢失。任务体改动（nowatch 心跳
          # 目标）仍须先向用户说明并获同意，本处只修代码侧接纳能力。
          "submit", "nowatch"]

STAGE_INFO = {
    "trend":            {"zh": "趋势抓取", "needs_ai": False},
    "select":           {"zh": "AI 选题", "needs_ai": True},
    "submit":           {"zh": "提交生成", "needs_ai": False},
    "nowatch":          {"zh": "看门狗心跳", "needs_ai": False},
    "score":            {"zh": "爆款打分", "needs_ai": False},
    "topic_select":     {"zh": "管线选题", "needs_ai": False},
    "generate":         {"zh": "视频生成", "needs_ai": True},
    "postprocess":      {"zh": "生成后处理", "needs_ai": False},
    "qc":               {"zh": "上传前质检", "needs_ai": False},
    "pending_approval": {"zh": "待人工审批", "needs_ai": False},
    "upload":           {"zh": "上传发布", "needs_ai": False},
    "publish":          {"zh": "发布(旧)", "needs_ai": False},
    "audit":            {"zh": "绕过审计", "needs_ai": False},
    "analyze":          {"zh": "数据分析", "needs_ai": False},
    "optimize":         {"zh": "发布后优化", "needs_ai": False},
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
    atomic_write_json(RUNS_FILE, d)

def log(tenant_id, stage, status="ok", detail="", count=0, receipt=None):
    """记录一次阶段执行。status: ok / working / error / idle。
    A11：未知阶段不再抛 ValueError（曾使 12 处 submit 心跳与 nowatch 心跳
    在子进程里静默丢失）——改为 stderr 警告 + 返回 False，调用方可据此
    落盘可见（见 auto_pipeline.pipeline_log 的非零处理）。
    C15（2026-10-29）：postop 记录可附 receipt（dict，形如
    {"exit_code": 0, "checked": "<video_id 哈希前 16 位>"}），即优化器
    本轮真实运行回执；无 receipt 的旧式记录由 postop_receipt_state()
    判为 legacy，不冒充 fresh。receipt 非 dict 时忽略（fail-open）。"""
    if stage not in STAGES:
        print(f"pipeline.log: 未知阶段 {stage}（未记录）", file=sys.stderr)
        return False
    d = _load()
    rec = {
        "tenant_id": tenant_id, "stage": stage, "status": status,
        "detail": detail, "count": count, "at": now_iso(),
    }
    if isinstance(receipt, dict):
        rec["receipt"] = receipt
    d["runs"].append(rec)
    _save(d)
    return True

def status(tenant_id="default"):
    """返回该租户各阶段的最新状态"""
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
        info = STAGE_INFO.get(s, {"zh": s, "needs_ai": False})
        # C13（2026-10-29）：select/generate/qc/publish 最新一条 status 为 ok
        # 但 count==0 时记 idle 而非 ok——做了零活不得显示绿灯。error 等
        # 非 ok 状态不受影响；其余阶段不套用（心跳类阶段 count 天然为 0）。
        st = latest["status"] if latest else "idle"
        if (latest and st == "ok" and s in ("select", "generate", "qc", "publish")
                and latest.get("count", 0) == 0):
            st = "idle"
        out[s] = {
            "label": info["zh"], "needs_ai": info["needs_ai"],
            "status": st,
            "last_run": latest["at"] if latest else None,
            "detail": latest["detail"] if latest else "暂无运行记录",
            "today_count": day_count,
        }
    return out


def postop_receipt_state(tenant_id="default", hours=12):
    """C15（2026-10-29）：postop 心跳的回执新鲜度三态，供未来任务体
    改查回执时调用（现行任务体仍按 at 时间判，函数本身不改变任何
    现有判定）。返回 {"state": ..., "at": ..., "receipt": ...}：
    - fresh：最新 postop 有 receipt 且 exit_code==0 且在 hours 内；
    - stale：最新 postop 有 receipt 但 exit_code!=0 或已超 hours；
    - legacy：最新 postop 无 receipt（旧任务体写法），不冒充 fresh；
    - none：无任何 postop 记录。"""
    d = _load()
    latest = None
    for r in reversed(d["runs"]):
        if r["tenant_id"] == tenant_id and r["stage"] == "postop":
            latest = r
            break
    if latest is None:
        return {"state": "none", "at": None, "receipt": None}
    rec = latest.get("receipt")
    if not isinstance(rec, dict):
        return {"state": "legacy", "at": latest["at"], "receipt": None}
    try:
        age_h = (datetime.now(timezone.utc)
                 - datetime.fromisoformat(latest["at"].replace("Z", "+00:00"))
                 ).total_seconds() / 3600.0
    except Exception:
        age_h = float("inf")
    if rec.get("exit_code") == 0 and age_h <= hours:
        return {"state": "fresh", "at": latest["at"], "receipt": rec}
    return {"state": "stale", "at": latest["at"], "receipt": rec}

def status_all():
    """所有租户的状态（Dashboard 用）"""
    d = _load()
    tenants = sorted({r["tenant_id"] for r in d["runs"]}) or ["default"]
    return {t: status(t) for t in tenants}

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 4:
        # pipeline.py <tenant> <stage> <status> [detail] [count] [receipt_json]
        # C15：第 6 参为可选回执 JSON（仅 postop 有意义），解析失败则忽略。
        receipt = None
        if len(sys.argv) > 6:
            try:
                receipt = json.loads(sys.argv[6])
            except Exception:
                receipt = None
        ok = log(sys.argv[1], sys.argv[2], sys.argv[3],
                 sys.argv[4] if len(sys.argv) > 4 else "",
                 int(sys.argv[5]) if len(sys.argv) > 5 else 0,
                 receipt=receipt)
        # A11：未知阶段退出码 2，使调用方（pipeline_log）能感知丢失的心跳。
        print("logged" if ok else "unknown stage")
        sys.exit(0 if ok else 2)
    elif len(sys.argv) == 2 and sys.argv[1] == "status":
        print(json.dumps(status_all(), ensure_ascii=False, indent=2))
    else:
        print("用法: pipeline.py <tenant> <stage> <status> [detail] [count]")
