#!/usr/bin/env python3
"""笔记本 Muse MCP 直调生成后端（2026-10-28 试跑沉淀）。

用途：管线生成后端之一，绕开卡死的 muse-main 队列，直接经 Tailscale 调
笔记本 muse 服务的 muse_video 生成 Shorts 成片，再挂回 ops_center.db 队列条目。

关键教训（2026-10-28 实证）：
- 管线 11k 字模板原文直送必被服务端 integrity_check_failed 拒绝；
  必须先浓缩成 400 字左右的故事 prompt（去模板元指令、正则黑名单、矛盾镜头指令）。
- muse_video 同步阻塞，单段约 10 秒，实测 76-81 秒出片；segments=1。
- key 不进本文件：读 /home/hatch/data/laptop_muse_mcp/api_key（600 权限）。

流程（失败时绝不写库）：
  1. 读 event_bus 指定 id 的 payload，全量备份到 workspace/muse_control_test/；
  2. 调 muse_video（account 默认体检通过的 morgan 号，可 --account 覆盖）；
  3. 成功后把成片拉回 /home/hatch/data/veo_inbox/<name>_YYYYMMDD.mp4；
  4. 更新条目：prompt=浓缩版、video_file=拉回路径、clip_source 备注；
     status / title / 后端字段一律不动，成片仍走正常手工 QC/派发路。

用法：
  python3 laptop_mcp_generate.py --id 3576 --name photobooth --prompt-file /path/to/condensed.txt
  python3 laptop_mcp_generate.py --id 3576 --name photobooth --prompt "Vertical short video..."
"""
import argparse
import base64
import http.client
import json
import os
import sqlite3
import sys
from urllib.parse import urlparse

KEY_FILE = "/home/hatch/data/laptop_muse_mcp/api_key"
DB = "/home/hatch/data/ops_center.db"
MCP_HOST = "laptop-cgb2026-1.tail5c5fad.ts.net"
BACKUP_DIR = os.path.expanduser("~/workspace/muse_control_test")
VEO_INBOX = "/home/hatch/data/veo_inbox"
# 2026-10-28 新增：直连端点模式。MCP_ENDPOINT 形如
# https://8101-<box>.instabox.tech/mcp 时直连，不走 Tailscale 隧道；
# 未设置时沿用旧的 Tailscale 直调路。MCP_API_KEY 覆盖文件 key，
# 仅瞬时使用，脚本本身永不写 key 到任何文件或日志。
DIRECT_ENDPOINT = os.environ.get("MCP_ENDPOINT", "")


QQBOX_KEY_FILE = "/home/hatch/data/laptop_muse_mcp/api_key_qqbox"


def get_key():
    if os.environ.get("MCP_API_KEY", ""):
        return os.environ["MCP_API_KEY"]
    if DIRECT_ENDPOINT and os.path.exists(QQBOX_KEY_FILE):
        return open(QQBOX_KEY_FILE).read().strip()
    return open(KEY_FILE).read().strip()


def open_conn(timeout):
    # 本机出网一律走运行时出口代理 CONNECT（直连 TLS 会被透明代理挡，
    # 报 SSL WRONG_VERSION_NUMBER）；直连端点与 Tailscale 模式只差隧道目标。
    px = urlparse(os.environ.get("HTTPS_PROXY", ""))
    auth = "Basic " + base64.b64encode((px.username + ":" + px.password).encode()).decode()
    if DIRECT_ENDPOINT:
        u = urlparse(DIRECT_ENDPOINT)
        if u.scheme == "http":
            # 本地 SSH 隧道直达（127.0.0.1:8748 等）：明文 HTTP，不走出口代理。
            return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout), u.path
        # MCP_PROXY_PORT 可覆盖出口代理端口（2026-10-28 实测：3128 路视频
        # 调用约 21 秒空 502，改 3130 隧道代理对照截断点是否在代理层）。
        pport = int(os.environ.get("MCP_PROXY_PORT", "0") or 0) or px.port or 3128
        conn = http.client.HTTPSConnection(px.hostname, pport, timeout=timeout)
        conn.set_tunnel(u.hostname, u.port or 443, {"Proxy-Authorization": auth})
        return conn, u.path
    conn = http.client.HTTPSConnection(px.hostname, 3130, timeout=timeout)
    conn.set_tunnel(MCP_HOST, 443, {"Proxy-Authorization": auth})
    return conn, "/muse/mcp"


def mcp_call(method, arguments, timeout):
    key = get_key()
    conn, path = open_conn(timeout)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": method, "arguments": arguments}}
    conn.request("POST", path, body=json.dumps(payload),
                 headers={"Content-Type": "application/json",
                          "Accept": "application/json, text/event-stream",
                          "X-API-Key": key})
    r = conn.getresponse()
    body = r.read().decode("utf-8", "replace")
    conn.close()
    msg = None
    for line in reversed(body.splitlines()):
        line = line.strip()
        if line.startswith("data:"):
            try:
                msg = json.loads(line[5:].strip())
                break
            except Exception:
                pass
    if msg is None:
        # 直连端点（InstaBox 公开端口）返回普通 JSON，不是 SSE
        try:
            msg = json.loads(body)
        except Exception:
            msg = {"raw": body[:500]}
    res = msg.get("result", {}) if isinstance(msg, dict) else {}
    texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
    return r.status, res.get("isError"), "\n".join(texts)


def mcp_download(filename, out_path, download_url=None):
    key = get_key()
    if DIRECT_ENDPOINT:
        # 直连模式：优先用结果里返回的下载地址（换到新端点主机），
        # 失败则回落到 /muse/v1/videos/<file>?key= 旧路径。
        u = urlparse(DIRECT_ENDPOINT)
        candidates = []
        if download_url:
            du = urlparse(download_url)
            candidates.append(du._replace(netloc=u.netloc, scheme="https").geturl())
            candidates.append(download_url)
        candidates.append(f"https://{u.netloc}/muse/v1/videos/{filename}?key={key}")
        last = None
        px = urlparse(os.environ.get("HTTPS_PROXY", ""))
        auth = "Basic " + base64.b64encode((px.username + ":" + px.password).encode()).decode()
        pport = int(os.environ.get("MCP_PROXY_PORT", "0") or 0) or px.port or 3128
        for url in candidates:
            cu = urlparse(url)
            try:
                if cu.scheme == "http":
                    conn = http.client.HTTPConnection(cu.hostname, cu.port or 80, timeout=300)
                else:
                    conn = http.client.HTTPSConnection(px.hostname, pport, timeout=300)
                    conn.set_tunnel(cu.hostname, cu.port or 443, {"Proxy-Authorization": auth})
                conn.request("GET", cu.path + ("?" + cu.query if cu.query else ""),
                             headers={"Accept": "*/*"})
                r = conn.getresponse()
                data = r.read()
                conn.close()
            except Exception as e:
                # 候选地址不可达（如下载 URL 指向沙箱禁直连的外域）时换下一个，
                # 不让单个候选的异常杀死整次下载。
                last = f"{type(e).__name__}"
                continue
            if r.status == 200 and len(data) > 10000:
                with open(out_path, "wb") as f:
                    f.write(data)
                return len(data)
            last = r.status
        # 隧道模式兜底：QQ 盒部署的 downloadUrl 外域沙箱禁直连、/muse/v1/videos/
        # 又 404，改走 VPS→盒子 SSH 直传（文件在盒内 generated-videos/）。
        if urlparse(DIRECT_ENDPOINT).scheme == "http":
            import subprocess
            safe = os.path.basename(filename)
            with open(out_path, "wb") as f:
                cp = subprocess.run(
                    ["/home/hatch/workspace/mcp-b-ssh.sh",
                     f"bash /tmp/qqbox_cat_video.sh {safe}"],
                    stdout=f, stderr=subprocess.PIPE, timeout=300)
            if cp.returncode == 0 and os.path.getsize(out_path) > 10000:
                return os.path.getsize(out_path)
        raise RuntimeError(f"download failed, last HTTP {last} for {filename}")
    px = urlparse(os.environ.get("HTTPS_PROXY", ""))
    auth = "Basic " + base64.b64encode((px.username + ":" + px.password).encode()).decode()
    conn = http.client.HTTPSConnection(px.hostname, 3130, timeout=300)
    conn.set_tunnel(MCP_HOST, 443, {"Proxy-Authorization": auth})
    conn.request("GET", "/muse/v1/videos/" + filename + "?key=" + key,
                 headers={"Accept": "*/*"})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    if r.status != 200:
        raise RuntimeError(f"download HTTP {r.status} for {filename}")
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, required=True, help="event_bus id")
    ap.add_argument("--name", required=True, help="短名，用于备份与成片文件名")
    ap.add_argument("--prompt-file", help="浓缩版 prompt 文件")
    ap.add_argument("--prompt", help="浓缩版 prompt 文本（与 --prompt-file 二选一）")
    ap.add_argument("--account", default="morgan_bennett@chaitgpt.org")
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args()
    if bool(args.prompt_file) == bool(args.prompt):
        ap.error("exactly one of --prompt-file / --prompt is required")
    prompt = open(args.prompt_file).read().strip() if args.prompt_file else args.prompt.strip()

    db = sqlite3.connect(DB)
    row = db.execute("SELECT payload FROM event_bus WHERE id=?", (args.id,)).fetchone()
    if not row:
        print(f"no event_bus row {args.id}", file=sys.stderr)
        return 1
    item = json.loads(row[0])
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, f"{args.name}_item_backup.json")
    json.dump(item, open(backup, "w"), ensure_ascii=False, indent=1)
    print(f"backup: {backup} (orig prompt {len(item.get('prompt', ''))} chars, "
          f"status={item.get('status')})")

    print(f"calling muse_video account={args.account} prompt_len={len(prompt)} ...", flush=True)
    status, is_error, text = mcp_call(
        "muse_video",
        {"account": args.account, "prompt": prompt, "segments": 1, "timeout": args.timeout},
        timeout=args.timeout + 300)
    print(f"CALL_STATUS: {status} IS_ERROR: {is_error}")
    if is_error:
        print("RESULT_TEXT:", text[:2000])
        print("FAILED: DB untouched")
        return 2
    try:
        parsed = json.loads(text[text.index("{"):])
    except Exception:
        print("unparsable result:", text[:2000])
        return 3
    files = parsed.get("files") or []
    if not files:
        print("no files in result:", text[:2000])
        return 4
    fname = files[0]["filename"]
    print(f"generated: {fname} sizeMB={files[0].get('sizeMB')} elapsed={parsed.get('elapsed')}")
    out_path = os.path.join(VEO_INBOX, f"{args.name}_condensed_20261028.mp4")
    dl_url = (files[0].get("downloadUrl") or files[0].get("playUrl")
              or parsed.get("downloadUrl") or parsed.get("playUrl"))
    nbytes = mcp_download(fname, out_path, download_url=dl_url)
    print(f"downloaded: {out_path} bytes={nbytes}")

    item["prompt_original_backup"] = backup
    item["prompt"] = prompt
    item["video_file"] = out_path
    # QQ 盒空间政策（2026-10-28）：记下盒内原片名，上传 YouTube 核验成功后
    # 凭此删除盒内原片；无此字段的旧条目不得凭猜测删除。
    item["box_filename"] = fname
    item["box_path"] = "/data/home/muse/generated-videos/" + fname
    item["clip_source"] = (f"laptop_mcp muse_video {args.account} condensed "
                           f"({len(prompt)} chars) 2026-10-28; orig template prompt "
                           f"failed integrity_check_failed when sent raw")
    db.execute("UPDATE event_bus SET payload=? WHERE id=?",
               (json.dumps(item, ensure_ascii=False), args.id))
    db.commit()
    verify = json.loads(db.execute(
        "SELECT payload FROM event_bus WHERE id=?", (args.id,)).fetchone()[0])
    print(f"VERIFY status={verify.get('status')} prompt_len={len(verify['prompt'])} "
          f"video_file={verify.get('video_file')} title={verify.get('title')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
