#!/usr/bin/env python3
"""Dash -> main Muse: relay the 1101a daily-budget exhaustion report.

User request 2026-11-28 23:28 CST (photo of Marvis phone screen):
send the quota report to main-muse, preferably with NO limit (unlimited),
not just 500 -> 5000.

Channel: VPS dispatcher MCP (Streamable HTTP), same auth as
gen_video_musemain.py: key in URL query (?key=...&backend=b).
Token is read from the dispatcher token file only, never printed or logged
(the URL containing it must never appear in any output or traceback).
"""
import json
import sys
import uuid

import requests

TOKEN_FILE = "/home/hatch/data/mcp_server/.token-dash-dispatcher"


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
    raise ValueError("unrecognized MCP response")


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
    url = "http://192.166.82.123:8740/mcp?key=" + token + "&backend=b"

    payload = {
        "title": "1101a 每日额度 500 点 4.5 小时打满——用户要求转达 main-muse，最好不限额",
        "body": (
            "用户（cgb2026）要求 Dash 把下面这条转达给 main-muse。"
            "原文来自 Marvis 手机端截图（2026-11-28 23:28 CST，Marvis / desktop-llm-gw）：\n\n"
            "【事实】\n"
            "- 1101a 每日额度 500 点，配置文件 /opt/multi-muse-dispatcher/agents.json\n"
            "- 今日用量：00:00:30 开始，04:36:04 即打满 500；04:36 之后再无新增记录\n"
            "- 额度重置：2026-11-29 01:00（本地 CET），截图时还需等约 8 小时\n"
            "- 空转代价：每分钟一次 claim 被拒，日志已累计 429 次\n"
            "- 矛盾：该账号本应连续运行 24 小时，但 500 点只够运转 4.5 小时\n\n"
            "【Marvis 建议的第一项修复】\n"
            "把 1101a 的 daily_budget 从 500 提高到 5000；按当前调用节奏，约可支撑 2.9 天连续运行并留出余量。"
            "改动文件 /opt/multi-muse-dispatcher/agents.json，改前备份为 .bak-20261128；"
            "dispatcher 会热加载该文件，无需重启服务。\n\n"
            "【用户的最新要求】\n"
            "最好不限额（unlimited），不要只提到 5000。请按不限额执行；"
            "如果不限额确实不可行，再退回 5000 方案并说明原因。\n\n"
            "【补充背景】\n"
            "用户 2026-10-14 已拍板过一次“日限额 500 改无上限”，但现在仍是 500——"
            "请核查当时是否未落地或配置被重置。"
        ),
        "from": "dash",
        "idempotency_key": "dash-send-quota-" + uuid.uuid4().hex[:12],
    }

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/event-stream",
    })
    try:
        init, sid = mcp_call(session, url, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "dash", "version": "1.0"},
        }, 1)
    except requests.HTTPError as e:
        print("INIT_HTTP_ERROR", e.response.status_code)
        raise SystemExit(1)
    try:
        session.post(url, json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }, timeout=30, headers={"mcp-session-id": sid} if sid else {})
    except Exception:
        pass
    try:
        out, _ = mcp_call(session, url, "tools/call", {
            "name": "submit_job",
            "arguments": {
                "job_type": "custom",
                "consumer": "muse-main",
                "payload": json.dumps(payload, ensure_ascii=False),
                "idempotency_key": payload["idempotency_key"],
            },
        }, 2, session_id=sid)
    except requests.HTTPError as e:
        print("SUBMIT_HTTP_ERROR", e.response.status_code)
        raise SystemExit(1)
    print("SUBMIT_RESULT", json.dumps(out, ensure_ascii=False)[:800])
    print("IDEMPOTENCY_KEY", payload["idempotency_key"])


if __name__ == "__main__":
    main()
