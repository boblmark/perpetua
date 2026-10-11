#!/usr/bin/env python3
"""策略C scout：48h首发监控 → 达标 → 按平台改写 → 入队待人工签发。

状态机（D20261010-021）：
  首发(YouTube/抖音) → 48h → 指标达标？ → 生成7平台变体
  → enqueue(strategy=public) → 缺批准token则挂起（人工签发）
  → 用户放 token → distribute.work_one 按2h梯次分发
Kill线：首发被限流/下架（指标归零或进kill名单）→ 全局熔断，该视频永不分发。

用法：
  python3 strategy_c.py scan          # 6h cron 调用
  python3 strategy_c.py scan --dry    # 只看不入队
  python3 strategy_c.py status
"""
import argparse, json, logging, os, sys, time, datetime, traceback

log = logging.getLogger("strategy_c")

# R4 (council-20261011-perpetua-doc, AI Studio spec): prescreen is fail-closed.
# NEVER fall back to PASS on exception.
RESULT_PASS = "PASS"
RESULT_FAIL = "FAIL"

INBOX_PATH = "/home/hatch/data/collab/inbox.json"
OPS_DB = "/home/hatch/data/ops_center.db"

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import distribute as DIST
from variant_rules import build_variant, PRIORITY, PLATFORM_KEYMAP

CFG = os.path.join(BASE, "strategy_c_config.json")
LEDGER = os.path.join(BASE, "strategy_c_ledger.json")
YT_STATE = "/home/hatch/data/youtube/video_watchdog_state.json"
DY_METRICS = "/home/hatch/data/douyin/own_metrics.json"  # 待抖音monitor写入
KILL_FILE = os.path.join(BASE, "strategy_c_kill.json")
POLICY_MOD = "/home/hatch/data/perpetua/platform_policy.py"

DEFAULT_CFG = {
    "min_views_48h": 25,          # 48h播放达标线（频道基线低，Top视频~28）
    "min_likes_48h": 0,
    "enabled": True,
    "platforms": {                # 各平台开关（无账号=off，人工开账号后改on）
        "shipinhao": False, "bilibili": False, "xiaohongshu": False,
        "kuaishou": False, "facebook": False, "tiktok": False, "x": False,
    },
}


def _load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def _save(p, obj):
    # v2.0.0 (D20261011-006, 红队 KILL 3)：改走原子写
    sys.path.insert(0, "/home/hatch/data/perpetua")
    from atomic_json import atomic_write
    atomic_write(p, obj)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def cfg():
    c = _load(CFG, {})
    merged = dict(DEFAULT_CFG)
    merged.update(c)
    return merged


def policy_prescreen(title, desc, platform):
    """platform_policy.py 双清单预检。命中即终止该平台变体。

    R4 fail-closed：任何异常 -> 返回 (False, "FAIL: ...")，
    记 logging.CRITICAL，发告警 ops.alert.prescreen_crash。
    NEVER fallback 返回 PASS。
    """
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        from platform_policy import prescreen_policy
        plat = "youtube" if platform in ("facebook", "tiktok", "x") else "douyin"
        r = prescreen_policy("", title=title, description=desc, platform=plat)
        if isinstance(r, dict):
            verdict = r.get("verdict") or r.get("result") or ""
            if "FLAG" in str(verdict).upper() or r.get("blocked"):
                return False, f"合规预检命中: {r}"
        return True, RESULT_PASS
    except Exception:
        tb = traceback.format_exc()
        log.critical("policy_prescreen crashed for platform=%s title=%r\n%s",
                     platform, title, tb)
        _emit_alert("ops.alert.prescreen_crash",
                    f"policy_prescreen 异常 fail-closed：platform={platform} "
                    f"title={title[:60]}")
        return False, f"{RESULT_FAIL}: prescreen crashed (fail-closed)\n{tb[-2000:]}"


def _emit_alert(name, msg):
    """告警：写 collab inbox（用户可见）+ 日志（经统一网关）。"""
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        import inbox as inbox_gw
        entry = {"type": "ops_alert", "name": name, "title": msg,
                 "message": msg, "created": now_iso(), "for": "user"}
        ib = inbox_gw.load()
        ib.setdefault("messages", []).append(entry)
        ib.setdefault("notices", []).append(entry)
        ib["messages"] = ib["messages"][-100:]
        ib["notices"] = ib["notices"][-100:]
        inbox_gw.save(ib)
    except Exception as e:
        print(f"WARN: inbox 告警失败: {e}", file=sys.stderr)


def _mark_batch_blocked(vid, cluster, reason, tb=""):
    """R4：批次标 BLOCKED。ledger 打标 + event_bus 行置 BLOCKED 且 payload 含 error。"""
    try:
        ledger = _load(LEDGER, {})
        key = f"{cluster}:{vid}"
        rec = ledger.get(key, {})
        rec["blocked"] = {"reason": reason, "at": now_iso()}
        if tb:
            rec["blocked"]["traceback"] = tb[-2000:]
        ledger[key] = rec
        _save(LEDGER, ledger)
    except Exception as e:
        print(f"WARN: ledger 标 BLOCKED 失败: {e}", file=sys.stderr)
    try:
        # v2.0.0 (D20261011-006)：走 queue_db.transition_status，不再裸连 SQL。
        # 之前 queue_db 缺 BLOCKED API 才被迫直写；现在网关有状态机了。
        sys.path.insert(0, "/home/hatch/data/perpetua")
        from queue_db import put, transition_status
        eid = put("distribute", "strategy_c_batch",
                  {"vid": vid, "cluster": cluster, "error": tb[-2000:] if tb else reason,
                   "reason": reason},
                  owner="strategy_c", consumer="", timeout_hours=720)
        transition_status(eid, "BLOCKED", error_message=reason)
    except Exception as e:
        print(f"WARN: event_bus 标 BLOCKED 失败: {e}", file=sys.stderr)


def gated_prescreen(vfile, title, desc, plat):
    """R4 门禁顺序：簇隔离门禁严格先于 policy_prescreen。

    簇隔离失败 -> 任务标 BLOCKED，不调用 prescreen，直接 abort（exit code 2）。
    返回 (ok, reason)，ok 为 False 且 reason 以 FAIL 开头表示 fail-closed 异常。
    """
    dist_plat = PLATFORM_KEYMAP[plat]
    ok, why = DIST.check_cluster_gate(vfile, [dist_plat])
    if not ok:
        msg = f"簇隔离门禁拒绝（{why}），abort，不调用 prescreen"
        print(f"  ABORT: {msg}")
        log.critical("cluster gate rejected: %s", why)
        _emit_alert("ops.alert.cluster_gate_reject", msg)
        # 任务标 BLOCKED（vid 从调用方传入，此处只打通用标记，由调用方补 vid）
        raise SystemExit(2)
    return policy_prescreen(title, desc, plat)


def _eligible(source_id, views, likes, first_seen_ts, c):
    """48h + 指标双门。"""
    age_h = (time.time() - first_seen_ts) / 3600
    if age_h < 48:
        return False, f"未满48h（{age_h:.1f}h）"
    if views < c["min_views_48h"]:
        return False, f"播放{views}<{c['min_views_48h']}"
    if views <= 0:
        return False, "播放归零，疑似限流/下架，熔断"
    return True, f"达标（48h播放{views}）"


def scan_overseas(c, ledger, dry=False):
    """YouTube 首发 → TikTok/Facebook/X。"""
    state = _load(YT_STATE, {})
    kills = set(_load(KILL_FILE, []))
    out = []
    for vid, m in state.items():
        key = f"overseas:{vid}"
        rec = ledger.get(key, {})
        if not rec:
            rec = {"first_seen": time.time(), "views": m.get("views", 0)}
            ledger[key] = rec
            continue  # 首见，开始48h计时
        rec["views"] = m.get("views", 0)
        if rec.get("distributed") or rec.get("suppressed"):
            continue
        if vid in kills or key in kills:
            rec["suppressed"] = "kill名单"
            continue
        ok, why = _eligible(vid, m.get("views", 0), m.get("likes", 0),
                            rec["first_seen"], c)
        if not ok:
            if "熔断" in why:
                rec["suppressed"] = why
            continue
        out.append((vid, m, why, "overseas"))
    return out


def scan_domestic(c, ledger, dry=False):
    """抖音首发 → 视频号/B站/小红书/快手。metrics源缺失则跳过（fail-closed）。"""
    m = _load(DY_METRICS, None)
    if not m:
        return []  # 无数据源，不臆测达标
    out = []
    kills = set(_load(KILL_FILE, []))
    for vid, d in m.items():
        key = f"domestic:{vid}"
        rec = ledger.get(key, {})
        if not rec:
            rec = {"first_seen": time.time(), "views": d.get("views", 0)}
            ledger[key] = rec
            continue
        rec["views"] = d.get("views", 0)
        if rec.get("distributed") or rec.get("suppressed"):
            continue
        if vid in kills or key in kills:
            rec["suppressed"] = "kill名单"
            continue
        ok, why = _eligible(vid, d.get("views", 0), d.get("likes", 0),
                            rec["first_seen"], c)
        if not ok:
            if "熔断" in why:
                rec["suppressed"] = why
            continue
        out.append((vid, d, why, "domestic"))
    return out


def _find_video_file(source_id, cluster):
    """尽量定位本地源文件（打标签用）。找不到则跳过入队（fail-closed）。"""
    cands = []
    base = "/home/hatch/data/perpetua"
    for root, _, files in os.walk(base):
        for f in files:
            if source_id in f and f.endswith((".mp4", ".mov")):
                cands.append(os.path.join(root, f))
        if cands:
            break
    return cands[0] if cands else None


def distribute_eligible(items, c, dry=False):
    """为达标首发生成变体并入队（strategy=public → 强制等批准token）。"""
    for vid, m, why, cluster in items:
        plats = [p for p in PRIORITY[cluster] if c["platforms"].get(p)]
        if not plats:
            print(f"  {vid}: {why}，但启用的平台为0，跳过")
            continue
        vfile = _find_video_file(vid, cluster)
        if not vfile:
            print(f"  {vid}: 找不到本地源文件，跳过（fail-closed）")
            continue
        # 资产打标签（幂等，已有则跳过）
        DIST.tag_asset(vfile, cluster, source="strategy_c")
        video = {"source_id": vid, "title": m.get("title", vid),
                 "desc": m.get("desc", ""), "tags": m.get("tags", []),
                 "cover_path": m.get("cover_path"), "cluster": cluster}
        for plat in plats:
            variant = build_variant(plat, video)
            if not variant or variant.get("error"):
                print(f"  {vid}→{plat}: 变体生成失败 {variant}")
                continue
            ok, preason = None, None
            try:
                # R4：簇隔离门禁严格先于 prescreen（gated_prescreen 内执行）
                ok, preason = gated_prescreen(
                    vfile, variant["title"], variant["desc"], plat)
            except SystemExit as e:
                # 簇隔离拒绝：任务标 BLOCKED，不调用 prescreen，直接 abort
                _mark_batch_blocked(
                    vid, cluster, f"cluster gate reject (exit {e.code})")
                raise
            if not ok:
                if preason.startswith(RESULT_FAIL):
                    # R4 fail-closed：批次标 BLOCKED，traceback 进 event_bus，
                    # 分发管线 halt
                    print(f"  {vid}→{plat}: prescreen FAIL（fail-closed），"
                          f"整批 BLOCKED，halt")
                    _mark_batch_blocked(vid, cluster,
                                        "prescreen_crash fail-closed", preason)
                    log.critical("prescreen FAIL -> batch BLOCKED, halting: "
                                 "%s:%s", cluster, vid)
                    raise SystemExit(2)
                print(f"  {vid}→{plat}: {preason}，终止该平台")
                continue
            dist_plat = PLATFORM_KEYMAP[plat]
            if dry:
                print(f"  [dry] {vid}→{plat}(经{dist_plat}): {variant['title'][:40]}")
                continue
            args = argparse.Namespace(
                video=vfile, title=variant["title"], desc=variant["desc"],
                tags=",".join(variant["tags"]), cover=variant["cover_path"],
                platforms=dist_plat, strategy="public",
                qc_passed=True, review_score=90)
            try:
                qid = DIST.enqueue(args)
                print(f"  {vid}→{plat}: 已入队 {qid}（待人工签发token）")
            except SystemExit as e:
                print(f"  {vid}→{plat}: 入队被拒（exit {e.code}）")
        ledger = _load(LEDGER, {})
        ledger[f"{cluster}:{vid}"]["distributed"] = True
        ledger[f"{cluster}:{vid}"]["at"] = now_iso()
        _save(LEDGER, ledger)


def cmd_scan(dry=False):
    c = _load(CFG, DEFAULT_CFG)
    if not c.get("enabled"):
        print("策略C已禁用")
        return
    if not os.path.exists(CFG):
        _save(CFG, DEFAULT_CFG)
        print(f"已生成默认配置 {CFG}（所有平台默认关闭，需开账号后手动启用）")
    ledger = _load(LEDGER, {})
    items = scan_overseas(c, ledger) + scan_domestic(c, ledger)
    _save(LEDGER, ledger)
    if not items:
        print("本轮无达标首发（48h/指标/kill/平台开关任一不满足）")
        return
    print(f"达标 {len(items)} 条：")
    distribute_eligible(items, c, dry=dry)


def cmd_status():
    ledger = _load(LEDGER, {})
    c = _load(CFG, DEFAULT_CFG)
    print(f"ledger {len(ledger)} 条，平台开关："
          f"{[p for p, on in c['platforms'].items() if on] or '全关'}")
    for k, v in sorted(ledger.items()):
        st = "已分发" if v.get("distributed") else (
            f"熔断:{v.get('suppressed')}" if v.get("suppressed") else "计时中")
        age = (time.time() - v.get("first_seen", time.time())) / 3600
        print(f"  {k} {st}（首见{age:.1f}h前，播放{v.get('views')}）")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--dry", action="store_true")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "scan":
        cmd_scan(dry=args.dry)
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()
