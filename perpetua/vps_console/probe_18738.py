#!/usr/bin/env python3
"""Frame probe for Gemini Live bridge via local tunnel 127.0.0.1:18738.

Protocol (bridge -> client): 4-byte BE length; length 0 = control frame,
followed by 4-byte BE JSON length + JSON. On Gemini setupComplete the
bridge sends {"type": "ready"}.
"""
import json
import socket
import struct
import sys
import time

HOST, PORT = "127.0.0.1", 18738
TIMEOUT = 20.0


def read_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("EOF")
        buf += chunk
    return buf


def main():
    t0 = time.time()
    with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as s:
        s.settimeout(TIMEOUT)
        hdr = read_exact(s, 4)
        (length,) = struct.unpack(">I", hdr)
        if length != 0:
            print(f"UNEXPECTED first frame length={length} (expected control frame)")
            return 2
        jlen = struct.unpack(">I", read_exact(s, 4))[0]
        payload = json.loads(read_exact(s, jlen).decode())
        dt = time.time() - t0
        print(f"frame probe got {json.dumps(payload)} in {dt:.2f}s")
        return 0 if payload.get("type") == "ready" else 3


if __name__ == "__main__":
    sys.exit(main())
