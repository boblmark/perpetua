#!/usr/bin/env python3
"""跨平台 SSH 隧道 supervisor（替代 vps_console/tunnel_*.sh + *_keepalive.sh）。

设计：直接驱动系统自带 ssh（二进制），Windows Server 2019+ 内置 OpenSSH，
零第三方依赖；命令行参数与现有 bash 脚本 1:1 对齐。

用法：
  tunnel_py.py run --name nano            # A类：while-true 自重连 worker
  tunnel_py.py keepalive --name nano      # B类：检查 worker 存活，不在则拉起
  tunnel_py.py keepalive-all              # 全部隧道走一遍 keepalive（供计划任务每5分钟调用）
  tunnel_py.py list                       # 列出隧道定义
  tunnel_py.py run --name nano --dry-run  # 打印将执行的 ssh 命令行，不执行

隧道定义可被 tunnels.json 覆盖（与本文件同目录，或 PERPETUA_DATA_DIR/perpetua/tunnels.json）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from config import get_data_dir, IS_WINDOWS  # noqa: E402

VPS_HOST = "root@192.166.82.123"
# 注意：ProxyCommand 里的 nc 代理是当前 Linux 环境的出口配置；
# Windows 侧如直连公网可留空，或按实际代理改写 tunnels.json。
DEFAULT_PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p" if not IS_WINDOWS else ""

TUNNELS = {
    # name: {forwards: [(kind, spec)], log, match_ports}
    "nano": {
        "forwards": [("R", "0.0.0.0:18736:localhost:18736"),
                     ("R", "0.0.0.0:18737:localhost:18737"),
                     ("R", "0.0.0.0:18739:localhost:18739")],
        "log": "tunnel_nano.log", "match_ports": ["18736", "18737", "18739"],
        "desc": "nanoMuse 反向隧道（perception WS/UI + 主控制台）",
    },
    "console_8080": {
        "forwards": [("R", "0.0.0.0:8080:localhost:8080")],
        "log": "tunnel_8080.log", "match_ports": ["8080"],
        "desc": "控制台/OA 反向隧道",
    },
    "mcp_8734": {
        "forwards": [("R", "0.0.0.0:8734:localhost:8734")],
        "log": "tunnel_8734.log", "match_ports": ["8734"],
        "desc": "MCP 8734 反向隧道",
    },
    "mcp_8738": {
        "forwards": [("R", "0.0.0.0:8738:localhost:8734")],
        "log": "tunnel_8738.log", "match_ports": ["8738"],
        "desc": "MCP 8738 反向隧道",
    },
    "gemini_18738": {
        "forwards": [("L", "127.0.0.1:18738:127.0.0.1:18738")],
        "log": "tunnel_18738.log", "match_ports": ["18738"],
        "desc": "Gemini Live 语音本地转发",
    },
    "tianshu_18901": {
        "forwards": [("R", "0.0.0.0:18901:localhost:18901")],
        "log": "tunnel_18901.log", "match_ports": ["18901"],
        "desc": "天枢控制台反向隧道",
    },
    "semantica_18091": {
        "forwards": [("R", "0.0.0.0:18091:localhost:18091"),
                     ("R", "0.0.0.0:18092:localhost:18092")],
        "log": "tunnel_18091.log", "match_ports": ["18091", "18092"],
        "desc": "Semantica 知识图谱反向隧道",
    },
}


def load_tunnels():
    tunnels = dict(TUNNELS)
    for cand in (os.path.join(HERE, "tunnels.json"),
                 os.path.join(get_data_dir(), "perpetua", "tunnels.json")):
        if os.path.exists(cand):
            try:
                tunnels.update(json.load(open(cand, encoding="utf-8")))
            except Exception as e:
                print(f"[tunnel] tunnels.json 读取失败 {cand}: {e}", file=sys.stderr)
    return tunnels


def ssh_key_path():
    home = os.path.expanduser("~")
    return os.path.join(home, ".ssh", "id_ed25519")


def build_cmd(name, tunnels):
    t = tunnels[name]
    proxy = t.get("proxy_command", DEFAULT_PROXY)
    cmd = ["ssh", "-i", ssh_key_path(), "-N"]
    if proxy:
        cmd += ["-o", f"ProxyCommand={proxy}"]
    cmd += ["-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes"]
    for kind, spec in t["forwards"]:
        cmd += [f"-{kind}", spec]
    cmd += [t.get("vps_host", VPS_HOST)]
    return cmd


def log_path(name, tunnels):
    d = os.path.join(get_data_dir(), "perpetua", "vps_console")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, tunnels[name].get("log", f"tunnel_{name}.log"))


def _log(msg, name, tunnels):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n"
    try:
        with open(log_path(name, tunnels), "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line.strip(), flush=True)


def worker_pids(name, tunnels):
    """跨平台检查 worker ssh 进程（对齐 keepalive 脚本的精确端口匹配，防误杀）。"""
    ports = tunnels[name].get("match_ports", [])
    found = []
    try:
        if IS_WINDOWS:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=15).stdout
            for line in out.splitlines():
                if '"ssh.exe"' in line.lower():
                    m = re.search(r'"(\d+)"\s*$', line)
                    if m:
                        found.append(int(m.group(1)))
        else:
            out = subprocess.run(["pgrep", "-f", "ssh.*" + ".*".join(ports)],
                                 capture_output=True, text=True, timeout=15).stdout
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit() and int(line) != os.getpid():
                    found.append(int(line))
    except Exception:
        pass
    # 二次确认：命令行确实含全部端口（tasklist 无命令行时保守返回）
    if not IS_WINDOWS and found:
        ok = []
        for pid in found:
            try:
                args = subprocess.run(["ps", "-p", str(pid), "-o", "args="],
                                      capture_output=True, text=True, timeout=10).stdout
                if all(p in args for p in ports):
                    ok.append(pid)
            except Exception:
                pass
        return ok
    return found


def cmd_run(name, dry_run=False):
    tunnels = load_tunnels()
    if name not in tunnels:
        print(f"[tunnel] 未知隧道: {name}（可用: {', '.join(sorted(tunnels))}）", file=sys.stderr)
        return 2
    cmd = build_cmd(name, tunnels)
    if dry_run:
        print("[dry-run] " + " ".join(cmd))
        return 0
    _log(f"{name} worker 启动: {' '.join(cmd[:4])} ...", name, tunnels)
    while True:
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.wait()
        except Exception as e:
            _log(f"{name} 启动失败: {e}", name, tunnels)
        _log(f"{name} tunnel died, retry in 5s", name, tunnels)
        time.sleep(5)


def cmd_keepalive(name, dry_run=False):
    tunnels = load_tunnels()
    if name not in tunnels:
        print(f"[tunnel] 未知隧道: {name}", file=sys.stderr)
        return 2
    pids = worker_pids(name, tunnels)
    if pids:
        if dry_run:
            print(f"[dry-run] {name} 运行中 pids={pids}，不拉起")
        return 0
    _log(f"{name} worker 不在运行，准备拉起", name, tunnels)
    # 清理残留 ssh（仅匹配本隧道端口，防误杀其他隧道）
    for pid in worker_pids(name, tunnels):
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, 15)
        except Exception:
            pass
    if dry_run:
        print("[dry-run] " + " ".join(build_cmd(name, tunnels)))
        print(f"[dry-run] worker 将以后台方式启动，日志: {log_path(name, tunnels)}")
        return 0
    time.sleep(3)
    cmd = [sys.executable, os.path.abspath(__file__), "run", "--name", name]
    logf = open(log_path(name, tunnels), "a", encoding="utf-8")
    kwargs = dict(stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x8)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    _log(f"{name} 已拉起", name, tunnels)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Perpetua 跨平台 SSH 隧道 supervisor")
    ap.add_argument("action", choices=["run", "keepalive", "keepalive-all", "list"])
    ap.add_argument("--name", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.action == "list":
        for n, t in sorted(load_tunnels().items()):
            print(f"{n:15} {t.get('desc', '')}  forwards={t['forwards']}")
        return 0
    if a.action == "keepalive-all":
        rc = 0
        for n in sorted(load_tunnels()):
            rc |= cmd_keepalive(n, a.dry_run)
        return rc
    if not a.name:
        print("--name 必需", file=sys.stderr)
        return 2
    if a.action == "run":
        return cmd_run(a.name, a.dry_run)
    return cmd_keepalive(a.name, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
