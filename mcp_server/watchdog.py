#!/usr/bin/env python3
"""看门狗：保活 MCP server + relay poller。由 cron 每 5 分钟执行。"""
import json
import os
import subprocess
import time
import urllib.request

HERE = "/home/hatch/data/mcp_server"
VENV_PY = os.path.join(HERE, "venv", "bin", "python")
LOG = os.path.join(HERE, "watchdog.log")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)


def alive(pattern):
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return r.returncode == 0


# 匹配 MCP server 进程：兼容 watchdog 全路径启动和手动相对路径启动两种方式
MCP_PATTERN = r"(mcp_server/server\.py|venv/bin/python server\.py)"


def health_ok():
    """健康检查：连续 3 次失败才判死，避免忙时单次超时误杀。"""
    import time
    for attempt in range(3):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8734/health", timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if attempt < 2:
            time.sleep(2)
    return False


def start(cmd, name):
    subprocess.Popen(cmd, cwd=HERE,
                     stdout=open(os.path.join(HERE, f"{name}.out.log"), "a"),
                     stderr=subprocess.STDOUT,
                     start_new_session=True)
    log(f"started {name}")


def main():
    if not health_ok():
        if alive(MCP_PATTERN):
            log("mcp server process exists but unhealthy; killing")
            subprocess.run(["pkill", "-f", MCP_PATTERN])
            time.sleep(2)
        start([VENV_PY, os.path.join(HERE, "server.py")], "mcp-server")
    else:
        log("mcp server ok")

    cfg_path = os.path.join(HERE, "relay_config.json")
    configured = False
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        configured = bool(cfg.get("worker_url"))
    if configured and not alive("ws_poller.py"):
        start([VENV_PY, os.path.join(HERE, "ws_poller.py")], "ws-poller")
    elif configured:
        log("ws poller ok")
    else:
        log("relay not configured yet (worker_url empty), skipping poller")

    # SSH 反向隧道保活（VPS 公网 -> 本地 8734）
    if not alive("tunnel.sh"):
        start(["/bin/bash", os.path.join(HERE, "tunnel.sh")], "tunnel")
    else:
        log("ssh tunnel ok")

    # Perpetua 独立控制台保活（本地 8080 + VPS 8080 隧道）
    CONSOLE = "/home/hatch/data/perpetua/vps_console"
    if not alive("vps_console/console_server.py"):
        start(["/usr/bin/python3", os.path.join(CONSOLE, "console_server.py")],
              "console-server")
        log("console backend restarted")
    else:
        log("console backend ok")
    if not alive("tunnel_8080.sh"):
        start(["/bin/bash", os.path.join(CONSOLE, "tunnel_8080.sh")], "tunnel-8080")
        log("console tunnel restarted")
    else:
        log("console tunnel ok")


if __name__ == "__main__":
    main()
