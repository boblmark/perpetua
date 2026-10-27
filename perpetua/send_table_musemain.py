#!/usr/bin/env python3
"""Dash -> main Muse: send the KarenVsAI 30-day execution table (xlsx).

Independent minimal MCP client for the VPS dispatcher (Streamable HTTP).
Token is read from the dispatcher token file only, never printed.
Sends the real file as base64 inside the job payload so the receiving
agent can reconstruct it (filesystems are not shared).
"""
import base64
import hashlib
import json
import sys
import uuid

import requests

TOKEN_FILE = "/home/hatch/data/mcp_server/.token-dash-dispatcher"
XLSX_PATH = "/home/hatch/workspace/user/files/KarenVsAI_30______20_3vqd.xlsx"
DISPATCHER_URL = "http://192.166.82.123:8740/mcp?backend=b"


def parse_mcp_response(resp):
    text = resp.text
    if text.lstrip().startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    raise ValueError(f"unrecognized MCP response: {text[:200]}")


def mcp_call(session, url, method, params, msg_id, session_id=None):
    headers = {}
    if session_id:
        headers["mcp-session-id"] = session_id
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}
    r = session.post(url, json=body, timeout=60, headers=headers)
    r.raise_for_status()
    return parse_mcp_response(r), r.headers.get("mcp-session-id")


def main():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        token = f.read().strip()
    with open(XLSX_PATH, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    sha = hashlib.sha256(raw).hexdigest()

    payload = {
        "title": "KarenVsAI 30\u5929\u6267\u884c\u8868\uff08xlsx\uff09\u2014\u2014 Dash \u8f6c\u4ea4",
        "body": (
            "Dash \u8f6c\u4ea4\uff1a\u7528\u6237\u8981\u6c42\u628a\u300aKaren vs AI\u300b30\u5929 YPP "
            "\u51b2\u523a\u9010\u65e5\u6267\u884c\u8868\u53d1\u7ed9 main-muse\u3002\n\n"
            "\u6587\u4ef6\uff1aKarenVsAI_30______20_3vqd.xlsx\uff08.xlsx\uff0c\u4e0d\u662f .xls\uff09\uff0c"
            f"\u539f\u59cb {len(raw)} \u5b57\u8282\uff0csha256 {sha}\u3002\n"
            "6 \u5f20\u8868\uff1a30\u5929\u9010\u65e5\u65e5\u5386\uff0857 \u884c\uff09\u3001KPI\u4eea\u8868\u76d8"
            "\uff0825\uff09\u3001\u5185\u5bb9\u6e05\u6d17\u6e05\u5355\uff08454\uff09\u3001\u6807\u9898\u7f29\u7565\u56fe\u5e93"
            "\uff0843\uff09\u3001\u7533\u8bf7\u524d\u5408\u89c4\u81ea\u67e5\uff0834\uff09\u3001\u8bca\u65ad\u539f\u59cb\u6570\u636e"
            "\uff0831\uff09\u3002\n\n"
            "\u65b0\u9c9c\u5ea6\u8b66\u793a\uff1a\u6700\u540e\u7ef4\u62a4\u662f 2026-10-21 23:49 CST\uff0c"
            "\u4e4b\u540e\u6ca1\u518d\u52a8\u8fc7\uff1b\u65e5\u5386\u8868 54 \u9879\u4efb\u52a1\u53ea\u6253\u4e86 16 \u4e2a\u52fe\uff0c"
            "\u52fe\u505c\u5728\u65e9\u671f\u9636\u6bb5\uff0c10-22 \u81f3 10-26 \u6ca1\u8865\u3002"
            "\u6309\u8868\u81ea\u5df1\u7684\u7b97\u6cd5\uff08Day 0 = 2026-10-09\uff09\u4eca\u5929\u662f Day 18\uff0c"
            "\u90a3\u884c\u5199\u7684\u662f EP6 \u53d1\u5e03\u2014\u2014\u8fd9\u53ea\u662f\u8868\u5f53\u521d\u6392\u7684\u8ba1\u5212\uff0c"
            "\u4e0d\u662f\u4eca\u5929\u786e\u8ba4\u8981\u53d1\u7684\u5b89\u6392\uff08\u751f\u6210\u7aef\u8fd8\u5361\u7740\u3001EP2/EP3 "
            "\u8bc4\u5ba1\u4e5f\u6ca1\u56de\u6765\uff09\u3002\n\n"
            "content_base64 \u5b57\u6bb5\u662f\u8fd9\u4e2a xlsx \u7684\u5b8c\u6574 base64\uff0c"
            "\u8bf7\u89e3\u7801\u540e\u4fdd\u5b58\u4e3a\u540c\u540d .xlsx \u6587\u4ef6\u518d\u8bfb\u3002"
        ),
        "from": "dash",
        "filename": "KarenVsAI_30______20_3vqd.xlsx",
        "content_base64": b64,
        "sha256": sha,
        "idempotency_key": f"dash-send-table-{uuid.uuid4().hex[:12]}",
    }

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
    })
    init, sid = mcp_call(session, DISPATCHER_URL, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "dash", "version": "1.0"},
    }, 1)
    # notifications/initialized is a notification (no response body expected)
    try:
        session.post(DISPATCHER_URL, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }, timeout=30, headers={"mcp-session-id": sid} if sid else {})
    except Exception:
        pass
    try:
        out, _ = mcp_call(session, DISPATCHER_URL, "tools/call", {
            "name": "submit_job",
            "arguments": {
                "job_type": "custom",
                "consumer": "muse-main",
                "payload": json.dumps(payload, ensure_ascii=False),
                "idempotency_key": payload["idempotency_key"],
            },
        }, 2, session_id=sid)
    except requests.HTTPError as e:
        print("SUBMIT_HTTP_ERROR", e.response.status_code, str(e.response.text)[:300])
        raise SystemExit(1)
    print("SUBMIT_RESULT", json.dumps(out, ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
