#!/usr/bin/env python3
"""本地代理转发器：监听 127.0.0.1:18888，无认证；
收到请求后转发到真实 egress proxy（自动带认证）。
解决 Chromium/Playwright 在沙箱代理下认证解析失败的问题。

用法：python3 local_proxy.py &
Chromium 启动参数：--proxy-server=http://127.0.0.1:18888
"""
import os, socket, threading
from urllib.parse import urlparse

LISTEN_PORT = 18888

def get_upstream():
    u = urlparse(os.environ.get("https_proxy", ""))
    return ("198.19.0.1", 3128, u.username, u.password)

def handle(client):
    try:
        req = client.recv(65536)
        if not req:
            client.close(); return
        host, port, user, pwd = get_upstream()
        up = socket.create_connection((host, port), timeout=15)
        # 注入 Proxy-Authorization
        import base64
        auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        lines = req.split(b"\r\n")
        # 找到空行（headers 结束），在之前插入认证头
        new_lines = []
        inserted = False
        for i, l in enumerate(lines):
            new_lines.append(l)
            if l == b"" and not inserted:
                new_lines.insert(-1, f"Proxy-Authorization: Basic {auth}".encode())
                inserted = True
        up.sendall(b"\r\n".join(new_lines))
        def fwd(src, dst):
            try:
                while True:
                    d = src.recv(65536)
                    if not d: break
                    dst.sendall(d)
            except Exception:
                pass
            try: src.close()
            except Exception: pass
            try: dst.close()
            except Exception: pass
        t = threading.Thread(target=fwd, args=(up, client), daemon=True)
        t.start()
        fwd(client, up)
    except Exception:
        try: client.close()
        except Exception: pass

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", LISTEN_PORT))
    s.listen(50)
    print(f"[local_proxy] listening on 127.0.0.1:{LISTEN_PORT}", flush=True)
    while True:
        c, _ = s.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

if __name__ == "__main__":
    main()
