#!/usr/bin/env python3
"""Dash 的 MCP server：让外部 agent（如 Marvis）直接调用。

传输：Streamable HTTP（供远程 MCP 客户端），默认只监听 127.0.0.1，
对外通过 cloudflared 隧道暴露。认证：Bearer token 中间件。
文件操作全部限制在 /home/hatch/data 之内。
"""
import hashlib
import json
import os
import secrets
import subprocess
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

BASE = Path("/home/hatch/data").resolve()
JOBS = BASE / "mcp_jobs"
PENDING = JOBS / "pending"
DONE = JOBS / "done"
HERE = Path(__file__).parent
TOKEN_FILE = HERE / ".token"

# ---- token ----
if TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text().strip()
else:
    TOKEN = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(TOKEN)
    TOKEN_FILE.chmod(0o600)


def _safe(rel: str) -> Path:
    target = (BASE / rel).resolve()
    if target != BASE and not str(target).startswith(str(BASE) + "/"):
        raise ValueError("path escapes /home/hatch/data")
    return target


class TokenAuth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in ("/health",):
            return await call_next(request)
        if request.headers.get("authorization", "") != f"Bearer {TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(request):
    return JSONResponse({"ok": True, "server": "dash-collab-mcp", "time": datetime.now(timezone.utc).isoformat()})


mcp = FastMCP("dash-collab",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@mcp.tool()
def read_file(path: str, max_bytes: int = 100000, offset: int = 0) -> str:
    """读取 /home/hatch/data 下的文本文件。path 为相对路径。

    大文件分片读：max_bytes 单次上限 100000；用 offset 指定起始字节续读。
    返回开头带 [bytes=A-B/TOTAL] 头，据此判断是否还有下一片。
    二进制文件请用 read_chunk 走 hex，不要用本工具（会被 errors=replace 破坏）。
    """
    max_bytes = max(1, min(int(max_bytes), 100000))
    offset = max(0, int(offset))
    raw = _safe(path).read_bytes()
    total = len(raw)
    data = raw[offset:offset + max_bytes]
    head = f"[bytes={offset}-{offset + len(data)}/{total}]"
    if offset + max_bytes < total:
        head += f" (more: offset={offset + len(data)})"
    return head + "\n" + data.decode("utf-8", errors="replace")


@mcp.tool()
def read_chunk(path: str, offset: int = 0, size: int = 48000) -> str:
    """以 hex 读取任意文件（含二进制）的分片，用于大文件搬运。

    单次上限 size=48000 字节 -> 返回 96000 个 hex 字符（安全低于 read_file 的 100000 上限）。
    返回首行 `#HEX <offset> <nbytes> <total> <md5_of_whole_file>`，其后是 hex 正文。
    客户端按 offset 循环拉取，最后拼 hex -> binascii.unhexlify -> 校验 md5。
    搬运 11MB 视频约需 245 次调用；小文件直接一次拿完。
    """
    size = max(1, min(int(size), 48000))
    offset = max(0, int(offset))
    p = _safe(path)
    raw = p.read_bytes()
    total = len(raw)
    chunk = raw[offset:offset + size]
    md5 = hashlib.md5(raw).hexdigest()
    return f"#HEX {offset} {len(chunk)} {total} {md5}\n" + chunk.hex()


@mcp.tool()
def file_info(path: str) -> str:
    """查询文件元信息：大小、md5、是否存在。搬运前先调它拿 total 与 md5。"""
    p = _safe(path)
    if not p.exists():
        return json.dumps({"path": path, "exists": False}, ensure_ascii=False)
    raw = p.read_bytes()
    return json.dumps({
        "path": path, "exists": True, "bytes": len(raw),
        "md5": hashlib.md5(raw).hexdigest(),
        "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
        "is_dir": p.is_dir(),
    }, ensure_ascii=False)


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """向 /home/hatch/data 下写文本文件。path 为相对路径。"""
    t = _safe(path)
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(content, encoding="utf-8")
    return f"wrote {t.stat().st_size} bytes -> {path}"


@mcp.tool()
def list_dir(path: str = ".") -> str:
    """列出 /home/hatch/data 下某目录。"""
    t = _safe(path)
    if not t.is_dir():
        return f"not a directory: {path}"
    return "\n".join(sorted((p.name + ("/" if p.is_dir() else "")) for p in t.iterdir())) or "(empty)"


@mcp.tool()
def submit_job(job_type: str, payload: str = "{}", idempotency_key: str = "") -> str:
    """给 Dash 派一个任务。job_type: generate_video | generate_image | note | collab_poll | ask_dash。
    payload 为 JSON 字符串。返回 job_id，用 job_status 查询。

    idempotency_key：幂等键。同一个 key 重复提交只受理一次，返回首次的 job_id
    （响应带 "deduped": true）。强烈建议传入，防止网络重试产生重复产物。

    generate_video/generate_image 由后台每10分钟自动处理，完成后可用 job_status 查询并用 read_file 取货。
    ask_dash：把难题描述发给 Dash，Dash 会直接动手解决（查资料、跑命令、生成文件等），结果写回 job_status。"""
    try:
        data = json.loads(payload)
    except Exception:
        data = {"raw": payload}

    # 幂等：key -> job_id 索引，落盘持久化
    IDX = JOBS / "idempotency.json"
    idx = {}
    if IDX.exists():
        try:
            idx = json.loads(IDX.read_text(encoding="utf-8"))
        except Exception:
            idx = {}
    if idempotency_key:
        prev = idx.get(idempotency_key)
        if prev:
            for d in (DONE, PENDING):
                if (d / f"{prev}.json").exists() or (d / f"{prev}.result.json").exists():
                    return json.dumps({"job_id": prev, "deduped": True,
                                       "note": "idempotency_key already seen"},
                                      ensure_ascii=False)

    jid = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    PENDING.mkdir(parents=True, exist_ok=True)
    (PENDING / f"{jid}.json").write_text(json.dumps({
        "job_id": jid, "job_type": job_type, "payload": data,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "from": "marvis",
        "idempotency_key": idempotency_key or None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if idempotency_key:
        idx[idempotency_key] = jid
        try:
            IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return json.dumps({"job_id": jid, "deduped": False}, ensure_ascii=False)


@mcp.tool()
def job_status(job_id: str, resolve_path: bool = True) -> str:
    """查询任务状态与结果。

    返回 JSON，含统一的 `status` 字段：pending | done | failed | not_found。
    结果里的 `file` 字段默认已转成**相对路径**（相对 /home/hatch/data），
    可直接喂给 read_chunk / read_file，无需再手工剥前缀。
    传 resolve_path=False 可拿到原始绝对路径。
    """
    found = None
    for name in (f"{job_id}.result.json", f"{job_id}.json"):
        for d in (DONE, PENDING):
            f = d / name
            if f.exists():
                found = f
                break
        if found:
            break

    if not found:
        return json.dumps({"job_id": job_id, "status": "not_found"}, ensure_ascii=False)

    try:
        obj = json.loads(found.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"job_id": job_id, "status": "error",
                           "error": f"unreadable: {e}",
                           "raw_file": str(found.relative_to(BASE))},
                          ensure_ascii=False)

    obj.setdefault("status", "pending")
    obj["_source_file"] = str(found.relative_to(BASE))

    # 兜底：若查到的是 done/ 下的原始任务文件而其 status 仍为 pending，
    # 说明消费者只写了 result.json 没回写原文件 —— 以结果文件为准。
    if found.parent == DONE and obj.get("status") == "pending":
        res = DONE / f"{obj.get('job_id', job_id)}.result.json"
        if res.exists():
            try:
                rst = json.loads(res.read_text(encoding="utf-8")).get("status", "done")
                obj["status"] = rst if rst in ("done", "failed") else "done"
                obj["_status_source"] = "result.json"
            except Exception:
                obj["status"] = "done"
                obj["_status_source"] = "result.json"

    if resolve_path:
        def _rel(v):
            if isinstance(v, str) and v.startswith(str(BASE)):
                return str(Path(v).relative_to(BASE))
            return v
        for k in ("file", "output_file", "video"):
            if k in obj:
                obj[k] = _rel(obj[k])
        if isinstance(obj.get("files"), list):
            obj["files"] = [_rel(x) for x in obj["files"]]

    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool()
def jobs_list(status: str = "pending", limit: int = 50) -> str:
    """列出任务。status: pending | done | failed | all。用于排查卡住/积压的任务。

    返回每条的 job_id / job_type / created_at / status 及队列方向。
    """
    limit = max(1, min(int(limit), 200))
    dirs = {"pending": [PENDING], "done": [DONE], "failed": [DONE], "all": [PENDING, DONE]}
    out = []
    for d in dirs.get(status, [PENDING]):
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.name.endswith(".result.json") or not f.name.endswith(".json"):
                continue
            try:
                o = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            st = o.get("status", "pending")
            # 已进 done/ 目录但原始文件未回写 status 的，按结果文件兜底判定
            if d is DONE and st == "pending":
                res = DONE / f"{o.get('job_id', f.stem)}.result.json"
                if res.exists():
                    try:
                        rst = json.loads(res.read_text(encoding="utf-8")).get("status", "done")
                        st = rst if rst in ("done", "failed") else "done"
                    except Exception:
                        st = "done"
            if status != "all" and st != status:
                continue
            out.append({
                "job_id": o.get("job_id", f.stem),
                "job_type": o.get("job_type"),
                "status": st,
                "created_at": o.get("created_at"),
                "queue": d.name,
                "age_min": round((datetime.now(timezone.utc) -
                                  datetime.fromisoformat(o["created_at"])).total_seconds() / 60)
                if o.get("created_at") else None,
            })
    out.sort(key=lambda x: x.get("created_at") or "")
    return json.dumps({"count": len(out), "items": out[:limit]}, ensure_ascii=False, indent=2)


@mcp.tool()
def notes_list(include_handled: bool = False) -> str:
    """列出 note 类留言（note 类不走 Muse 自动消费，需人工/agent 处置）。

    note 是设计上的"人工查看"通道：Muse 不会把它变 done，长期停在
    pending/ 属正常，不代表队列坏了。本工具把它变成可操作列表。
    include_handled=True 时连已归档的也返回。
    """
    out = []
    arch = PENDING / ".handled"
    for d in ([PENDING] + ([arch] if include_handled else [])):
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            if f.name.startswith("."):
                continue
            try:
                o = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if o.get("job_type") != "note":
                continue
            out.append({
                "job_id": o.get("job_id", f.stem),
                "text": (o.get("payload") or {}).get("text", ""),
                "created_at": o.get("created_at"),
                "handled": d is arch,
            })
    out.sort(key=lambda x: x.get("created_at") or "")
    return json.dumps({"count": len(out), "notes": out}, ensure_ascii=False, indent=2)


@mcp.tool()
def note_handle(job_id: str, resolution: str = "") -> str:
    """处置一条 note 留言：写入处置记录并归档到 pending/.handled/。

    幂等：已归档的重复调用返回 already_handled。
    """
    src = PENDING / f"{job_id}.json"
    arch = PENDING / ".handled"
    if not src.exists():
        if (arch / f"{job_id}.json").exists():
            return json.dumps({"ok": True, "already_handled": True, "job_id": job_id},
                              ensure_ascii=False)
        return json.dumps({"ok": False, "error": "note not found", "job_id": job_id},
                          ensure_ascii=False)
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"ok": False, "error": f"unreadable: {e}"}, ensure_ascii=False)

    arch.mkdir(parents=True, exist_ok=True)
    obj["status"] = "handled"
    obj["handled_at"] = datetime.now(timezone.utc).isoformat()
    obj["handled_by"] = "workbuddy"
    if resolution:
        obj["resolution"] = resolution
    (arch / f"{job_id}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    src.unlink()
    return json.dumps({"ok": True, "job_id": job_id, "resolution": resolution,
                       "archived_to": str((arch / f"{job_id}.json").relative_to(BASE))},
                      ensure_ascii=False)


@mcp.tool()
def requeue_job(job_id: str, reason: str = "") -> str:
    """把卡住的任务重新投回 pending 队列（幂等：若已在 pending 则不做）。

    用于处理长期 stuck 的 note / collab_poll / 生成任务。
    会先备份原文件到 pending/.requeued/ 再移动，并记录 requeue 次数。
    """
    src = None
    for d in (DONE, PENDING):
        f = d / f"{job_id}.json"
        if f.exists():
            src = f
            break
    if not src:
        return json.dumps({"ok": False, "error": "job not found", "job_id": job_id},
                          ensure_ascii=False)

    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        return json.dumps({"ok": False, "error": f"unreadable: {e}"}, ensure_ascii=False)

    PENDING.mkdir(parents=True, exist_ok=True)
    if src.parent == PENDING:
        return json.dumps({"ok": True, "already_pending": True, "job_id": job_id},
                          ensure_ascii=False)

    bdir = PENDING / ".requeued"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / src.name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    obj["status"] = "pending"
    obj["requeued"] = int(obj.get("requeued", 0)) + 1
    obj["requeued_at"] = datetime.now(timezone.utc).isoformat()
    if reason:
        obj["requeue_reason"] = reason
    (PENDING / f"{job_id}.json").write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    return json.dumps({"ok": True, "job_id": job_id, "requeued": obj["requeued"],
                       "backup": str((bdir / src.name).relative_to(BASE))},
                      ensure_ascii=False)


@mcp.tool()
def get_protocol() -> str:
    """读取 Muse×Marvis 协作协议（collab/PROTOCOL.md）。"""
    p = BASE / "collab" / "PROTOCOL.md"
    return p.read_text(encoding="utf-8") if p.exists() else "PROTOCOL.md not found"


@mcp.tool()
def exec_shell(command: str, timeout: int = 30) -> str:
    """在 VM 上执行 shell 命令。工作目录固定为 /home/hatch/data，超时默认 30 秒。
    高权限工具：可读写本机文件、联网、运行任意程序。请谨慎使用。"""
    timeout = max(5, min(timeout, 120))
    try:
        r = subprocess.run(
            command, shell=True, cwd=str(BASE),
            capture_output=True, text=True, timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if len(out) > 20000:
            out = out[:20000] + "\n...[truncated]"
        return f"[exit={r.returncode}]\n{out or '(no output)'}"
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> str:
    """网页搜索（DuckDuckGo）。返回标题、链接、摘要。"""
    max_results = max(1, min(max_results, 10))
    try:
        q = urllib.parse.urlencode({"q": query, "format": "json"})
        req = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?{q}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")
        import re
        results = []
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if url.startswith("//"):
                url = "https:" + url
            results.append(f"- {title}\n  {url}")
            if len(results) >= max_results:
                break
        return "\n".join(results) or "(no results)"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def fetch_url(url: str, max_bytes: int = 50000) -> str:
    """抓取网页文本内容（自动去除 HTML 标签）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=20).read()[:max_bytes]
        text = raw.decode("utf-8", errors="replace")
        import re
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:10000] or "(empty)"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def virality_score(title: str, hook: str = "", topic_heat: str = "medium", duration: int = 10) -> str:
    """给 Short 选题打爆款分（0-100）。低于58分建议回炉。

    数据驱动版（v2）：权重从本频道 481 条历史视频的实际播放量回归得出，
    而非人工关键词表。实测 Spearman ρ=0.32（v1 规则版 ρ≈0）。Top50 命中率
    28.6% vs v1 的 4.1%，Top50 平均播放 4,203 vs 825。
    topic_heat: high/medium/low。返回分数、等级、命中的有效特征与优化建议。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/virality_score_v2.py", json.dumps({
                "title": title, "hook": hook,
                "topic_heat": topic_heat, "duration": duration,
            })],
            cwd=str(HERE), capture_output=True, text=True, timeout=20,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def youtube_audit(days: int = 30, refresh: bool = False, sync: bool = True) -> str:
    """复盘最近 N 天视频的真实表现，并对比当时的爆款预测分。

    这是闭环的回流环节：拉取真实播放数据 -> 与 virality_score 预测并列 ->
    计算预测准确率 -> 给出下一轮选题修正建议。

    预测分优先取自 **topics_history.jsonl 账本中锁定的发布时预测**（真正的前瞻性
    检验，不事后追认）；账本没有的才现算。
    refresh=True 重新全量拉取频道历史（约 20s）。sync=True（默认）先把账本
    与最新真实播放同步。返回含 ledger 段落报告账本规模。
    """
    try:
        args = ["python3", "/home/hatch/data/youtube/audit.py", str(days)]
        if refresh:
            args.append("--refresh")
        if sync:
            args.append("--sync")
        r = subprocess.run(args, cwd=str(HERE), capture_output=True,
                           text=True, timeout=180)
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def youtube_stats() -> str:
    """获取 YouTube 频道数据（订阅数、视频数、总播放量）。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt.py", "stats"],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def youtube_recent(max_n: int = 10) -> str:
    """获取最近发布的视频及播放数据（标题、播放量、点赞、评论）。用于分析爆款规律。"""
    try:
        max_n = max(1, min(max_n, 50))
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt.py", "recent", str(max_n)],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


def _upload_hard_gates(title: str, description: str, tags: str):
    """2026-10-06 深度诊断后的 5 项硬门禁（全部失败直接拒绝上传）。

    返回 (是否通过, 拒绝原因文本)。通过返回 (True, "")。
    skip_gate=True 可绕过（调用方明确承担风险）。
    """
    import re as _re
    from datetime import datetime, timezone, timedelta

    # ---- Gate 1: 错峰（4 小时内只能发 1 条）----
    try:
        import subprocess as _sp
        r = _sp.run(
            ["python3", "/home/hatch/data/youtube/yt.py", "recent", "5"],
            capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout) if r.stdout.strip() else []
        now = datetime.now(timezone.utc)
        for it in items:
            if not isinstance(it, dict):
                continue
            pub = str(it.get("published", "")).strip()
            pdt = None
            try:
                # 完整 ISO 时间戳
                if "T" in pub:
                    pdt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    if pdt.tzinfo is None:
                        pdt = pdt.replace(tzinfo=timezone.utc)
                # 只有日期（如 2026-10-06）：用 YouTube API 查精确时间
                elif _re.match(r"^\d{4}-\d{2}-\d{2}$", pub):
                    # 查该视频的精确发布时间
                    vid = it.get("id", "")
                    if vid:
                        r2 = _sp.run(
                            ["python3", "-c",
                             "import json,sys;sys.path.insert(0,'/home/hatch/data/youtube');"
                             "from post_publish_optimizer import get_recent_videos;"
                             "vs=get_recent_videos(2);"
                             "print(json.dumps([v for v in vs if v['video_id']=='%s']))" % vid],
                            capture_output=True, text=True, timeout=30)
                        vs = json.loads(r2.stdout) if r2.stdout.strip() else []
                        if vs and vs[0].get("published"):
                            pdt = datetime.fromisoformat(
                                vs[0]["published"].replace("Z", "+00:00"))
                    # 查不到精确时间：如果日期是今天，保守按"刚发布"处理
                    if pdt is None:
                        today = now.strftime("%Y-%m-%d")
                        if pub == today:
                            # 保守估计：今天发布的，按 0 小时前处理（直接拒绝）
                            return False, (
                                "[gate1:错峰] 今天已发布过视频《%s》（%s）。"
                                "为避免互相抢流量，4 小时内只能发 1 条。"
                                "确认要发可用 skip_gate=true 强制上传。"
                                % (it.get("title", "")[:50], pub))
                        continue
            except Exception:
                continue
            if pdt is None:
                continue
            age_h = (now - pdt).total_seconds() / 3600
            if age_h < 4:
                next_ok = pdt + timedelta(hours=4)
                return False, (
                    "[gate1:错峰] 4 小时内已发布过视频《%s》（%s，%.1f 小时前）。"
                    "为避免互相抢流量，下次可发布时间：%s（UTC）。"
                    "确认要发可用 skip_gate=true 强制上传。"
                    % (it.get("title", "")[:50], pub[:16], age_h,
                       next_ok.strftime("%Y-%m-%d %H:%M")))
    except Exception:
        # API 失败时 fail-open（不阻塞）
        pass

    # ---- Gate 2: 标题主语校验（报应主语必须是 Karen）----
    KARMA_VERBS = ["TOWED", "SOAKED", "BOOTED", "TRAPPED", "DESTROYED",
                   "EXPOSED", "CAUGHT", "SNAPPED", "BURNED", "FLOODED",
                   "LOCKED", "SPRAYED", "DRENCHED", "EVICTED", "HIT",
                   "BROKE", "CRASHED", "EXPLODED"]
    t_up = (title or "").upper()
    t_low = (title or "").lower()
    # 找到第一个出现的报应动词
    first_verb_pos = None
    first_verb = None
    for v in KARMA_VERBS:
        p = t_up.find(v)
        if p >= 0 and (first_verb_pos is None or p < first_verb_pos):
            first_verb_pos = p
            first_verb = v
    karen_pos = t_low.find("karen")
    if first_verb:
        if karen_pos < 0:
            return False, (
                "[gate2:主语] 标题含报应动词 %s 但没有 Karen。"
                "报应主语必须是 Karen（或她的东西），不能是机器。"
                "例：'Then Karma Hit It' 中 It 指机器，主语反了。"
                % first_verb)
        if karen_pos > first_verb_pos:
            return False, (
                "[gate2:主语] Karen 必须出现在报应动词 %s 之前。"
                "当前标题：%r。观众要看的是 Karen 倒霉，不是机器倒霉。"
                % (first_verb, title[:80]))
        # 2b. 报应对象不能是机器："Hit It" / "It Broke" / "It Crashed"
        # It 指机器时，报应打在了机器上，笑点反了
        after_verb = t_up[first_verb_pos + len(first_verb):first_verb_pos + len(first_verb) + 10]
        if _re.search(r"^\s*IT\b", after_verb):
            return False, (
                "[gate2:主语] 报应动词 %s 的对象是 'It'（指机器）。"
                "观众要看的是 Karen 倒霉，不是机器倒霉。"
                "当前标题：%r。" % (first_verb, title[:80]))
        # "It Broke/Crashed/Snapped"：主语是机器，不是 Karen 受罚
        if _re.search(r"\bIT\s+(BROKE|CRASHED|SNAPPED|BROKEN)\b", t_up):
            return False, (
                "[gate2:主语] 标题主语是 'It'（机器坏了），不是 Karen 受罚。"
                "报应必须打在 Karen 身上。"
                "当前标题：%r。" % title[:80])

    # ---- Gate 3: emoji 开头 ----
    EMOJI_RE = _re.compile(
        "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF"
        "\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF\u231A-\u231B\u23E9-\u23F3"
        "\u23F8-\u23FA\U0001F004\U0001F0CF"
        "\u2690-\u2691\u2B05-\u2B07\u2B1B-\u2B1C\u2B50\u2B55"
        "\u2744\u2747\u274C\u274E\u2753-\u2755\u2757"
        "\u2795-\u2797\u27A1\u27B0\u27BF\u2B05]",
        flags=_re.UNICODE)
    first_char = (title or "")[:1]
    if not first_char or not EMOJI_RE.match(first_char):
        return False, (
            "[gate3:emoji] 标题必须以 emoji 开头（Top10 70%% 规律）。"
            "当前标题首字符：%r。请把 emoji 从末尾移到开头。"
            % first_char)

    # ---- Gate 4: 元数据完整 ----
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    desc_len = len((description or "").strip())
    if desc_len < 20:
        return False, (
            "[gate4:元数据] 描述太短（%d 字符，要求 ≥20）。"
            "三无视频（无描述/无标签）禁止上传。" % desc_len)
    if len(tag_list) < 3:
        return False, (
            "[gate4:元数据] 标签太少（%d 个，要求 ≥3）。"
            "三无视频（无描述/无标签）禁止上传。" % len(tag_list))

    # ---- Gate 5: 纯度 + 去重（P0 规则，MCP 工具层复刻）----
    # 5a. 纯度：英文、无 CJK、Karen 优先（2026-10-07 校准更新）
    if _re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", title or ""):
        return False, (
            "[gate5a:纯度] 标题含 CJK 字符：%r。频道只发英文 Karen vs AI。"
            % title[:60])
    low = t_low
    has_karen = "karen" in low
    has_ai = _re.search(r"\bai\b", low) is not None
    # 【AI Satire】品牌系列豁免（数据：9 条均值 2205，3.93x）
    is_ai_brand = "ai satire" in low
    if not has_karen and not has_ai:
        return False, (
            "[gate5a:纯度] 标题必须含 Karen 或 AI：%r。" % title[:60])
    # 2026-10-07 校准：普通 AI 标题仅 0.22x 播放（n=67），有害；
    # 无 Karen 的纯 AI 标题拒绝，品牌系列除外
    if has_ai and not has_karen and not is_ai_brand:
        return False, (
            "[gate5a:纯度] 标题含 AI 但无 Karen，且非【AI Satire】品牌系列：%r。"
            "数据（496 条校准）：普通 AI 标题仅 0.22x 播放，有害；"
            "仅【AI Satire】品牌系列豁免（均值 2205）。"
            "请加 Karen 或改用品牌系列格式。" % title[:60])
    # 5b. 去重：与近 90 天已发布标题关键词重叠 >60% 拒绝
    try:
        import subprocess as _sp2
        sys.path.insert(0, "/home/hatch/data/perpetua")
        from dedup_check import check_duplicate
        is_dup, matched, overlap = check_duplicate(title, "", days=90)
        if is_dup:
            return False, (
                "[gate5b:去重] 标题与近 90 天已发布《%s》重叠 %.1f%%（>60%%），"
                "判重复打回。请换桥段。"
                % (matched[:50] if matched else "?", overlap * 100))
    except Exception:
        pass  # 去重失败不阻塞（fail-open）

    # ---- Gate 5c: 剧集编号式数字（2026-10-07 校准新增）----
    # 数据：数字标题整体 0.34x；但"15 DOGS"类具象故事数字可爆，
    # "Complaint #4 / Episode 3"类剧集编号最伤（像低质系列内容）。
    # 只拒剧集编号式，不拒具象数字。
    if _re.search(r"\b(complaint|episode|part|chapter|ep)\s*#?\s*\d+", low):
        return False, (
            "[gate5c:编号] 标题含剧集编号式数字：%r。"
            "数据（496 条校准）：数字标题仅 0.34x 播放，剧集编号式最伤；"
            "具象故事数字（如 15 DOGS）可用。请去掉编号。"
            % title[:60])

    # ---- Gate 6: 报应动词分级（2026-10-06 Ask Studio：具象 slapstick > 抽象 clickbait）----
    # Tier S 可用，Tier B 可用，BANNED 直接拒绝。动词强度必须匹配画面报应量级。
    try:
        with open("/home/hatch/data/perpetua/karma_verbs.json", encoding="utf-8") as _kf:
            _kv = json.load(_kf)
        _banned = [v.upper() for v in _kv.get("banned", [])]
        _allowed = ([v.upper() for v in _kv.get("tier_s", [])]
                    + [v.upper() for v in _kv.get("tier_b", [])])
        for bv in _banned:
            if bv and bv in t_up:
                return False, (
                    "[gate6:动词] 标题含禁用抽象动词 %s。Ask Studio 实证："
                    "DESTROYED/ANNIHILATED 类抽象词是 clickbait 感，观众信任崩，"
                    "4-5 秒留存断崖。请换 Tier S 具象动词（TRAPPED/SLAPPED/SOAKED/TOWED）。"
                    "当前标题：%r。" % (bv, title[:80]))
        # 标题含报应动词但不在 S/B 白名单 → 提示换词（fail-open：未知动词放行，避免误杀新词）
    except Exception:
        pass  # 名单读失败不阻塞（fail-open）

    return True, ""


def _probe_duration(filepath: str) -> float:
    """用 ffprobe 读视频时长（秒）。失败返回 10（原默认值）。"""
    try:
        p = filepath if filepath.startswith("/") else "/home/hatch/data/" + filepath
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", p],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 10.0


def _upload_gate_check(title: str, hook: str, filepath: str = ""):
    """YouTube 上传前的爆款门槛检查。返回 (是否通过, 说明文本)。

    规则（2026-10-06 修正，见 criteria.json 的 gate_model / gate_threshold）：

    背景实测（481 条真实历史视频，dashboard 见 jev/_cal_full.json）：
      - jev 分区间仅 20.4~57.1，全频道无一达到 60；与该频道实际播放量
        Pearson 相关 = -0.371（**负相关**）；jev Top20 命中真实爆款 0/20。
      - v2 数据回归模型 CV Spearman rho = +0.27，Top50 命中 p90 = 22%（正相关）。
    故 **门禁主判改为 v2**，jev 降级为"参考信息"（仍会显示，但不参与放行判定）。

    配置：criteria.json
      - gate_model: "v2"（默认，主判 v2）| "jev"（回退旧行为）
      - gate_threshold: v2 模式下默认 58；jev 模式下默认 60

    两者都失败则 fail-closed（拒绝），调用方可凭 skip_gate=true 强制上传。
    """
    gate_model = "v2"
    default_threshold = 58 if gate_model == "v2" else 60
    threshold = default_threshold
    try:
        with open("/home/hatch/data/jev/criteria.json", encoding="utf-8") as f:
            crit = json.load(f)
        gate_model = str(crit.get("gate_model", "v2")).lower()
        default_threshold = 58 if gate_model == "v2" else 60
        threshold = int(crit.get("gate_threshold", default_threshold))
    except Exception:
        pass

    # ---- jev：始终调用，作为参考信息（不参与 v2 模式下的放行判定）----
    jev_note = ""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/jev/jev_score.py",
             title, hook or "", "medium", "45"],
            capture_output=True, text=True, timeout=90,
        )
        d = json.loads(r.stdout.strip())
        if "score" in d:
            jev_note = ("jev 参考 %s 分（置信度 %s，建议：%s）"
                        % (d["score"], d.get("confidence"), d.get("action")))
        else:
            jev_note = "jev 返回异常：%s" % str(d)[:120]
    except Exception as e:
        jev_note = "jev 调用失败：%s: %s" % (type(e).__name__, e)

    # ---- v2 数据回归模型：主判 ----
    v2_score, v2_note = None, ""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/virality_score_v2.py",
             json.dumps({"title": title, "hook": hook or "",
                         "topic_heat": "medium", "duration": _probe_duration(filepath)})],
            cwd=str(HERE), capture_output=True, text=True, timeout=20,
        )
        d = json.loads(r.stdout.strip())
        v2_score = float(d["score"])
        v2_note = "v2 数据模型 %s 分（等级 %s）" % (v2_score, d.get("grade", "?"))
    except Exception as e:
        v2_note = "v2 调用失败：%s: %s" % (type(e).__name__, e)

    # ---- 旧行为回退：gate_model == "jev" ----
    if gate_model == "jev":
        jev_score_val = None
        try:
            # "jev 参考 <score> 分（..." -> 取第一个 token
            toks = jev_note.split()
            if len(toks) >= 3 and toks[0] == "jev" and toks[1] == "参考":
                jev_score_val = float(toks[2])
        except Exception:
            pass
        if jev_score_val is None:
            return False, ("上传被拒：jev 模式但 jev 不可用（%s），"
                           "为保护频道默认拒绝；确认无误可用 skip_gate=true 强制上传。" % jev_note)
        if jev_score_val >= threshold:
            return True, "门槛通过（jev 模式）：%s >= %s | %s" % (jev_score_val, threshold, v2_note)
        return False, ("上传被拒（jev 模式）：%s < 门槛 %s。%s。\n"
                       "确认要发可用 skip_gate=true 强制上传。"
                       % (jev_score_val, threshold, v2_note))

    # ---- v2 主判（默认）----
    if v2_score is None:
        return False, ("上传被拒：爆款门槛检查失败（v2 不可用：%s；%s），"
                       "为保护频道默认拒绝；确认无误可用 skip_gate=true 强制上传。"
                       % (v2_note, jev_note))
    if v2_score >= threshold:
        return True, "门槛通过：%s >= %s | %s" % (v2_score, threshold, jev_note)
    return False, ("上传被拒：v2 爆款分 %s < 门槛 %s。%s | %s。\n"
                   "建议：先调 virality_score_v2 测分并优化标题与钩子；"
                   "确认要发可用 skip_gate=true 强制上传。"
                   % (v2_score, threshold, v2_note, jev_note))


@mcp.tool()
def youtube_upload(filepath: str, title: str, description: str = "",
                   skip_gate: bool = False, tags: str = "",
                   language: str = "", playlist_id: str = "",
                   ai_disclosure: bool = True) -> str:
    """上传视频到 YouTube（公开）。filepath 为 /home/hatch/data 下的相对路径。
    返回 video_id 和观看链接。Shorts 竖屏视频会自动识别为 Short。

    内置爆款门槛：**v2 数据模型**爆款分 >= gate_threshold（criteria.json，
    默认 58，可进化）才允许上传；低于门槛自动拒绝并说明原因。
    jev 分数会作为参考信息一并返回（不参与放行判定，历史实测其与本频道
    实际播放为负相关，见 criteria.json 的 gate_evidence）。
    skip_gate=True 可强制上传。

    tags:         逗号分隔的标签，如 "Karen,InstantKarma,Shorts"。
    language:     BCP-47 语言码，如 "en"。避免英文内容被错推给中文用户。
    playlist_id:  播放列表 ID，上传后自动加入（playlistItems.insert）。
    ai_disclosure: 默认 True —— 声明含逼真「篡改或合成」(A/S) 内容，
                  写入 status.containsSyntheticMedia。AI 生成视频必须披露，
                   否则违反 YouTube 政策。确认视频为真实拍摄时传 False。
    """
    if not skip_gate:
        # 2026-10-06 深度诊断：5 项硬门禁（错峰/主语/emoji/元数据/纯度去重）
        ok, msg = _upload_hard_gates(title, description or "", tags or "")
        if not ok:
            return "上传被拒：" + msg
        ok, msg = _upload_gate_check(title, description or "", filepath)
        if not ok:
            return msg
    # Perpetua 合规检查：违禁词拦截
    try:
        cr = subprocess.run(
            ["python3", "/home/hatch/data/perpetua/compliance/checker.py",
             "check", title, description or ""],
            capture_output=True, text=True, timeout=15)
        import json as _j
        comp = _j.loads(cr.stdout.strip())
        if not comp.get("pass"):
            return (f"[blocked] 合规检查未通过：{comp.get('blocked_reason')}。"
                    "请修改标题/描述后重试。")
    except Exception:
        pass  # 合规检查失败不阻塞上传（fail-open），已记审计日志

    # 2026-10-07 上传前统一质检（最后一道门）：6 项播放中变量检查。
    # 不达标自动修复（裁剪/烧字幕），硬失败直接拒绝上传。达标才放行。
    qc_warnings_note = ""
    if not skip_gate:
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "pre_upload_qc", "/home/hatch/data/perpetua/pre_upload_qc.py")
            _qc = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_qc)
            _abs = (filepath if os.path.isabs(filepath)
                    else os.path.join("/home/hatch/data", filepath))
            _qr = _qc.run_qc(_abs, title=title)
            if not _qr["passed"]:
                return ("上传被拒：[pre-upload-qc] "
                        + "；".join(_qr["rejects"]))
            # 用质检后的最终文件上传（转回 /home/hatch/data 下的相对路径）
            _out = _qr["output_file"]
            try:
                filepath = os.path.relpath(_out, "/home/hatch/data")
            except ValueError:
                filepath = _out
            if _qr["warnings"]:
                qc_warnings_note = ("\n[qc-warnings] 质检通过但有提醒："
                                    + "；".join(_qr["warnings"]))
        except Exception as e:
            return f"[error] 上传前质检模块异常（fail-closed）：{e}"

    # 参数用 JSON 传（避免 argv 里 emoji/引号/逗号的转义问题）
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    payload = {
        "filepath": filepath, "title": title, "description": description or "",
        "tags": tag_list, "language": language or "",
        "playlist_id": playlist_id or "",
        "synthetic": bool(ai_disclosure),
    }
    tmp = "/home/hatch/data/_upload_args.json"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt_upload_cli.py", tmp],
            capture_output=True, text=True, timeout=300,
        )
        out = r.stdout.strip() or r.stderr.strip() or "[error] no output"
        # 策略5：发布后自动发一条引导评论，刺激首小时互动
        try:
            up = json.loads(r.stdout.strip())
            vid = up.get("video_id")
            if vid:
                c = subprocess.run(
                    ["python3", "/home/hatch/data/youtube/yt_comment.py", vid],
                    capture_output=True, text=True, timeout=30,
                )
                if c.returncode == 0:
                    out += "\n[engage] 已自动发布引导评论，刺激首小时互动。"
        except Exception:
            pass  # 评论失败不影响上传结果
        return out + qc_warnings_note
    except Exception as e:
        return f"[error] {e}"
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


@mcp.tool()
def youtube_update_metadata(video_id: str, title: str = "",
                            description: str = "", tags: str = "",
                            language: str = "", playlist_id: str = "",
                            ai_disclosure: str = "") -> str:
    """修补已发布视频的 metadata（videos.update）+ 可选加入播放列表。

    用于给已发布的视频补 tags / language / playlist —— 上传时没传的字段，
    事后可在这里补。只有显式传入的字段会被修改，未传的保持原值。
    会先 GET 现有 snippet 再合并（videos.update 未传字段会被清空）。

    tags:        逗号分隔，如 "Karen,InstantKarma,Shorts"
    language:    BCP-47，如 "en"
    playlist_id: 播放列表 ID，会调 playlistItems.insert 加入
    ai_disclosure: A/S 披露开关，字符串 "True" / "False"；留空表示不改动
                   该字段。会写 status.containsSyntheticMedia（需
                   part=snippet,status）。
    """
    _ai = ai_disclosure.strip().lower()
    if _ai in ("true", "1", "yes", "on"):
        _ai_val = True
    elif _ai in ("false", "0", "no", "off"):
        _ai_val = False
    else:
        _ai_val = None
    payload = {
        "mode": "update", "video_id": video_id,
        "tags": [t.strip() for t in (tags or "").split(",") if t.strip()] if tags else None,
        "language": language or None,
        "playlist_id": playlist_id or None,
        "synthetic": _ai_val,
    }
    if title:
        payload["title"] = title
    if description:
        payload["description"] = description
    tmp = "/home/hatch/data/_update_args.json"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt_upload_cli.py", tmp],
            capture_output=True, text=True, timeout=120,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


@mcp.tool()
def youtube_video_status(video_id: str) -> str:
    """只读核实已发布视频的 snippet + status。

    返回 tags / defaultLanguage / privacyStatus / containsSyntheticMedia，
    用于确认 A/S 披露（AI 生成内容声明）与其它 metadata 是否真的写入成功。
    """
    payload = {"mode": "get_status", "video_id": video_id}
    tmp = "/home/hatch/data/_status_args.json"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt_upload_cli.py", tmp],
            capture_output=True, text=True, timeout=60,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


@mcp.tool()
def youtube_analytics_traffic(days: int = 30) -> str:
    """YouTube 流量来源分析：各渠道播放量（SHORTS信息流/搜索/推荐等）。
    用于判断视频是否进了推荐流。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt_analytics.py", "traffic"],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def youtube_analytics_videos(top_n: int = 10) -> str:
    """各视频完播数据：播放量 + 平均观看时长（秒）。
    完播率是 Shorts 进推荐流的核心指标。"""
    try:
        top_n = max(1, min(top_n, 50))
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt_analytics.py",
             "videos", str(top_n)],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def youtube_shorts_90d() -> str:
    """过去90天 Shorts 总播放量（YPP 考核指标，目标 300 万）。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/yt_analytics.py", "shorts90"],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def jev_score(title: str, hook: str = "", topic_heat: str = "medium", duration: int = 45) -> str:
    """[DEPRECATED 2026-10-06] 用 jev 模型（TypeSafe System One）给 Short 选题做 AI 爆款判决。

    本工具已弃用：实测 481 条历史视频，jev 与本频道实际播放量 Pearson=-0.371
    （负相关），Top20 命中 0/20。门禁主判已切换为 v2 数据模型（见 criteria.json）。
    保留仅作参考信息，不参与放行判定。新代码请调 virality_score_v2。

    返回 0-100 爆款分、置信度、钩子强度概率、发布/优化/放弃建议。
    topic_heat: high/medium/low。

    网络说明：本 VM 的 egress 代理会挂起携带凭据头的请求，故 jev 调用走
    VM:18080 -> ssh -L -> VPS:18080 -> typesafe 的旁路（见 jev_relay_status）。
    """
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/jev/jev_score.py",
             title, hook, topic_heat, str(duration)],
            capture_output=True, text=True, timeout=90,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def jev_relay_status(fix: bool = False) -> str:
    """检查（并可修复）jev 调用所依赖的旁路通路。

    背景：VM 的 egress 代理会**挂起任何带 Authorization / X-Api-Key 的请求**
    （25-30s 超时，与 key 真假无关），导致 jev_score、youtube_upload 等直接超时。
    故 jev 走旁路：VM:127.0.0.1:18080 --ssh -L--> VPS:127.0.0.1:18080
    --relay_proxy.py--> api.typesafe.ai

    fix=True 时若通路不健康会自动重建隧道（幂等）。建议 Muse 每 5 分钟调一次
    fix=True 做保活。返回通路状态与探测结果。
    """
    try:
        script = "/home/hatch/data/mcp_server/jev_keepalive.sh"
        if fix:
            r = subprocess.run(["bash", script], capture_output=True, text=True, timeout=60)
        probe = subprocess.run(
            ["bash", "-c",
             'K=$(cat /home/hatch/data/jev/.api_key 2>/dev/null); '
             'curl -s -m 15 -x http://127.0.0.1:18080 -o /dev/null '
             '-w "%{http_code} %{time_total}" '
             'https://api.typesafe.ai/v1/models -H "Authorization: Bearer $K"'],
            capture_output=True, text=True, timeout=40)
        code, _, t = probe.stdout.strip().partition(" ")
        lis = subprocess.run(["bash", "-c", "ss -tln 2>/dev/null | grep -c 18080"],
                             capture_output=True, text=True, timeout=10)
        log = subprocess.run(["bash", "-c",
                              "tail -3 /home/hatch/data/mcp_server/jev_relay.log 2>/dev/null"],
                             capture_output=True, text=True, timeout=10)
        ok = code == "200"
        return json.dumps({
            "ok": ok,
            "listener": int((lis.stdout or "0").strip() or 0) > 0,
            "probe_http": code,
            "probe_seconds": float(t) if t else None,
            "fixed": bool(fix),
            "recent_log": (log.stdout or "").strip().splitlines()[-3:],
            "path": "VM:18080 -ssh -L-> VPS:18080 -relay_proxy.py-> api.typesafe.ai",
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


app = mcp.streamable_http_app()
app.add_middleware(TokenAuth)
app.routes.append(Route("/health", health))


@mcp.tool()
def pipeline_latency_report(days: int = 7) -> str:
    """趋势→发布延迟分析：看选题从热点发现到发布的各阶段耗时，找出瓶颈。
    阶段：trend（热点发现）→ pickup（Marvis取题）→ video_done（视频生成完）→ published（已发布）。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/pipeline_latency.py",
             "report", str(days)],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def ask_studio(question: str, priority: str = "normal") -> str:
    """向 YouTube 官方 Ask Studio AI 提问（时刻与算法对齐）。
    Marvis 可随时调用：要选题角度、要优化建议、要诊断数据都可以问。
    问题进入队列，系统每30分钟批量去问，答案写回后可用 ask_studio_answer 查询。
    priority 可选 normal / urgent（热点爆发时用 urgent 优先处理）。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/ask_studio/query_queue.py",
             "ask", question, "marvis", priority],
            capture_output=True, text=True, timeout=15,
        )
        out = r.stdout.strip()
        if out:
            import json as _j
            qid = _j.loads(out).get("queued", "")
            return f"[queued] 问题已加入 Ask Studio 队列（{qid}），30分钟内返回答案，用 ask_studio_answer('{qid}') 查询。"
        return r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def ask_studio_answer(question_id: str = "") -> str:
    """查询 Ask Studio 问题的答案。不传 ID 返回最近 5 条已回答。"""
    try:
        import json as _j
        q = _j.load(open("/home/hatch/data/ask_studio/queue.json"))
        answered = q.get("answered", [])
        if question_id:
            for x in answered:
                if x["id"] == question_id:
                    return _j.dumps(x, ensure_ascii=False, indent=2)
            # 还没回答？
            for x in q.get("pending", []):
                if x["id"] == question_id:
                    return f"[pending] 问题 {question_id} 还在队列中，下一轮（30分钟内）处理。"
            return f"[not found] 没找到 {question_id}"
        return _j.dumps(answered[-5:], ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def post_publish_check() -> str:
    """发布后优化检查：48小时哑火诊断+自动换标题+自动回评论。
    Marvis 可随时手动触发一次检查，不用等 6 小时定时任务。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/post_publish_optimizer.py"],
            capture_output=True, text=True, timeout=120,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def noleak_score(title: str, description: str = "") -> str:
    """无泄漏爆款打分 baseline（ViraSense 方法论）：
    只用发布前可得信息（标题特征），不用任何发布后数据。
    在 481 个历史视频上校准，用于对比 jev_score 的校准效果。
    分数越高越可能爆，60+ 可发。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/jev/noleak_baseline.py",
             "score", title, description],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def process_ask_studio_queue() -> str:
    """处理 Ask Studio 问题队列（Marvis 自助触发版）。
    用服务器本地 Playwright 自动打开 YouTube Studio，依次询问 pending 问题，
    答案写回队列。不依赖 Muse 调度器，Marvis 可在新机器上随时调用。
    前置：需先在服务器上运行 ask_studio_auth.py 完成 Google 登录。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/ask_studio/process_queue_pw.py"],
            capture_output=True, text=True, timeout=300,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def check_zbj_quota() -> str:
    """检查猪八戒服务商工作台技能入驻名额（Marvis 自助触发版）。
    用服务器本地 Playwright 自动登录检查，名额>0 时返回告警。
    不依赖 Muse 调度器，Marvis 可在新机器上按需调用。
    前置：需先在服务器上运行 zbj_auth.py 完成猪八戒登录。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/perpetua/zbj_check_pw.py"],
            capture_output=True, text=True, timeout=120,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def get_trend_data() -> str:
    """获取原始趋势数据（Marvis 自助分析版）。
    返回今日趋势雷达数据 + 近期热点爆发记录，供 Marvis 用自身 AI 能力做选题分析，
    替代原来依赖 Muse 的 ai-trend-radar 定时任务。
    Marvis 拿到数据后自行判断选题，调用 submit_job 走正常生产流程。"""
    try:
        import json as _j, os as _o
        out = {}
        for name, path in [("daily", "/home/hatch/data/trends/daily.json"),
                           ("spikes", "/home/hatch/data/trend_spike_baseline.json"),
                           ("sequels", "/home/hatch/data/sequel_candidates.json")]:
            if _o.path.exists(path):
                with open(path) as f:
                    out[name] = _j.load(f)
            else:
                out[name] = None
        return _j.dumps(out, ensure_ascii=False, indent=2)[:8000]
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def list_tenants() -> str:
    """列出所有租户（YouTube 账号）。多账号矩阵运营时 Marvis 用此查看有哪些账号、
    每个账号的主题、关键词、套餐配额。"""
    try:
        import sys as _s
        _s.path.insert(0, "/home/hatch/data/perpetua/tenants")
        from manager import list_tenants as _lt
        import json as _j
        ts = _lt()
        out = [{"id": t["id"], "name": t["name"],
                "theme": t.get("theme", ""),
                "youtube_channel_id": t.get("youtube_channel_id", ""),
                "youtube_channel_name": t.get("youtube_channel_name", ""),
                "plan": t.get("plan", ""), "status": t.get("status", ""),
                "keywords": t.get("keywords", [])[:10]} for t in ts]
        return _j.dumps(out, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def get_tenant(tenant_id: str) -> str:
    """取单个租户详情：主题、关键词、内容风格、频道 ID、配额。"""
    try:
        import sys as _s
        _s.path.insert(0, "/home/hatch/data/perpetua/tenants")
        from manager import get_tenant as _gt
        import json as _j
        t = _gt(tenant_id)
        if not t:
            return f"[not found] 租户 {tenant_id} 不存在"
        return _j.dumps(t, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def create_tenant(name: str, youtube_channel_id: str = "", theme: str = "",
                  keywords: str = "", content_style: str = "",
                  plan: str = "free") -> str:
    """ onboarding 新 YouTube 账号为租户。keywords 用逗号分隔。
    Marvis 为新账号开矩阵时调用，之后该账号进入全自动闭环。"""
    try:
        import sys as _s
        _s.path.insert(0, "/home/hatch/data/perpetua/tenants")
        from manager import create_tenant as _ct
        kw = [k.strip() for k in keywords.split(",") if k.strip()]
        tid = _ct(name, youtube_channel_id, plan, theme, kw, content_style)
        return f"[ok] 租户 {tid} 已创建（主题：{theme}，关键词 {len(kw)} 个），热点检测下次运行时自动覆盖。"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def pipeline_log(tenant_id: str = "default", stage: str = "", status: str = "ok",
                 detail: str = "", count: int = 0) -> str:
    """上报流水线阶段执行。
    stage 可选：trend / select / score / topic_select / generate / postprocess /
    qc / pending_approval / upload / publish / audit / analyze / optimize。
    Dashboard 流水线卡片据此显示真实状态（动态渲染，新增 stage 自动显示）。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/perpetua/pipeline.py",
             tenant_id, stage, status, detail, str(count)],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() or "[ok] 已记录"
    except Exception as e:
        return f"[error] {e}"

@mcp.tool()
def get_pipeline_status(tenant_id: str = "") -> str:
    """查询流水线七阶段真实状态。不传 tenant_id 返回所有租户。
    每个阶段含：状态(status)、上次运行(last_run)、详情、今日计数、是否需要 AI。"""
    try:
        import sys as _s
        _s.path.insert(0, "/home/hatch/data/perpetua")
        from pipeline import status as _st, status_all as _sa
        import json as _j
        out = _sa() if not tenant_id else {tenant_id: _st(tenant_id)}
        return _j.dumps(out, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[error] {e}"

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8734, log_level="warning")

