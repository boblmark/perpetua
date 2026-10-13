#!/usr/bin/env python3
"""Credential proxy client - drop-in replacement for direct token file reads.

Usage:
    from credential_proxy_client import get_token
    token = get_token("youtube")
"""
import json
import socket

SOCKET_PATH = "/run/credential-proxy/proxy.sock"

def _call(action, service, **kwargs):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCKET_PATH)
    req = {"action": action, "service": service, **kwargs}
    s.sendall(json.dumps(req).encode())
    resp = json.loads(s.recv(8192).decode())
    s.close()
    return resp

def get_token(service="youtube"):
    """Get current access token for a service. Auto-refreshes if needed."""
    resp = _call("GET_TOKEN", service)
    if resp.get("status") == "OK":
        return resp["token"]
    raise RuntimeError(f"Proxy error: {resp.get('error', 'unknown')}")

def revoke(service="youtube", force=False):
    """Revoke a credential. Blocked if shared without force=True."""
    resp = _call("REVOKE", service, force=force)
    if resp.get("status") == "DENIED":
        raise PermissionError(f"Revoke denied: {resp.get('error')}")
    if resp.get("status") == "REVOKED":
        return True
    raise RuntimeError(f"Proxy error: {resp.get('error', 'unknown')}")
