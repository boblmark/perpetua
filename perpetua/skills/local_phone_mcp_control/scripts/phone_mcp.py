#!/usr/bin/env python3
"""Client for the user's phone MCP channel (see ../SKILL.md).

Usage:
  phone_mcp.py status                 connect, show server info, device info, current app
  phone_mcp.py tools                  list the 18 tool names
  phone_mcp.py call <tool> [json]     call one tool with a JSON args object
  phone_mcp.py screen                 compact on-screen element list
  phone_mcp.py text                   extract on-screen text

The MCP token is read from /home/hatch/data/phone_mcp/tokens.env (MCP_TOKEN=...)
and is never printed. Connections retry for up to ~2 minutes because the
phone-side frp link flaps when the phone app sits in the background.
"""
import json
import sys
import time
import urllib.request
import urllib.error

URL = "http://127.0.0.1:18766/mcp"
TOKENS_FILE = "/home/hatch/data/phone_mcp/tokens.env"
PROTOCOL = "2025-03-26"


def load_token():
    for line in open(TOKENS_FILE):
        if line.startswith("MCP_TOKEN="):
            return line.strip().split("=", 1)[1]
    raise SystemExit("MCP_TOKEN not found in " + TOKENS_FILE)


class PhoneMCP:
    def __init__(self):
        self.token = load_token()
        self.sid = None
        self._cid = 100

    def _post(self, payload, timeout=30):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + self.token}
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode(errors="replace")
                nsid = r.headers.get("Mcp-Session-Id")
                if nsid:
                    self.sid = nsid
                return r.status, body
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")

    @staticmethod
    def _parse(body):
        out = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                try:
                    out.append(json.loads(line[5:]))
                except Exception:
                    pass
            elif line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        return out

    def connect(self, attempts=16, pause=5):
        last = None
        for i in range(attempts):
            try:
                st, body = self._post(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                                "clientInfo": {"name": "phone-mcp-cli", "version": "1.0"}}},
                    timeout=15)
                if st == 200:
                    for m in self._parse(body):
                        if "result" in m:
                            self.server_info = m["result"].get("serverInfo", {})
                    self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                               timeout=15)
                    return True
                last = "http %s" % st
            except Exception as e:
                last = type(e).__name__
            time.sleep(pause)
        raise SystemExit("connect failed after %s attempts (%s). "
                         "See SKILL.md troubleshooting." % (attempts, last))

    def call(self, name, args=None, timeout=120):
        self._cid += 1
        st, body = self._post(
            {"jsonrpc": "2.0", "id": self._cid, "method": "tools/call",
             "params": {"name": name, "arguments": args or {}}}, timeout=timeout)
        for m in self._parse(body):
            if "result" in m:
                res = m["result"]
                texts = []
                for c in res.get("content", []):
                    if c.get("type") == "text":
                        texts.append(c.get("text", ""))
                    elif c.get("type") == "image":
                        texts.append("[image content]")
                return res.get("isError", False), "\n".join(texts)
            if "error" in m:
                return True, "RPC error: " + json.dumps(m["error"], ensure_ascii=False)
        return True, "no result (http %s)" % st

    def list_tools(self):
        self._cid += 1
        st, body = self._post({"jsonrpc": "2.0", "id": self._cid,
                               "method": "tools/list", "params": {}}, timeout=30)
        for m in self._parse(body):
            if "result" in m:
                return [t["name"] for t in m["result"].get("tools", [])]
        return []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    cli = PhoneMCP()
    cli.connect()
    if cmd == "status":
        print("server:", json.dumps(cli.server_info, ensure_ascii=False))
        for tool in ("get_device_info", "get_current_app"):
            err, txt = cli.call(tool)
            print(tool + ":", txt[:400])
    elif cmd == "tools":
        names = cli.list_tools()
        print("%d tools:" % len(names))
        for n in names:
            print(" -", n)
    elif cmd == "call":
        tool = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        err, txt = cli.call(tool, args)
        print("isError:", err)
        print(txt)
    elif cmd == "screen":
        err, txt = cli.call("get_screen_elements", {"limit": 60})
        try:
            d = json.loads(txt)
            print("total_on_screen:", d.get("total_on_screen"))
            for e in d.get("elements", []):
                print(" -", repr(e.get("text")), "| desc:", repr(e.get("desc")),
                      "| id:", (e.get("id") or "").split("/")[-1],
                      "| click:", e.get("clickable"), "| edit:", e.get("editable"))
        except Exception:
            print(txt[:3000])
    elif cmd == "text":
        err, txt = cli.call("extract_text")
        print(txt[:3000])
    else:
        print("unknown command:", cmd)
        print(__doc__)


if __name__ == "__main__":
    main()
