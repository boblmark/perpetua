"""DNA 统一控制台后端 API。所有数据来自真实模块，非 mockup。"""
import json, os, sys, sqlite3
sys.path.insert(0, "/home/hatch/data/perpetua")
PERPETUA_DIR = "/home/hatch/data/perpetua"

def _run_pipeline_status():
    """真实 pipeline 状态。"""
    import subprocess
    try:
        out = subprocess.run(
            [sys.executable, "auto_pipeline.py", "status"],
            cwd=PERPETUA_DIR, capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout) if out.stdout.strip() else []
    except Exception as e:
        return {"error": str(e)}

def api_pipeline_stages():
    """视频工厂 6 阶段真实数据。"""
    items = _run_pipeline_status()
    if isinstance(items, dict): return items
    from collections import Counter
    c = Counter(d.get("status", "?") for d in items)
    return {
        "total": len(items),
        "stages": {
            "select": c.get("teaser_validation", 0),
            "review": sum(1 for d in items if (d.get("score") or 0) >= 85),
            "generate": c.get("teaser_awaiting_check", 0),
            "qc": c.get("teaser_validation", 0),
            "approve": sum(1 for d in items if d.get("status") in ("teaser_awaiting_check",)),
            "publish": c.get("teaser_published", 0) + c.get("published", 0) + c.get("uploaded_private", 0),
        },
        "by_status": dict(c),
    }

def api_approval_queue():
    """真实审批队列。"""
    items = _run_pipeline_status()
    if isinstance(items, dict): return items
    queue = [d for d in items if d.get("status") in ("teaser_awaiting_check", "teaser_validation")]
    return {"total": len(queue), "items": queue[:20],
            "note": "审批通过/驳回需调用 approve_video.py"}

def api_experiment_stats():
    """实验科学真实数据。"""
    db_path = os.path.join(PERPETUA_DIR, "causal.db")
    if not os.path.exists(db_path):
        return {"viral_rate": None, "n": 0, "note": "因果库无数据"}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT COUNT(*) c, SUM(is_viral) v FROM videos WHERE views_72h IS NOT NULL").fetchone()
    n, v = rows["c"] or 0, rows["v"] or 0
    conn.close()
    return {"viral_rate": round(v/n, 4) if n else None, "n": n,
            "viral": v, "definition": "P(播放>10万|72h)"}

def api_evolution_log(n=10):
    """真实进化日志。"""
    p = os.path.join(PERPETUA_DIR, "evolution_log.jsonl")
    if not os.path.exists(p):
        return {"events": [], "note": "暂无进化日志"}
    lines = open(p, encoding="utf-8").read().strip().split("\n")
    events = [json.loads(l) for l in lines[-n:] if l.strip()]
    return {"events": events, "total": len(lines)}

def api_causal_size():
    db_path = os.path.join(PERPETUA_DIR, "causal.db")
    if not os.path.exists(db_path): return {"size": 0}
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    conn.close()
    return {"size": n}

if __name__ == "__main__":
    import sys as _s
    fn = _s.argv[1] if len(_s.argv) > 1 else "api_pipeline_stages"
    print(json.dumps(globals()[fn](), ensure_ascii=False, indent=2))
