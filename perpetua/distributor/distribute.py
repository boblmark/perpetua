#!/usr/bin/env python3
"""Perpetua 自动分发器 v1 — 双文化簇路由 + 硬门禁。

国内簇: douyin(浏览器→存草稿,P1) / xiaohongshu(备料→人工发,P1) / bilibili(phase2)
海外簇: youtube(官方API private, 沿用现有通道) / tiktok(phase2) / facebook+x(stub)

定位声明（2026-10-10 四脑议会 D20261010-019）：
簇隔离硬门禁是"战略执行锁"，不是"合规防火墙"。
它的合法性来自用户的战略方向（国内外另开内容），不是平台政策——
YouTube 并不惩罚跨平台分发（Ask Studio 2026-10-10 实证）。
真正的合规控制是内容级的 platform_policy.py 预检 + 终审 Q4。
本门禁防的是操作事故：一条手滑的 --platforms douyin,youtube。

铁律（违反任一条直接拒绝，不执行）:
0. 簇隔离：enqueue 拒绝跨簇平台混搭；视频资产必须带 home-cluster 标签；
   标签与目标平台簇不一致直接拒绝。fail-closed，绝不部分入队。
1. 默认永不自动公开：策略只允许 draft/private/scheduled/hold/unlisted
2. public/immediate 需要用户明确批准：磁盘 token distribute_approve/<qid>.token
3. 抖音 P1 强制 draft（jury Y 人工首月），无视请求的策略
4. 门禁：QC通过 + Ask Studio>=85 + 单平台120分钟间隔 + 抖音B'限流
5. cookie 一账号一文件、600权限、不跨机；失效直接失败不重试

用法：
  打标签: python3 distribute.py tag --video f.mp4 --cluster domestic --source ingest
  enqueue: python3 distribute.py enqueue --video f.mp4 --title T --desc D --tags a,b --platforms douyin,xiaohongshu [--cover c.jpg] [--strategy draft]
  worker:  python3 distribute.py work-one     # 处理队首一条（cron调用）
  status:  python3 distribute.py status
"""
import argparse, json, os, subprocess, sys, time, datetime
import sys; sys.path.insert(0, "/home/hatch/data/perpetua")
from atomic_json import atomic_write

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(BASE, "distribute_queue.json")
STATE = os.path.join(BASE, "distributor_state.json")
APPROVE_DIR = os.path.join(BASE, "distribute_approve")
MANUAL_DIR = os.path.join(BASE, "pending_manual")
COOKIE_DIR = os.path.join(BASE, "cookies")
TAG_FILE = os.path.join(BASE, "asset_tags.json")          # 资产 home-cluster 标签
DECISION_LOG = os.path.join(BASE, "distribute_decisions.log.json")  # 簇门禁决策日志
DRIVER_TIMEOUT = 900
REVIEW_FLOOR = 85
PLATFORM_INTERVAL_SEC = 120 * 60
CLUSTERS = ("domestic", "overseas")

# R3 (council-20261011-perpetua-doc, AI Studio spec): 平台 AI 披露内建。
# 抖音发布请求 schema 必须携带 ai_generated=1；缺失 -> 任务 BLOCKED +
# MissingPlatformDisclosureException，NEVER 只告警不阻断。
DOUYIN_AI_DECLARATION_CODE = 1

# v1.0.0 (2026-10-11, D20261011-006)：平台列表唯一真相源迁至 platform_registry。
# 加平台 = 注册表加 1 行，禁止在此硬编码。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from platform_registry import PLATFORMS, get_platform, list_platforms
AUTO_PUBLIC_STRATEGIES = {"public", "immediate"}

def _load(p, default):
    try: return json.load(open(p))
    except Exception: return default

def _save(p, obj):
    atomic_write(p, obj)

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

# ---------------- 簇隔离硬门禁（2026-10-10 D20261010-019） ----------------
# 定位：战略执行锁（执行"国内外另开内容"），不是合规防火墙。
# 真合规靠内容级 platform_policy.py；本门禁防手滑误操作。fail-closed。

def _log_decision(entry):
    """M8: 记录每次簇门禁 accept/reject 决策。"""
    try:
        log = _load(DECISION_LOG, [])
        log.append(dict(entry, at=now_iso()))
        _save(DECISION_LOG, log[-500:])
    except Exception:
        pass


def normalize_platforms(raw):
    """M1: 归一化平台列表（小写、去空格、去重、过滤未知）。返回 (known, unknown)。"""
    seen, known, unknown = set(), [], []
    for p in (raw or "").split(","):
        p = p.strip().lower()
        if not p or p in seen:
            continue
        seen.add(p)
        (known if p in PLATFORMS else unknown).append(p)
    return known, unknown


def tag_asset(video_path, cluster, source="manual"):
    """T1-T4: 给视频资产打 home-cluster 标签。write-once，二次写入拒绝。"""
    if cluster not in CLUSTERS:
        return False, f"cluster 必须是 {CLUSTERS}"
    ap = os.path.abspath(video_path)
    if not os.path.exists(ap):
        return False, f"文件不存在: {ap}"
    tags = _load(TAG_FILE, {})
    if ap in tags:
        # T4: write-once
        return False, f"REFUSE: home-cluster tag immutable（已有标签 {tags[ap].get('home_cluster')}）"
    st = os.stat(ap)
    tags[ap] = {"home_cluster": cluster, "size": st.st_size,
                "mtime": st.st_mtime, "tagged_at": now_iso(),
                "source": source}  # T3: 标签只来自来源配置，不猜内容
    _save(TAG_FILE, tags)
    return True, f"已打标签 {cluster}: {ap}"


def read_home_cluster(video_path):
    """M4/T5: 读取资产 home-cluster 标签。返回 (cluster|None, reason)。
    文件 size/mtime 变化视为标签失效（T5: 按 untagged 处理）。"""
    ap = os.path.abspath(video_path)
    tags = _load(TAG_FILE, {})
    rec = tags.get(ap)
    if not rec:
        return None, "无标签"
    try:
        st = os.stat(ap)
    except Exception:
        return None, "文件不可读"
    if st.st_size != rec.get("size") or st.st_mtime != rec.get("mtime"):
        return None, "文件已变更，标签失效"  # T5
    c = rec.get("home_cluster")
    if c not in CLUSTERS:
        return None, "标签损坏"
    return c, "ok"


def check_cluster_gate(video_path, platforms):
    """簇门禁（enqueue 时 fail-fast）。返回 (ok, reason)。
    M2/M3/M5/M6/M7 + N1/N2/N8。gate_override 不豁免本门禁（N6/N7）。"""
    # M2: 未知平台直接拒绝（不再静默过滤）
    known, unknown = normalize_platforms(",".join(platforms))
    if unknown:
        return False, f"REJECT: 未知平台 {unknown}"
    if not known:
        return False, "REJECT: 无有效平台"
    # M3/N1: 跨簇混搭拒绝（只认代码内 canonical 表，M6）
    clusters = {PLATFORMS[p]["cluster"] for p in known}
    if len(clusters) > 1:
        dom = [p for p in known if PLATFORMS[p]["cluster"] == "domestic"]
        ove = [p for p in known if PLATFORMS[p]["cluster"] == "overseas"]
        return False, (f"REJECT: cross-cluster enqueue "
                       f"(mixed: {dom} | {ove})")
    # M4/N2: 资产必须有 home-cluster 标签
    home, why = read_home_cluster(video_path)
    if home is None:
        return False, f"REJECT: missing home-cluster tag for {video_path}（{why}，先用 tag 命令打标签）"
    # M5: 目标平台簇必须 == 资产 home 簇（防拆单绕过 M3，N6）
    want = clusters.pop()
    if want != home:
        return False, (f"REJECT: cluster mismatch（资产 home={home}，"
                       f"目标平台属 {want}）")
    return True, f"簇门禁通过（home={home}，平台={known}）"


def assert_worker_cluster(item, platform):
    """G8/N3: worker 上传前重断言。返回 (ok, reason)。"""
    home, why = read_home_cluster(item.get("video_path", ""))
    if home is None:
        return False, f"ABORT: cluster mismatch（资产标签缺失/失效：{why}）"
    want = PLATFORMS[platform]["cluster"]
    if want != home:
        return False, (f"ABORT: cluster mismatch（资产 home={home}，"
                       f"平台 {platform} 属 {want}）")
    return True, "ok"

# ---------------- 门禁 ----------------
def check_gates(item, platform):
    """返回 (ok, reason)。任一条不满足 → 拒绝。"""
    plat = PLATFORMS[platform]
    strategy = item.get("strategy") or plat["default"]
    # 抖音P1强制draft
    if platform == "douyin" and plat.get("p1_force"):
        strategy = plat["p1_force"]
    # 1. 永不自动公开
    if strategy in AUTO_PUBLIC_STRATEGIES:
        tok = os.path.join(APPROVE_DIR, item["qid"] + ".token")
        if not os.path.exists(tok):
            return False, f"策略{strategy}需用户批准token（{tok}不存在）"
    # 2. QC + 评审分
    if not item.get("qc_passed"):
        return False, "QC未通过"
    if (item.get("review_score") or 0) < REVIEW_FLOOR and not item.get("gate_override"):
        return False, f"评审分{item.get('review_score')} < {REVIEW_FLOOR}"
    # 3. 单平台120分钟间隔（只对真实上传；备料hold/跳过不计）
    will_upload = (plat.get("driver") not in (None, "youtube_api")) and strategy != "hold"
    if will_upload:
        state = _load(STATE, {})
        last = (state.get("last_distribute") or {}).get(platform, 0)
        if time.time() - last < PLATFORM_INTERVAL_SEC:
            return False, f"{platform}距上次分发不足120分钟"
    # 4. （2026-10-11 金丝雀修正：原 B'限流误用在此——B' 统计的是 YouTube
    #    近7天发布量，B-稳期间每天 2-3 条会永久堵死抖音分发。抖音节奏改由
    #    上面的 120 分钟平台间隔控制。如需抖音单独日上限，另立常量。）
    pass
    # 5. cookie存在性（driver内再做有效性校验）
    if (plat.get("driver") or "").endswith("_driver.py"):
        ck = os.path.join(COOKIE_DIR, platform, "account.json")
        if not os.path.exists(ck):
            return False, f"cookie不存在: {ck}（需用户扫码登录）"
    return True, f"门禁通过，策略={strategy}"

# ---------------- 执行 ----------------
def run_driver(item, platform, strategy):
    plat = PLATFORMS[platform]
    driver = plat.get("driver")
    if driver is None or plat.get("default") == "hold":
        return stage_manual(item, platform)
    if driver == "youtube_api":
        return {"ok": True, "skipped": True,
                "detail": "YouTube沿用现有官方API通道（youtube_upload private），本分发器不重复执行"}
    drv = os.path.join(BASE, "drivers", driver)
    payload = {"qid": item["qid"], "video_path": item["video_path"],
               "title": item["title"], "desc": item.get("desc", ""),
               "tags": item.get("tags", []), "cover_path": item.get("cover_path"),
               "strategy": strategy,
               # R3：抖音 AI 披露声明内建为发布请求 schema 的硬字段
               "ai_generated": DOUYIN_AI_DECLARATION_CODE,
               "cookie_file": os.path.join(COOKIE_DIR, platform, "account.json"),
               "vendor_dir": os.path.join(BASE, "vendor")}
    try:
        p = subprocess.run([sys.executable, drv], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=DRIVER_TIMEOUT)
        out = (p.stdout or "").strip().splitlines()
        receipt = json.loads(out[-1]) if out else {"ok": False, "detail": "driver无输出"}
        if p.returncode != 0 and receipt.get("ok"):
            receipt = {"ok": False, "detail": f"driver退出码{p.returncode}: {receipt.get('detail')}"}
        return receipt
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"driver超时({DRIVER_TIMEOUT}s)，fail-closed"}
    except Exception as e:
        return {"ok": False, "detail": f"driver异常: {e}"}

def stage_manual(item, platform):
    """hold策略：备料到pending_manual，人工发。"""
    d = os.path.join(MANUAL_DIR, item["qid"], platform)
    os.makedirs(d, exist_ok=True)
    meta = {k: item.get(k) for k in ("title", "desc", "tags", "video_path", "cover_path")}
    meta["platform"] = platform
    meta["staged_at"] = now_iso()
    _save(os.path.join(d, "meta.json"), meta)
    # 拷贝视频引用（不复制大文件，记路径）
    return {"ok": True, "staged": True,
            "detail": f"已备料至 {d}，待人工发布（P1政策）"}

def work_one():
    q = _load(QUEUE, [])
    for item in q:
        if item.get("status") not in ("queued", "retry", "waiting_approval"):
            continue
        print(f"处理 {item['qid']}: {item['title'][:30]}")
        receipts = item.get("receipts", {})
        all_ok = True
        for platform in item.get("platforms", []):
            if platform not in PLATFORMS:
                receipts[platform] = {"ok": False, "detail": "未知平台"}
                all_ok = False
                continue
            if receipts.get(platform, {}).get("ok"):
                continue
            # G8/N3: worker 上传前重断言簇一致（防队列文件被手动改过）
            cok, creason = assert_worker_cluster(item, platform)
            if not cok:
                receipts[platform] = {"ok": False, "detail": creason}
                all_ok = False
                continue
            ok, reason = check_gates(item, platform)
            plat = PLATFORMS[platform]
            strategy = plat.get("p1_force") or item.get("strategy") or plat["default"]
            if not ok:
                receipts[platform] = {"ok": False, "detail": f"门禁拒绝: {reason}"}
                # 策略C补丁（D20261010-021）：等人工签发token不算失败，
                # 不计 attempts、不进 dead_letter，一直挂起直到用户批准。
                if "需用户批准token" in reason:
                    item["status"] = "waiting_approval"
                    item["updated_at"] = now_iso()
                    _save(QUEUE, q)
                    print(f"  → waiting_approval（等用户签发token）")
                    return item["qid"], item["status"]
                all_ok = False
                continue
            r = run_driver(item, platform, strategy)
            receipts[platform] = r
            if r.get("ok") and not r.get("staged") and not r.get("skipped"):
                state = _load(STATE, {})
                state.setdefault("last_distribute", {})[platform] = time.time()
                _save(STATE, state)
            else:
                all_ok = False
        item["receipts"] = receipts
        item["attempts"] = item.get("attempts", 0) + 1
        item["updated_at"] = now_iso()
        # R3：披露缺失等硬阻断 -> BLOCKED（不进 retry/dead_letter，需人工处理）
        if any(isinstance(r, dict) and r.get("blocked")
               for r in receipts.values()):
            item["status"] = "blocked"
            print(f"  → blocked（硬阻断，需人工处理）")
        elif all_ok:
            item["status"] = "done"
        elif item["attempts"] >= 2:
            item["status"] = "dead_letter"
            print(f"  → dead_letter，已失败2次")
        else:
            item["status"] = "retry"
        _save(QUEUE, q)
        print(f"  → {item['status']}")
        return item["qid"], item["status"]
    print("队列为空")
    return None, "empty"

def enqueue(args):
    # G1-G2: 簇门禁 fail-fast（在 QC/评审/可见性门禁之前）
    qid = f"dist-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(2).hex()}"
    plats_raw = [p.strip() for p in args.platforms.split(",") if p.strip()]
    ok, reason = check_cluster_gate(args.video, plats_raw)
    plats, _ = normalize_platforms(",".join(plats_raw))
    _log_decision({"qid": qid, "video": os.path.abspath(args.video),
                   "platforms": plats_raw, "decision": "accept" if ok else "reject",
                   "reason": reason})
    if not ok:
        print(reason, file=sys.stderr)
        sys.exit(2)  # M7/M9: fail-closed，非零退出，不入队
    q = _load(QUEUE, [])
    home, _ = read_home_cluster(args.video)
    item = {"qid": qid, "video_path": args.video, "title": args.title,
            "desc": args.desc or "", "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
            "cover_path": args.cover, "platforms": plats,
            "home_cluster": home,  # 入队时快照，worker 再重断言（G8）
            "strategy": args.strategy, "qc_passed": args.qc_passed,
            "review_score": args.review_score, "gate_override": False,
            "status": "queued", "attempts": 0, "receipts": {},
            "created_at": now_iso(), "updated_at": now_iso()}
    q.append(item)
    _save(QUEUE, q)
    print(f"已入队 {qid}: {plats}")
    return qid

def status():
    q = _load(QUEUE, [])
    from collections import Counter
    c = Counter(i.get("status") for i in q)
    print(dict(c), f"共{len(q)}条")
    for i in q[-5:]:
        print(f"  {i['qid']} {i['status']} {i['title'][:28]}")

def cmd_tag(args):
    ok, msg = tag_asset(args.video, args.cluster, args.source)
    print(msg)
    if not ok:
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tag")
    t.add_argument("--video", required=True); t.add_argument("--cluster", required=True)
    t.add_argument("--source", default="manual")
    e = sub.add_parser("enqueue")
    e.add_argument("--video", required=True); e.add_argument("--title", required=True)
    e.add_argument("--desc", default=""); e.add_argument("--tags", default="")
    e.add_argument("--cover", default=None); e.add_argument("--platforms", required=True)
    e.add_argument("--strategy", default=None)
    e.add_argument("--qc-passed", dest="qc_passed", action="store_true")
    e.add_argument("--review-score", dest="review_score", type=float, default=0)
    sub.add_parser("work-one"); sub.add_parser("status")
    args = ap.parse_args()
    os.makedirs(APPROVE_DIR, exist_ok=True); os.makedirs(MANUAL_DIR, exist_ok=True)
    if args.cmd == "tag": cmd_tag(args)
    elif args.cmd == "enqueue": enqueue(args)
    elif args.cmd == "work-one": work_one()
    elif args.cmd == "status": status()

if __name__ == "__main__":
    main()
