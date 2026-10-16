#!/usr/bin/env python3
"""Chromium 代理转发器：127.0.0.1:3129 -> 198.19.0.1:3128

背景：Chromium 直连 hatch-egress-proxy 会稳定报 ERR_TUNNEL_CONNECTION_FAILED，
而经本地 TCP 转发就正常（原因未明，疑为 Chromium socket 与代理的 TCP 层不兼容）。
curl/Python/socat 直连代理都正常，只有 Chromium 不行。

本转发器做纯 TCP 透传，不解析、不改写字节。
"""
import socket
import threading
import logging

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 3129
UPSTREAM_HOST = "198.19.0.1"
UPSTREAM_PORT = 3128

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("proxy-fwd")


def forward(src: socket.socket, dst: socket.socket):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def handle(client: socket.socket):
    try:
        upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=15)
    except OSError as e:
        log.warning("upstream connect failed: %s", e)
        client.close()
        return
    # TCP_NODELAY：减少转发延迟
    for s in (client, upstream):
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
    threading.Thread(target=forward, args=(client, upstream), daemon=True).start()
    forward(upstream, client)


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(100)
    log.info("forwarding %s:%d -> %s:%d", LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT)
    while True:
        client, _ = srv.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
