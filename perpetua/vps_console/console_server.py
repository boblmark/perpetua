#!/usr/bin/env python3
"""Perpetua 独立控制台后端（纯标准库，无第三方依赖）。
1:1 复刻 Muse Dashboard artifact 的 6 个后端 action：
  chat / exec_terminal / getdashboardsnapshot / getpipelinelogs / getpipelinestatus / refreshdashboardsnapshot
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DATA = "/home/hatch/data"
# D20261011-001 P1: pipeline_queue/private_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import sys as _sys
if "/home/hatch/data/perpetua" not in _sys.path:
    _sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db
# 360° v2：发布真相源 YouTube API 结果内存缓存（10min TTL；前端每 5s 轮询，不缓存会烧光 API 配额）
import threading as _threading
_PUBTRUTH_CACHE = {"at": 0.0, "data": {}, "err": ""}
_PUBTRUTH_LOCK = _threading.Lock()
TOKEN_FILE = os.path.join(DATA, "mcp_server", ".token")
AUDIT_LOG = os.path.join(DATA, "perpetua", "terminal_audit.log")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_FILE = os.path.join(DATA, "perpetua", "dashboard_snapshot.json")
PIPELINE_FILE = os.path.join(DATA, "perpetua", "pipeline_runs.json")
CHAT_REQ = os.path.join(DATA, "collab", "chat_requests.json")
CHAT_RESP = os.path.join(DATA, "collab", "chat_responses.json")

# 日志源映射（与 Muse 版一致）
LOG_SOURCES = {
    "mcp": os.path.join(DATA, "mcp_server", "mcp-server.out.log"),
    "watchdog": os.path.join(DATA, "mcp_server", "watchdog.log"),
    "tunnel": os.path.join(DATA, "mcp_server", "tunnel.out.log"),
    "poller": os.path.join(DATA, "mcp_server", "ws-poller.out.log"),
}

# 危险命令拦截
BLOCKED = [
    r"\brm\s+-rf?\s+/(?:\s|$)",
    r"\brm\s+-rf?\s+~(?:\s|$|/)",
    r"\brm\s+-rf?\s+/home(?:\s|$)",
    r":\(\)\s*\{\s*:\|\:&\s*\}\s*;",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r"\b(shutdown|reboot|halt|poweroff)\b",
]

# 密钥脱敏
REDACT_PATTERNS = [
    (re.compile(r'(bearer\s+)[A-Za-z0-9\-._~+/]+=*', re.I), r'\1[REDACTED]'),
    (re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.I), r'\1[REDACTED]'),
    (re.compile(r'(token["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.I), r'\1[REDACTED]'),
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.I), r'\1[REDACTED]'),
    (re.compile(r'(secret["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+', re.I), r'\1[REDACTED]'),
]

# 八阶段定义（2026-10-07 基准数据架构，与 pipeline_runs.json 的 stage id 一致）
STAGES = [
    ("trend", "趋势输入", "Trend", False),
    ("select", "选题生成", "Select", True),
    ("review", "Ask Studio 评审", "Review", True),
    ("generate", "视频生成", "Generate", True),
    ("qc", "QC 质检", "QC", False),
    ("publish", "终审上传", "Publish", False),
    ("postop", "发布后运营", "PostOp", False),
    ("evolve", "数据进化", "Evolve", True),
]

# 演示快照（与 Muse 版 dashboard_snapshots 一致，sample:true）
SAMPLE_SNAPSHOT = {
    "version": 2,
    "sample": True,
    "channelName": "Mark Bobl | Karen vs AI",
    "channelId": "@karenvsai",
    "subscriberCount": 532,
    "videosToday": 3,
    "views7d": 30600,
    "shortsViews90d": 746214,
    "shortsGoal": 3000000,
    "watchHoursDiag": 2796.2,
    "watchHoursGoal": 4000,
    "watchHoursNote": "诊断值，非 qualified hours",
    "viralityRate": 37.8,
    "plan": "Pro",
    "quotaUsed": 3,
    "quotaTotal": 10,
    "updatedAt": "2026-10-06T06:53:46.238Z",
    "videos": [
        {"id": "v-101", "videoId": "A7kLm9Qp2Xs", "title": "Karen vs AI 机器人笼斗", "publishedAt": "10月6日 03:42", "views": 13672, "status": "published"},
        {"id": "v-102", "videoId": "B8nMm0Rr3Yt", "title": "Posiflex AI kiosk 实测", "publishedAt": "10月6日 01:15", "views": 8421, "status": "published"},
        {"id": "v-103", "videoId": "C9oNn1Ss4Zu", "title": "扫地机器人叫保安", "publishedAt": "10月5日 22:30", "views": 5930, "status": "published"},
        {"id": "v-104", "videoId": "D0pOo2Tt5Av", "title": "得来速分贝检测挑战", "publishedAt": "10月5日 19:08", "views": 2150, "status": "published"},
        {"id": "v-105", "videoId": "E1qPp3Uu6Bw", "title": "购物车锁死事件", "publishedAt": "10月5日 16:44", "views": 890, "status": "processing"},
    ],
    "health": [
        {"id": "mcp", "name": "MCP 服务器", "detail": "30 tools online", "healthy": True},
        {"id": "youtube", "name": "YouTube API", "detail": "Quota nominal", "healthy": True},
        {"id": "trend", "name": "热点探测器", "detail": "3 sources scanning", "healthy": True},
        {"id": "studio", "name": "Ask Studio 队列", "detail": "0 waiting", "healthy": False},
    ],
}

# pipeline 缓存（60 秒）
_pipeline_cache = {"at": 0, "data": None}

# 真实数据快照缓存（10 分钟，避免频繁消耗 YouTube API 配额）
_real_snapshot_cache = {"at": 0, "data": None}
REAL_SNAPSHOT_TTL = 600


def _run_yt_script(args, timeout=30):
    """调用 youtube/ 下的脚本，返回解析后的 JSON，失败返回 None。"""
    try:
        r = subprocess.run(
            ["python3"] + args,
            capture_output=True, text=True, timeout=timeout,
            cwd="/home/hatch/data",
        )
        out = (r.stdout or "").strip()
        if not out or out.startswith("[error]"):
            return None
        return json.loads(out)
    except Exception:
        return None


def fetch_real_snapshot():
    """从 YouTube Data API v3 + Analytics API 获取真实频道快照。

    返回 dict（字段与 SAMPLE_SNAPSHOT 对齐），全部失败时返回 None。
    带 10 分钟缓存。
    """
    now = time.time()
    if _real_snapshot_cache["data"] and now - _real_snapshot_cache["at"] < REAL_SNAPSHOT_TTL:
        return _real_snapshot_cache["data"]

    snap = dict(SAMPLE_SNAPSHOT)
    snap["sample"] = False
    ok_any = False

    # 1) 频道基础数据：订阅数、视频数、总播放
    stats = _run_yt_script(["/home/hatch/data/youtube/yt.py", "stats"])
    if stats:
        snap["channelName"] = stats.get("title", snap["channelName"])
        for key, field in (("subs", "subscriberCount"), ("videos", "videoCount"),
                           ("views", "totalViews")):
            try:
                v = stats.get(key)
                if v is not None and str(v).strip() != "":
                    snap[field] = int(str(v).strip())
                    ok_any = True
            except (ValueError, TypeError):
                pass
        # 订阅数是核心指标，单独标记
        if snap.get("subscriberCount"):
            ok_any = True

    # 2) 最近 5 个视频
    recent = _run_yt_script(["/home/hatch/data/youtube/yt.py", "recent", "5"])
    if isinstance(recent, list) and recent:
        vids = []
        for v in recent[:5]:
            vids.append({
                "id": v.get("id", ""),
                "videoId": v.get("id", ""),
                "title": v.get("title", ""),
                "publishedAt": v.get("published", ""),
                "views": int(v.get("views", 0) or 0),
                "status": "published",
            })
        snap["videos"] = vids
        ok_any = True

    # 3) YPP 长视频路径指标（2026-10-10 战略转向）：订阅 + 观看小时诊断值
    #    旧 90 天 Shorts 播放口径已废弃，保留字段兼容
    s90_views = None
    try:
        r = subprocess.run(
            ["python3", os.path.join(BASE_DIR, "ytq.py"),
             "views", "90", "insightTrafficSourceType"],
            capture_output=True, text=True, timeout=40,
            cwd="/home/hatch/data",
        )
        rows = json.loads((r.stdout or "[]").strip() or "[]")
        for row in rows:
            if row[0] == "SHORTS":
                s90_views = int(row[1])
                ok_any = True
                break
    except Exception:
        pass
    if s90_views is not None:
        snap["shortsViews90d"] = s90_views

    # 3b) YPP 观看小时诊断值 + 订阅数（长视频路径，2026-10-10）
    try:
        ypp_rows = open("/home/hatch/data/youtube/ypp_daily.jsonl").read().strip().split("\n")
        last = json.loads(ypp_rows[-1])
        snap["subscriberCount"] = last.get("subs", snap.get("subscriberCount"))
        diag = (last.get("diagnostic_365d") or {}).get("videoOnDemand_hours_DIAGNOSTIC_ONLY")
        if diag is not None:
            snap["watchHoursDiag"] = round(float(diag), 1)
    except Exception:
        pass

    # 4) 近 7 日观看量（经 ytq.py 走 relay；失败则估算并注明）
    views7d = None
    views7d_note = ""
    try:
        r = subprocess.run(
            ["python3", os.path.join(BASE_DIR, "ytq.py"), "views", "7"],
            capture_output=True, text=True, timeout=40,
            cwd="/home/hatch/data",
        )
        rows = json.loads((r.stdout or "[]").strip() or "[]")
        if rows and rows[0]:
            views7d = int(rows[0][0])
            ok_any = True
    except Exception:
        pass
    if views7d is None and isinstance(recent, list) and recent:
        # 降级：用最近视频播放量估算
        views7d = sum(int(v.get("views", 0) or 0) for v in recent[:5])
        views7d_note = "estimated"
    if views7d is not None:
        snap["views7d"] = views7d
        if views7d_note:
            snap["views7d_note"] = views7d_note

    # 5) 爆款率：近 30 天播放 Top10% 占比的简化版 —— 用近期视频中播放 > 均值2倍的比例
    if isinstance(recent, list) and len(recent) >= 3:
        vs = [int(v.get("views", 0) or 0) for v in recent]
        avg = sum(vs) / len(vs) if vs else 1
        hot = sum(1 for x in vs if x > avg * 2)
        snap["viralityRate"] = round(hot / len(vs) * 100, 1)

    # 6) 今日发布数（从 pipeline 真实遥测）
    try:
        pipe = read_json_file(PIPELINE_FILE) or {}
        runs = pipe.get("runs", [])
        today = time.strftime("%Y-%m-%d")
        snap["videosToday"] = sum(
            1 for r in runs
            if r.get("stage") == "publish" and (r.get("at") or "").startswith(today)
        )
    except Exception:
        pass

    snap["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if ok_any:
        _real_snapshot_cache["at"] = now
        _real_snapshot_cache["data"] = snap
        return snap
    return None


# ---- 观众评论（5 分钟缓存） ----
_real_comments_cache = {"at": 0, "data": None}
REAL_COMMENTS_TTL = 300

def fetch_real_comments(max_n=20):
    """从 YouTube Data API 拉取频道最新评论。失败返回 None。带 5 分钟缓存。"""
    now = time.time()
    if _real_comments_cache["data"] is not None and now - _real_comments_cache["at"] < REAL_COMMENTS_TTL:
        return _real_comments_cache["data"]
    comments = _run_yt_script([os.path.join(BASE_DIR, "ytc.py"), str(max_n)], timeout=60)
    if isinstance(comments, list):
        _real_comments_cache["at"] = now
        _real_comments_cache["data"] = comments
        return comments
    return None


def reply_to_comment(comment_id, text):
    """手动回复一条评论（走 relay）。返回 dict 结果，失败返回 {"error": ...}。"""
    try:
        r = subprocess.run(
            ["python3", "-c",
             "import sys, json, random; "
             "sys.path.insert(0, '/home/hatch/data/youtube'); "
             "from comment_sweep import do_reply; "
             "txt = sys.argv[2] or random.choice(["
             "'Thanks for watching! 🔥 Which part was your favorite?', "
             "'Glad you enjoyed it! 😂 More Karen vs AI coming soon!', "
             "'Appreciate the comment! 👀 What should the AI do next?']); "
             "r = do_reply(sys.argv[1], txt); "
             "print(json.dumps({'ok': True, 'reply_id': r.get('id','')}))",
             comment_id, text or ""],
            capture_output=True, text=True, timeout=40,
            cwd="/home/hatch/data",
        )
        out = (r.stdout or "").strip()
        if out:
            return json.loads(out)
        return {"error": (r.stderr or "no output")[:200]}
    except Exception as e:
        return {"error": str(e)[:200]}


def get_token():
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


# ---- MCP 服务端代理（token 不下发前端） ----
# MCP 是 Streamable HTTP（JSON-RPC over POST），且要求先 initialize 建会话。
# 会话在服务端维护，前端只调 /api/mcp*，永远接触不到真实 token。
_mcp_proxy = {"session_id": "", "at": 0}
_MCP_URL = "http://127.0.0.1:8734/mcp"


def _mcp_post(payload, session_id=""):
    """向 MCP 发一次 JSON-RPC POST，返回 (status, new_session_id, body)。"""
    import urllib.request
    import urllib.error
    token = get_token()
    if not token:
        return 0, "", "mcp token missing"
    req = urllib.request.Request(
        _MCP_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    if session_id:
        req.add_header("Mcp-Session-Id", session_id)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Mcp-Session-Id", ""), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, "", body
    except Exception as e:
        return 0, "", str(e)


def _mcp_ensure_session():
    """建（或复用）MCP 会话，返回 session_id，失败返回 ''。"""
    if _mcp_proxy["session_id"] and time.time() - _mcp_proxy["at"] < 600:
        return _mcp_proxy["session_id"]
    st, sid, _ = _mcp_post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "console-proxy", "version": "1.0"}},
    })
    if st == 200 and sid:
        _mcp_proxy.update(session_id=sid, at=time.time())
        return sid
    _mcp_proxy.update(session_id="", at=0)
    return ""


def _mcp_rpc(method, params):
    """调 MCP 的 JSON-RPC 方法，返回 (result, error)。"""
    sid = _mcp_ensure_session()
    if not sid:
        return None, "mcp session init failed"
    st, _, body = _mcp_post(
        {"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}}, sid)
    if st == 400 and "session" in body.lower():
        # 会话过期：清掉重建并重试一次
        _mcp_proxy.update(session_id="", at=0)
        sid = _mcp_ensure_session()
        if not sid:
            return None, "mcp session re-init failed"
        st, _, body = _mcp_post(
            {"jsonrpc": "2.0", "id": 3, "method": method, "params": params or {}}, sid)
    if st != 200:
        return None, "mcp http %s: %s" % (st, body[:200])
    for line in body.splitlines():
        if line.startswith("data:"):
            try:
                d = json.loads(line[5:].strip())
            except ValueError:
                continue
            if "error" in d:
                return None, str(d["error"])[:300]
            return d.get("result"), ""
    return None, "mcp empty response"


def _audit_mcp_call(method):
    """代理调用审计：只记方法名，不记参数/token。"""
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write("%s [mcp-proxy] %s\n" % (
                time.strftime("%Y-%m-%dT%H:%M:%S"), method))
    except OSError:
        pass


def json_resp(handler, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


MATRIX_SYNC_JOB = "/home/hatch/data/perpetua/distributor/matrix_sync_job.json"

def _matrix_job_load():
    """读矩阵同步 job 文件（2026-10-11 状态机重做：持久化，不用 /tmp）"""
    try:
        with open(MATRIX_SYNC_JOB) as f:
            return json.load(f)
    except Exception:
        return None

def _matrix_job_save(job):
    tmp = MATRIX_SYNC_JOB + ".tmp"
    with open(tmp, "w") as f:
        json.dump(job, f, ensure_ascii=False)
    os.replace(tmp, MATRIX_SYNC_JOB)

def _matrix_job_maybe_done():
    """所有平台都终态 → job 标 done（2026-10-11）"""
    job = _matrix_job_load()
    if not job or job.get("status") != "running":
        return
    ps = job.get("platforms", {})
    if ps and all(v in ("done", "error", "stale") for v in ps.values()):
        job["status"] = "done"
        job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _matrix_job_save(job)


def _fmt_elapsed(s):
    """秒 → 人类可读时长（2026-10-11 生成进度用）"""
    if s is None:
        return "-"
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%d分%d秒" % (s // 60, s % 60)
    return "%d小时%d分" % (s // 3600, (s % 3600) // 60)


def read_json_file(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json_file(path, data):
    # v2.0.0 (2026-10-11, D20261011-006, 红队 KILL 3)：改走原子写
    #（lockfile + tmp + fsync + rename），不再裸 open("w")。
    try:
        _sys.path.insert(0, "/home/hatch/data/perpetua")
        from atomic_json import atomic_write
        atomic_write(path, data)
        return True
    except OSError:
        return False


def redact(text):
    for pat, repl in REDACT_PATTERNS:
        text = pat.sub(repl, text)
    return text


def tail_file(path, lines=100):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            data = f.read().decode("utf-8", errors="replace")
        return redact("\n".join(data.splitlines()[-lines:]))
    except OSError:
        return ""


# ---- 统一发布计划（5 分钟缓存） ----
_publish_plan_cache = {"at": 0, "data": None}
PUBLISH_PLAN_TTL = 300

def _norm_title(t):
    """标题归一化用于去重比对：小写、去 emoji/标点/空格。"""
    import re as _re
    t = (t or "").lower()
    t = _re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t

def fetch_publish_plan():
    """统一发布计划：待生成(queued) → 待取货/待发布(ready) → 已发布(published)。

    - 待生成：perpetua/jobs/pending/ 中的 generate_video 任务
    - 待取货：collab/inbox.json 的 pending_pickup（待 Marvis 上传）
    - 已发布：YouTube Data API 最近视频（与 Studio 一致）
    本地 pending 与已发布做标题去重，避免重复显示。
    """
    now = time.time()
    if _publish_plan_cache["data"] and now - _publish_plan_cache["at"] < PUBLISH_PLAN_TTL:
        return _publish_plan_cache["data"]

    plan = {"queued": [], "ready": [], "private_waiting": [], "published": [],
            "sample": False,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # 1) 待生成：jobs/pending/ 中的 generate_video
    try:
        pj = os.path.join(DATA, "perpetua", "jobs", "pending")
        for fn in sorted(os.listdir(pj)):
            if not fn.endswith(".json") or fn.endswith(".result.json"):
                continue
            d = read_json_file(os.path.join(pj, fn))
            if not d or d.get("job_type") != "generate_video":
                continue
            p = d.get("payload") or {}
            plan["queued"].append({
                "stage": "queued",
                "job_id": d.get("job_id", ""),
                "title": p.get("title") or p.get("prompt", "")[:60],
                "created_at": d.get("created_at", ""),
                "from": d.get("from", ""),
            })
    except OSError:
        pass

    # 2) 待取货：inbox.json pending_pickup（待 Marvis 上传，经统一网关）
    try:
        import inbox as inbox_gw
        inbox = inbox_gw.load()
        for item in inbox.get("pending_pickup", []):
            plan["ready"].append({
                "stage": "ready",
                "title": item.get("title", ""),
                "file": item.get("file", ""),
                "created": item.get("created", ""),
                "status": item.get("status", "ready"),
            })
    except Exception:
        pass

    # 3) 已发布：YouTube Data API 最近视频（与 Studio 一致）
    recent = _run_yt_script(["/home/hatch/data/youtube/yt.py", "recent", "10"])
    if isinstance(recent, list) and recent:
        for v in recent[:10]:
            plan["published"].append({
                "stage": "published",
                "videoId": v.get("id", ""),
                "title": v.get("title", ""),
                "publishedAt": v.get("published", ""),
                "views": int(v.get("views", 0) or 0),
            })
    else:
        plan["sample"] = True

    # 3.5) 私享待发：private_queue.json 中 status=waiting 的视频（2026-10-08 新增）
    # QC 通过后已上传为 private，等待排期翻 public
    try:
        pq = queue_db.privateq_load()  # D20261011-001 P1: 已迁 SQLite
        for item in pq:
            if item.get("status") == "waiting":
                plan["private_waiting"].append({
                    "stage": "private_waiting",
                    "videoId": item.get("video_id", ""),
                    "title": item.get("title", ""),
                    "scheduled_at": item.get("scheduled_at", ""),
                    "slot": item.get("slot", ""),
                    "queued_at": item.get("queued_at", ""),
                })
    except Exception:
        pass

    # 4) 去重：本地 queued/ready 中标题与已发布高度重合的，视为已发布，不再显示在待办
    pub_norm = {_norm_title(v["title"]) for v in plan["published"]}
    def is_dup(title):
        nt = _norm_title(title)
        if not nt:
            return False
        return any(nt in p or p in nt for p in pub_norm if p)
    plan["queued"] = [q for q in plan["queued"] if not is_dup(q["title"])]
    plan["ready"] = [r for r in plan["ready"] if not is_dup(r["title"])]

    plan["counts"] = {k: len(plan[k]) for k in ("queued", "ready", "private_waiting", "published")}
    _publish_plan_cache["at"] = now
    _publish_plan_cache["data"] = plan
    return plan


class Handler(BaseHTTPRequestHandler):
    server_version = "PerpetuaConsole/2.0"
    protocol_version = "HTTP/1.0"  # 短连接，隧道更可靠

    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/oauth2callback":
            self.serve_oauth_callback(parsed)
            return
        if path == "/":
            self.serve_index()
            return
        if path == "/oa":
            self.serve_file("oa.html", "text/html; charset=utf-8")
            return
        if path == "/command":
            # 2026-10-16 退役：360° 已并入 Battle 标签页，/command 永久跳转到 /
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
            return
            return
        if path == "/qr-douyin":
            self.serve_qr_douyin_page()
            return
        if path == "/qr-douyin.png":
            self.serve_qr_douyin_png()
            return
        if path == "/api/oa/approve" and self.command == "POST":
            self.api_oa_decide(True)
            return
        if path == "/api/oa/reject" and self.command == "POST":
            self.api_oa_decide(False)
            return
        if path == "/api/app.css":
            self.serve_file("app.css", "text/css; charset=utf-8")
            return
        if path == "/api/app.js":
            self.serve_file("app.js", "application/javascript; charset=utf-8")
            return
        if path.startswith("/api/"):
            # MCP 服务端代理：前端不再持有 token，所有 MCP 调用走这里。
            # token 只在服务端读 .token 文件，不下发前端。
            if path == "/api/mcp/tools/list":
                self.api_mcp_tools_list()
                return
            qs = parse_qs(parsed.query)
            if path == "/api/snapshot":
                self.api_snapshot()
            elif path == "/api/pipeline":
                self.api_pipeline(qs.get("tenant_id", ["default"])[0])
            elif path == "/api/logs":
                self.api_logs(qs.get("source", ["all"])[0], min(int(qs.get("lines", ["100"])[0]), 500))
            elif path == "/api/tenants":
                self.api_tenants()
            elif path == "/api/health":
                self.api_health()
            elif path == "/api/comments":
                self.api_comments()
            elif path == "/api/publish_plan":
                self.api_publish_plan()
            elif path == "/api/generation_progress":
                self.api_generation_progress()
            elif path == "/api/live_model":
                self.api_live_model_get()
            elif path == "/api/kb/search":
                self.api_kb_search(qs)
            elif path == "/api/postop_status":
                self.api_postop_status()
            elif path == "/api/policy_gate":
                self.api_policy_gate()
            elif path == "/api/douyin":
                self.api_douyin()
            elif path == "/api/distributor":
                self.api_distributor()
            elif path == "/api/platform_matrix":
                self.api_platform_matrix()
            elif path == "/api/matrix_sync":
                self.api_matrix_sync()
            elif path == "/api/matrix_sync/status":
                self.api_matrix_sync_status()
            elif path == "/api/matrix_img":
                self.api_matrix_img()
            elif path.startswith("/api/imgcache/"):
                self.api_imgcache()
            elif path == "/api/branding_requests":
                self.api_branding_requests()
            elif path == "/api/pipeline/queue":
                self.api_pipeline_queue()
            elif path == "/api/quarantine/list":
                self.api_quarantine_list()
            elif path == "/api/agent/cron-cache":
                self.api_agent_cron_cache()
            elif path == "/api/agent/hotstandby":
                self.api_agent_hotstandby()
            elif path == "/api/command/live":
                self.api_command_live()
            elif path == "/api/mutate/pending":
                self.api_mutate_pending(parsed)
                return
            elif path == "/api/cron/requests":
                self.api_cron_requests()
                return
            elif path == "/api/oa/org":
                self.api_oa_org()
            elif path == "/api/oa/approvals":
                self.api_oa_approvals()
            elif path == "/api/oa/departments":
                self.api_oa_departments()
            elif path == "/api/oa/audit":
                self.api_oa_audit()
            elif path == "/api/oa/videos":
                self.api_oa_videos()
            elif path == "/api/oa/marvis":
                self.api_oa_marvis()
            elif path == "/api/oa/stage_logs":
                self.api_oa_stage_logs()
            elif path == "/api/oa/charts":
                self.api_oa_charts()
            elif path == "/api/oa/content/brief":
                self.api_oa_content("brief", {})
            elif path == "/api/oa/leads":
                self.api_oa_growth("leads_list", {})
            elif path == "/api/oa/distribution":
                self.api_oa_growth("dist_list", {})
            elif path == "/api/oa/revenue":
                self.api_oa_growth("revenue", {})
            else:
                json_resp(self, {"error": "not found"}, 404)
            return
        self.send_response(404)
        self.end_headers()

    def api_sleep_hook(self, path, payload):
        # Sleep as Android 自定义 Webhook 接收端（2026-10-22）：睡眠事件秒级落盘
        # 多用户（2026-10-22）：token 先查 sleep_monitor/users.json 的 tokens 映射认人；
        # 未命中再回退单用户 hook_token.txt（归属默认用户 cgb2026，兼容已配置的手机）。
        got = path[len("/sleep-hook/"):].strip("/")
        user = ""
        try:
            with open(os.path.join(DATA, "sleep_monitor", "users.json")) as f:
                user = json.load(f).get("tokens", {}).get(got, "")
        except (OSError, ValueError):
            user = ""
        if not user:
            token_file = os.path.join(DATA, "sleep_monitor", "hook_token.txt")
            try:
                expected = open(token_file).read().strip()
            except OSError:
                expected = ""
            if expected and got == expected:
                user = "cgb2026"
        if not user:
            json_resp(self, {"ok": False, "error": "bad token"}, code=403)
            return
        rec = {
            "received_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "user": user,
            "event": str(payload.get("event", ""))[:64],
            "value1": str(payload.get("value1", ""))[:256],
            "value2": str(payload.get("value2", ""))[:256],
            "value3": str(payload.get("value3", ""))[:256],
        }
        try:
            log_path = os.path.join(DATA, "sleep_monitor", "events.jsonl")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            json_resp(self, {"ok": False, "error": "write failed"}, code=500)
            return
        json_resp(self, {"ok": True})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        if parsed.path.startswith("/sleep-hook/"):
            self.api_sleep_hook(parsed.path, payload)
            return
        if parsed.path == "/api/exec":
            self.api_exec(payload.get("command", ""))
            return
        if parsed.path == "/api/chat":
            self.api_chat(payload.get("message", ""))
            return
        if parsed.path == "/api/commander/chat":
            self.api_commander_chat(payload)
            return
        if parsed.path == "/api/commander/poll":
            self.api_commander_poll(payload)
            return
        if parsed.path == "/api/oa/approve":
            self._oa_decide_body(payload, True)
            return
        if parsed.path == "/api/oa/reject":
            self._oa_decide_body(payload, False)
            return
        if parsed.path == "/api/matrix_reply":
            self.api_matrix_reply(payload)
            return
        if parsed.path == "/api/branding_request":
            self.api_branding_request(payload)
            return
        if parsed.path == "/api/matrix_order":
            self.api_matrix_order(payload)
            return
        if parsed.path == "/api/matrix_sync":
            self.api_matrix_sync()
            return
        if parsed.path == "/api/live_model":
            self.api_live_model_set(payload)
            return
            return
        if parsed.path == "/api/snapshot/refresh":
            self.api_snapshot_refresh()
            return
        if parsed.path == "/api/settings":
            self.api_settings_save(payload)
            return
        if parsed.path == "/api/tenant/add":
            self.api_tenant_add(payload)
            return
        if parsed.path == "/api/tenant/update":
            self.api_tenant_update(payload)
            return
        if parsed.path == "/api/tenant/delete":
            self.api_tenant_delete(payload)
            return
        if parsed.path == "/api/comments/reply":
            self.api_comment_reply(payload.get("comment_id", ""), payload.get("text", ""))
            return
        if parsed.path == "/api/oa/content":
            self.api_oa_content(payload.get("tool", ""), payload)
            return
        if parsed.path == "/api/oa/leads":
            self.api_oa_growth("lead_upsert", payload)
            return
        if parsed.path == "/api/oa/distribution/add":
            self.api_oa_growth("dist_add", payload)
            return
        if parsed.path == "/api/oa/distribution/update":
            self.api_oa_growth("dist_update", payload)
            return
        if parsed.path == "/api/oa/revenue/add":
            self.api_oa_growth("revenue_add", payload)
            return
        if parsed.path == "/api/mcp":
            # 通用 MCP JSON-RPC 代理：payload {"method": "tools/list", "params": {...}}
            self.api_mcp_call(payload)
            return
        if parsed.path == "/api/pipeline/recovery-approve":
            self.api_pipeline_recovery_approve(payload)
            return
        if parsed.path == "/api/mutate":
            self.api_mutate(payload)
            return
        if parsed.path == "/api/quarantine/unfreeze":
            self.api_quarantine_unfreeze(payload)
            return
        if parsed.path == "/api/quarantine/title-swap":
            self.api_quarantine_title_swap(payload)
            return
        self.send_response(404)
        self.end_headers()

    # ---- 页面 ----
    def serve_qr_douyin_page(self):
        # 抖音扫码登录实时页：二维码每 10 秒自动刷新，用户电脑打开、手机抖音扫一扫。
        # 二维码由登录进程持续刷新到 /tmp/douyin_login_qr.png。
        html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>抖音扫码登录</title>
<style>
body{background:#161823;color:#fff;font-family:sans-serif;text-align:center;padding:40px 20px;margin:0}
.qr{width:320px;height:320px;background:#fff;border-radius:12px;margin:24px auto;display:flex;align-items:center;justify-content:center}
.qr img{width:300px;height:300px}
.tip{color:#999;font-size:14px;margin-top:16px;line-height:1.8}
.timer{color:#fe2c55;font-size:13px;margin-top:8px}
</style></head><body>
<h2>抖音扫码登录</h2>
<div class="qr"><img id="qr" src="/qr-douyin.png" alt="二维码"></div>
<div class="tip">手机打开 <b>抖音 APP</b> → 首页 → 搜索 → <b>扫一扫</b><br>对准上方二维码扫描</div>
<div class="timer" id="timer"></div>
<script>
var n=10;
function tick(){
  document.getElementById('timer').textContent='二维码 '+n+' 秒后自动刷新';
  n--;
  if(n<0){ n=10; document.getElementById('qr').src='/qr-douyin.png?t='+Date.now(); }
  setTimeout(tick,1000);
}
tick();
</script></body></html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_qr_douyin_png(self):
        # 返回登录进程刷新的最新二维码；登录进程未启动时返回 404。
        try:
            with open("/tmp/douyin_login_qr.png", "rb") as f:
                body = f.read()
        except OSError:
            body = b"qr not ready"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_oauth_callback(self, parsed):
        import urllib.parse as up
        qs = up.parse_qs(parsed.query)
        code = qs.get('code', [''])[0]
        err = qs.get('error', [''])[0]
        if err:
            body = f"<h2>授权失败: {err}</h2>".encode()
        elif code:
            # 把 code 存到文件，由后台脚本换 token（避免在响应里暴露）
            with open('/home/hatch/data/youtube/.oauth_code', 'w') as f:
                f.write(code)
            body = "<h2>授权成功！可以关闭此页面，回到控制台继续。</h2>".encode('utf-8')
        else:
            body = "<h2>未收到授权码</h2>".encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, filename, ctype):
        try:
            with open(os.path.join(BASE_DIR, filename), "rb") as f:
                body = f.read()
            # 安全：不再向前端注入任何 token。
            # 高权限 MCP token 只留在服务端（/.token 文件 + /api/mcp 代理），
            # 页面源码中不再出现真实 token。
        except OSError:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        accept = self.headers.get("Accept-Encoding", "")
        if "gzip" in accept and len(body) > 1024:
            import gzip
            body = gzip.compress(body)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            # 2026-10-11：控制台是实时看板，HTML 禁缓存（曾导致用户看到旧按钮/旧布局）
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
        self.wfile.write(body)

    def serve_index(self):
        # 直接 serving 完整单文件 index.html（42KB），不再分片加载
        # 分片方案在手机浏览器上不可靠
        self.serve_file("index.html", "text/html; charset=utf-8")

    # ---- 快照 ----
    def api_snapshot(self):
        # 优先真实 YouTube API 数据，失败时回退演示数据并标注
        real = fetch_real_snapshot()
        if real:
            json_resp(self, real)
            return
        data = read_json_file(SNAPSHOT_FILE)
        if not data:
            data = dict(SAMPLE_SNAPSHOT)
        data["sample"] = True
        json_resp(self, data)

    def api_snapshot_refresh(self):
        # 强制刷新：清缓存后取真实数据，失败回退演示
        _real_snapshot_cache["at"] = 0
        _real_snapshot_cache["data"] = None
        real = fetch_real_snapshot()
        if real:
            write_json_file(SNAPSHOT_FILE, real)
            json_resp(self, real)
            return
        # 回退：演示数据
        data = read_json_file(SNAPSHOT_FILE) or dict(SAMPLE_SNAPSHOT)
        data["sample"] = True
        data["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_json_file(SNAPSHOT_FILE, data)
        json_resp(self, data)

    # ---- 观众评论 ----
    def api_publish_plan(self):
        plan = fetch_publish_plan()
        json_resp(self, plan)

    def api_generation_progress(self):
        """单条视频生成实时进度（2026-10-11 新增）：
        从 pipeline_queue 读生成相关状态的条目，返回每条的阶段、已耗时、后端信息。
        状态机：review_passed(排队待提交) → job_submitted(主Muse生成中)
                → generated(片已回) / generate_failed(失败)
        """
        import sys as _sys
        _sys.path.insert(0, "/home/hatch/data/perpetua")
        try:
            import queue_db
            items = queue_db.pipeline_load() or []
        except Exception:
            items = []
        GEN_STATES = ("review_passed", "job_submitted", "generated",
                      "generate_failed")
        STATE_LABEL = {
            "review_passed": ("排队待提交", "queued"),
            "job_submitted": ("主Muse生成中", "generating"),
            "generated": ("成片已回", "done"),
            "generate_failed": ("生成失败", "failed"),
        }
        now = time.time()
        out = []
        for it in items:
            st = it.get("status")
            if st not in GEN_STATES:
                continue
            label, phase = STATE_LABEL[st]
            # 已耗时：job_submitted 用 submitted_at，其它用 updated_at/created_at
            ts_raw = (it.get("submitted_at") or it.get("updated_at")
                      or it.get("created_at") or "")
            elapsed_s = None
            try:
                ts = ts_raw[:19]
                if ts_raw[19:20] == 'Z' or '+' in ts_raw[19:]:
                    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
                    ets = dt.replace(tzinfo=timezone.utc).timestamp()
                else:
                    ets = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
                elapsed_s = max(0, int(now - ets))
            except (ValueError, TypeError):
                pass
            vf = it.get("video_file") or ""
            out.append({
                "topic": it.get("topic", ""),
                "title": it.get("title", ""),
                "status": st,
                "label": label,
                "phase": phase,
                "elapsed_s": elapsed_s,
                "elapsed_human": _fmt_elapsed(elapsed_s),
                "backend": it.get("gen_backend", ""),
                "muse_job_id": (it.get("muse_job_id") or "")[-12:],
                "video_file": os.path.basename(vf) if vf else "",
                "has_video": bool(vf and os.path.exists(vf)),
                "score": it.get("virality_score") or it.get("score"),
                "error": (it.get("generate_error") or "")[:120],
                "at": ts_raw,
            })
        # 排序：生成中 > 排队 > 已完成/失败（按时间倒序）
        order = {"job_submitted": 0, "review_passed": 1,
                 "generate_failed": 2, "generated": 3}
        out.sort(key=lambda x: (order.get(x["status"], 9), -(x["elapsed_s"] or 0)))
        json_resp(self, {"items": out, "count": len(out),
                         "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime())})

    def api_live_model_get(self):
        """读取实时语音/视频模型配置（2026-10-12 新增）"""
        import os
        cfg_path = "/home/hatch/data/nanomuse-migration/perception/server/live_model_config.yaml"
        defaults = {
            "live_model": "gemini-2.0-flash-exp",
            "video_fps": 1,
            "video_quality": 70,
            "audio_sample_rate": 16000,
        }
        try:
            import yaml
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                defaults.update(cfg)
        except Exception as e:
            defaults["error"] = str(e)
        json_resp(self, defaults)

    def api_live_model_set(self, payload):
        """更新实时语音/视频模型配置（2026-10-12 新增）"""
        import os
        cfg_path = "/home/hatch/data/nanomuse-migration/perception/server/live_model_config.yaml"
        allowed = {"live_model", "video_fps", "video_quality", "audio_sample_rate"}
        try:
            import yaml
            cfg = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
            for k in allowed:
                if k in payload:
                    cfg[k] = payload[k]
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True)
            json_resp(self, {"ok": True, "config": cfg})
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)})

    def api_kb_search(self, qs):
        """知识库语义检索（2026-10-11 新增）：查 OpenViking MCP 向量库。
        embedding 走 curl（绕沙箱），向量存本地 JSON，自算余弦相似度。
        GET 参数：q=查询词，limit=条数（默认5，上限10）。
        """
        import sys as _sys
        _sys.path.insert(0, "/home/hatch/data/openviking_mcp")
        q = (qs.get("q", [""])[0] or "").strip()
        limit = min(int(qs.get("limit", ["5"])[0] or 5), 10)
        if not q:
            json_resp(self, {"ok": False, "error": "缺少查询词 q"})
            return
        try:
            import kb_lib
            items = kb_lib.kb_search(q, limit)
            json_resp(self, {"ok": True, "query": q, "items": items,
                             "count": len(items),
                             "stats": kb_lib.kb_stats()})
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:200]})

    def api_postop_status(self):
        """发布后运营状态（2026-10-08 新增）：
        哑火诊断、钩子强化、7×24 看门狗、网关拦截
        """
        status = {
            "dud_diagnosed_7d": 0,      # 7天内哑火诊断数
            "hook_boost_signals_7d": 0,  # 7天内钩子强化信号数
            "hook_boost_active": False,  # 钩子强化是否激活（≥3条）
            "watchdog_last_check": None,
            "watchdog_videos_checked": 0,
            "watchdog_anomalies": 0,
            "gateway_rejects_7d": 0,     # 7天内网关拦截数
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)

        # 1. 哑火诊断：从 post_publish_optimizer 日志统计
        try:
            log_path = os.path.join(DATA, "youtube", "post_publish.log")
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8") as f:
                    for line in f:
                        if "dud_diagnosed" in line:
                            # 简单的时间过滤（日志行首有时间戳）
                            try:
                                # 假设格式 [2026-10-08T...]
                                ts_str = line[1:26] if line.startswith("[") else ""
                                if ts_str:
                                    ts = datetime.fromisoformat(
                                        ts_str.replace("Z", "+00:00"))
                                    if ts > cutoff:
                                        status["dud_diagnosed_7d"] += 1
                            except Exception:
                                pass
        except Exception:
            pass

        # 2. 钩子强化信号：dud_feedback.jsonl
        try:
            fb_path = os.path.join(DATA, "perpetua", "dud_feedback.jsonl")
            if os.path.exists(fb_path):
                with open(fb_path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            e = json.loads(line)
                            ts = datetime.fromisoformat(
                                e.get("ts", "").replace("Z", "+00:00"))
                            if ts > cutoff and e.get("signal") == "strengthen_hook":
                                status["hook_boost_signals_7d"] += 1
                        except Exception:
                            continue
                status["hook_boost_active"] = status["hook_boost_signals_7d"] >= 3
        except Exception:
            pass

        # 3. 看门狗状态：video_watchdog.log 最后几行
        try:
            wd_log = os.path.join(DATA, "youtube", "video_watchdog.log")
            if os.path.exists(wd_log):
                with open(wd_log, encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in reversed(lines[-20:]):
                        if "检查完成" in line:
                            # [2026-10-08T15:28:23...] 检查完成：14 个视频，0 个异常
                            try:
                                ts_str = line[1:32] if line.startswith("[") else ""
                                if ts_str:
                                    status["watchdog_last_check"] = ts_str
                                # 解析数字
                                import re
                                m = re.search(r"(\d+) 个视频，(\d+) 个异常", line)
                                if m:
                                    status["watchdog_videos_checked"] = int(m.group(1))
                                    status["watchdog_anomalies"] = int(m.group(2))
                                break
                            except Exception:
                                pass
        except Exception:
            pass

        # 4. 网关拦截：upload_gateway_rejects.jsonl
        try:
            gw_path = os.path.join(DATA, "perpetua", "upload_gateway_rejects.jsonl")
            if os.path.exists(gw_path):
                with open(gw_path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            e = json.loads(line)
                            ts = datetime.fromisoformat(
                                e.get("ts", "").replace("Z", "+00:00"))
                            if ts > cutoff:
                                status["gateway_rejects_7d"] += 1
                        except Exception:
                            continue
        except Exception:
            pass

        json_resp(self, status)

    def api_policy_gate(self):
        """平台政策合规门状态（2026-10-10 新增）：
        prescreen 确定性预检 + Ask Studio 终审 Q4 的 FLAG 统计与最近记录。
        数据源：policy_flag.log.json（FLAG 日志）、prompt_review_manual.json（人工复核队列）。
        """
        import json as _json
        base = "/home/hatch/data/perpetua"
        flags = []
        for name in ("policy_flag.log.json",):
            p = os.path.join(base, name)
            try:
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as f:
                        flags.extend(_json.load(f) or [])
            except Exception:
                pass
        manual = []
        try:
            mp = os.path.join(base, "prompt_review_manual.json")
            if os.path.exists(mp):
                with open(mp, encoding="utf-8") as f:
                    manual = _json.load(f) or []
        except Exception:
            pass
        # 最近 10 条（按 at 倒序，缺 at 的放后面）
        recent = sorted(flags, key=lambda e: e.get("at", ""), reverse=True)[:10]
        recent_out = [{
            "at": e.get("at", ""),
            "topic": e.get("topic", ""),
            "title": (e.get("title", "") or "")[:60],
            "stage": e.get("stage", ""),
            "rules": [r.get("rule", "") for r in (e.get("reasons") or [])],
        } for e in recent]
        json_resp(self, {
            "flag_total": len(flags),
            "manual_pending": len(manual),
            "recent": recent_out,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def api_douyin(self):
        """抖音 Pilot1 进度（2026-10-10 新增）：
        71 分镜回齐状态 + prompt 生成机制状态。
        数据源：douyin/pilot1_clip_jobs.json、douyin/douyin_prompt.py。
        """
        import json as _json
        jobs = {}
        try:
            jp = "/home/hatch/data/douyin/pilot1_clip_jobs.json"
            if os.path.exists(jp):
                with open(jp, encoding="utf-8") as f:
                    jobs = _json.load(f) or {}
        except Exception:
            pass
        episodes = {}
        for ep in ("up", "mid", "down"):
            eps = {k: v for k, v in jobs.items() if k.startswith(ep + "-")}
            c = {"total": len(eps), "collected": 0, "submitted": 0, "failed": 0}
            for v in eps.values():
                st = v.get("status", "")
                if st == "collected":
                    c["collected"] += 1
                elif st == "failed":
                    c["failed"] += 1
                else:
                    c["submitted"] += 1
            episodes[ep] = c
        failed_list = [
            {"shot": k, "job": (v.get("muse_job_id", "") or "")[-12:],
             "error": (v.get("error", "") or "")[:120]}
            for k, v in jobs.items() if v.get("status") == "failed"
        ]
        # prompt 生成机制状态
        prompt_gen = {"available": False, "style": None}
        try:
            pp = "/home/hatch/data/douyin/douyin_prompt.py"
            if os.path.exists(pp):
                prompt_gen = {"available": True, "style": "dark_archive",
                              "module": "douyin_prompt.py"}
        except Exception:
            pass
        json_resp(self, {
            "episodes": episodes,
            "total": sum(e["total"] for e in episodes.values()),
            "collected": sum(e["collected"] for e in episodes.values()),
            "failed": failed_list,
            "prompt_gen": prompt_gen,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def api_distributor(self):
        """分发器状态（2026-10-10 新增）：队列、簇门禁决策日志、资产标签数。"""
        import json as _json
        base = "/home/hatch/data/perpetua/distributor"
        q, tags, decisions = [], {}, []
        try:
            with open(os.path.join(base, "distribute_queue.json"), encoding="utf-8") as f:
                q = _json.load(f) or []
        except Exception:
            pass
        try:
            with open(os.path.join(base, "asset_tags.json"), encoding="utf-8") as f:
                tags = _json.load(f) or {}
        except Exception:
            pass
        try:
            with open(os.path.join(base, "distribute_decisions.log.json"), encoding="utf-8") as f:
                decisions = _json.load(f) or []
        except Exception:
            pass
        from collections import Counter
        qc = Counter(i.get("status") for i in q)
        dc = Counter(d.get("decision") for d in decisions)
        recent = [{
            "at": (d.get("at", "") or "")[:19].replace("T", " "),
            "decision": d.get("decision", ""),
            "platforms": d.get("platforms", []),
            "reason": (d.get("reason", "") or "")[:80],
        } for d in decisions[-8:]]
        recent.reverse()
        json_resp(self, {
            "queue": dict(qc), "queue_total": len(q),
            "assets_tagged": len(tags),
            "gate": {"accept": dc.get("accept", 0), "reject": dc.get("reject", 0)},
            "recent_decisions": recent,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def api_platform_matrix(self):
        """八平台分发矩阵（2026-10-11 新增）：各平台频道内容+评论同步快照。
        2026-10-11 23:20 增强：返回跨平台汇总、趋势（vs上次）、过期小时数。"""
        import json as _json, os as _os, time as _time
        fp = "/home/hatch/data/perpetua/distributor/platform_matrix.json"
        hist_fp = "/home/hatch/data/perpetua/distributor/matrix_history.json"
        try:
            with open(fp, encoding="utf-8") as f:
                d = _json.load(f)
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:100]})
            return
        platforms = d.get("platforms", {})
        now = _time.time()
        # 当前各平台总量
        cur = {}
        total_views, total_videos = 0, 0
        for k, p in platforms.items():
            vids = p.get("videos", []) or []
            tv = sum(v.get("views", 0) or 0 for v in vids)
            cur[k] = {"views": tv, "count": len(vids)}
            total_views += tv
            total_videos += len(vids)
        # 读历史，算趋势
        prev = {}
        try:
            with open(hist_fp, encoding="utf-8") as f:
                prev = _json.load(f).get("platforms", {})
        except Exception:
            pass
        trends = {}
        for k, c in cur.items():
            pv = prev.get(k, {}).get("views", c["views"])
            trends[k] = c["views"] - pv
        # 写回历史（原子写）
        try:
            tmp = hist_fp + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump({"updated_at": now, "platforms": cur}, f)
            _os.replace(tmp, hist_fp)
        except Exception:
            pass
        # 过期小时数
        stale_hours = {}
        for k, p in platforms.items():
            sa = p.get("synced_at", "")
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(sa.replace("Z", "+00:00"))
                stale_hours[k] = round((now - dt.timestamp()) / 3600, 1)
            except Exception:
                stale_hours[k] = 999
        json_resp(self, {"ok": True, "updated_at": d.get("updated_at"),
                         "order": d.get("order", []),
                         "platforms": platforms,
                         "summary": {"total_views": total_views, "total_videos": total_videos,
                                     "platform_count": len(platforms)},
                         "trends": trends,
                         "stale_hours": stale_hours,
                         "login_warnings": [k for k,v in stale_hours.items() if v > 12]})

    def api_matrix_sync(self):
        """矩阵手动同步触发（2026-10-11 重做）：持久 job 文件状态机。
        POST → 建 job(status=running)，后台线程跑 YouTube 直连同步；
        matrix-sync-ondemand cron（5分钟）捡起 job，对 8 平台派浏览器抓取，
        逐平台更新 job 文件；全部完成 → status=done。
        按钮轮询 /api/matrix_sync/status，直到 done/timeout 才恢复。
        """
        import threading as _th
        job = _matrix_job_load()
        if job and job.get("status") == "running":
            try:
                started = datetime.strptime(job["started_at"][:19], "%Y-%m-%dT%H:%M:%S")
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - started).total_seconds()
            except Exception:
                age = 0
            if age < 1800:
                json_resp(self, {"ok": False, "error": "已有同步在进行中"})
                return
        platforms = {p: "pending" for p in
                     ["youtube", "douyin", "xiaohongshu", "kuaishou", "shipinhao",
                      "bilibili", "facebook", "tiktok", "x"]}
        job = {"status": "running",
               "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "triggered_by": "console",
               "platforms": platforms}
        _matrix_job_save(job)

        def _yt():
            import subprocess as _sp
            try:
                r = _sp.run(
                    ["python3", "/home/hatch/data/perpetua/distributor/platform_matrix_sync.py",
                     "--youtube"],
                    capture_output=True, timeout=120)
                st = "done" if r.returncode == 0 else "error"
            except Exception:
                st = "error"
            j = _matrix_job_load() or {}
            ps = j.get("platforms", {})
            ps["youtube"] = st
            j["platforms"] = ps
            _matrix_job_save(j)
            _matrix_job_maybe_done()

        _th.Thread(target=_yt, daemon=True).start()
        json_resp(self, {"ok": True, "status": "running"})

    def api_matrix_sync_status(self):
        """矩阵同步 job 状态查询（2026-10-11 新增）"""
        job = _matrix_job_load()
        if not job:
            json_resp(self, {"status": "idle", "platforms": {}})
            return
        if job.get("status") == "running":
            try:
                started = datetime.strptime(job["started_at"][:19], "%Y-%m-%dT%H:%M:%S")
                age = (datetime.now(timezone.utc).replace(tzinfo=None) - started).total_seconds()
            except Exception:
                age = 0
            if age > 1800:
                job["status"] = "timeout"
                _matrix_job_save(job)
        json_resp(self, {"status": job.get("status", "idle"),
                         "platforms": job.get("platforms", {}),
                         "started_at": job.get("started_at", "")})

    def api_imgcache(self):
        """本地图片缓存服务（2026-10-11）：platform_matrix.json 里 /api/imgcache/ 开头的
        URL 直接从 img_cache/ 目录读文件，不再依赖平台签名。"""
        import os as _os
        name = self.path.split("/api/imgcache/")[-1].split("?")[0].split("/")[0]
        if not name or ".." in name or not name.replace(".","").replace("_","").isalnum():
            self.send_response(400); self.end_headers(); return
        fp = _os.path.join("/home/hatch/data/perpetua/vps_console/img_cache", name)
        if not _os.path.isfile(fp):
            self.send_response(404); self.end_headers(); return
        ctype = "image/jpeg"
        if name.endswith(".webp"): ctype = "image/webp"
        elif name.endswith(".png"): ctype = "image/png"
        try:
            data = open(fp, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(500); self.end_headers()

    def api_matrix_img(self):
        """矩阵图片代理（2026-10-11）：绕过平台 CDN 防盗链/签名过期。
        用法：/api/matrix_img?url=<urlencode>"""
        import urllib.parse as _up
        qs = _up.urlparse(self.path).query
        params = _up.parse_qs(qs)
        raw = (params.get("url") or [""])[0]
        if not raw or not raw.startswith(("http://", "https://")):
            self.send_response(400); self.end_headers(); return
        # 只允许图片类域名，防 SSRF
        host = _up.urlparse(raw).hostname or ""
        allowed = ("douyinpic.com", "xhscdn.com", "xiaohongshu.com", "kwimgs.com", "yximgs.com",
                   "wsukwai.com", "kwaicdn.com",
                   "hdslb.com", "fbcdn.net", "twimg.com", "googleusercontent.com",
                   "ytimg.com", "weixin.qq.com", "qlogo.cn",
                   "tiktokcdn.com", "tiktokcdn-us.com", "ibytedtos.com")
        if not any(host.endswith(a) for a in allowed):
            self.send_response(403); self.end_headers(); return
        try:
            import urllib.request as _req
            r = _req.Request(raw, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bilibili.com/",
            })
            with _req.urlopen(r, timeout=15) as resp:
                data = resp.read(2 * 1024 * 1024)  # 最多 2MB
                ctype = resp.headers.get("Content-Type", "image/jpeg")
            self.send_response(200)
            self.send_header("Content-Type", ctype.split(";")[0])
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(502); self.end_headers()

    def api_matrix_reply(self, payload):
        """矩阵评论回复：只写草稿进 reply_gate 人工门，不直接发出。
        每天 09:00/21:00 批量报批；非 YouTube 平台即使批准也只记 manual，需人工去 App 发。"""
        import json as _json
        _sys.path.insert(0, "/home/hatch/data/youtube")
        try:
            import reply_gate
        except Exception as e:
            json_resp(self, {"ok": False, "error": "reply_gate 不可用: " + str(e)[:80]})
            return
        platform = (payload.get("platform") or "youtube").strip()
        comment_id = (payload.get("comment_id") or "").strip()
        draft = (payload.get("draft") or "").strip()
        if not comment_id or not draft:
            json_resp(self, {"ok": False, "error": "缺少 comment_id 或 draft"})
            return
        if len(draft) > 500:
            json_resp(self, {"ok": False, "error": "回复过长（>500字）"})
            return
        ok = reply_gate.add_draft(
            comment_id,
            payload.get("author", "")[:60],
            payload.get("text", "")[:120],
            draft,
            payload.get("video_id", ""))
        if ok:
            # 打上平台标记
            try:
                items = reply_gate._load_pending()
                for it in items:
                    if it.get("comment_id") == comment_id and it.get("status") == "pending":
                        it["platform"] = platform
                        it["source"] = "matrix"
                reply_gate._save_pending(items)
            except Exception:
                pass
        json_resp(self, {"ok": bool(ok),
                         "msg": "已入人工待批池" if ok else "重复或已处理",
                         "platform": platform,
                         "auto_post": platform == "youtube",
                         "note": "" if platform == "youtube" else "该平台暂不支持自动发出，批准后请人工去 App 回复"})

    def api_branding_requests(self):
        """资料修改申请列表（GET）。"""
        import json as _json
        fp = "/home/hatch/data/perpetua/distributor/branding_requests.json"
        try:
            items = _json.load(open(fp, encoding="utf-8"))
        except Exception:
            items = []
        # 不下发图片原数据，只给元信息
        out = []
        for r in reversed(items[-20:]):
            out.append({k: v for k, v in r.items()
                        if k not in ("avatar_data", "cover_data")})
            out[-1]["has_avatar"] = bool(r.get("avatar_data"))
            out[-1]["has_cover"] = bool(r.get("cover_data"))
        json_resp(self, {"ok": True, "requests": out})

    def api_branding_request(self, payload):
        """资料修改申请（POST）：只收申请进待批队列，不直接改任何平台。
        审批在聊天里由用户完成，批准后主 agent 经浏览器执行。"""
        import json as _json, time as _time, random as _rand
        fp = "/home/hatch/data/perpetua/distributor/branding_requests.json"
        platform = (payload.get("platform") or "").strip()
        desc = (payload.get("description") or "").strip()
        avatar_data = payload.get("avatar_data") or ""
        cover_data = payload.get("cover_data") or ""
        # v1.0.0 (2026-10-11)：平台集合从注册表动态读，不再硬编码
        _sys.path.insert(0, "/home/hatch/data/perpetua/distributor")
        from platform_registry import list_platforms as _lpl
        valid = set(_lpl())
        if platform not in valid:
            json_resp(self, {"ok": False, "error": "未知平台"})
            return
        if not desc and not avatar_data and not cover_data:
            json_resp(self, {"ok": False, "error": "至少改一项：简介/头像/封面"})
            return
        if len(desc) > 1000:
            json_resp(self, {"ok": False, "error": "简介过长（>1000字）"})
            return
        for label, data in (("头像", avatar_data), ("封面", cover_data)):
            if data and (not data.startswith("data:image/") or len(data) > 3_000_000):
                json_resp(self, {"ok": False, "error": f"{label}图片无效或超过约2MB"})
                return
        try:
            items = _json.load(open(fp, encoding="utf-8"))
        except Exception:
            items = []
        rid = "br-%s-%04d" % (_time.strftime("%Y%m%d%H%M%S"), _rand.randint(0, 9999))
        items.append({
            "id": rid,
            "platform": platform,
            "description": desc,
            "avatar_data": avatar_data,
            "avatar_name": (payload.get("avatar_name") or "")[:80],
            "cover_data": cover_data,
            "cover_name": (payload.get("cover_name") or "")[:80],
            "status": "pending",
            "notified": False,
            "created_at": _time.strftime("%Y-%m-%dT%H:%M:%S+08:00", _time.localtime()),
        })
        from atomic_json import atomic_write as _atomic_write
        _atomic_write(fp, items)
        json_resp(self, {"ok": True, "id": rid,
                         "msg": "申请已提交，待审批（审批通过后才会执行修改）"})

    def api_matrix_order(self, payload):
        """矩阵卡片排序（POST）：{"order": [8个平台key]}，全量校验后持久化。"""
        import json as _json
        _sys.path.insert(0, "/home/hatch/data/perpetua/distributor")
        from platform_registry import list_platforms as _lpl2
        order = payload.get("order")
        valid = set(_lpl2())
        if not (isinstance(order, list) and set(order) == valid
                and len(order) == len(valid)):
            json_resp(self, {"ok": False, "error": "order 必须恰好包含 8 个平台"})
            return
        fp = "/home/hatch/data/perpetua/distributor/platform_matrix.json"
        try:
            d = _json.load(open(fp, encoding="utf-8"))
        except Exception:
            json_resp(self, {"ok": False, "error": "矩阵文件读取失败"})
            return
        d["order"] = order
        from atomic_json import atomic_write as _atomic_write2
        _atomic_write2(fp, d)
        json_resp(self, {"ok": True})

    def api_comments(self):
        comments = fetch_real_comments(20)
        if comments is None:
            json_resp(self, {"ok": False, "comments": [], "sample": True,
                             "error": "YouTube API 不可用"})
            return
        unreplied = sum(1 for c in comments if not c.get("replied"))
        json_resp(self, {"ok": True, "comments": comments, "sample": False,
                         "total": len(comments), "unreplied": unreplied,
                         "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    def api_comment_reply(self, comment_id, text):
        if not comment_id:
            json_resp(self, {"ok": False, "error": "缺少 comment_id"}, 400)
            return
        result = reply_to_comment(comment_id, text or "")
        if result.get("ok"):
            # 回复成功后清缓存，下次拉取刷新状态
            _real_comments_cache["at"] = 0
            _real_comments_cache["data"] = None
        json_resp(self, result)

    # ---- 流水线 ----
    def api_pipeline(self, tenant_id):
        now = time.time()
        if _pipeline_cache["data"] and now - _pipeline_cache["at"] < 60:
            cached = _pipeline_cache["data"]
        else:
            raw = read_json_file(PIPELINE_FILE) or {"runs": []}
            cached = raw
            _pipeline_cache["data"] = raw
            _pipeline_cache["at"] = now
        runs = cached.get("runs", [])
        # 按 tenant+stage 取最新
        latest = {}
        for r in runs:
            if r.get("tenant_id", "default") != tenant_id:
                continue
            k = r["stage"]
            if k not in latest or (r.get("at") or "") > (latest[k].get("at") or ""):
                latest[k] = r
        # 各阶段期望频率（分钟）：超过 2 倍周期未运行才算 STALE
        # 2026-10-07 按实际调度频率判，不再一刀切 5 分钟
        STAGE_FREQ = {
            "trend": 60,      # 每小时
            "select": 480,    # 每天 3 档，约 8 小时
            "review": 30,     # 每 30 分钟
            "generate": 600,  # 每天 3 档
            "qc": 20,         # 每 20 分钟 collect
            "publish": 1440,  # 每天 3 条，不固定
            "postop": 360,    # 每 6 小时
            "evolve": 1440,   # 每天
        }
        stages = []
        for sid, cname, ename, is_ai in STAGES:
            info = latest.get(sid, {})
            at = info.get("at", "")
            has = bool(info.get("stage"))
            freshness = "offline"
            if has:
                try:
                    # 时间戳可能是 UTC（带 Z）或本地时间，统一按 UTC 解析
                    ats = at[:19]
                    if at[19:20] == 'Z' or '+' in at[19:]:
                        # UTC 时间
                        dt = datetime.strptime(ats, "%Y-%m-%dT%H:%M:%S")
                        ts = dt.replace(tzinfo=timezone.utc).timestamp()
                    else:
                        ts = time.mktime(time.strptime(ats, "%Y-%m-%dT%H:%M:%S"))
                    age_min = (now - ts) / 60
                    freq = STAGE_FREQ.get(sid, 60)
                    # 1 倍周期内=live，2 倍周期内=stale，超过=offline（可能挂了）
                    if age_min <= freq:
                        freshness = "live"
                    elif age_min <= freq * 2:
                        freshness = "stale"
                    else:
                        freshness = "offline"
                except (ValueError, TypeError):
                    freshness = "stale"
            stages.append({
                "id": sid, "name": cname, "nameEn": ename, "ai": is_ai,
                "status": info.get("status", "idle"),
                "detail": info.get("detail", ""),
                "count": info.get("count", 0),
                "at": at, "freshness": freshness,
            })
        # 整体状态
        overall = "offline"
        if any(s["freshness"] == "live" for s in stages):
            overall = "live"
        elif any(s["freshness"] == "stale" for s in stages):
            overall = "stale"
        json_resp(self, {"stages": stages, "overall": overall, "tenant_id": tenant_id})

    # ---- ViralLoop OA ----
    def api_oa_org(self):
        """组织架构 + 实时状态"""
        org = {
            "ceo": {"name": "cgb2026", "title": "CEO", "status": "active"},
            "chief_of_staff": {"name": "Dash", "title": "幕僚长", "status": "active"},
            "departments": [
                {"id": "content", "name": "内容部", "roles": [
                    {"id": "trend", "name": "趋势研究员", "status": self._stage_status("trend")},
                    {"id": "select", "name": "选题策略师", "status": self._stage_status("select"), "skills": ["内容指导", "爆款钩子", "内容重塑"]},
                    {"id": "review", "name": "审查员", "status": self._stage_status("review"), "note": "唯一有权批准内容", "skills": ["品牌简报", "贴文评分"]},
                    {"id": "generate", "name": "制片人", "status": self._stage_status("generate"), "skills": ["文案撰写"]},
                ]},
                {"id": "qc", "name": "质检部", "roles": [
                    {"id": "qc", "name": "QC 质检员", "status": self._stage_status("qc")},
                ]},
                {"id": "publish", "name": "发布部", "roles": [
                    {"id": "publish", "name": "发布者", "status": self._stage_status("publish"), "note": "需人类授权"},
                ]},
                {"id": "ops", "name": "运营部", "roles": [
                    {"id": "postop", "name": "运营经理", "status": self._stage_status("postop"), "skills": ["发帖排期"]},
                    {"id": "evolve", "name": "数据分析师", "status": self._stage_status("evolve")},
                ]},
                {"id": "audit", "name": "审计部", "roles": [
                    {"id": "audit", "name": "审计员", "status": "active"},
                ]},
                {"id": "marketing", "name": "市场部", "roles": [
                    {"id": "distribute", "name": "分发专员", "status": "idle", "note": "多平台分发矩阵", "skills": ["内容重塑"]},
                    {"id": "bizdev", "name": "商务拓展", "status": "idle", "note": "品牌合作/渠道"},
                ]},
                {"id": "sales", "name": "销售部", "roles": [
                    {"id": "leads", "name": "线索挖掘员", "status": "idle", "note": "商机监控+线索评分"},
                    {"id": "presales", "name": "售前顾问", "status": "idle", "note": "方案报价需人类确认"},
                    {"id": "success", "name": "客户成功", "status": "idle", "note": "交付/回款/复购"},
                ]},
            ],
            "external": {"name": "Marvis", "title": "外部协作", "status": "restricted", "note": "已切断直接API"},
        }
        json_resp(self, org)

    def _stage_status(self, stage_id):
        """从 pipeline_runs 获取阶段状态"""
        try:
            raw = read_json_file(PIPELINE_FILE) or {"runs": []}
            for r in reversed(raw.get("runs", [])):
                if r.get("stage") == stage_id:
                    return r.get("status", "idle")
        except Exception:
            pass
        return "idle"

    def api_oa_approvals(self):
        """待审批中心"""
        approvals = []
        # 待终审视频
        try:
            a = read_json_file(os.path.join(DATA, "perpetua", "awaiting_approval.json")) or []
            items = a if isinstance(a, list) else a.get("items", [])
            for it in items:
                st = it.get("status")
                if st in ("approved", "rejected"):
                    continue
                if it.get("type") == "auto_retitle":
                    approvals.append({
                        "type": "retitle",
                        "title": it.get("title", ""),
                        "video_id": it.get("video_id", ""),
                        "reason": it.get("reason", ""),
                        "created": it.get("created", ""),
                    })
                elif it.get("video_file"):
                    approvals.append({
                        "type": "video",
                        "title": it.get("title", ""),
                        "topic": it.get("topic", ""),
                        "created": it.get("created_at", ""),
                    })
        except Exception:
            pass
        # Ask Studio 待回答
        try:
            q = read_json_file(os.path.join(DATA, "ask_studio", "queue.json")) or {}
            for p in q.get("pending", []):
                approvals.append({
                    "type": "ask_studio",
                    "title": p.get("question", "")[:50],
                    "id": p.get("id", ""),
                    "created": p.get("created", ""),
                })
        except Exception:
            pass
        json_resp(self, {"approvals": approvals, "count": len(approvals)})

    def api_oa_departments(self):
        """部门 KPI"""
        depts = {
            "content": {"name": "内容部", "kpis": {}},
            "qc": {"name": "质检部", "kpis": {}},
            "publish": {"name": "发布部", "kpis": {}},
            "ops": {"name": "运营部", "kpis": {}},
            "audit": {"name": "审计部", "kpis": {}},
        }
        # 内容部：今日选题数
        try:
            q = queue_db.pipeline_load()  # D20261011-001 P1: 已迁 SQLite
            items = q if isinstance(q, list) else q.get("items", [])
            depts["content"]["kpis"]["topics_today"] = len([i for i in items if "2026-10-07" in str(i.get("created_at", ""))])
        except Exception:
            pass
        # 审计部：违规数（从 bypass 日志）
        try:
            import glob
            logs = glob.glob(os.path.join(DATA, "perpetua", "audit", "*.log"))
            depts["audit"]["kpis"]["violations"] = len(logs)
        except Exception:
            pass
        json_resp(self, {"departments": depts})

    def _oa_decide_body(self, body, approved):
        """CEO 审批：批准/驳回待终审视频（body 已解析）"""
        title = body.get('title', '')
        fp = os.path.join(DATA, "perpetua", "awaiting_approval.json")
        try:
            items = read_json_file(fp) or []
            if isinstance(items, dict):
                items = items.get('items', [])
            found = None
            for it in items:
                if it.get('title') == title or it.get('topic') == title:
                    found = it
                    break
            if not found:
                json_resp(self, {"ok": False, "error": "not found"})
                return
            if approved:
                found['human_approved'] = True
                found['approved_at'] = datetime.now().isoformat()
                found['status'] = 'approved'
                # 写入决策日志
                log_fp = os.path.join(DATA, "perpetua", "approval_decisions.jsonl")
                with open(log_fp, 'a') as lf:
                    lf.write(json.dumps({"title": title, "decision": "approved",
                        "at": datetime.now().isoformat(), "by": "CEO"}) + "\n")
            else:
                found['human_approved'] = False
                found['status'] = 'rejected'
                found['rejected_at'] = datetime.now().isoformat()
            write_json_file(fp, items)
            json_resp(self, {"ok": True, "decision": "approved" if approved else "rejected"})
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)})

    def api_oa_audit(self):
        """审计日志：从真实文件读取"""
        events = []
        # 1. 审批决策记录
        try:
            fp = os.path.join(DATA, "perpetua", "approval_decisions.jsonl")
            if os.path.exists(fp):
                with open(fp) as f:
                    for line in f:
                        line=line.strip()
                        if line:
                            d=json.loads(line)
                            events.append({"type":"decision","title":f"{'批准' if d.get('decision')=='approved' else '驳回'}：{d.get('title','')[:40]}","at":d.get('at','')[:19],"level":"info"})
        except Exception:
            pass
        # 2. bypass 审计（从 inbox notices，经统一网关）
        try:
            import inbox as inbox_gw2
            ib = inbox_gw2.load()
            for n in ib.get("notices",[]):
                t=n.get("type","")
                if t in ("bypass_alert","marvis_bypass","zero_view_alert","dead_state_alert"):
                    events.append({"type":"violation","title":n.get("title","")[:60],"at":n.get("created","")[:19],"level":"urgent"})
        except Exception:
            pass
        # 3. 上传审计记录
        try:
            fp=os.path.join(DATA,"youtube","marvis_upload_audit.json")
            if os.path.exists(fp):
                d=json.load(open(fp))
                for a in d.get("alerts",[])[-10:]:
                    events.append({"type":"audit","title":str(a)[:80],"at":"","level":"warn"})
        except Exception:
            pass
        events=sorted(events,key=lambda x:x.get("at",""),reverse=True)[:30]
        json_resp(self,{"events":events,"count":len(events)})

    def api_oa_videos(self):
        """视频库：从 all_videos.json 读取"""
        try:
            fp=os.path.join(DATA,"youtube","all_videos.json")
            d=json.load(open(fp)) if os.path.exists(fp) else []
            videos=sorted(d,key=lambda x:x.get("published",""),reverse=True)[:30]
            json_resp(self,{"videos":videos,"count":len(d)})
        except Exception as e:
            json_resp(self,{"videos":[],"count":0,"error":str(e)[:100]})

    def api_oa_marvis(self):
        """Marvis 协作状态"""
        info={"status":"unknown","last_pickup":"","pending_count":0,"violations":0}
        try:
            import inbox as inbox_gw3
            ib=inbox_gw3.load()
            pp=ib.get("pending_pickup",[])
            info["pending_count"]=len(pp)
            if pp:
                info["last_pickup"]=str(pp[-1].get("created",""))[:19]
            # 取货延迟
            from datetime import datetime,timezone
            now=datetime.now(timezone.utc)
            delays=[]
            for p in pp:
                try:
                    c=p.get("created","")
                    if c:
                        dt=datetime.fromisoformat(c.replace("Z","+00:00"))
                        delays.append((now-dt).total_seconds()/3600)
                except Exception:
                    pass
            info["max_delay_h"]=round(max(delays),1) if delays else 0
            info["status"]="delayed" if info["max_delay_h"]>2 else "active" if pp else "idle"
        except Exception:
            pass
        # 违规数
        try:
            fp=os.path.join(DATA,"youtube","marvis_upload_audit.json")
            if os.path.exists(fp):
                d=json.load(open(fp))
                info["violations"]=len(d.get("alerts",[]))
        except Exception:
            pass
        json_resp(self,info)

    def api_oa_stage_logs(self):
        """某阶段最近 10 次运行日志"""
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        stage = (q.get("stage") or [""])[0]
        try:
            fp = os.path.join(DATA, "perpetua", "pipeline_runs.json")
            d = json.load(open(fp)) if os.path.exists(fp) else {}
            runs = d.get("runs", []) if isinstance(d, dict) else []
            out = [r for r in runs if r.get("stage") == stage][-10:]
            out = list(reversed(out))
            json_resp(self, {"stage": stage, "logs": out, "count": len(out)})
        except Exception as e:
            json_resp(self, {"stage": stage, "logs": [], "count": 0, "error": str(e)[:100]})

    def api_oa_charts(self):
        """图表数据：日产量 / QC 通过率 / 播放量趋势"""
        try:
            from collections import Counter
            fp = os.path.join(DATA, "perpetua", "pipeline_runs.json")
            d = json.load(open(fp)) if os.path.exists(fp) else {}
            runs = d.get("runs", []) if isinstance(d, dict) else []
            # 日产量：按天统计 select 阶段的 count
            daily = Counter()
            qc_ok = qc_total = 0
            for r in runs:
                day = str(r.get("at", ""))[:10]
                if r.get("stage") == "select" and r.get("status") == "ok":
                    daily[day] += r.get("count", 0) or 0
                if r.get("stage") == "qc":
                    qc_total += 1
                    if r.get("status") == "ok":
                        qc_ok += 1
            # 播放量趋势：近 30 天发布的视频
            views_trend = []
            vfp = os.path.join(DATA, "youtube", "all_videos.json")
            if os.path.exists(vfp):
                vs = json.load(open(vfp))
                vd = Counter()
                for v in vs:
                    day = str(v.get("published", ""))[:10]
                    if day >= "2026-09-07":
                        vd[day] += v.get("views", 0) or 0
                views_trend = [{"day": k, "views": vd[k]} for k in sorted(vd)]
            json_resp(self, {
                "daily_output": [{"day": k, "count": daily[k]} for k in sorted(daily)[-14:]],
                "qc_rate": round(qc_ok / qc_total * 100, 1) if qc_total else 0,
                "qc_total": qc_total,
                "views_trend": views_trend[-14:],
            })
        except Exception as e:
            json_resp(self, {"error": str(e)[:100]})

    # ---- 内容工具箱（7 项技能） ----
    def api_oa_content(self, tool, payload):
        """内容工具箱：brand-briefing / content-guide / copywriter /
        viral-hooks / post-score / scheduler / repurpose"""
        try:
            import content_tools as ct
            if tool == "brief":
                json_resp(self, ct.brand_briefing())
            elif tool == "guide":
                json_resp(self, ct.content_guide(payload.get("topic", "")))
            elif tool == "copy":
                json_resp(self, ct.copywriter(payload.get("topic", ""), payload.get("hook", "")))
            elif tool == "hooks":
                json_resp(self, ct.viral_hooks(payload.get("topic", ""), payload.get("device", "")))
            elif tool == "score":
                json_resp(self, ct.post_score(payload.get("title", ""), payload.get("script", "")))
            elif tool == "schedule":
                json_resp(self, ct.scheduler(payload.get("topics", [])))
            elif tool == "repurpose":
                json_resp(self, ct.repurpose(payload.get("video_id", ""), payload.get("topic", "")))
            else:
                json_resp(self, {"error": "unknown tool"}, 400)
        except Exception as e:
            json_resp(self, {"error": str(e)[:200]})

    # ---- 增长模块（销售管道 / 分发矩阵 / 变现看板） ----
    def api_oa_growth(self, action, payload):
        try:
            import growth_tools as gt
            if action == "leads_list":
                json_resp(self, gt.leads_list())
            elif action == "lead_upsert":
                json_resp(self, gt.lead_upsert(payload))
            elif action == "dist_list":
                json_resp(self, gt.dist_list())
            elif action == "dist_add":
                json_resp(self, gt.dist_add(payload))
            elif action == "dist_update":
                json_resp(self, gt.dist_update(payload))
            elif action == "revenue":
                json_resp(self, gt.revenue_summary())
            elif action == "revenue_add":
                json_resp(self, gt.revenue_add(payload))
            else:
                json_resp(self, {"error": "unknown action"}, 400)
        except Exception as e:
            json_resp(self, {"error": str(e)[:200]})

    # ---- 日志 ----
    def api_logs(self, source, lines):
        result = {}
        sources = LOG_SOURCES if source == "all" else {source: LOG_SOURCES.get(source, "")}
        for sid, path in sources.items():
            if path:
                result[sid] = tail_file(path, lines)
        json_resp(self, {"logs": result, "at": time.strftime("%H:%M:%S")})

    # ---- 租户 ----
    def api_tenants(self):
        data = read_json_file(os.path.join(DATA, "perpetua", "tenants", "registry.json"))
        json_resp(self, data or {"tenants": {}})

    # ---- 作战指挥中心：360 全息实时聚合（2026-10-16）----
    def _cmd_read_json(self, path, default=None):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _cmd_pgrep(self, pat):
        try:
            out = subprocess.run(["pgrep", "-f", "--", pat],
                                 capture_output=True, timeout=4)
            return out.returncode == 0
        except Exception:
            return False

    def _cmd_tail(self, path, n=15):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            return [l.rstrip("\n") for l in lines[-n:] if l.strip()]
        except Exception:
            return []

    def _cmd_http_ok(self, url, timeout=6):
        """轻量 HTTP 存活检查（dispatcher 在 VPS 上，走 HTTP 不走 pgrep）"""
        try:
            out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                  "-m", str(timeout), url],
                                 capture_output=True, text=True, timeout=timeout + 2)
            return out.stdout.strip() not in ("", "000")
        except Exception:
            return False

    # ---- 360° v2：六个扩展模块（全部只读，禁止写入/修复/触发） ----
    def _cmd_age_h(self, ts):
        """ISO 时间戳 → 距今小时数；解析失败返回 None"""
        if not ts:
            return None
        try:
            s = str(ts).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        except Exception:
            return None

    def _cmd_fmt_age(self, h):
        if h is None:
            return "未知"
        if h < 1:
            return f"{h * 60:.0f}分钟"
        if h < 48:
            return f"{h:.1f}小时"
        return f"{h / 24:.1f}天"

    def _mod_fleet(self):
        """1. 舰队视图：nanoMuse MCP/主控制台/Dispatcher 存活探针 + 外部智能体取货新鲜度"""
        items = []
        mcp_ok = self._cmd_http_ok("http://127.0.0.1:8735/health", timeout=4)
        items.append({"t": "nanoMuse MCP :8735（热备指挥官）", "s": "在线" if mcp_ok else "离线"})
        con_ok = self._cmd_http_ok("http://127.0.0.1:18739/", timeout=4)
        items.append({"t": "nanoMuse 主控制台 :18739", "s": "在线" if con_ok else "离线"})
        disp_ok = self._cmd_http_ok("http://192.166.82.123:8740/", timeout=6)
        items.append({"t": "Dispatcher :8740（VPS，主 Muse 通道）", "s": "在线" if disp_ok else "离线"})
        items.append({"t": "主 agent（本控制台服务）", "s": "在线"})
        ib = self._cmd_read_json(os.path.join(DATA, "collab", "inbox.json"), {})
        pend = ib.get("pending_pickup", []) if isinstance(ib, dict) else []
        picked = ib.get("picked_up", []) if isinstance(ib, dict) else []
        last_age = None
        if picked and isinstance(picked[-1], dict):
            last = picked[-1]
            last_age = self._cmd_age_h(last.get("picked_at") or last.get("created"))
        if last_age is None:
            ext_s = "unknown"
        elif last_age > 24:
            ext_s = "STALE " + self._cmd_fmt_age(last_age) + "前"
        else:
            ext_s = "在线（" + self._cmd_fmt_age(last_age) + "前取货）"
        items.append({"t": f"外部智能体（Marvis 取货，待取 {len(pend)}）", "s": ext_s})
        n_off = sum(1 for i in items if i["s"] == "离线")
        stale_ext = last_age is not None and last_age > 24
        status = "bad" if n_off >= 2 else ("warn" if (n_off == 1 or stale_ext) else "ok")
        return {"id": "fleet", "name": "智能体舰队", "status": status,
                "summary": f"{len(items) - n_off}/{len(items)} 在线" + (f" · 外部取货{self._cmd_fmt_age(last_age)}前" if last_age is not None else ""),
                "detail": "只读探针：127.0.0.1:8735/health、127.0.0.1:18739、192.166.82.123:8740 存活 + collab/inbox.json 取货新鲜度",
                "items": items}

    def _mod_quota(self):
        """2. 生成后端额度：dispatch_health 探针口径的轻量复刻（只读，不提交生成任务）。
        geminigen 完整探针太重（~60s 浏览器 eval），取最近一次生命线巡检缓存并标注年龄。"""
        import glob as _glob
        items = []
        states = {}  # name -> (ok|warn|bad, note)
        # 最近一次 dispatch-lifeline-watch 缓存
        logp = os.path.join(os.path.expanduser("~"), "workspace", "goals", "karenvsai",
                            "hidden_files", "dispatch-health", "run.log")
        cache_age = None
        cached = {}
        try:
            lines = self._cmd_tail(logp, 40)
            hi = -1
            for i, l in enumerate(lines):
                if "dispatch-lifeline-watch" in l:
                    hi = i
            if hi >= 0:
                m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", lines[hi])
                if m:
                    cache_age = self._cmd_age_h(m.group(1).replace(" ", "T") + ":00+08:00")
                for l in lines[hi + 1:]:
                    m2 = re.match(r"\s{2}(\S[^:]*):\s*(OK|SUSPECT|CONFIRMED)\b\s*(.*)", l)
                    if m2:
                        cached[m2.group(1).strip().lower()] = (m2.group(2), m2.group(3).strip()[:70])
        except Exception:
            pass
        age_note = ("巡检缓存" + self._cmd_fmt_age(cache_age) + "前") if cache_age is not None else "无巡检缓存"

        def get_cached(*keys):
            for k in keys:
                if k in cached:
                    return cached[k]
            return ("UNKNOWN", "无记录")

        # dispatcher：实时探针
        d_ok = self._cmd_http_ok("http://192.166.82.123:8740/mcp", timeout=6)
        states["dispatcher :8740"] = ("ok", "实时探针 HTTP 有响应") if d_ok else ("bad", "实时探针不可达")
        # mcp-b 队列：缓存
        qv, qn = get_cached("queue mcp-b", "queue")
        states["mcp-b 队列"] = ({"OK": "ok"}.get(qv, "warn"), age_note + " " + qn)
        # geminigen：缓存（重探针）
        gv, gn = get_cached("geminigen")
        if gv == "OK":
            states["geminigen（免费档）"] = ("ok", age_note + " " + gn)
        elif gv in ("CONFIRMED",):
            states["geminigen（免费档）"] = ("bad", age_note + " " + gn)
        else:
            states["geminigen（免费档）"] = ("warn", age_note + " " + gn)
        # h3：实时（配置文件，无地址即 SUSPECT）
        h3_addr = os.environ.get("H3_ADDR", "")
        if not h3_addr:
            for cfg in ["/home/hatch/data/perpetua/h3_config.json", "/home/hatch/data/h3_addr.txt"]:
                try:
                    with open(cfg, encoding="utf-8") as f:
                        h3_addr = f.read().strip().split()[0]
                        if h3_addr:
                            break
                except Exception:
                    pass
        states["H3 备链"] = ("warn", "未配置地址（已知）") if not h3_addr else ("ok", "已配置，实时探针略")
        # vids：实时（日期口径）
        try:
            from datetime import date as _date
            states["vids"] = ("warn", "配额耗尽至 2026-11-01（已知）") if _date.today() < _date(2026, 11, 1) else ("warn", "恢复日期已到，需重测")
        except Exception:
            states["vids"] = ("warn", "日期口径异常")
        # builtin：实时（24h 出片）
        try:
            now = time.time()
            recent = [f for f in _glob.glob("/home/hatch/data/perpetua/videos/job-*.mp4")
                      if now - os.path.getmtime(f) < 24 * 3600]
            states["builtin"] = ("ok", f"24h 内出片 {os.path.basename(sorted(recent)[-1])}") if recent else ("warn", "24h 内无出片记录")
        except Exception:
            states["builtin"] = ("warn", "目录不可读")
        for name, (st, note) in states.items():
            items.append({"t": name, "s": ({"ok": "OK", "warn": "SUSPECT", "bad": "DOWN"}[st]) + " · " + note})
        worst = "bad" if any(s == "bad" for _, (s, _) in states.items()) else ("warn" if any(s == "warn" for _, (s, _) in states.items()) else "ok")
        return {"id": "quota", "name": "生成后端额度", "status": worst,
                "summary": " · ".join(f"{k.split()[0]}:{v}" for k, (v, _) in states.items()),
                "detail": "复用 dispatch_health.py 探针口径；geminigen/mcp-b 取生命线巡检缓存（重探针），其余实时；只读，未提交任何生成任务",
                "items": items}

    def _mod_council(self):
        """3. 四脑议会：brain_council/synthesis.md × MEMORY.md 议会决策登记处"""
        bc = os.path.join(DATA, "brain_council")
        try:
            memtxt = open(os.path.join(os.path.expanduser("~"), "MEMORY.md"), encoding="utf-8").read()
        except Exception:
            memtxt = ""
        dirs = []
        try:
            dirs = sorted([d for d in os.listdir(bc)
                           if d.startswith("council-") and os.path.isdir(os.path.join(bc, d))],
                          reverse=True)[:3]
        except Exception:
            pass
        items = []
        worst = "ok"
        for d in dirs:
            title, draft = d, False
            try:
                with open(os.path.join(bc, d, "synthesis.md"), encoding="utf-8") as f:
                    head = [l.rstrip("\n") for l in f.readlines()[:25]]
                for l in head:
                    if l.startswith("#"):
                        title = l.lstrip("# ").strip()[:42]
                        break
                blob = "\n".join(head)
                draft = ("草案" in blob) or ("待拍板" in blob)
            except Exception:
                title = d + "（无 synthesis）"
            if d in memtxt and not draft:
                lab = "已拍板"
            elif draft:
                lab, worst = "草案", "warn"
            else:
                lab, worst = "待拍板", "warn"
            items.append({"t": title, "s": lab})
        if not items:
            return {"id": "council", "name": "四脑议会", "status": "unknown",
                    "summary": "无议会目录", "detail": "brain_council 下无 council-* 目录", "items": []}
        return {"id": "council", "name": "四脑议会", "status": worst,
                "summary": "最近议会：" + "、".join(i["s"] for i in items),
                "detail": "brain_council/*/synthesis.md 标题 × MEMORY.md 顶部议会决策登记处（只读）",
                "items": items}

    def _mod_anomaly(self):
        """4. 异常治理：只展示数字。D20261015-007 冻结中，不做任何自动修复/降级。"""
        al = self._cmd_read_json(os.path.join(DATA, "perpetua", "anomaly_ledger.json"), [])
        items_all = al if isinstance(al, list) else al.get("items", [])
        open_ = [i for i in items_all if isinstance(i, dict) and not i.get("resolved")]
        byc = {}
        for i in open_:
            byc[i.get("checker", "?")] = byc.get(i.get("checker", "?"), 0) + 1
        esc = self._cmd_read_json(os.path.join(DATA, "perpetua", "escalation_inbox.json"), [])
        esc_items = esc if isinstance(esc, list) else esc.get("items", [])
        pend = [e for e in esc_items if isinstance(e, dict) and not e.get("ack_by")]
        p1 = [e for e in pend if e.get("severity") == "P1"]
        items = [{"t": f"SUSPECT:{c}", "s": f"{n} 条"} for c, n in sorted(byc.items(), key=lambda x: -x[1])]
        items.append({"t": "升级待 ack", "s": f"{len(pend)} 条"})
        items.append({"t": "其中 P1 分页", "s": f"{len(p1)} 条"})
        status = "ok" if not open_ else ("bad" if len(p1) >= 20 else "warn")
        return {"id": "anomaly", "name": "异常治理", "status": status,
                "summary": f"未解决 {len(open_)} · 待 ack {len(pend)} · P1 {len(p1)}",
                "detail": "anomaly_ledger.json（按 checker 分组）+ escalation_inbox.json（只展示；D20261015-007 冻结中，不做自动修复/降级）",
                "items": items}

    def _mod_cron(self):
        """5. cron 舰队：cron.list/cron.runs 快照（只读；STALE>30min 标 unknown）"""
        snap = self._cmd_read_json(os.path.join(BASE_DIR, "cron_fleet_snapshot.json"), {})
        if not snap:
            return {"id": "cron", "name": "cron 舰队", "status": "unknown",
                    "summary": "无快照", "detail": "cron_fleet_snapshot.json 缺失", "items": []}
        age = self._cmd_age_h(snap.get("captured_at"))
        stale = age is None or age > 0.5
        chain = snap.get("key_chain", [])
        items = [{"t": "总数/启用/禁用",
                  "s": f"{snap.get('schedule_total')}/{snap.get('enabled_total')}/{len(snap.get('disabled', []))}"}]
        bad_chain = 0
        for j in chain:
            ok = j.get("status") == "succeeded"
            bad_chain += 0 if ok else 1
            items.append({"t": j.get("id", "?"),
                          "s": ("OK " + str(j.get("last_run", ""))[:16]) if ok else ("异常:" + str(j.get("status", "?")))})
        for r in snap.get("recent_non_ok", [])[:3]:
            items.append({"t": "跳过/" + str(r.get("job_id", "?")), "s": str(r.get("status", "?"))})
        dis = snap.get("disabled", [])
        if dis:
            items.append({"t": "已禁用", "s": "、".join(dis[:6])})
        status = "unknown" if stale else ("warn" if bad_chain else "ok")
        return {"id": "cron", "name": "cron 舰队", "status": status,
                "summary": f"{snap.get('enabled_total')}/{snap.get('schedule_total')} 启用 · 关键链路 {len(chain) - bad_chain}/{len(chain)} 正常" + (f" · 快照{self._cmd_fmt_age(age)}前" if age is not None else ""),
                "detail": "cron.list/cron.runs 快照（只读；STALE>30min 标 unknown，需定时刷新快照以保持实时）",
                "items": items}

    def _mod_pubtruth(self):
        """6. 发布真相源：private_queue.json × YouTube Data API videos.list 实拉 privacyStatus。
        10min 内存缓存（前端每 5s 轮询，不缓存会烧光 API 配额）；只读查询，不做任何翻转。"""
        import threading as _th
        q = self._cmd_read_json(os.path.join(DATA, "youtube", "private_queue.json"), [])
        vids = q if isinstance(q, list) else []
        targets = [v for v in vids if isinstance(v, dict) and v.get("status") == "waiting"][:3]
        recent_pub = [v for v in vids if isinstance(v, dict) and v.get("status") in ("published", "public")][:2]
        targets = targets + [v for v in recent_pub if v not in targets]
        now = time.time()
        with _PUBTRUTH_LOCK:
            fresh = (now - _PUBTRUTH_CACHE["at"] < 600) and bool(_PUBTRUTH_CACHE["data"])
            cache_at = _PUBTRUTH_CACHE["at"]
        results = dict(_PUBTRUTH_CACHE["data"]) if fresh else {}
        err = _PUBTRUTH_CACHE.get("err", "")
        if not fresh and targets:
            box = {}

            def _worker():
                try:
                    import sys as _s
                    if "/home/hatch/data/youtube" not in _s.path:
                        _s.path.insert(0, "/home/hatch/data/youtube")
                    from yt_upload import get_status
                    for v in targets:
                        vid = v.get("video_id")
                        try:
                            box[vid] = get_status(vid)
                        except BaseException as e:
                            # BaseException：连 Exception 都没接住的也如实记录，不静默丢
                            import sys as _se
                            print(f"[pubtruth] get_status({vid}) raised {type(e).__name__}: {e}",
                                  file=_se.stderr)
                            box[vid] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
                except Exception as e:
                    box["_fatal"] = str(e)[:100]

            th = _th.Thread(target=_worker, daemon=True)
            th.start()
            th.join(10)
            if th.is_alive():
                err = "API 查询超时(10s)，本次显示 unknown"
            else:
                err = box.pop("_fatal", "")
            results = box
            with _PUBTRUTH_LOCK:
                # 超时则只缓存 60s（很快重试），成功则缓存 10min
                _PUBTRUTH_CACHE["at"] = now if not th.is_alive() else now - 540
                _PUBTRUTH_CACHE["data"] = dict(box)
                _PUBTRUTH_CACHE["err"] = err
            cache_at = now
        items = []
        worst = "ok"
        for v in targets:
            vid = v.get("video_id", "?")
            r = results.get(vid, {})
            priv = r.get("privacyStatus") if isinstance(r, dict) else None
            slot = v.get("slot") or (str(v.get("scheduled_at", ""))[:16])
            qs = v.get("status")
            if priv:
                src = "API 实拉 " + time.strftime("%H:%M", time.localtime(cache_at))
                expect = "private" if qs == "waiting" else "public"
                match = (priv == expect)
                s = f"{priv} ✓" if match else f"{priv} ✗应为{expect}"
                if not match:
                    worst = "warn"
            else:
                src = "unknown"
                s = "unknown" + (f"({r.get('error', '')[:30]})" if isinstance(r, dict) and r.get("error") else "")
                worst = "warn"
            items.append({"t": (v.get("title") or vid)[:28], "s": f"{s} · 档{slot} · 真相源={src}",
                          "vid": vid, "qstatus": qs})
        if not targets:
            items.append({"t": "队列为空", "s": "无 waiting 视频"})
        return {"id": "pubtruth", "name": "发布真相源", "status": worst,
                "summary": f"{len(targets)} 条已核验" + (f" · {err}" if err else ""),
                "detail": "private_queue.json × YouTube Data API videos.list 实拉 privacyStatus（10min 内存缓存，不烧配额；只读）",
                "items": items}

    def api_command_live(self):
        """GET /api/command/live — 作战指挥中心全息快照（只读聚合，<2s）"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        out = {"ok": True, "at": now}
        D = DATA
        # ---- 1. 八阶段管线 ----
        stages = []
        try:
            pq = self._cmd_read_json(os.path.join(D, "perpetua", "pipeline_queue.json"), [])
            terminal = {"teaser_failed", "retired", "review_failed", "archived",
                        "teaser_published", "uploaded"}
            active = [i for i in pq if i.get("status") not in terminal]
            stages.append({"id": "topics", "name": "选题池", "count": len(active),
                           "detail": f"{len(pq)} 候选中 {len(active)} 流转中",
                           "items": [{"t": i.get("topic", "?")[:28], "s": i.get("status")}
                                     for i in active[:6]]})
        except Exception as e:
            stages.append({"id": "topics", "name": "选题池", "count": -1, "detail": str(e)[:80], "items": []})
        try:
            asq = self._cmd_read_json(os.path.join(D, "ask_studio", "queue.json"), {})
            pend = asq.get("pending", []) if isinstance(asq, dict) else []
            iq = self._cmd_read_json(os.path.join(D, "ask_studio", "instant_queue.json"), {})
            iitems = iq.get("items", iq.get("pending", [])) if isinstance(iq, dict) else []
            # 只计真正待回答：排除 answered/superseded（2026-10-16 修：曾把 42 条已回答误计为待回答）
            ipend = [i for i in iitems if isinstance(i, dict) and i.get("status") not in ("answered", "superseded")]
            pend = [p for p in pend if isinstance(p, dict) and p.get("status") == "pending"] if isinstance(pend, list) else []
            n_pend = len(pend) + len(ipend)
            stages.append({"id": "review", "name": "Ask Studio 评审", "count": n_pend,
                           "detail": f"待回答 {n_pend}",
                           "items": [{"t": (p.get("question") or p.get("topic") or "?")[:28], "s": "pending"}
                                     for p in (pend + ipend)[:4]]})
        except Exception as e:
            stages.append({"id": "review", "name": "Ask Studio 评审", "count": -1, "detail": str(e)[:80], "items": []})
        try:
            pj = "/home/hatch/data/mcp_jobs/pending"
            n_gen = len([f for f in os.listdir(pj) if f.endswith(".json") and not f.endswith(".result.json")]) if os.path.isdir(pj) else 0
            stages.append({"id": "generate", "name": "视频生成", "count": n_gen,
                           "detail": f"生成队列 {n_gen} 待处理", "items": []})
        except Exception as e:
            stages.append({"id": "generate", "name": "视频生成", "count": -1, "detail": str(e)[:80], "items": []})
        try:
            aa = self._cmd_read_json(os.path.join(D, "perpetua", "awaiting_approval.json"), [])
            qc_ok = sum(1 for i in aa if i.get("qc_passed"))
            stages.append({"id": "qc", "name": "QC 质检", "count": qc_ok,
                           "detail": f"{len(aa)} 条待终审，{qc_ok} 条 QC 通过",
                           "items": [{"t": (i.get("title") or "?")[:28], "s": i.get("status")}
                                     for i in aa[:6]]})
        except Exception as e:
            stages.append({"id": "qc", "name": "QC 质检", "count": -1, "detail": str(e)[:80], "items": []})
        try:
            priv = self._cmd_read_json(os.path.join(D, "youtube", "private_queue.json"), [])
            pitems = priv if isinstance(priv, list) else priv.get("queue", priv.get("items", []))
            waiting = [i for i in pitems if i.get("status") == "waiting"] if isinstance(pitems, list) else []
            pubd = [i for i in pitems if i.get("status") in ("published", "public")] if isinstance(pitems, list) else []
            stages.append({"id": "upload", "name": "上传 Private", "count": len(waiting) + len(pubd),
                           "detail": f"{len(waiting)} 等待翻转 / {len(pubd)} 已公开",
                           "items": [{"t": (i.get("title") or "?")[:28], "s": i.get("status")}
                                     for i in waiting[:4]]})
            stages.append({"id": "schedule", "name": "排期翻 Public", "count": len(waiting),
                           "detail": ("下一档 " + str(waiting[0].get("scheduled_at") or waiting[0].get("slot") or "?")[:16]) if waiting else "无排期",
                           "items": []})
        except Exception as e:
            stages.append({"id": "upload", "name": "上传 Private", "count": -1, "detail": str(e)[:80], "items": []})
            stages.append({"id": "schedule", "name": "排期翻 Public", "count": -1, "detail": str(e)[:80], "items": []})
        try:
            crp = self._cmd_read_json(os.path.join(D, "youtube", "comment_reply_pending.json"), [])
            n_crp = len(crp) if isinstance(crp, list) else len(crp.get("items", []))
            stages.append({"id": "postop", "name": "发布后运营", "count": n_crp,
                           "detail": f"{n_crp} 条评论待回复", "items": []})
        except Exception as e:
            stages.append({"id": "postop", "name": "发布后运营", "count": -1, "detail": str(e)[:80], "items": []})
        try:
            evo_log = os.path.join(os.path.expanduser("~"), "workspace", "goals", "karenvsai",
                                   "hidden_files", "daily-evolution-runlog.md")
            el = self._cmd_tail(evo_log, 2)
            last_evo = el[-1][:60] if el else "暂无记录"
            stages.append({"id": "reflow", "name": "数据回流", "count": 1 if el else 0,
                           "detail": "每日进化: " + last_evo, "items": []})
        except Exception as e:
            stages.append({"id": "reflow", "name": "数据回流", "count": -1, "detail": str(e)[:80], "items": []})
        out["stages"] = stages
        # ---- 2. 服务网格 ----
        svc = [
            {"id": "console", "name": "控制台 :8080", "ok": True, "note": "本服务"},
            {"id": "mcp", "name": "MCP Server", "ok": self._cmd_pgrep("mcp_server/server.py"), "note": ""},
            {"id": "dispatcher", "name": "Dispatcher :8740", "ok": self._cmd_http_ok("http://192.166.82.123:8740/mcp"), "note": "VPS"},
            {"id": "perception", "name": "Perception :18736", "ok": self._cmd_pgrep("perception_server.py"), "note": ""},
            {"id": "nanowebui", "name": "Nano WebUI :18737", "ok": self._cmd_pgrep("http.server 18737"), "note": ""},
            {"id": "t8738", "name": "隧道 8738", "ok": self._cmd_pgrep("[-]R 0[.]0[.]0[.]0:8738:"), "note": "MCP 对外"},
            {"id": "t18901", "name": "隧道 18901", "ok": self._cmd_pgrep("[-]R 0[.]0[.]0[.]0:18901:"), "note": "天枢控制台"},
            {"id": "t18738", "name": "隧道 18738", "ok": self._cmd_pgrep("[-]L 127[.]0[.]0[.]1:18738:"), "note": "Gemini Live"},
        ]
        out["services"] = svc
        out["services_ok"] = sum(1 for s in svc if s["ok"])
        out["services_total"] = len(svc)
        # ---- 3. 九平台矩阵 ----
        plats = []
        try:
            pm = self._cmd_read_json(os.path.join(D, "perpetua", "distributor", "platform_matrix.json"), {})
            pd = pm.get("platforms", pm) if isinstance(pm, dict) else {}
            for k, v in pd.items():
                if not isinstance(v, dict):
                    continue
                plats.append({"id": k, "status": v.get("status", "ok"),
                              "videos": len(v.get("videos", [])),
                              "comments": len(v.get("comments", []))})
        except Exception:
            pass
        out["platforms"] = plats
        out["platforms_ok"] = sum(1 for p in plats if p["status"] == "ok")
        # ---- 4. 健康常量（读最近 publish runlog）----
        consts = []
        try:
            rl = self._cmd_tail("/home/hatch/workspace/goals/karenvsai/hidden_files/publish-health-watch-runlog.md", 3)
            last = rl[-1] if rl else ""
            import re
            m1 = re.search(r"hours_since_last_publish=([\d.]+)", last)
            m2 = re.search(r"publishes_last_24h=(\d+)", last)
            m3 = re.search(r"max_schedule_deviation_min_48h=(\d+)", last)
            consts = [
                {"id": "gap", "name": "距上次发布", "value": (m1.group(1) + "h") if m1 else "?",
                 "target": "≤18h", "ok": (float(m1.group(1)) <= 18) if m1 else None},
                {"id": "daily", "name": "24h 发布数", "value": (m2.group(1) + "条") if m2 else "?",
                 "target": "≥2条", "ok": (int(m2.group(1)) >= 2) if m2 else None},
                {"id": "dev", "name": "排期偏差", "value": (m3.group(1) + "min") if m3 else "?",
                 "target": "≤15min", "ok": (int(m3.group(1)) <= 15) if m3 else None},
            ]
        except Exception:
            pass
        out["constants"] = consts
        # ---- 5. 异常与队列 ----
        try:
            al = self._cmd_read_json(os.path.join(D, "perpetua", "anomaly_ledger.json"), [])
            items = al if isinstance(al, list) else al.get("items", al.get("anomalies", []))
            out["anomaly_open"] = len(items) if isinstance(items, list) else 0
        except Exception:
            out["anomaly_open"] = -1
        try:
            conn = sqlite3.connect(os.path.join("/home/hatch/data", "ops_center.db"))
            cur = conn.cursor()
            cur.execute("SELECT status, COUNT(*) FROM event_bus GROUP BY status")
            out["event_bus"] = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT event_type, created_at FROM event_bus ORDER BY created_at DESC LIMIT 8")
            out["recent_bus"] = [{"t": r[0], "at": r[1]} for r in cur.fetchall()]
            conn.close()
        except Exception:
            out["event_bus"] = {}
            out["recent_bus"] = []
        # ---- 6. 实时事件流 ----
        events = []
        try:
            mem = self._cmd_tail(os.path.join(os.path.expanduser("~"), "memory",
                                              time.strftime("%Y-%m-%d") + ".md"), 25)
            for line in mem:
                s = line.strip()
                if s.startswith("- ") and len(s) > 4:
                    events.append({"src": "巡检日志", "text": s[2:110]})
        except Exception:
            pass
        try:
            aud = self._cmd_tail(os.path.join(D, "perpetua", "audit.log"), 8)
            for line in aud[-5:]:
                events.append({"src": "审计", "text": line[:110]})
        except Exception:
            pass
        out["events"] = events[-20:]
        # ---- 7. 360° v2 六个扩展模块（只读聚合） ----
        modules = []
        for _fn in (self._mod_fleet, self._mod_quota, self._mod_council,
                    self._mod_anomaly, self._mod_cron, self._mod_pubtruth):
            try:
                modules.append(_fn())
            except Exception as _e:
                modules.append({"id": "mod_err", "name": "模块采集异常", "status": "unknown",
                                "summary": "采集异常", "detail": str(_e)[:120], "items": []})
        out["modules"] = modules
        # ---- 总 verdict（服务 bad + 模块 bad 合并计数，口径与八阶段一致） ----
        bad_svc = [s for s in svc if not s["ok"]]
        bad_mod = [m for m in modules if m.get("status") == "bad"]
        n_bad = len(bad_svc) + len(bad_mod)
        out["verdict"] = "HEALTHY" if n_bad == 0 else ("DEGRADED" if n_bad <= 2 else "DOWN")
        _vn = []
        if bad_svc:
            _vn.append("服务异常: " + "、".join(s["name"] for s in bad_svc))
        if bad_mod:
            _vn.append("模块异常: " + "、".join(m["name"] for m in bad_mod))
        out["verdict_note"] = "；".join(_vn) if _vn else "全部服务在线"
        json_resp(self, out)

    # ---- 健康 ----
    def api_health(self):
        def pgrep(pat):
            try:
                out = subprocess.run(["pgrep", "-f", pat], capture_output=True, timeout=5)
                return out.returncode == 0
            except Exception:
                return False
        try:
            st = os.statvfs(DATA)
            disk = {"total_gb": round(st.f_blocks * st.f_frsize / 1e9, 1),
                    "free_gb": round(st.f_bavail * st.f_frsize / 1e9, 1)}
        except OSError:
            disk = {}
        json_resp(self, {
            "ok": True,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mcp_server": pgrep("mcp_server/server.py"),
            "tunnel_8734": pgrep("8734:localhost:8734"),
            "tunnel_8080": pgrep("8080:localhost:8080"),
            "disk": disk,
        })

    # ---- 统一控制台：四脑议会方案 A（D20261013-001）----
    # Tab 1: Pipeline & Cadence Gate / Tab 2: HITL Quarantine / Tab 3: Agent Infrastructure
    # 红队修订已纳入：KILL-3（逐条审批）、KILL-4（STALE 显示）、WEAKEN-1（身份+审计）

    def _audit_unified_console(self, action, target, operator, detail=None):
        """统一控制台 mutation 审计日志（红队 WEAKEN-1：不可变审计）"""
        try:
            log_path = os.path.join(DATA, "perpetua", "vps_console", "unified_console_audit.log")
            entry = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": action,
                "target": target,
                "operator": operator or "unknown",
                "detail": detail or {},
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"WARN: 统一控制台审计写入失败: {e}", file=_sys.stderr)

    def api_pipeline_queue(self):
        """GET /api/pipeline/queue — 发布队列状态（读 SQLite 真相源）"""
        try:
            import sqlite3
            db = os.path.join(DATA, "ops_center.db")
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # 队列概览
            cur.execute("SELECT status, COUNT(*) as c FROM event_bus GROUP BY status")
            by_status = {r["status"]: r["c"] for r in cur.fetchall()}
            # 最近 10 条 PENDING
            cur.execute(
                "SELECT event_id, queue_name, event_type, status, created_at, updated_at "
                "FROM event_bus WHERE status='PENDING' ORDER BY created_at DESC LIMIT 10"
            )
            pending = [dict(r) for r in cur.fetchall()]
            # 队首等待时长（最老 PENDING 的年龄）
            cur.execute(
                "SELECT MIN(created_at) as oldest FROM event_bus WHERE status='PENDING'"
            )
            oldest = cur.fetchone()["oldest"]
            queue_delay_min = None
            if oldest:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    queue_delay_min = round(
                        (datetime.now(timezone.utc) - dt).total_seconds() / 60, 1
                    )
                except Exception:
                    pass
            conn.close()
            # burst lock：队列延迟 >120min 则锁定（红队 KILL-2：执行层 interlock 由 publisher 侧实现，此处仅报告状态）
            burst_locked = queue_delay_min is not None and queue_delay_min > 120
            json_resp(self, {
                "ok": True,
                "by_status": by_status,
                "pending_sample": pending,
                "queue_delay_min": queue_delay_min,
                "burst_locked": burst_locked,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:200]}, 500)

    def api_quarantine_list(self):
        """GET /api/quarantine/list — 隔离视频列表"""
        try:
            qpath = os.path.join(DATA, "youtube", "quarantine.json")
            items = []
            if os.path.exists(qpath):
                with open(qpath, encoding="utf-8") as f:
                    data = json.load(f)
                # 兼容 dict 和 list 两种格式
                if isinstance(data, dict):
                    for vid, info in data.items():
                        if isinstance(info, dict):
                            info["video_id"] = vid
                            items.append(info)
                elif isinstance(data, list):
                    items = data
            json_resp(self, {
                "ok": True,
                "count": len(items),
                "items": items,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:200]}, 500)

    def api_agent_cron_cache(self):
        """GET /api/agent/cron-cache — 116 cron 状态镜像（红队 KILL-4：必须显 STALE+缓存年龄）"""
        try:
            cache_path = os.path.join(DATA, "perpetua", "vps_console", "agent_cron_cache.json")
            now = time.time()
            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    cache = json.load(f)
                cached_at = cache.get("cached_at", 0)
                age_sec = now - cached_at if cached_at else None
                # 超过 120s 未刷新则标 STALE
                stale = age_sec is None or age_sec > 120
                json_resp(self, {
                    "ok": True,
                    "stale": stale,
                    "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cached_at)) if cached_at else None,
                    "age_sec": round(age_sec, 1) if age_sec is not None else None,
                    "jobs": cache.get("jobs", []),
                    "job_count": len(cache.get("jobs", [])),
                    "heartbeat": cache.get("heartbeat", "unknown"),
                })
            else:
                # 无缓存 = UNKNOWN，不伪装成健康
                json_resp(self, {
                    "ok": True,
                    "stale": True,
                    "cached_at": None,
                    "age_sec": None,
                    "jobs": [],
                    "job_count": 0,
                    "heartbeat": "unknown",
                    "note": "no cache yet — status UNKNOWN, not healthy",
                })
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:200]}, 500)

    def api_commander_chat(self, payload):
        """POST /api/commander/chat — 指挥官对话
        payload: {target: 'muse'|'nano', message: str}
        nano: 直接调 nano-call，同步返回
        muse: 关键词即时回复；复杂问题进队列异步处理，前端轮询 /api/commander/poll
        """
        import uuid
        target = (payload.get("target") or "muse").strip()
        message = (payload.get("message") or "").strip()
        if not message:
            json_resp(self, {"ok": False, "error": "消息为空"}, 400)
            return
        if target == "nano":
            try:
                nano_call = os.path.expanduser("~/workspace/skills/nanomuse-caller/bin/nano-call")
                r = subprocess.run(
                    [_sys.executable, nano_call, message, "--timeout", "120", "--json"],
                    capture_output=True, text=True, timeout=150,
                )
                try:
                    out = json.loads(r.stdout.strip())
                    reply = out.get("reply") or out.get("response") or out.get("text") or r.stdout.strip()[:2000]
                except Exception:
                    reply = r.stdout.strip()[:2000] or f"nano 调用异常: {r.stderr[:200]}"
                json_resp(self, {"ok": True, "target": "nano", "reply": reply, "async": False})
            except Exception as e:
                json_resp(self, {"ok": True, "target": "nano",
                                 "reply": f"nano 暂时不可用: {e}", "async": False})
            return
        # muse: 需要口令验证（防公网滥用子 agent）
        token = (payload.get("token") or "").strip()
        token_ok = False
        try:
            saved = open(os.path.join(DATA, "perpetua", "commander_chat_token"), encoding="utf-8").read().strip()
            token_ok = bool(token) and token == saved
        except Exception:
            pass
        if not token_ok:
            json_resp(self, {"ok": False, "error": "口令错误或缺失，Muse 对话需要口令验证"}, 403)
            return
        # muse: 关键词即时
        reply = self.chat_keyword(message)
        if reply:
            json_resp(self, {"ok": True, "target": "muse", "reply": reply, "async": False, "source": "local"})
            return
        # muse: 异步队列（由 cron worker 起子 agent 处理）
        qpath = os.path.join(DATA, "perpetua", "commander_chat_queue.json")
        qid = "ccq-" + uuid.uuid4().hex[:8]
        queue = []
        if os.path.exists(qpath):
            try:
                queue = json.load(open(qpath, encoding="utf-8"))
            except Exception:
                queue = []
        # 取同 session 历史（最近 10 条）供子 agent 上下文
        session_id = (payload.get("session_id") or "default").strip()
        history = []
        for x in queue:
            if x.get("session_id") == session_id and x.get("status") == "done":
                history.append({"role": "user", "content": x.get("message", "")})
                if x.get("reply"):
                    history.append({"role": "assistant", "content": x["reply"]})
        history = history[-20:]  # 最近 10 轮
        queue.append({
            "qid": qid,
            "session_id": session_id,
            "target": "muse",
            "message": message,
            "history": history,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reply": None,
        })
        # 只保留最近 50 条
        queue = queue[-50:]
        with open(qpath, "w", encoding="utf-8") as f:
            json.dump(queue, f, ensure_ascii=False, indent=2)
        json_resp(self, {"ok": True, "target": "muse", "async": True, "qid": qid,
                         "reply": "已收到，正在处理（主 agent 每 2 分钟扫一次队列）…"})

    def api_commander_poll(self, payload):
        """POST /api/commander/poll — 轮询 muse 异步回复
        payload: {qid: str} → {ok, status: pending|done, reply}
        """
        qid = (payload.get("qid") or "").strip()
        qpath = os.path.join(DATA, "perpetua", "commander_chat_queue.json")
        if not os.path.exists(qpath):
            json_resp(self, {"ok": False, "error": "队列不存在"}, 404)
            return
        try:
            queue = json.load(open(qpath, encoding="utf-8"))
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:200]}, 500)
            return
        item = next((x for x in queue if x.get("qid") == qid), None)
        if not item:
            json_resp(self, {"ok": False, "error": "qid 不存在"}, 404)
            return
        json_resp(self, {"ok": True, "qid": qid, "status": item.get("status"),
                         "reply": item.get("reply")})

    def api_agent_hotstandby(self):
        """GET /api/agent/hotstandby — 指挥官热备状态（muse-main vs nanoMuse 路由/降级链）"""
        try:
            import subprocess
            base = os.path.join(DATA, "perpetua")
            # 1. backend_config.json
            cfg = {}
            cfg_path = os.path.join(base, "backend_config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
            # 2. muse_or_nano.py --status（路由+健康+额度）
            status_out = {}
            try:
                r = subprocess.run(
                    [_sys.executable, os.path.join(base, "muse_or_nano.py"), "--status"],
                    capture_output=True, text=True, timeout=60,
                )
                if r.stdout.strip():
                    status_out = json.loads(r.stdout.strip())
            except Exception as e:
                status_out = {"error": str(e)[:200]}
            # 3. fallback_daemon 最近日志（最近 5 行）
            fb_log = []
            fb_path = os.path.join(base, "fallback_daemon.log")
            if os.path.exists(fb_path):
                with open(fb_path, encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip()]
                fb_log = lines[-5:]
            # 4. shadow 模式
            shadow = os.environ.get("FALLBACK_SHADOW", "true").lower() == "true"
            json_resp(self, {
                "ok": True,
                "config": cfg,
                "router_status": status_out,
                "fallback_log_tail": fb_log,
                "shadow_mode": shadow,
            })
        except Exception as e:
            json_resp(self, {"ok": False, "error": str(e)[:200]}, 500)

    def api_pipeline_recovery_approve(self, payload):
        """POST /api/pipeline/recovery-approve — 逐条恢复审批（红队 KILL-3：删除一键恢复，改为逐视频/逐档位）"""
        video_id = (payload.get("video_id") or "").strip()
        slot = (payload.get("slot") or "").strip()
        operator = (payload.get("operator") or "").strip() or "console-user"
        if not video_id:
            json_resp(self, {"ok": False, "error": "video_id required"}, 400)
            return
        # 只记录审批意图，实际恢复由管线执行（不直接改生产状态）
        self._audit_unified_console("recovery_approve", video_id, operator,
                                     {"slot": slot})
        json_resp(self, {
            "ok": True,
            "video_id": video_id,
            "slot": slot,
            "operator": operator,
            "note": "approval recorded; pipeline executor will process",
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def api_quarantine_unfreeze(self, payload):
        """POST /api/quarantine/unfreeze — 单条解冻审批"""
        video_id = (payload.get("video_id") or "").strip()
        operator = (payload.get("operator") or "").strip() or "console-user"
        reason = (payload.get("reason") or "").strip()
        if not video_id:
            json_resp(self, {"ok": False, "error": "video_id required"}, 400)
            return
        self._audit_unified_console("quarantine_unfreeze", video_id, operator,
                                     {"reason": reason})
        json_resp(self, {
            "ok": True,
            "video_id": video_id,
            "operator": operator,
            "note": "unfreeze approval recorded; use pipeline to execute",
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    def api_quarantine_title_swap(self, payload):
        """POST /api/quarantine/title-swap — 标题更换审批"""
        video_id = (payload.get("video_id") or "").strip()
        new_title = (payload.get("new_title") or "").strip()
        operator = (payload.get("operator") or "").strip() or "console-user"
        if not video_id or not new_title:
            json_resp(self, {"ok": False, "error": "video_id and new_title required"}, 400)
            return
        self._audit_unified_console("quarantine_title_swap", video_id, operator,
                                     {"new_title": new_title})
        json_resp(self, {
            "ok": True,
            "video_id": video_id,
            "new_title": new_title,
            "operator": operator,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # ---- 可写层 mutation API（D20261016-003：ack/刷新/重试探针直行；Tier3 只建审批）----
    MUTATE_DIRECT = {"anomaly.ack", "sync.refresh", "probe.retry",
                       "pipeline.trigger", "title.swap"}
    MUTATE_TIER3_KINDS = {"publish", "delete", "flip_public", "quarantine",
                          "revoke_credential", "infra_change", "bulk_reputation"}
    # 直接调用即视为 Tier3 执行意图的一律拦截（必须走 approval.create）
    MUTATE_TIER3_BLOCKED = {"video.publish", "video.delete", "video.flip_public",
                            "credential.revoke", "infra.change", "video.bulk_reputation",
                            "video.quarantine"}

    def _mutate_identity(self):
        ip = self.client_address[0] if self.client_address else "?"
        ua = (self.headers.get("User-Agent") or "")[:40]
        return f"web-console:{ip}"

    def _mutate_idem_path(self):
        return os.path.join(DATA, "perpetua", "vps_console", "mutation_idempotency.json")

    def _mutate_idem_get(self, key):
        try:
            d = json.load(open(self._mutate_idem_path(), encoding="utf-8"))
        except Exception:
            return None
        rec = d.get(key)
        if not rec:
            return None
        if time.time() - rec.get("at", 0) > 86400:
            return None
        return rec.get("result")

    def _mutate_idem_set(self, key, result):
        try:
            p = self._mutate_idem_path()
            d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
            # 清理过期
            now = time.time()
            d = {k: v for k, v in d.items() if now - v.get("at", 0) <= 86400}
            d[key] = {"at": now, "result": result}
            with open(p, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
        except Exception as e:
            print(f"WARN: 幂等存储失败: {e}", file=_sys.stderr)

    def _mutate_inbox_path(self):
        return os.path.join(DATA, "perpetua", "escalation_inbox.json")

    def _mutate_inbox_load(self):
        try:
            d = json.load(open(self._mutate_inbox_path(), encoding="utf-8"))
            return d if isinstance(d, list) else d.get("items", [])
        except Exception:
            return []

    def _mutate_inbox_save(self, items):
        with open(self._mutate_inbox_path(), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)

    def _mutate_anomaly_ack(self, params, operator):
        """直行：异常 ack。带操作前状态 + 回读验证。"""
        eid = (params.get("escalation_id") or "").strip()
        note = (params.get("note") or "").strip()[:200]
        if not eid:
            raise ValueError("escalation_id required")
        items = self._mutate_inbox_load()
        it = next((x for x in items if x.get("escalation_id") == eid), None)
        if not it:
            raise ValueError("escalation_id 不存在")
        pre = {"acked": bool(it.get("ack_by")), "ack_by": it.get("ack_by")}
        if pre["acked"]:
            return {"escalation_id": eid, "already_acked": True, "pre": pre}
        it["ack_by"] = operator
        it["ack_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if note:
            it["ack_note"] = note
        self._mutate_inbox_save(items)
        # 回读验证
        back = [x for x in self._mutate_inbox_load() if x.get("escalation_id") == eid]
        if not back or back[0].get("ack_by") != operator:
            raise RuntimeError("回读验证失败：ack 未落盘")
        self._audit_unified_console("anomaly.ack", eid, operator,
                                    {"pre": pre, "note": note})
        return {"escalation_id": eid, "acked": True, "pre": pre, "readback": "ok"}

    def _mutate_sync_refresh(self, params, operator):
        """直行：刷新同步。target: matrix | snapshot | pipeline"""
        target = (params.get("target") or "").strip()
        if target == "matrix":
            # 与 api_matrix_sync 同逻辑：建 job，后台 cron 捡起执行
            job = _matrix_job_load()
            if job and job.get("status") == "running":
                return {"target": "matrix", "already_running": True}
            platforms = {p: "pending" for p in
                         ["youtube", "douyin", "xiaohongshu", "kuaishou", "shipinhao",
                          "bilibili", "facebook", "tiktok", "x"]}
            _matrix_job_save({"status": "running",
                              "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "triggered_by": "console-mutate:" + operator,
                              "platforms": platforms})
            self._audit_unified_console("sync.refresh", "matrix", operator, {})
            return {"target": "matrix", "job": "created"}
        if target == "snapshot":
            _real_snapshot_cache["at"] = 0
            _real_snapshot_cache["data"] = None
            real = fetch_real_snapshot()
            if real:
                write_json_file(SNAPSHOT_FILE, real)
                self._audit_unified_console("sync.refresh", "snapshot", operator, {})
                return {"target": "snapshot", "refreshed": True}
            return {"target": "snapshot", "refreshed": False, "fallback": True}
        if target == "pipeline":
            # 管线数据由 /api/command/live 实时读取，服务端无缓存；刷新=确认读取正常
            self._audit_unified_console("sync.refresh", "pipeline", operator, {})
            return {"target": "pipeline", "refreshed": True, "note": "live 数据实时读取，无缓存"}
        raise ValueError("target 须为 matrix|snapshot|pipeline")

    def _mutate_probe_retry(self, params, operator):
        """直行：重试探针。probe: dispatch_health"""
        probe = (params.get("probe") or "").strip()
        if probe != "dispatch_health":
            raise ValueError("probe 仅支持 dispatch_health")
        r = subprocess.run(
            [_sys.executable, os.path.join(DATA, "perpetua", "dispatch_health.py")],
            capture_output=True, text=True, timeout=60)
        out = (r.stdout or "")[-1500:]
        self._audit_unified_console("probe.retry", probe, operator,
                                    {"exit": r.returncode})
        return {"probe": probe, "exit": r.returncode,
                "verdict": "HEALTHY" if r.returncode == 0 else "DEGRADED",
                "output_tail": out}

    def _mutate_approval_create(self, params, operator):
        """Tier3：只创建逐条审批，永不执行。"""
        kind = (params.get("kind") or "").strip()
        target = (params.get("target") or "").strip()
        reason = (params.get("reason") or "").strip()
        if kind not in self.MUTATE_TIER3_KINDS:
            raise ValueError("kind 须为 " + "|".join(sorted(self.MUTATE_TIER3_KINDS)))
        if not target or not reason:
            raise ValueError("target 和 reason 必填")
        items = self._mutate_inbox_load()
        eid = f"web-{int(time.time())}-{os.urandom(4).hex()}"
        entry = {
            "escalation_id": eid,
            "dedup_key": "web-" + eid,
            "checker": "web-console",
            "subject": f"tier3:{kind}:{target}",
            "condition": "待人工批准（控制台创建，禁止自动执行）",
            "severity": "P1",
            "detail": f"[{kind}] {target} —— {reason}",
            "evidence_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checker_health": {"probe_ok": True},
            "filed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "filed_at_epoch": time.time(),
            "tier3_kind": kind,
            "tier3_target": target,
            "tier3_reason": reason,
            "created_by": operator,
            "must_approve_before_execute": True,
        }
        items.append(entry)
        self._mutate_inbox_save(items)
        self._audit_unified_console("approval.create", f"{kind}:{target}", operator,
                                    {"escalation_id": eid, "reason": reason})
        return {"escalation_id": eid, "kind": kind, "target": target,
                "status": "pending_approval",
                "note": "已创建逐条审批，等待人工批准后方可执行"}


    def _yt_mod(self):
        """延迟导入 YouTube 模块（避免启动期拖慢）"""
        _sys.path.insert(0, "/home/hatch/data/youtube")
        import yt_upload
        return yt_upload

    def _exec_flip_public(self, video_id, operator):
        """执行器：翻公开。操作前状态 + emergency flip + 回读验证。"""
        yt = self._yt_mod()
        try:
            pre = yt.get_status(video_id) or {}
        except Exception as e:
            raise RuntimeError(f"操作前状态读取失败: {e}"[:200])
        pre_privacy = pre.get("privacyStatus", "")
        if pre_privacy == "public":
            return {"executed": False, "already_public": True,
                    "pre_privacy": pre_privacy}
        if pre_privacy != "private":
            # 操作前状态不明（视频不存在 / API 异常）→ 拒绝执行，保守失败
            raise RuntimeError(
                f"拒绝执行：操作前 privacyStatus={pre_privacy!r} 不是 private")
        r = subprocess.run(
            [_sys.executable, os.path.join(DATA, "youtube", "private_flip.py"),
             "emergency", video_id],
            capture_output=True, text=True, timeout=180)
        tail = ((r.stdout or "") + (r.stderr or ""))[-1200:]
        try:
            post = yt.get_status(video_id) or {}
        except Exception as e:
            post = {"error": str(e)[:120]}
        post_privacy = post.get("privacyStatus", "")
        ok = post_privacy == "public"
        self._audit_unified_console(
            "exec.flip_public", video_id, operator,
            {"pre_privacy": pre_privacy, "post_privacy": post_privacy,
             "cli_exit": r.returncode, "verified": ok})
        if not ok:
            raise RuntimeError(f"翻转后回读验证失败: privacyStatus={post_privacy}")
        return {"executed": True, "pre_privacy": pre_privacy,
                "post_privacy": post_privacy, "verified": True,
                "cli_tail": tail[-400:]}

    def _exec_quarantine_unfreeze(self, video_id, operator):
        """执行器：隔离解冻。从 quarantine.json 移除 + 翻回 public + 回读验证。"""
        qpath = os.path.join(DATA, "youtube", "quarantine.json")
        try:
            q = json.load(open(qpath, encoding="utf-8")) if os.path.exists(qpath) else {}
        except Exception:
            q = {}
        pre_in_q = video_id in q if isinstance(q, dict) else False
        yt = self._yt_mod()
        try:
            pre = yt.get_status(video_id) or {}
        except Exception as e:
            raise RuntimeError(f"操作前状态读取失败: {e}"[:200])
        if pre.get("privacyStatus", "") != "private":
            raise RuntimeError(
                "拒绝执行：操作前 privacyStatus 不是 private（视频不存在或状态不明）")
        if isinstance(q, dict) and video_id in q:
            del q[video_id]
            with open(qpath, "w", encoding="utf-8") as f:
                json.dump(q, f, ensure_ascii=False, indent=1)
        try:
            res = yt.update_metadata(video_id, privacy="public")
        except Exception as e:
            raise RuntimeError(f"翻回 public 失败: {e}"[:200])
        if not res.get("updated"):
            raise RuntimeError(f"翻回 public 被拒: {res.get('error', 'unknown')}"[:200])
        try:
            post = yt.get_status(video_id) or {}
        except Exception as e:
            post = {"error": str(e)[:120]}
        ok = post.get("privacyStatus") == "public"
        self._audit_unified_console(
            "exec.quarantine_unfreeze", video_id, operator,
            {"was_in_quarantine": pre_in_q,
             "pre_privacy": pre.get("privacyStatus", ""),
             "post_privacy": post.get("privacyStatus", ""), "verified": ok})
        if not ok:
            raise RuntimeError("解冻后回读验证失败")
        return {"executed": True, "was_in_quarantine": pre_in_q, "verified": True}

    def _mutate_approval_decide(self, params, operator):
        """审批决策：approve（批准并执行）/ reject（驳回）。
        批准即执行——点击者即为该具体操作的批准人，审计留痕。
        flip_public / quarantine 有自动执行器；其余 kind 批准后标记待 Dash 执行。"""
        eid = (params.get("escalation_id") or "").strip()
        decision = (params.get("decision") or "").strip()
        note = (params.get("note") or "").strip()[:200]
        if not eid:
            raise ValueError("escalation_id required")
        if decision not in ("approve", "reject"):
            raise ValueError("decision 须为 approve|reject")
        items = self._mutate_inbox_load()
        it = next((x for x in items if x.get("escalation_id") == eid), None)
        if not it:
            raise ValueError("escalation_id 不存在")
        if not it.get("must_approve_before_execute"):
            raise ValueError("该条目不是 Tier3 审批")
        pre = {"decision": it.get("tier3_decision"),
               "kind": it.get("tier3_kind"), "target": it.get("tier3_target")}
        if pre["decision"]:
            return {"escalation_id": eid, "already_decided": True, "pre": pre}
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        it["tier3_decision"] = decision
        it["tier3_decided_by"] = operator
        it["tier3_decided_at"] = now
        if note:
            it["tier3_decision_note"] = note
        exec_result = None
        if decision == "approve":
            kind = it.get("tier3_kind")
            target = it.get("tier3_target") or ""
            vid = target.split()[0] if target else ""
            if kind == "flip_public" and vid:
                exec_result = self._exec_flip_public(vid, operator)
            elif kind == "quarantine" and vid:
                exec_result = self._exec_quarantine_unfreeze(vid, operator)
            else:
                exec_result = {"executed": False,
                               "pending": "approved_pending_execution",
                               "note": f"kind={kind} 暂无自动执行器，已批准，待 Dash 执行"}
            it["tier3_exec_result"] = exec_result
        self._mutate_inbox_save(items)
        # 回读验证
        back = [x for x in self._mutate_inbox_load()
                if x.get("escalation_id") == eid]
        if not back or back[0].get("tier3_decision") != decision:
            raise RuntimeError("回读验证失败：决策未落盘")
        self._audit_unified_console("approval.decide", eid, operator,
                                    {"pre": pre, "decision": decision,
                                     "exec": exec_result, "note": note})
        return {"escalation_id": eid, "decision": decision, "pre": pre,
                "exec": exec_result, "readback": "ok"}

    def _mutate_pipeline_trigger(self, params, operator):
        """直行：管线手动触发。stage: select|review|submit|collect|status"""
        stage = (params.get("stage") or "").strip()
        if stage not in ("select", "review", "submit", "collect", "status"):
            raise ValueError("stage 须为 select|review|submit|collect|status")
        cmd = [_sys.executable, os.path.join(DATA, "perpetua", "auto_pipeline.py"),
               stage]
        if stage == "select":
            n = params.get("n", 2)
            try:
                n = max(1, min(5, int(n)))
            except Exception:
                n = 2
            cmd += ["--n", str(n)]
            if params.get("slot"):
                cmd += ["--slot", str(params["slot"])[:8]]
        if stage == "review":
            # 控制台触发不阻塞等待：只捡答案+提交，不等新答案
            cmd += ["--wait", "0", "--instant-timeout", "0"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        out = ((r.stdout or "") + (r.stderr or ""))[-2000:]
        self._audit_unified_console("pipeline.trigger", stage, operator,
                                    {"exit": r.returncode})
        return {"stage": stage, "exit": r.returncode,
                "output_tail": out[-800:]}

    def _mutate_title_swap(self, params, operator):
        """直行：单视频标题更换。带操作前标题 + 回读验证。"""
        video_id = (params.get("video_id") or "").strip()
        new_title = (params.get("new_title") or "").strip()
        if not video_id or not new_title:
            raise ValueError("video_id 和 new_title 必填")
        if len(new_title) > 100:
            raise ValueError("标题过长（>100字）")
        yt = self._yt_mod()
        try:
            pre = yt.get_status(video_id) or {}
        except Exception as e:
            raise RuntimeError(f"操作前状态读取失败: {e}"[:200])
        pre_title = pre.get("title", "")
        try:
            res = yt.update_metadata(video_id, title=new_title)
        except Exception as e:
            raise RuntimeError(f"标题更换失败: {e}"[:200])
        if not res.get("updated"):
            raise RuntimeError(f"标题更换被拒: {res.get('error', 'unknown')}"[:200])
        try:
            post = yt.get_status(video_id) or {}
        except Exception as e:
            post = {"error": str(e)[:120]}
        ok = post.get("title", "") == new_title
        self._audit_unified_console("title.swap", video_id, operator,
                                    {"pre_title": pre_title[:60],
                                     "new_title": new_title[:60],
                                     "verified": ok})
        if not ok:
            raise RuntimeError("回读验证失败：标题未变更")
        return {"video_id": video_id, "pre_title": pre_title,
                "new_title": new_title, "verified": True}

    def _mutate_flip_emergency(self, params, operator):
        """Tier3：紧急翻公开申请。只创建审批（kind=flip_public + 紧急标记），不执行。"""
        video_id = (params.get("video_id") or "").strip()
        reason = (params.get("reason") or "").strip()
        if not video_id:
            raise ValueError("video_id required")
        return self._mutate_approval_create(
            {"kind": "flip_public", "target": video_id,
             "reason": "[EMERGENCY] " + (reason or "紧急翻公开申请")}, operator)

    def _mutate_cron_request(self, params, operator):
        """cron 操作请求：写入队列，由 Dash 处理执行（控制台无直连 cron 控制面）。"""
        op = (params.get("op") or "").strip()
        job_id = (params.get("job_id") or "").strip()
        detail = (params.get("detail") or "").strip()[:300]
        if op not in ("pause", "resume", "update_body", "delete", "run_now"):
            raise ValueError("op 须为 pause|resume|update_body|delete|run_now")
        if not job_id:
            raise ValueError("job_id required")
        qpath = os.path.join(DATA, "perpetua", "cron_ops_queue.json")
        try:
            q = json.load(open(qpath, encoding="utf-8")) if os.path.exists(qpath) else []
        except Exception:
            q = []
        req_id = f"cronreq-{int(time.time())}-{os.urandom(3).hex()}"
        q.append({"request_id": req_id, "op": op, "job_id": job_id,
                  "detail": detail, "requested_by": operator,
                  "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "status": "pending"})
        with open(qpath, "w", encoding="utf-8") as f:
            json.dump(q, f, ensure_ascii=False, indent=1)
        self._audit_unified_console("cron.request", f"{op}:{job_id}", operator,
                                    {"request_id": req_id, "detail": detail})
        return {"request_id": req_id, "op": op, "job_id": job_id,
                "status": "pending",
                "note": "已入队，待 Dash 处理执行"}

    def api_mutate_pending(self, parsed):
        """GET /api/mutate/pending?kind=anomaly|tier3 — 抽屉操作区数据源（只读）"""
        qs = parse_qs(parsed.query)
        kind = (qs.get("kind", ["anomaly"])[0] or "anomaly").strip()
        items = self._mutate_inbox_load()
        if kind == "anomaly":
            out = [{"escalation_id": e.get("escalation_id"),
                    "subject": e.get("subject"), "condition": e.get("condition"),
                    "severity": e.get("severity"),
                    "detail": (e.get("detail") or "")[:160],
                    "filed_at": e.get("filed_at")}
                   for e in items if isinstance(e, dict) and not e.get("ack_by")][:20]
        elif kind == "tier3":
            out = [{"escalation_id": e.get("escalation_id"),
                    "kind": e.get("tier3_kind"), "target": e.get("tier3_target"),
                    "reason": e.get("tier3_reason"), "created_by": e.get("created_by"),
                    "filed_at": e.get("filed_at"),
                    "decision": e.get("tier3_decision"),
                    "emergency": "[EMERGENCY]" in (e.get("tier3_reason") or "")}
                   for e in items if isinstance(e, dict)
                   and e.get("must_approve_before_execute")
                   and not e.get("ack_by") and not e.get("tier3_decision")][:20]
        else:
            out = []
        json_resp(self, {"ok": True, "kind": kind, "items": out})

    def api_cron_requests(self):
        """GET /api/cron/requests — cron 操作请求队列（只读）"""
        qpath = os.path.join(DATA, "perpetua", "cron_ops_queue.json")
        try:
            q = json.load(open(qpath, encoding="utf-8")) if os.path.exists(qpath) else []
        except Exception:
            q = []
        json_resp(self, {"ok": True, "items": q if isinstance(q, list) else []})

    def api_mutate(self, payload):
        """POST /api/mutate — 统一写入入口（D20261016-003）
        payload: {action, idempotency_key, params}
        直行：anomaly.ack / sync.refresh / probe.retry / pipeline.trigger /
              title.swap（执行+审计）
        Tier3：approval.create（只建审批）/ approval.decide（批准并执行，
              flip_public 与 quarantine 有自动执行器）/ flip.emergency（只建审批）；
              cron.request 只入队待 Dash 执行；直接执行类 action 一律 403
        每条 mutation：身份 + 审计日志 + 幂等键 + 操作前状态 + 回读验证
        """
        action = (payload.get("action") or "").strip()
        idem = (payload.get("idempotency_key") or "").strip()
        params = payload.get("params") or {}
        operator = self._mutate_identity()
        if not action or not idem:
            json_resp(self, {"ok": False, "error": "action 与 idempotency_key 必填"}, 400)
            return
        if not isinstance(params, dict):
            json_resp(self, {"ok": False, "error": "params 须为对象"}, 400)
            return
        # 幂等：重复 key 直接返回上次结果
        cached = self._mutate_idem_get(idem)
        if cached is not None:
            json_resp(self, {"ok": True, "idempotent": True, "result": cached})
            return
        # Tier3 直接执行意图拦截
        if action in self.MUTATE_TIER3_BLOCKED:
            self._audit_unified_console("mutate_blocked_tier3", action, operator,
                                        {"params": params, "idempotency_key": idem})
            json_resp(self, {"ok": False, "error": "TIER3_BLOCKED",
                             "message": "Tier 3 动作禁止直接执行，请用 approval.create 创建逐条审批，待人工批准"},
                      403)
            return
        try:
            if action == "anomaly.ack":
                result = self._mutate_anomaly_ack(params, operator)
            elif action == "sync.refresh":
                result = self._mutate_sync_refresh(params, operator)
            elif action == "probe.retry":
                result = self._mutate_probe_retry(params, operator)
            elif action == "approval.create":
                result = self._mutate_approval_create(params, operator)
            elif action == "approval.decide":
                result = self._mutate_approval_decide(params, operator)
            elif action == "pipeline.trigger":
                result = self._mutate_pipeline_trigger(params, operator)
            elif action == "title.swap":
                result = self._mutate_title_swap(params, operator)
            elif action == "flip.emergency":
                result = self._mutate_flip_emergency(params, operator)
            elif action == "cron.request":
                result = self._mutate_cron_request(params, operator)
            else:
                json_resp(self, {"ok": False, "error": "未知 action: " + action}, 400)
                return
        except ValueError as e:
            json_resp(self, {"ok": False, "error": str(e)[:300]}, 400)
            return
        except Exception as e:
            self._audit_unified_console("mutate_error", action, operator,
                                        {"error": str(e)[:200], "idempotency_key": idem})
            json_resp(self, {"ok": False, "error": str(e)[:300]}, 500)
            return
        self._mutate_idem_set(idem, result)
        json_resp(self, {"ok": True, "action": action, "operator": operator,
                         "result": result})

    # ---- 终端 ----
    def api_exec(self, command):
        command = (command or "").strip()
        if not command:
            json_resp(self, {"error": "empty command"}, 400)
            return
        for pat in BLOCKED:
            if re.search(pat, command):
                self.audit(command, "BLOCKED")
                json_resp(self, {"output": "BLOCKED: 危险命令已拦截", "exit_code": 126, "blocked": True}, 200)
                return
        try:
            r = subprocess.run(command, shell=True, cwd=DATA, capture_output=True,
                               text=True, timeout=30)
            output = redact((r.stdout or "") + (r.stderr or ""))
            truncated = False
            if len(output) > 20480:
                output = output[:20480] + "\n...[truncated]"
                truncated = True
            self.audit(command, f"exit={r.returncode}")
            json_resp(self, {"output": output, "exit_code": r.returncode, "truncated": truncated})
        except subprocess.TimeoutExpired as e:
            out = redact((e.stdout or b"").decode(errors="replace") + (e.stderr or b"").decode(errors="replace"))
            self.audit(command, "TIMEOUT")
            json_resp(self, {"output": out + "\n[30秒超时，已终止]", "exit_code": -1, "timeout": True})

    def audit(self, command, result):
        try:
            with open(AUDIT_LOG, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {result} | {command[:500]}\n")
            os.chmod(AUDIT_LOG, 0o600)
        except OSError:
            pass

    # ---- 聊天 ----
    def api_chat(self, message):
        msg = (message or "").strip()
        if not msg:
            json_resp(self, {"reply": "请输入问题。"}, 200)
            return
        # 关键词直达
        reply = self.chat_keyword(msg)
        if reply:
            json_resp(self, {"reply": reply, "source": "local"}, 200)
            return
        # Marvis 异步队列
        qid = self.chat_enqueue(msg)
        json_resp(self, {"reply": "复杂问题已转交 Marvis 异步处理，请稍候…", "source": "marvis", "qid": qid}, 200)

    def chat_keyword(self, msg):
        m = msg.lower()
        snap = read_json_file(SNAPSHOT_FILE) or SAMPLE_SNAPSHOT
        if "热点" in msg or "trend" in m:
            try:
                r = subprocess.run(["python3", os.path.join(DATA, "trend_spike_detector.py")],
                                   capture_output=True, text=True, timeout=60, cwd=DATA)
                out = (r.stdout or "")[-800:]
                return f"热点检测已执行：\n{out or '(无输出)'}"
            except Exception as e:
                return f"热点检测执行失败：{e}"
        if "猪八戒" in msg or "zbj" in m:
            return "猪八戒配额：已入驻 1 个，剩余 0（每日 09:49 自动检查，仅在 0→>0 时通知）。"
        if "队列" in msg or "ask" in m:
            q = read_json_file(os.path.join(DATA, "ask_studio", "queue.json")) or {}
            items = q.get("queue", q if isinstance(q, list) else [])
            n = len(items) if isinstance(items, list) else 0
            return f"Ask Studio 队列：{n} 个待处理问题。"
        if "健康" in msg or "health" in m:
            hs = snap.get("health", [])
            lines = [f"{'✓' if h.get('healthy') else '✗'} {h.get('name')}: {h.get('detail')}" for h in hs]
            return "系统健康：\n" + "\n".join(lines)
        if "ypp" in m:
            subs = snap.get("subscriberCount", 0)
            wh = snap.get("watchHoursDiag", 0)
            wg = snap.get("watchHoursGoal", 4000)
            return (f"YPP 进度（长视频路径）：订阅 {subs}/1000（还差 {1000-subs}）；"
                    f"观看小时 {wh}/4000 诊断值（还差 {wg-wh:.0f}，非 qualified，以 Studio Eligibility 为准）。")
        if "配额" in msg or "quota" in m:
            return f"今日配额：{snap.get('quotaUsed', 0)} / {snap.get('quotaTotal', 10)}（每日 00:00 重置）。"
        if "日志" in msg or "log" in m:
            return "请切换到「实时日志」面板查看，或问我具体哪个服务的日志（mcp/watchdog/tunnel/poller）。"
        return None

    def chat_enqueue(self, msg):
        reqs = read_json_file(CHAT_REQ) or {"requests": []}
        qid = f"q-{int(time.time())}"
        reqs.setdefault("requests", []).append({
            "id": qid, "message": msg, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "pending",
        })
        write_json_file(CHAT_REQ, reqs)
        return qid

    # ---- 租户管理 ----
    def _tenant_registry(self):
        path = os.path.join(DATA, "perpetua", "tenants", "registry.json")
        return path, read_json_file(path) or {"tenants": {}}

    def api_tenant_add(self, payload):
        path, reg = self._tenant_registry()
        tid = (payload.get("name") or "").strip().lower().replace(" ", "-") or f"t-{int(time.time())}"
        tenants = reg.setdefault("tenants", {})
        if tid in tenants:
            json_resp(self, {"error": "租户已存在"}, 400)
            return
        plan = payload.get("plan", "Pro")
        quota_map = {"Free": 3, "Pro": 10, "Enterprise": 50}
        tenants[tid] = {
            "id": tid,
            "name": payload.get("name", tid),
            "youtube_channel_id": payload.get("channel_id", ""),
            "youtube_channel_name": payload.get("channel_id", ""),
            "plan": plan,
            "quota": {"videos_per_day": quota_map.get(plan, 10)},
            "status": "active",
            "theme": "",
            "created": time.strftime("%Y-%m-%d"),
        }
        write_json_file(path, reg)
        json_resp(self, {"ok": True, "id": tid})

    def api_tenant_update(self, payload):
        path, reg = self._tenant_registry()
        tid = payload.get("id", "")
        t = reg.get("tenants", {}).get(tid)
        if not t:
            json_resp(self, {"error": "租户不存在"}, 404)
            return
        if "quota" in payload:
            t.setdefault("quota", {})["videos_per_day"] = int(payload["quota"])
        if "status" in payload:
            t["status"] = payload["status"]
        if "plan" in payload:
            t["plan"] = payload["plan"]
        write_json_file(path, reg)
        json_resp(self, {"ok": True})

    def api_tenant_delete(self, payload):
        path, reg = self._tenant_registry()
        tid = payload.get("id", "")
        if tid == "default":
            json_resp(self, {"error": "default 租户不可删除"}, 400)
            return
        if tid in reg.get("tenants", {}):
            del reg["tenants"][tid]
            write_json_file(path, reg)
            json_resp(self, {"ok": True})
        else:
            json_resp(self, {"error": "租户不存在"}, 404)

    # ---- 设置 ----
    def api_settings_save(self, payload):
        path = os.path.join(DATA, "perpetua", "console_settings.json")
        cur = read_json_file(path) or {}
        cur.update({k: payload.get(k, v) for k, v in {
            "daily_target": 2, "virality_threshold": 60, "plan": "Pro",
            "spike_detector": True, "auto_retitle": True, "ask_studio_auto": True,
        }.items() if k in payload})
        write_json_file(path, cur)
        json_resp(self, {"ok": True, "settings": cur})

    # ---- MCP 服务端代理 ----
    def api_mcp_tools_list(self):
        """GET /api/mcp/tools/list：服务端调 MCP tools/list，原样返回。"""
        _audit_mcp_call("tools/list")
        result, err = _mcp_rpc("tools/list", {})
        if err:
            json_resp(self, {"error": err}, 502)
            return
        json_resp(self, result or {})

    def api_mcp_call(self, payload):
        """POST /api/mcp：通用 JSON-RPC 代理，payload {"method","params"}。"""
        method = (payload or {}).get("method", "")
        params = (payload or {}).get("params", {})
        if not method or not isinstance(method, str):
            json_resp(self, {"error": "method required"}, 400)
            return
        _audit_mcp_call(method)
        result, err = _mcp_rpc(method, params)
        if err:
            json_resp(self, {"error": err}, 502)
            return
        json_resp(self, result if result is not None else {})


def main():
    port = int(os.environ.get("CONSOLE_PORT", "8080"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True  # 主进程退出时工作线程不阻塞
    print(f"Perpetua console v2 (threaded) on 127.0.0.1:{port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
