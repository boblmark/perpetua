#!/usr/bin/env python3
"""Dash MCP WebSocket 中继 poller：与 Cloudflare Worker 建长连接，
收到 Marvis 的 JSON-RPC 请求后转发给本地 MCP server (127.0.0.1:8734)，
结果经 WebSocket 原路返回。不再轮询 KV。

配置：同目录 relay_config.json {"worker_url": "https://<worker>.workers.dev", "relay_secret": "..."}
由后台常驻运行 + cron 看门狗保活。
"""
import asyncio
import fcntl
import json
import os
import sys
import time
import urllib.request
import urllib.error

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(HERE, ".poller.lock")
TOKEN_FILE = os.path.join(HERE, ".token")
LOCAL_MCP = "http://127.0.0.1:8734/mcp"

_lock_handle = None

def acquire_lock():
    global _lock_handle
    f = open(LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another poller is running, exiting", flush=True)
        sys.exit(0)
    f.write(str(os.getpid()))
    f.flush()
    _lock_handle = f  # 必须保留句柄，否则 GC 关闭文件会释放锁
    return f


def ts():
    return time.strftime("%H:%M:%S")


def log(*a):
    print(f"[{ts()}]", *a, flush=True)


def load_config():
    p = os.path.join(HERE, "relay_config.json")
    try:
        with open(p) as f:
            return json.load(f)
    except OSError:
        return {}


def local_token():
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


LOCAL_AUTH = {"Authorization": f"Bearer {local_token()}"} if local_token() else {}


def http_json(url, data, headers=None, timeout=60):
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    # 取 SSE data: 行或纯 JSON
    for line in raw.splitlines():
        if line.startswith("data: "):
            return 200, line[6:]
    return 200, raw


class LocalMCP:
    """带 session 保持的本地 MCP 客户端。"""

    def __init__(self):
        self.sid = None

    def _post(self, payload):
        headers = dict(LOCAL_AUTH)
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        return http_json(LOCAL_MCP, payload, headers)

    def _init_session(self):
        import http.client
        from urllib.parse import urlparse
        u = urlparse(LOCAL_MCP)
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=15)
        body = json.dumps({
            "jsonrpc": "2.0", "id": "init", "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "ws-poller", "version": "1"}}})
        try:
            conn.request("POST", u.path, body, {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **LOCAL_AUTH,
            })
            resp = conn.getresponse()
            sid = resp.getheader("Mcp-Session-Id")
            resp.read()
            return sid if resp.status == 200 else None
        except Exception as e:
            log("init session exc:", e)
            return None

    def ensure_session(self):
        if self.sid:
            return True
        self.sid = self._init_session()
        return self.sid is not None

    def call(self, payload):
        if not self.ensure_session():
            return {"error": {"code": -32000, "message": "local mcp unavailable"}}
        status, body = self._post(payload)
        if status == 404:
            self.sid = None
            if not self.ensure_session():
                return {"error": {"code": -32000, "message": "local mcp unavailable"}}
            status, body = self._post(payload)
        if status != 200:
            return {"error": {"code": -32000, "message": f"local mcp http {status}"}}
        try:
            data = json.loads(body)
        except Exception:
            return {"error": {"code": -32000, "message": f"bad local response: {body[:200]}"}}
        # FastMCP 可能包一层 result
        return data.get("result", data)


async def run_poller(worker_url, relay_secret):
    ws_url = worker_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = ws_url.rstrip("/") + f"/ws?secret={relay_secret}"
    mcp = LocalMCP()

    backoff = 2
    while True:
        try:
            log("connecting", ws_url.split("?")[0], "...")
            async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
                log("ws connected")
                backoff = 2
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    rid = str(msg.get("id"))
                    body = msg.get("body")
                    if rid is None or body is None:
                        continue
                    t0 = time.time()
                    try:
                        result = await asyncio.to_thread(mcp.call, body)
                        await ws.send(json.dumps({"id": rid, "result": result}))
                    except Exception as e:
                        log(f"handle {rid} exc: {e}")
                        try:
                            await ws.send(json.dumps(
                                {"id": rid, "error": {"code": -32603, "message": str(e)[:200]}}))
                        except Exception:
                            pass
                    log(f"handled {rid} in {time.time()-t0:.1f}s")
        except Exception as e:
            log(f"ws error: {e}, retry in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


def main():
    acquire_lock()
    cfg = load_config()
    worker_url = cfg.get("worker_url")
    relay_secret = cfg.get("relay_secret")
    if not worker_url or not relay_secret:
        log("relay_config.json 未配置 worker_url/relay_secret，等待配置后由看门狗启动")
        # 别忙循环，等看门狗 5 分钟后重试
        time.sleep(240)
        return
    # 先确认本地 MCP 存活
    try:
        with urllib.request.urlopen("http://127.0.0.1:8734/health", timeout=5) as r:
            log("local mcp:", r.read().decode()[:60])
    except Exception as e:
        log("local mcp not ready:", e)
    asyncio.run(run_poller(worker_url, relay_secret))


if __name__ == "__main__":
    main()
