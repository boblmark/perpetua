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


def mcp_call(method, arguments, timeout):
    key = open(KEY_FILE).read().strip()
    px = urlparse(os.environ.get("HTTPS_PROXY", ""))
    auth = "Basic " + base64.b64encode((px.username + ":" + px.password).encode()).decode()
    conn = http.client.HTTPSConnection(px.hostname, 3130, timeout=timeout)
    conn.set_tunnel(MCP_HOST, 443, {"Proxy-Authorization": auth})
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": method, "arguments": arguments}}
    conn.request("POST", "/muse/mcp", body=json.dumps(payload),
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
        try:
            msg = json.loads(body)
        except Exception:
            msg = {"raw": body[:500]}
    res = msg.get("result", {}) if isinstance(msg, dict) else {}
    texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
    return r.status, res.get("isError"), "\n".join(texts)


def mcp_download(filename, out_path):
    key = open(KEY_FILE).read().strip()
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
    nbytes = mcp_download(fname, out_path)
    print(f"downloaded: {out_path} bytes={nbytes}")

    item["prompt_original_backup"] = backup
    item["prompt"] = prompt
    item["video_file"] = out_path
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
