#!/usr/bin/env python3
"""Perpetua 可靠性：健康检查 + 状态页 + 自动 failover

检查项：
- mcp-server 进程 + 端口
- SSH 隧道到 VPS
- YouTube OAuth token 有效性
- 磁盘空间
- 关键 cron 是否存活

failover：主上传通道（YouTube API）失败时，自动切浏览器上传备用通道
"""
import json, os, subprocess, urllib.request
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"
STATUS_FILE = f"{BASE}/health/status.json"
VPS = "192.166.82.123"

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def check_port(port, host="127.0.0.1"):
    import socket
    try:
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        return True
    except Exception:
        return False

def check_process(pattern):
    r = subprocess.run(["pgrep", "-f", pattern],
                       capture_output=True, text=True)
    return r.returncode == 0

def check_oauth():
    try:
        d = json.load(open("/home/hatch/data/youtube/.oauth.json"))
        # 试调一个轻量 API
        req = urllib.request.Request(
            "https://www.googleapis.com/youtube/v3/channels?part=id&mine=true",
            headers={"Authorization": f"Bearer {d['token']}"})
        urllib.request.urlopen(req, timeout=10)
        return True, "ok"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "token expired"
        return False, f"http {e.code}"
    except Exception as e:
        return False, str(e)[:50]

def check_disk():
    st = os.statvfs("/home/hatch/data")
    free_gb = st.f_bavail * st.f_frsize / 1e9
    return free_gb > 5, f"{free_gb:.1f}GB free"

def run_checks():
    checks = {}
    # MCP server
    ok = check_port(8734) and check_process("server.py")
    checks["mcp_server"] = {"ok": ok, "detail": "port 8734 + process"}
    # SSH 隧道
    ok = check_process("ssh.*8734") or check_port(8734, VPS)
    checks["ssh_tunnel"] = {"ok": ok, "detail": f"to {VPS}:8734"}
    # YouTube OAuth
    ok, detail = check_oauth()
    checks["youtube_oauth"] = {"ok": ok, "detail": detail}
    # 磁盘
    ok, detail = check_disk()
    checks["disk"] = {"ok": ok, "detail": detail}
    # 关键 cron（检查定义文件存在）
    cron_dir = "/home/hatch/workspace/goals/karenvsai/crons"
    important = ["trend-spike-watch", "ask-studio-queue-processor",
                 "post-publish-optimizer"]
    missing = []
    for c in important:
        found = False
        for root, _, files in os.walk("/home/hatch/workspace/goals"):
            if any(c in f for f in files):
                found = True
                break
        if not found:
            missing.append(c)
    checks["crons"] = {"ok": not missing,
                       "detail": "missing: " + ",".join(missing) if missing else "all present"}
    all_ok = all(c["ok"] for c in checks.values())
    status = {"ts": now_iso(), "healthy": all_ok, "checks": checks}
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    json.dump(status, open(STATUS_FILE, "w"), ensure_ascii=False, indent=2)
    return status

def failover_upload(filepath, title, description=""):
    """主通道（API）失败时切备用通道（浏览器上传）

    返回 (success, method, detail)
    """
    # 先试主通道
    r = subprocess.run(
        ["python3", "/home/hatch/data/youtube/yt_upload.py",
         filepath, title, description],
        capture_output=True, text=True, timeout=300)
    if r.returncode == 0:
        return True, "api", r.stdout.strip()[:100]
    # 主通道失败 → 浏览器备用通道
    with open(f"{BASE}/health/failover.log", "a") as f:
        f.write(json.dumps({"ts": now_iso(), "action": "failover_triggered",
                            "api_error": r.stderr.strip()[:200],
                            "file": filepath}) + "\n")
    try:
        br = subprocess.run(
            ["python3", f"{BASE}/browser_upload.py",
             filepath, title, description],
            capture_output=True, text=True, timeout=600)
        bout = json.loads(br.stdout.strip().split("\n")[-1])
        if bout.get("ok"):
            with open(f"{BASE}/health/failover.log", "a") as f:
                f.write(json.dumps({"ts": now_iso(),
                                    "action": "failover_success",
                                    "url": bout.get("url", "")}) + "\n")
            return True, "browser", bout.get("url", "")
        return False, "browser_failed", bout.get("error", "unknown")
    except Exception as e:
        return False, "browser_error", str(e)[:150]

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        s = run_checks()
        print(json.dumps(s, ensure_ascii=False, indent=2))
    elif cmd == "failover":
        ok, method, detail = failover_upload(sys.argv[2], sys.argv[3],
                                             sys.argv[4] if len(sys.argv) > 4 else "")
        print(json.dumps({"ok": ok, "method": method, "detail": detail},
                         ensure_ascii=False))
