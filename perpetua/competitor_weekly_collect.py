#!/usr/bin/env python3
"""
竞品每周增量采集（2026-11-02 重写，接真逻辑，替代 2026-10-15 占位版）

应对红队 KILL-2：素材生命周期 6 天，数据必须每周更新。

架构说明（为什么这样接）：
- 五个平台（抖音/快手/小红书/视频号/X）都没有公开 API 可直接拉取“上周新发布竞品”，
  且本机备用 Chrome（CDP 9335）实测未登录抖音、搜索页不渲染结果——脚本直连抓取必然撞登录墙/反爬。
  因此采集分两段，缺一段就记缺口、不编数：
  1. 浏览器段（登录态浏览器任务，见 competitor_panel.json 的 queries）：按平台 queries 搜集
     本周公开视频，写成 weekly_pending/<platform>.json（{items, status, reason}）。
     本段由定时任务的浏览器步骤执行，不在本脚本内假装完成。
  2. 落盘段（本脚本）：读 pending，去重（URL 对全量 competitor_reach/*.json），
     只把新条目追加到 weekly_YYYY-MM-DD.json，更新 state。
- 缺口纪律：pending 缺失/空/失败 → 该平台记 status=gap、count 不计入 total，
  绝不把“没采到”写成 0 条新增。per-platform last_success 保证缺口周下次仍从上次成功点起算，
  不丢窗口。
- 幂等：同一天重跑，先读当日 weekly 文件，已落盘的 URL 不重复追加。

pending 文件格式：
  {"status": "ok"|"partial", "reason": "可选说明",
   "items": [{"title": str, "url": str, "author": str, "likes": str|int|None,
              "published_at": str|None, "query": str}]}
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(os.environ.get("COMPETITOR_REACH_DIR", "/home/hatch/data/competitor_reach"))
STATE_FILE = BASE_DIR / "weekly_collect_state.json"
PENDING_DIR = BASE_DIR / "weekly_pending"
PANEL_FILE = Path("/home/hatch/data/perpetua/competitor_panel.json")

PLATFORMS = ["douyin", "kuaishou", "xiaohongshu", "shipinhao", "x"]
URL_KEYS = ("url", "video_url", "link")


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
    else:
        state = {"last_collect": None, "weekly_counts": []}
    state.setdefault("platform_last_success", {})
    state.setdefault("weekly_counts", [])
    return state


def save_state(state):
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def _collect_urls(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in URL_KEYS and isinstance(v, str) and v.startswith("http"):
                out.add(v)
            else:
                _collect_urls(v, out)
    elif isinstance(obj, list):
        for it in obj:
            _collect_urls(it, out)


def known_urls():
    urls = set()
    today_name = f"weekly_{datetime.now().strftime('%Y-%m-%d')}.json"
    for path in BASE_DIR.glob("*.json"):
        if path.name in ("weekly_collect_state.json", today_name):
            # state 不含条目 URL；当日 weekly 文件由 today_out 单独处理（幂等合并）。
            # 往期 weekly 文件全部计入已知：2026-11-16 实测，跳过 weekly 文件致
            # 11-02 的 60 条被重算为本周新增（URL 100% 重合）。
            continue
        try:
            with open(path) as f:
                _collect_urls(json.load(f), urls)
        except Exception:
            continue
    return urls


def load_pending(platform):
    path = PENDING_DIR / f"{platform}.json"
    if not path.exists():
        return None, "pending 文件缺失（浏览器段未产出）"
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return None, f"pending 文件损坏：{e!r}"
    return data, None


def collect_platform(platform, since, known, today_out):
    """落盘单个平台。返回 (status, new_items, reason)。
    status: ok | partial | gap。gap 时 new_items 为 [] 且不计入 total。"""
    data, err = load_pending(platform)
    if data is None:
        return "gap", [], err
    items = data.get("items") or []
    if data.get("status") not in ("ok", "partial"):
        return "gap", [], data.get("reason") or "pending 状态非 ok/partial"
    if not items:
        return "gap", [], "pending items 为空（浏览器段未读到内容，不等于无新增）"
    new_items = []
    seen_today = {it.get("url") for it in today_out.get(platform, {}).get("items", [])}
    for it in items:
        url = it.get("url") or ""
        if not url or url in known or url in seen_today:
            continue
        new_items.append({
            "title": it.get("title") or "",
            "url": url,
            "author": it.get("author") or "",
            "likes": it.get("likes"),
            "published_at": it.get("published_at"),
            "query": it.get("query") or "",
            "platform": platform,
            "collected_at": datetime.now().isoformat(),
        })
    status = "ok" if data.get("status") == "ok" else "partial"
    reason = data.get("reason") or ""
    return status, new_items, reason


def main():
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = BASE_DIR / f"weekly_{today}.json"
    today_out = {}
    if out_path.exists():
        try:
            with open(out_path) as f:
                today_out = json.load(f).get("by_platform", {})
        except Exception:
            today_out = {}

    known = known_urls()
    # 当日已落盘的也算已知（幂等）
    for plat_data in today_out.values():
        for it in plat_data.get("items", []):
            if it.get("url"):
                known.add(it["url"])

    results = {}
    total_new = 0
    for p in PLATFORMS:
        last_ok = state["platform_last_success"].get(p)
        since = datetime.fromisoformat(last_ok) if last_ok else datetime.now() - timedelta(days=7)
        try:
            status, new_items, reason = collect_platform(p, since, known, today_out)
        except Exception as e:
            status, new_items, reason = "gap", [], f"落盘异常：{e!r}"
        # 幂等合并：当日已落盘的条目不因重跑丢失；重跑时 pending 缺失也不抹掉当日已有成果。
        prior = today_out.get(p, {})
        prior_items = prior.get("items", []) if isinstance(prior, dict) else []
        if prior_items:
            merged = list(prior_items) + [it for it in new_items
                                          if it["url"] not in {x.get("url") for x in prior_items}]
            status = prior.get("status", status) if status == "gap" else status
            reason = reason or prior.get("reason", "")
            new_items = merged
        results[p] = {"status": status, "new_count": len(new_items), "reason": reason,
                      "items": new_items}
        if status in ("ok", "partial"):
            state["platform_last_success"][p] = datetime.now().isoformat()
            total_new += len(new_items)
            for it in new_items:
                known.add(it["url"])
        print(f"[{p}] {status} 新增 {len(new_items)} 条" + (f"（{reason}）" if reason else ""))

    payload = {"date": today, "window_days": 7, "total_new": total_new,
               "by_platform": {p: {"status": r["status"], "new_count": r["new_count"],
                                   "reason": r["reason"], "items": r["items"]}
                               for p, r in results.items()}}
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, out_path)

    state["last_collect"] = datetime.now().isoformat()
    # 剔除 2026-11-02 占位轮的假 0 记录（若存在）：那轮 collect 恒 return 0，未读任何平台。
    state["weekly_counts"] = [w for w in state["weekly_counts"]
                              if not (w.get("date") == "2026-11-02" and w.get("total") == 0
                                      and all(v == 0 for v in w.get("by_platform", {}).values()))]
    state["weekly_counts"] = [w for w in state["weekly_counts"] if w.get("date") != today]
    state["weekly_counts"].append({
        "date": today, "total": total_new,
        "by_platform": {p: {"status": r["status"], "new_count": r["new_count"]}
                        for p, r in results.items()},
    })
    state["weekly_counts"] = state["weekly_counts"][-12:]
    save_state(state)

    print(f"\n本周新增：{total_new} 条（仅计 ok/partial 平台；gap 平台不计 0）")
    for p, r in results.items():
        print(f"  {p}: {r['status']} {r['new_count']}")
    print(f"落盘：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
