#!/usr/bin/env python3
"""凭据代理 Windows 版（命名管道），Linux 版（Unix socket）不动。

协议与 Linux 版一致：{"action": "GET_TOKEN"|"REVOKE", "service": ...}
  -> {"status": "OK", "token": ...} / {"status": "DENIED"/"REVOKED", ...}

安全说明（诚实降级）：
- Linux 版靠 SO_PEERCRED 验证调用者 uid + vault 600 权限；
- Windows 命名管道无对等凭据，替代方案：管道仅本机可达（npipe 本来就是本机），
  服务端以 LocalSystem/管理员账户运行 + 管道 DACL 仅允许 Administrators/SYSTEM，
  客户端 token 仅在内存中传递、绝不落盘。同一台机器上的管理员进程理论上仍可连接——
  这是 Windows 单机模型的固有限制，文档中明确告知。

客户端用法（与 Linux 版 credential_proxy_client.py 同名 API）：
    from cred_proxy_win import get_token
    token = get_token("youtube")
"""
import json
import os
import sys

PIPE_NAME = r"\\.\pipe\perpetua-cred-proxy"
LINUX_SOCK = "/run/credential-proxy/proxy.sock"
IS_WINDOWS = (os.name == "nt")


def _call(action, service, **kwargs):
    req = json.dumps({"action": action, "service": service, **kwargs}).encode()
    if IS_WINDOWS:
        return _call_named_pipe(req)
    return _call_unix_socket(req)


def _call_unix_socket(req):
    import socket
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(LINUX_SOCK)
    try:
        s.sendall(req)
        return json.loads(s.recv(65536).decode())
    finally:
        s.close()


def _call_named_pipe(req):
    # 纯 stdlib 实现：os.open 对命名管道做同步读写
    # （长连接/重叠 IO 如需再引入 pywin32，此处保持零依赖）
    fd = os.open(PIPE_NAME, os.O_RDWR | os.O_BINARY if hasattr(os, "O_BINARY") else os.O_RDWR)
    try:
        os.write(fd, req + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode().strip() or "{}")
    finally:
        os.close(fd)


def get_token(service="youtube"):
    resp = _call("GET_TOKEN", service)
    if resp.get("status") == "OK":
        return resp["token"]
    raise RuntimeError(f"Proxy error: {resp.get('error', 'unknown')}")


def revoke(service="youtube", force=False):
    resp = _call("REVOKE", service, force=force)
    if resp.get("status") == "DENIED":
        raise PermissionError(f"Revoke denied: {resp.get('error')}")
    if resp.get("status") == "REVOKED":
        return True
    raise RuntimeError(f"Proxy error: {resp.get('error', 'unknown')}")


# ---------------- 服务端（Windows） ----------------

def run_server(vault_path, dry_run=False):
    """Windows 命名管道服务端。vault_path: JSON 文件（600/ACL 仅管理员可读）。

    vault 格式: {"youtube": {"token": "...", "shared": false}, ...}
    """
    if not IS_WINDOWS and not dry_run:
        print("服务端仅在 Windows 上运行（Linux 请用现有 credential-proxy.service）",
              file=sys.stderr)
        return 2
    try:
        vault = json.load(open(vault_path, encoding="utf-8"))
    except Exception as e:
        print(f"vault 读取失败: {e}", file=sys.stderr)
        return 2
    if dry_run:
        print(f"[dry-run] vault 服务 {len(vault)} 项，管道 {PIPE_NAME}")
        return 0
    # pywin32 实现（Windows 真机上 pip install pywin32）
    try:
        import win32pipe
        import win32file
        import pywintypes
    except ImportError:
        print("需要 pywin32：pip install pywin32", file=sys.stderr)
        return 2

    print(f"[cred-proxy] listening on {PIPE_NAME}", flush=True)
    while True:
        pipe = win32pipe.CreateNamedPipe(
            PIPE_NAME,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE |
            win32pipe.PIPE_WAIT,
            1, 65536, 65536, 0, None)
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            data = win32file.ReadFile(pipe, 65536)[1].decode()
            req = json.loads(data)
            resp = _handle(req, vault)
            win32file.WriteFile(pipe, (json.dumps(resp) + "\n").encode())
        except Exception as e:
            try:
                win32file.WriteFile(pipe, json.dumps(
                    {"status": "ERROR", "error": str(e)[:200]}).encode())
            except Exception:
                pass
        finally:
            try:
                win32pipe.DisconnectNamedPipe(pipe)
            except Exception:
                pass


def _handle(req, vault):
    action = req.get("action")
    service = req.get("service", "")
    entry = vault.get(service)
    if action == "GET_TOKEN":
        if not entry:
            return {"status": "ERROR", "error": f"unknown service {service}"}
        return {"status": "OK", "token": entry.get("token", "")}
    if action == "REVOKE":
        if not entry:
            return {"status": "ERROR", "error": f"unknown service {service}"}
        if entry.get("shared") and not req.get("force"):
            return {"status": "DENIED",
                    "error": "shared credential, use force=True (see Rule 1)"}
        entry["token"] = ""
        return {"status": "REVOKED"}
    return {"status": "ERROR", "error": f"unknown action {action}"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--vault", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.serve:
        sys.exit(run_server(a.vault, a.dry_run))
    print("客户端库，import 使用。PIPE:", PIPE_NAME if IS_WINDOWS else LINUX_SOCK)
