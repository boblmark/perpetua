#!/usr/bin/env python3
"""
跨平台控制台看门狗
2026-10-14 新增：替代 watchdog.sh，支持 Linux + Windows

逻辑：连续两次探测失败才重启（防单线程服务偶发慢响应被误杀）

用法：
    python3 console_watchdog.py [--port 8080] [--path /oa]
"""

import argparse
import datetime
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_adapter import pa


def log(msg: str, log_file: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} {msg}\n"
    print(line.strip())
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)


def probe(port: int, path: str, timeout: int = 10) -> bool:
    """探测控制台是否存活"""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def restart_console(log_file: str):
    """重启控制台（精确杀进程，不用宽泛 pkill）"""
    console_dir = pa.get_console_dir()

    # 找 console_server.py 进程
    killed = []
    for pid, cmdline in pa.find_processes("console_server.py"):
        # 排除自己
        if pid == os.getpid():
            continue
        # 确认是 python 运行的 console_server.py（防误杀）
        if "python" in cmdline.lower() and "console_server" in cmdline:
            log(f"终止旧控制台进程 PID {pid}", log_file)
            pa.kill_process(pid, force=True)
            killed.append(pid)

    time.sleep(2)

    # 启动新进程
    server_py = os.path.join(console_dir, "console_server.py")
    python_cmd = pa.python_cmd()
    log_path = os.path.join(console_dir, "console_server.log")

    log(f"启动控制台: {python_cmd} {server_py}", log_file)

    with open(log_path, "a", encoding="utf-8") as lf:
        if pa.is_windows():
            subprocess.Popen(
                [python_cmd, server_py],
                cwd=console_dir,
                stdout=lf, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            # Linux: 用 setsid 脱离终端
            subprocess.Popen(
                [python_cmd, server_py],
                cwd=console_dir,
                stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    log(f"控制台已重启（杀掉 {len(killed)} 个旧进程）", log_file)


def main():
    parser = argparse.ArgumentParser(description="跨平台控制台看门狗")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--path", default="/oa")
    parser.add_argument("--log-file", default="")
    args = parser.parse_args()

    log_file = args.log_file or os.path.join(
        pa.get_perpetua_dir(), "vps_console", "watchdog.log"
    )

    # 第一次探测
    if probe(args.port, args.path):
        sys.exit(0)

    # 等 10 秒复测
    time.sleep(10)
    if probe(args.port, args.path):
        log("单次探测超时、复测正常，未重启", log_file)
        sys.exit(0)

    # 连续两次失败，重启
    log("连续两次探测失败，重启控制台", log_file)
    restart_console(log_file)


if __name__ == "__main__":
    main()
