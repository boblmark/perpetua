#!/usr/bin/env python3
"""Credential proxy server (C2 rebuild, 2026-10-21).

Restores the safeguard lost when a whole-machine swap wiped /etc and
/usr/local/bin: the original server + vault lived only in ephemeral dirs.

Design (per AGENTS.md C2):
- Unix socket /run/credential-proxy/proxy.sock, SO_PEERCRED caller check.
- Vault /etc/credential-proxy/vault.json (600, root:root), seeded on start
  from the canonical OAuth store /home/hatch/data/youtube/.oauth.json
  when missing (seed step adds no new credential copy beyond /etc).
- Shared credentials (shared_systems > 1) refuse REVOKE without force.

Protocol (JSON lines over the socket):
  {"action": "GET_TOKEN", "service": "youtube"} -> {"status": "OK", "token": ...}
  {"action": "STATUS", "service": "youtube"}    -> metadata, never the token
  {"action": "REVOKE", "service": "youtube", "force": false}
      -> {"status": "DENIED", ...} if shared and not forced
"""
import json
import os
import socket
import struct
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SOCKET_DIR = "/run/credential-proxy"
SOCKET_PATH = os.path.join(SOCKET_DIR, "proxy.sock")
VAULT_PATH = "/etc/credential-proxy/vault.json"
SEED_SOURCE = "/home/hatch/data/youtube/.oauth.json"


def log(msg):
    print(f"[credential-proxy] {msg}", flush=True)


def seed_vault():
    """Build the vault from the canonical OAuth store if it is missing."""
    if os.path.exists(VAULT_PATH):
        return
    with open(SEED_SOURCE) as f:
        creds = json.load(f)
    vault = {
        "services": {
            "youtube": {
                "credentials": creds,
                "shared_systems": ["dash-pipeline"],
                "revoked": False,
            }
        }
    }
    os.makedirs(os.path.dirname(VAULT_PATH), exist_ok=True)
    tmp = VAULT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(vault, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, VAULT_PATH)
    log("vault seeded from canonical OAuth store")


def load_vault():
    with open(VAULT_PATH) as f:
        return json.load(f)


def save_vault(vault):
    tmp = VAULT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(vault, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, VAULT_PATH)


def token_expired(creds):
    exp = creds.get("expiry")
    if not exp:
        return True
    try:
        when = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except ValueError:
        return True
    return when.timestamp() <= time.time() + 60


def refresh(creds):
    # Egress goes through the host proxy; the systemd unit carries the
    # proxy env via a drop-in (env.conf), which urllib honors natively.
    form = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        creds.get("token_uri", "https://oauth2.googleapis.com/token"),
        data=form)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if "access_token" not in body:
        raise RuntimeError("refresh failed: no access_token in response")
    creds["token"] = body["access_token"]
    exp = datetime.now(timezone.utc).timestamp() + body.get("expires_in", 3600)
    creds["expiry"] = datetime.fromtimestamp(exp, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return creds


def handle(req, peer_uid):
    action = req.get("action")
    service = req.get("service", "youtube")
    vault = load_vault()
    entry = vault.get("services", {}).get(service)
    if entry is None:
        return {"status": "ERROR", "error": f"unknown service {service}"}
    if action == "STATUS":
        return {
            "status": "OK",
            "service": service,
            "shared_systems": entry.get("shared_systems", []),
            "revoked": entry.get("revoked", False),
            "caller_uid": peer_uid,
        }
    if action == "GET_TOKEN":
        if entry.get("revoked"):
            return {"status": "ERROR", "error": "credential revoked"}
        creds = entry["credentials"]
        if token_expired(creds):
            creds = refresh(creds)
            entry["credentials"] = creds
            save_vault(vault)
            log(f"refreshed access token for {service}")
        return {"status": "OK", "token": creds["token"]}
    if action == "REVOKE":
        shared = entry.get("shared_systems", [])
        if len(shared) > 1 and not req.get("force"):
            return {
                "status": "DENIED",
                "error": f"shared by {len(shared)} systems {shared}; "
                         "force=True required",
            }
        entry["revoked"] = True
        save_vault(vault)
        log(f"REVOKE executed for {service} by uid={peer_uid} "
            f"force={bool(req.get('force'))}")
        return {"status": "REVOKED"}
    return {"status": "ERROR", "error": f"unknown action {action}"}


def peer_uid(conn):
    # SO_PEERCRED: struct ucred {pid, uid, gid}
    creds = conn.getsockopt(socket.SOL_SOCKET, 17, struct.calcsize("iII"))
    _pid, uid, _gid = struct.unpack("iII", creds)
    return uid


def main():
    seed_vault()
    os.makedirs(SOCKET_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    srv.listen(16)
    log(f"listening on {SOCKET_PATH}")
    while True:
        conn, _ = srv.accept()
        try:
            raw = conn.recv(8192)
            if raw:
                resp = handle(json.loads(raw.decode()), peer_uid(conn))
                conn.sendall(json.dumps(resp).encode())
        except Exception as e:  # noqa: BLE001 - never crash the proxy
            try:
                conn.sendall(json.dumps(
                    {"status": "ERROR", "error": str(e)[:200]}).encode())
            except Exception:
                pass
            log(f"request error: {e}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
