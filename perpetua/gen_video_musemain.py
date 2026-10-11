#!/usr/bin/env python3
"""主 Muse 视频生成后端（2026-10-10 接入，替代 GeminiGen / GMI / Vids）。

调用链：
  本机 → VPS dispatcher (http://192.166.82.123:8740/mcp, backend=b)
  → MCP initialize（Accept: application/json, text/event-stream + mcp-session-id 会话头）
  → tools/call submit_job(job_type="generate_video", consumer="muse-main", payload=JSON字符串)
  → tools/call job_status 轮询
  → VPS /opt/mcp-b/data/output/<muse_job_id>/ 下的 mp4 → scp 回本机 videos/

公开 API：
  submit(prompt_text, job_id) -> muse_job_id
  check(muse_job_id) -> ("done", 本机mp4路径) | ("pending", None) | ("failed", 原因)
  poll(muse_job_id, timeout_min=30) -> 本机mp4路径（阻塞；失败抛异常）

约束（硬）：
  - dispatcher key 只从 /home/hatch/data/mcp_server/.token-dash-dispatcher 读取，
    不打印、不记日志、不写任何文件。
  - instruction 禁止出现 "Karen"（沿用 GeminiGen 绕行措辞；v5.2 模板已替换，
    这里做防御性二次替换）。
  - muse-main 每日预算 500/天，调用方自行节流（管线侧：每天 ≤3 条测试外按排期来）。
"""
import json
import os
import re
import subprocess
import tempfile
import time
import uuid

DISPATCHER_PATH = "/home/hatch/data/mcp_server/.token-dash-dispatcher"
VPS_HOST = "root@192.166.82.123"
VPS_OUTPUT_BASE = "/opt/mcp-b/data/output"
LOCAL_VIDEO_DIR = "/home/hatch/data/perpetua/videos"
SSH_BASE = [
    "ssh", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
    "-o", "StrictHostKeyChecking=no",
    "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
    VPS_HOST,
]
HDR = ["-H", "Content-Type: application/json",
       "-H", "Accept: application/json, text/event-stream"]


class MuseMainError(Exception):
    pass


def _read_key():
    with open(DISPATCHER_PATH, encoding="utf-8") as f:
        return f.read().strip()


def _sanitize_instruction(text):
    # 防御性替换：绝不让 "Karen" 进入 instruction
    return re.sub(r"\bKaren\b", "the entitled woman", text)


def _rpc(method, params, session, retries=3):
    """MCP HTTP 调用（带重试）。

    2026-10-10 诊断：本机→VPS 经 egress 代理的 SSE 响应约 20% 间歇性丢包/
    截断（curl exit 18/52），dispatcher 服务端正常。失败自动重试：
      - 读操作（initialize/job_status）天然幂等；
      - submit_job 由 dispatcher 侧 idempotency_key 去重（同一 body 重发
        只返回首次 job_id，不重复建 job），重试安全。
    """
    body = {"jsonrpc": "2.0", "id": session["req"], "method": method,
            "params": params}
    session["req"] += 1
    # headers 落临时文件（不用 -D - 并入 stdout，避免 header 行干扰 data: 解析）
    fd, hdr_file = tempfile.mkstemp(prefix="mcp-hdr-")
    os.close(fd)
    try:
        last_err = ""
        for attempt in range(retries):
            try:
                cmd = ["curl", "-s", "-m", "40", "--dump-header", hdr_file,
                       "-X", "POST", session["url"]] + HDR
                if session["sid"]:
                    cmd += ["-H", f"mcp-session-id: {session['sid']}"]
                cmd += ["-d", json.dumps(body)]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                out = r.stdout
                with open(hdr_file, encoding="utf-8", errors="replace") as f:
                    hdrs = f.read()
                m = re.search(r"(?im)^mcp-session-id:\s*(\S+)", hdrs)
                if m:
                    session["sid"] = m.group(1)
                data_lines = [l[5:].strip() for l in out.splitlines()
                              if l.startswith("data:")]
                if not data_lines:
                    raise MuseMainError(f"dispatcher 无响应 ({method})")
                try:
                    return json.loads(data_lines[-1])
                except Exception:
                    raise MuseMainError(
                        "dispatcher 返回非 JSON (%s): %s"
                        % (method, data_lines[-1][:120]))
            except MuseMainError as e:
                last_err = str(e)
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise MuseMainError("%s（已重试 %d 次）" % (last_err, retries))
    finally:
        try:
            os.remove(hdr_file)
        except OSError:
            pass


def _new_session():
    key = _read_key()
    session = {"url": f"http://192.166.82.123:8740/mcp?key={key}&backend=b",
               "sid": None, "req": 1}
    res = _rpc("initialize",
               {"protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "dash-gen-video", "version": "1.0"}},
               session)
    if "result" not in res:
        raise MuseMainError(f"initialize 失败: {str(res)[:200]}")
    return session


def _tool_call(session, name, arguments):
    res = _rpc("tools/call", {"name": name, "arguments": arguments}, session)
    try:
        txt = res["result"]["content"][0]["text"]
    except Exception:
        raise MuseMainError(f"tools/call {name} 返回异常: {str(res)[:200]}")
    try:
        return json.loads(txt)
    except Exception:
        raise MuseMainError(f"tools/call {name} 非 JSON 结果: {txt[:200]}")


def submit(prompt_text, job_id):
    """提交生成任务。返回 muse 侧 job_id。失败抛 MuseMainError。"""
    session = _new_session()
    instruction = _sanitize_instruction(prompt_text)
    payload = {
        # 2026-10-10 补：muse-main 侧 cron 上下文要求任务明确声明视频数量，
        # 否则按管线规范生成 0 个视频。每次提交只生成 1 个。
        "video_count": 1,
        "instruction": ("本次请求生成 1 个视频（video_count=1）。用内置多媒体视频管线生成"
                        "竖屏 9:16 短视频（约8秒，h264+aac mp4）。场景描述如下：\n"
                        + instruction),
        "purpose": "perpetua 管线正式生成",
        "from": "dash",
        "idempotency_key": f"dash-pipe-{job_id}-{uuid.uuid4().hex[:6]}",
    }
    out = _tool_call(session, "submit_job", {
        "job_type": "generate_video",
        "consumer": "muse-main",
        "payload": json.dumps(payload, ensure_ascii=False),
        "idempotency_key": payload["idempotency_key"],
    })
    muse_jid = out.get("job_id")
    if not muse_jid:
        raise MuseMainError(f"submit_job 未返回 job_id: {str(out)[:200]}")
    return muse_jid


def _fetch_mp4(muse_job_id, rel_path):
    """从 VPS 取回 mp4。返回本机路径。"""
    os.makedirs(LOCAL_VIDEO_DIR, exist_ok=True)
    remote = f"{VPS_OUTPUT_BASE}/{muse_job_id}/{os.path.basename(rel_path)}"
    local = os.path.join(LOCAL_VIDEO_DIR, f"{muse_job_id}.mp4")
    r = subprocess.run(
        ["scp", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
         "-o", "StrictHostKeyChecking=no",
         "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
         f"{VPS_HOST}:{remote}", local],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(local):
        raise MuseMainError(f"scp 取回失败 {remote}: {r.stderr[-200:]}")
    return local


def _check_via_ssh(muse_job_id):
    """SSH 直读 dispatcher 任务文件（transport 降级时的只读兜底）。

    只读远端文件，不写任何状态。返回与 job_status 同形的 dict，
    找不到返回 {}。
    """
    if not re.fullmatch(r"[\w-]+", muse_job_id):
        raise MuseMainError(f"非法 job_id: {muse_job_id[:40]}")
    # 纯 shell（ssh 会把参数拼成整串交远端 shell，避免 python -c 嵌套引号问题）
    sh = ("for f in /opt/mcp-b/data/mcp_jobs/done/%s.result.json "
          "/opt/mcp-b/data/mcp_jobs/pending/%s*.json "
          "/opt/mcp-b/data/mcp_jobs/done/%s.json; do "
          "[ -f \"$f\" ] && { cat \"$f\"; break; }; done"
          % (muse_job_id, muse_job_id, muse_job_id))
    r = subprocess.run(SSH_BASE + [sh],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        raise MuseMainError(f"ssh 状态查询失败: {r.stderr[-120:]}")
    try:
        return json.loads(r.stdout.strip())
    except Exception:
        raise MuseMainError("ssh 状态查询返回非 JSON")


def check(muse_job_id):
    """单次状态查询。
    返回 ("done", 本机mp4路径) | ("pending", None) | ("failed", 原因字符串)。
    MCP transport 连续失败时降级为 SSH 直读（只读兜底）；仍失败才抛
    MuseMainError（调用方视为 transient，可下轮重试）。
    """
    try:
        session = _new_session()
        st = _tool_call(session, "job_status", {"job_id": muse_job_id})
    except MuseMainError:
        st = _check_via_ssh(muse_job_id)
        if not st:
            raise MuseMainError(f"job 不存在（API+SSH 均无结果）: {muse_job_id}")
    status = str(st.get("status", "")).lower()
    if status in ("done", "completed", "succeeded"):
        rel = st.get("file") or ""
        if not rel:
            return ("failed", "done 但结果无 file 字段")
        local = _fetch_mp4(muse_job_id, rel)
        return ("done", local)
    if status in ("failed", "error"):
        return ("failed", str(st.get("error") or st.get("note") or "muse-main 侧失败")[:300])
    return ("pending", None)


def poll(muse_job_id, timeout_min=30, interval_sec=60):
    """阻塞等待完成。返回本机 mp4 路径；失败/超时抛 MuseMainError。"""
    deadline = time.time() + timeout_min * 60
    last = "pending"
    while time.time() < deadline:
        state, info = check(muse_job_id)
        last = state
        if state == "done":
            return info
        if state == "failed":
            raise MuseMainError(f"生成失败: {info}")
        time.sleep(interval_sec)
    raise MuseMainError(f"等待超时 ({timeout_min}min)，最后状态={last}")


if __name__ == "__main__":
    import sys
    # 用法：python3 gen_video_musemain.py --submit <prompt_file> <job_id>
    #       python3 gen_video_musemain.py --poll <muse_job_id> [timeout_min]
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--submit":
        prompt = open(sys.argv[2], encoding="utf-8").read()
        jid = sys.argv[3] if len(sys.argv) > 3 else f"manual-{uuid.uuid4().hex[:6]}"
        print(submit(prompt, jid))
    elif sys.argv[1] == "--poll":
        tm = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        print(poll(sys.argv[2], timeout_min=tm))
