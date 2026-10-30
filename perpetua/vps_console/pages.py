#!/usr/bin/env python3
"""蜂群自定义仪表盘 Pages（2026-10-30 接入现有控制台 v1）。

设计原则：
- 只读数据源，绝不改队列、不发任务、不调 YouTube API（配额已耗尽至 11-01）。
- 页面配置只存本机 /home/hatch/data/perpetua/pages/pages.json，原子写（tmp+replace），
  不进 /tmp，不含任何 token/密码/验证码。
- 每个 widget 的数据都带来源与时间戳，读不到就明说 unknown，绝不编数。
- 共享方式 = 同一控制台链接 /pages?id=<page_id>，与控制台本身同等访问权限，
  不另外开公开链接。
"""
import json
import os
import shutil
import socket
import sqlite3
import time
import urllib.request

DATA = "/home/hatch/data"
PAGES_DIR = os.path.join(DATA, "perpetua", "pages")
PAGES_FILE = os.path.join(PAGES_DIR, "pages.json")

SERVICES = [
    ("控制台 OA", 8080),
    ("感知 Perception", 18736),
    ("nano WebUI", 18737),
    ("nanoMuse Serve", 18739),
    ("MCP 8734", 8734),
    ("nanoMuse MCP 8735", 8735),
    ("Semantica KB", 18091),
    ("浏览器代理转发", 3129),
]

WIDGET_TYPES = {
    "services": "机器与服务状态",
    "disk": "本机磁盘",
    "queue": "分发队列",
    "decisions": "待拍板事项",
    "routine": "最近管线运行",
    "ypp": "YPP 进度（诊断值）",
    "note": "自定义文字卡片",
}

COLUMNS = {"top": "顶部数据", "left": "左栏·待拍板", "center": "中栏·已完成/在途", "right": "右栏·例行任务"}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())


def _default_doc():
    return {
        "version": 1,
        "pages": [
            {
                "id": "fleet-overview",
                "title": "蜂群总览",
                "created_at": _now(),
                "widgets": [
                    {"id": "w-services", "type": "services", "column": "top", "title": "机器与服务状态"},
                    {"id": "w-disk", "type": "disk", "column": "top", "title": "本机磁盘"},
                    {"id": "w-ypp", "type": "ypp", "column": "top", "title": "YPP 进度（诊断值）"},
                    {"id": "w-decisions", "type": "decisions", "column": "left", "title": "待拍板事项"},
                    {"id": "w-queue", "type": "queue", "column": "center", "title": "分发队列"},
                    {"id": "w-routine", "type": "routine", "column": "right", "title": "最近管线运行"},
                ],
            }
        ],
    }


def load_doc():
    try:
        with open(PAGES_FILE, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("pages"), list):
            return doc
    except (OSError, ValueError):
        pass
    doc = _default_doc()
    save_doc(doc)
    return doc


def save_doc(doc):
    os.makedirs(PAGES_DIR, exist_ok=True)
    tmp = PAGES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PAGES_FILE)
    return doc


def _find_page(doc, page_id):
    for p in doc["pages"]:
        if p["id"] == page_id:
            return p
    return None


def _new_id(prefix):
    return "%s-%d" % (prefix, int(time.time() * 1000) % 100000000)


# ---- 只读 widget 数据 ----

def _probe_port(port, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def data_services():
    items = []
    for name, port in SERVICES:
        up = _probe_port(port)
        items.append({"name": name, "port": port, "up": up})
    return {"ok": True, "at": _now(), "source": "本机端口直探 127.0.0.1",
            "items": items, "up": sum(1 for i in items if i["up"]), "total": len(items)}


def data_disk():
    try:
        u = shutil.disk_usage("/")
        pct = round(100.0 * (u.total - u.free) / u.total, 1) if u.total else None
        return {"ok": True, "at": _now(), "source": "本机 / 磁盘（非 VPS）",
                "used_pct": pct, "free_gb": round(u.free / 1024**3, 2),
                "total_gb": round(u.total / 1024**3, 1)}
    except OSError as e:
        return {"ok": False, "at": _now(), "error": str(e)[:200]}


def data_queue():
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % os.path.join(DATA, "ops_center.db"), uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) AS c FROM event_bus GROUP BY status")
        by_status = {r["status"]: r["c"] for r in cur.fetchall()}
        cur.execute("SELECT event_id, queue_name, event_type, status, created_at "
                    "FROM event_bus WHERE status='PENDING' ORDER BY created_at DESC LIMIT 5")
        pending = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"ok": True, "at": _now(), "source": "/home/hatch/data/ops_center.db event_bus（真相源）",
                "by_status": by_status, "pending_sample": pending}
    except Exception as e:
        return {"ok": False, "at": _now(), "error": str(e)[:200]}


def data_decisions():
    try:
        with open(os.path.join(DATA, "perpetua", "awaiting_approval.json"), encoding="utf-8") as f:
            items = json.load(f)
        if not isinstance(items, list):
            items = []
        from collections import Counter
        by_status = dict(Counter(str(x.get("status", "?")) for x in items))
        sample = [{"topic": str(x.get("topic", ""))[:60], "status": str(x.get("status", "")),
                   "title": str(x.get("title", ""))[:60]} for x in items[:5]]
        return {"ok": True, "at": _now(), "source": "awaiting_approval.json",
                "total": len(items), "by_status": by_status, "sample": sample}
    except Exception as e:
        return {"ok": False, "at": _now(), "error": str(e)[:200]}


def data_routine():
    try:
        with open(os.path.join(DATA, "perpetua", "pipeline_runs.json"), encoding="utf-8") as f:
            doc = json.load(f)
        runs = doc.get("runs", []) if isinstance(doc, dict) else []
        recent = [{"stage": r.get("stage"), "status": r.get("status"),
                   "detail": str(r.get("detail", ""))[:80], "at": r.get("at")}
                  for r in runs[-5:]]
        return {"ok": True, "at": _now(), "source": "pipeline_runs.json",
                "recent": recent, "total_runs": len(runs)}
    except Exception as e:
        return {"ok": False, "at": _now(), "error": str(e)[:200]}


def data_ypp():
    try:
        path = os.path.expanduser("~/workspace/goals/youtube-ypp/hidden_files/daily.jsonl")
        last = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = json.loads(line)
        if not last:
            return {"ok": False, "at": _now(), "error": "daily.jsonl 为空"}
        return {"ok": True, "at": _now(), "source": "YPP 日报 daily.jsonl（最后一条）",
                "date": last.get("date"), "subs": last.get("subs"), "subs_gap": last.get("subs_gap"),
                "watch_hours_diag": last.get("watch_hours_diag"),
                "warning": "诊断值，不是官方 qualified 小时；官方合格小时基线 2.0（2026-10-15 Studio 读数），须用户去 Studio Eligibility 页刷新后录入。"}
    except Exception as e:
        return {"ok": False, "at": _now(), "error": str(e)[:200]}


WIDGET_DATA = {
    "services": data_services,
    "disk": data_disk,
    "queue": data_queue,
    "decisions": data_decisions,
    "routine": data_routine,
    "ypp": data_ypp,
}


def widget_data(wtype):
    fn = WIDGET_DATA.get(wtype)
    if fn is None:
        return {"ok": True, "at": _now(), "note": "自定义文字卡片，无实时数据"}
    return fn()


# ---- HTTP 路由（由 console_server 转发调用，返回 (code, obj)） ----

def handle_get(path, query):
    doc = load_doc()
    if path == "/api/pages":
        return 200, {"ok": True, "pages": [{"id": p["id"], "title": p["title"],
                                             "widgets": len(p.get("widgets", []))} for p in doc["pages"]],
                     "widget_types": WIDGET_TYPES, "columns": COLUMNS}
    if path == "/api/pages/get":
        page = _find_page(doc, query.get("id", [""])[0])
        if not page:
            return 404, {"ok": False, "error": "page not found"}
        return 200, {"ok": True, "page": page}
    if path == "/api/pages/widget":
        return 200, widget_data(query.get("type", [""])[0])
    return None


def handle_post(path, payload):
    doc = load_doc()
    if path == "/api/pages/create":
        title = str(payload.get("title", "")).strip()[:60] or "未命名仪表盘"
        page = {"id": _new_id("page"), "title": title, "created_at": _now(), "widgets": []}
        doc["pages"].append(page)
        save_doc(doc)
        return 200, {"ok": True, "page": page}
    if path == "/api/pages/delete":
        pid = payload.get("id", "")
        before = len(doc["pages"])
        doc["pages"] = [p for p in doc["pages"] if p["id"] != pid]
        if len(doc["pages"]) == before:
            return 404, {"ok": False, "error": "page not found"}
        save_doc(doc)
        return 200, {"ok": True}
    if path == "/api/pages/widget/add":
        page = _find_page(doc, payload.get("page_id", ""))
        if not page:
            return 404, {"ok": False, "error": "page not found"}
        wtype = payload.get("type", "")
        if wtype not in WIDGET_TYPES:
            return 400, {"ok": False, "error": "unknown widget type"}
        col = payload.get("column", "center")
        if col not in COLUMNS:
            col = "center"
        w = {"id": _new_id("w"), "type": wtype, "column": col,
             "title": str(payload.get("title", "")).strip()[:60] or WIDGET_TYPES[wtype],
             "text": str(payload.get("text", ""))[:500]}
        page.setdefault("widgets", []).append(w)
        save_doc(doc)
        return 200, {"ok": True, "widget": w}
    if path == "/api/pages/widget/delete":
        page = _find_page(doc, payload.get("page_id", ""))
        if not page:
            return 404, {"ok": False, "error": "page not found"}
        wid = payload.get("widget_id", "")
        before = len(page.get("widgets", []))
        page["widgets"] = [w for w in page["widgets"] if w["id"] != wid]
        if len(page["widgets"]) == before:
            return 404, {"ok": False, "error": "widget not found"}
        save_doc(doc)
        return 200, {"ok": True}
    return None
