#!/usr/bin/env python3
"""B站雷达轮询器（Phase 2，D20261017-002）：只读快照，禁自动快车道。

数据源（按优先级）：
  A. 公开 API：x/space/acc/info（UP 信息）→ x/space/wbi/arc/search（视频列表，需 wbi 签名）
     → x/web-interface/archive/stat（单视频统计）。免 key、无配额，需 1.2s+ 间隔。
  B. 公开视频页 HTML（window.__INITIAL_STATE__）兜底解析。
  C. 全部失败 → 降级：写 run log + platform_health.json，不造假数据，exit 0。

实测 2026-10-17：本机出口 IP 被 B站风控（acc/info 返回 -799、arc/search 412、
stat 404、视频页只返回 25KB 骨架页）。脚本保留完整实现，IP 解封/换出口即自动恢复。
备选：VPS 出口测试、用户 创作中心 cookie（走保险库）、手动 bvid 种子。

用法：python3 bilibili_snapshot.py [--limit 50]
种子文件：competitors_bilibili.json {"mids": [...], "bvids": [...]}
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from radar_lib import (connect, track_video, insert_snapshot, thumbnail_hash, thumb_phash,
                       append_run_log, ts_str)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://www.bilibili.com"}
API = "https://api.bilibili.com"
OWN_MID = "33246131808"
BASE = os.path.dirname(os.path.abspath(__file__))
SEED_FILE = os.path.join(BASE, "competitors_bilibili.json")
HEALTH_FILE = os.path.join(BASE, "platform_health.json")

MIXIN_TABLE = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43,
               5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16,
               24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59,
               6, 63, 57, 62, 11, 36, 20, 34, 44, 12]


def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def wbi_keys():
    nav = http_json(f"{API}/x/web-interface/nav")
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = wbi["img_url"].split("/")[-1].split(".")[0]
    sub = wbi["sub_url"].split("/")[-1].split(".")[0]
    return img, sub


def wbi_sign(params, img, sub):
    s = img + sub
    mixin = "".join(s[i] for i in MIXIN_TABLE)[:32]
    p = dict(params)
    p["wts"] = int(time.time())
    qs = urllib.parse.urlencode(sorted(p.items()))
    return qs + "&w_rid=" + hashlib.md5((qs + mixin).encode()).hexdigest()


def list_videos_api(mid, max_items):
    """A 路径：wbi 签名的投稿列表。返回 [(bvid, title, pic)]。"""
    img, sub = wbi_keys()
    out, pn = [], 1
    while len(out) < max_items:
        qs = wbi_sign({"mid": str(mid), "ps": "50", "pn": str(pn), "order": "pubdate",
                       "tid": "0", "keyword": "", "platform": "web"}, img, sub)
        d = http_json(f"{API}/x/space/wbi/arc/search?" + qs)
        if d.get("code") != 0:
            raise RuntimeError(f"wbi arc/search code={d.get('code')} msg={d.get('message')}")
        vlist = ((d.get("data") or {}).get("list") or {}).get("vlist") or []
        if not vlist:
            break
        out += [(v["bvid"], v["title"], v.get("pic")) for v in vlist]
        pn += 1
        time.sleep(1.5)
    return out[:max_items]


def video_stat_api(bvid):
    d = http_json(f"{API}/x/web-interface/archive/stat?bvid={bvid}")
    if d.get("code") != 0:
        raise RuntimeError(f"archive/stat code={d.get('code')}")
    return d["data"]


def video_stat_page(bvid):
    """B 路径：公开视频页 __INITIAL_STATE__ 兜底。"""
    req = urllib.request.Request(f"https://www.bilibili.com/video/{bvid}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "ignore")
    m = re.search(r"__INITIAL_STATE__=(\{.*?\})[;<]", html, re.S)
    if not m:
        raise RuntimeError("no __INITIAL_STATE__ in page (likely bot-check skeleton)")
    vd = (json.loads(m.group(1)).get("videoData")) or {}
    return {"title": vd.get("title"), "pic": vd.get("pic"),
            "view": (vd.get("stat") or {}).get("view"),
            "like": (vd.get("stat") or {}).get("like"),
            "reply": (vd.get("stat") or {}).get("reply")}


def load_seeds():
    if not os.path.exists(SEED_FILE):
        with open(SEED_FILE, "w", encoding="utf-8") as f:
            json.dump({"mids": [], "bvids": [],
                       "_how_to_add": "mids: 竞品 UP 主 UID；bvids: 直接跟踪的视频 BV 号。"
                       "只读快照，不触发任何选题动作。"}, f, ensure_ascii=False, indent=2)
        return {"mids": [], "bvids": []}
    with open(SEED_FILE, encoding="utf-8") as f:
        return json.load(f)


def set_health(status, detail):
    try:
        h = {}
        if os.path.exists(HEALTH_FILE):
            h = json.load(open(HEALTH_FILE, encoding="utf-8"))
        h["bilibili"] = {"status": status, "detail": detail, "checked_at": ts_str()}
        json.dump(h, open(HEALTH_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    seeds = load_seeds()
    con = connect()
    n_snap, errors = 0, []

    def snap(platform, vid, ch_id, label, title, pic, views, likes, comments):
        nonlocal n_snap
        track_video(con, platform, vid, ch_id, label)
        insert_snapshot(con, platform, vid, views, likes, comments, title, pic,
                        thumbnail_hash(pic), thumb_phash=thumb_phash(pic))
        n_snap += 1

    # 自有账号视频列表
    own_list = []
    try:
        own_list = list_videos_api(OWN_MID, args.limit)
        set_health("ok", f"wbi arc/search 正常，{len(own_list)} 条")
    except Exception as e:
        errors.append(f"own list failed: {e}")
        set_health("degraded", f"视频列表被风控: {e}")
    for bvid, title, pic in own_list:
        try:
            st = video_stat_api(bvid)
            snap("bilibili", bvid, OWN_MID, "own", title, pic,
                 st.get("view"), st.get("like"), st.get("reply"))
        except Exception as e:
            try:
                st = video_stat_page(bvid)
                snap("bilibili", bvid, OWN_MID, "own", st["title"] or title, pic,
                     st.get("view"), st.get("like"), st.get("reply"))
            except Exception as e2:
                errors.append(f"{bvid}: {e} / {e2}")
        time.sleep(1.5)
    # 竞品 UP
    for mid in seeds.get("mids") or []:
        try:
            for bvid, title, pic in list_videos_api(mid, 20):
                try:
                    st = video_stat_api(bvid)
                    snap("bilibili", bvid, str(mid), "competitor", title, pic,
                         st.get("view"), st.get("like"), st.get("reply"))
                except Exception as e:
                    errors.append(f"{bvid}: {e}")
                time.sleep(1.5)
        except Exception as e:
            errors.append(f"mid {mid}: {e}")
    # 手动 bvid 种子
    for bvid in seeds.get("bvids") or []:
        try:
            st = video_stat_api(bvid)
            v = http_json(f"{API}/x/web-interface/view?bvid={bvid}").get("data") or {}
            snap("bilibili", bvid, str((v.get("owner") or {}).get("mid")), "competitor",
                 v.get("title"), v.get("pic"), st.get("view"), st.get("like"), st.get("reply"))
        except Exception as e:
            errors.append(f"seed {bvid}: {e}")
        time.sleep(1.5)
    con.commit()
    con.close()
    line = (f"bilibili_snapshot done snapshots={n_snap} errors={len(errors)} "
            f"{'; '.join(errors[:3])}")
    append_run_log("bilibili_snapshot", line)
    print(line)


if __name__ == "__main__":
    main()
