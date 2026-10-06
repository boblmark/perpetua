#!/usr/bin/env python3
"""Dash MCP 中继轮询器：经代理轮询 Cloudflare Worker，取出 Marvis 的
JSON-RPC 请求，转发给本地 MCP server (127.0.0.1:8734)，再把结果推回 Worker。

配置：同目录 relay_config.json {"worker_url": "...", "relay_secret": "..."}
由后台常驻运行 + cron 看门狗保活。
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
import fcntl

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "relay_config.json")
LOCAL_MCP = "http://127.0.0.1:8734/mcp"
POLL_INTERVAL = 1
LOCK_FILE = os.path.join(HERE, ".poller.lock")
TOKEN_FILE = os.path.join(HERE, ".token")


def local_token():
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


LOCAL_AUTH = {"Authorization": f"Bearer {local_token()}"} if local_token() else {}


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


def load_config():
    if not os.path.exists(CONFIG):
        return None
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def http(method, url, headers=None, data=None, timeout=30):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
    h.update(headers or {})
    req = urllib.request.Request(url, method=method,
                                 headers=h,
                                 data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)


class LocalMCP:
    def __init__(self):
        self.sid = None

    def _post(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        headers.update(LOCAL_AUTH)
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        status, body = http("POST", LOCAL_MCP, headers, payload, timeout=60)
        return status, body

    def ensure_session(self):
        if self.sid:
            return True
        status, body = self._post({
            "jsonrpc": "2.0", "id": "init", "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "relay-poller", "version": "1"}},
        })
        # session id 可能在响应头里；urllib 不直接给，这里用简化处理：
        # FastMCP streamable_http 在新会话时返回 Mcp-Session-Id 头。
        # 为稳妥，重新用带 header 捕获的方式拿一次。
        self.sid = self._init_with_headers()
        return self.sid is not None

    def _init_with_headers(self):
        import http.client
        from urllib.parse import urlparse
        u = urlparse(LOCAL_MCP)
        conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
        body = json.dumps({
            "jsonrpc": "2.0", "id": "init", "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "relay-poller", "version": "1"}},
        })
        conn.request("POST", u.path, body, {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **LOCAL_AUTH,
        })
        resp = conn.getresponse()
        sid = resp.getheader("Mcp-Session-Id")
        resp.read()
        conn.close()
        return sid

    def call(self, payload):
        if not self.ensure_session():
            return {"jsonrpc": "2.0", "id": payload.get("id"),
                    "error": {"code": -32000, "message": "local mcp unavailable"}}
        status, body = self._post(payload)
        if status == 404:  # 会话过期，重建一次
            self.sid = None
            if not self.ensure_session():
                return {"jsonrpc": "2.0", "id": payload.get("id"),
                        "error": {"code": -32000, "message": "local mcp unavailable"}}
            status, body = self._post(payload)
        for line in body.splitlines():
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except Exception:
                    continue
        return {"jsonrpc": "2.0", "id": payload.get("id"),
                "error": {"code": -32000, "message": f"bad local response: {body[:200]}"}}


def main():
    acquire_lock()
    cfg = load_config()
    if not cfg or not cfg.get("worker_url") or not cfg.get("relay_secret"):
        print("relay_config.json 未配置 worker_url/relay_secret，等待配置后由看门狗启动", flush=True)
        return
    worker = cfg["worker_url"].rstrip("/")
    secret = cfg["relay_secret"]
    mcp = LocalMCP()
    print(f"relay poller started -> {worker}", flush=True)
    while True:
        try:
            status, body = http("GET", f"{worker}/relay/pop",
                                 {"x-relay-secret": secret}, timeout=30)
            if status == 200:
                data = json.loads(body)
                if not data.get("empty"):
                    req_body = data["body"]
                    rid = req_body.get("id")
                    print(f"{ts()} popped {rid}", flush=True)
                    result = mcp.call(req_body)
                    ps, pb = http("POST", f"{worker}/relay/push",
                         {"x-relay-secret": secret, "Content-Type": "application/json"},
                         {"id": rid, "result": result}, timeout=30)
                    print(f"{ts()} relayed {rid} push_status={ps}", flush=True)
                # else: 静默（队列为空是常态）
            elif status == 401:
                print("relay auth failed (x-relay-secret)，检查配置", flush=True)
                time.sleep(60)
            else:
                print(f"{ts()} pop unexpected status={status} body={body[:120]}", flush=True)
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"poller error: {e}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    main()
