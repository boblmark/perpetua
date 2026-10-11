#!/usr/bin/env python3
"""ViralLoop 增长模块：销售管道 / 分发矩阵 / 变现看板的数据层。

销售线索、报价发出等对外动作仍走审批红线：本模块只记录和流转，
不自动发消息、不自动报价。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json
import os
import time
import uuid

DATA = "/home/hatch/data"
LEADS_FILE = os.path.join(DATA, "sales", "leads.json")
DIST_FILE = os.path.join(DATA, "marketing", "distribution.json")
REVENUE_FILE = os.path.join(DATA, "sales", "revenue.json")

LEAD_STAGES = ["新线索", "跟进中", "已报价", "已成交", "已交付", "复购"]
LEAD_SOURCES = ["猪八戒", "Upwork", "转介绍", "自然流量", "其他"]
PLATFORMS = ["youtube_shorts", "tiktok", "instagram_reels", "x"]
PLATFORM_NAMES = {"youtube_shorts": "YouTube Shorts", "tiktok": "TikTok",
                  "instagram_reels": "IG Reels", "x": "X"}


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    atomic_write_json(path, data)


# ---------------- 销售管道 ----------------
def leads_list():
    d = _load(LEADS_FILE, {"leads": []})
    leads = d.get("leads", [])
    by_stage = {s: [] for s in LEAD_STAGES}
    for l in leads:
        by_stage.setdefault(l.get("stage", "新线索"), []).append(l)
    return {"stages": LEAD_STAGES, "by_stage": by_stage, "total": len(leads),
            "won_value": sum(float(l.get("amount", 0) or 0) for l in leads
                             if l.get("stage") in ("已成交", "已交付", "复购"))}


def lead_upsert(payload):
    d = _load(LEADS_FILE, {"leads": []})
    leads = d.get("leads", [])
    now = time.strftime("%Y-%m-%d %H:%M")
    lid = payload.get("id")
    if lid:
        for l in leads:
            if l.get("id") == lid:
                for k in ("name", "source", "contact", "demand", "budget", "stage", "amount", "notes"):
                    if k in payload:
                        l[k] = payload[k]
                l["updated_at"] = now
                break
        else:
            return {"error": "lead not found"}
    else:
        lid = "L" + uuid.uuid4().hex[:8].upper()
        leads.append({
            "id": lid,
            "name": payload.get("name", ""),
            "source": payload.get("source", "其他"),
            "contact": payload.get("contact", ""),
            "demand": payload.get("demand", ""),
            "budget": payload.get("budget", ""),
            "stage": "新线索",
            "amount": payload.get("amount", 0),
            "notes": payload.get("notes", ""),
            "created_at": now,
            "updated_at": now,
        })
    _save(LEADS_FILE, {"leads": leads})
    return {"ok": True, "id": lid}


# ---------------- 分发矩阵 ----------------
def dist_list():
    d = _load(DIST_FILE, {"queue": []})
    return {"platforms": [{"id": p, "name": PLATFORM_NAMES[p]} for p in PLATFORMS],
            "queue": d.get("queue", [])}


def dist_add(payload):
    d = _load(DIST_FILE, {"queue": []})
    q = d.get("queue", [])
    item = {
        "id": "D" + uuid.uuid4().hex[:8].upper(),
        "video_id": payload.get("video_id", ""),
        "title": payload.get("title", ""),
        "platforms": {p: {"status": "待分发", "url": ""} for p in PLATFORMS},
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    q.append(item)
    _save(DIST_FILE, {"queue": q})
    return {"ok": True, "id": item["id"]}


def dist_update(payload):
    d = _load(DIST_FILE, {"queue": []})
    for it in d.get("queue", []):
        if it.get("id") == payload.get("id"):
            p = payload.get("platform")
            if p in PLATFORMS:
                it["platforms"][p] = {"status": payload.get("status", "待分发"),
                                      "url": payload.get("url", "")}
            _save(DIST_FILE, d)
            return {"ok": True}
    return {"error": "item not found"}


# ---------------- 变现看板 ----------------
def revenue_summary():
    d = _load(REVENUE_FILE, {"entries": []})
    entries = d.get("entries", [])
    total = sum(float(e.get("amount", 0) or 0) for e in entries)
    by_source = {}
    by_type = {}
    for e in entries:
        amt = float(e.get("amount", 0) or 0)
        by_source[e.get("source", "其他")] = by_source.get(e.get("source", "其他"), 0) + amt
        by_type[e.get("type", "其他")] = by_type.get(e.get("type", "其他"), 0) + amt
    return {"total": round(total, 2),
            "by_source": [{"source": k, "amount": round(v, 2)} for k, v in sorted(by_source.items(), key=lambda x: -x[1])],
            "by_type": [{"type": k, "amount": round(v, 2)} for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
            "entries": sorted(entries, key=lambda e: e.get("date", ""), reverse=True)[:50],
            "count": len(entries)}


def revenue_add(payload):
    d = _load(REVENUE_FILE, {"entries": []})
    d.get("entries", []).append({
        "id": "R" + uuid.uuid4().hex[:8].upper(),
        "date": payload.get("date") or time.strftime("%Y-%m-%d"),
        "source": payload.get("source", "其他"),
        "type": payload.get("type", "服务"),
        "amount": float(payload.get("amount", 0) or 0),
        "note": payload.get("note", ""),
    })
    _save(REVENUE_FILE, d)
    return {"ok": True}
