#!/usr/bin/env python3
"""
跨平台 SSH 隧道保活脚本
2026-10-14 新增：替代 tunnel_*.sh bash 脚本，支持 Linux + Windows

用法：
    python3 tunnel_keepalive.py --local-port 8734 --remote-port 8734 \
        --remote-host root@192.166.82.123 --name "8734"

    python3 tunnel_keepalive.py --config tunnel_8734.yaml
"""

import argparse
import datetime
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_adapter import pa


def log(msg: str, log_file: str):
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{timestamp} {msg}\n"
    print(line.strip())
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)


def is_tunnel_running(local_port: int, remote_port: int) -> bool:
    """检查隧道是否在运行（锚定真实 ssh 进程）"""
    # 匹配模式：ssh ... -R ...remote_port:localhost:local_port
    # 或 ssh ... -R ...remote_port:...
    patterns = [
        f"{remote_port}:localhost:{local_port}",
        f"{remote_port}:127.0.0.1:{local_port}",
    ]
    for proc_pid, cmdline in pa.find_processes("ssh"):
        # 排除 autossh supervisor（只看真实 ssh）
        if "autossh" in cmdline:
            continue
        # 必须含 ssh 且含端口转发
        if "/ssh" in cmdline or cmdline.startswith("ssh "):
            for pat in patterns:
                if pat in cmdline:
                    return True
    return False


def cleanup_stale(local_port: int, remote_port: int, log_file: str):
    """清理残留的隧道进程（只杀匹配的，不碰其他隧道）"""
    patterns = [
        f"{remote_port}:localhost:{local_port}",
        f"{remote_port}:127.0.0.1:{local_port}",
    ]
    for proc_pid, cmdline in pa.find_processes("ssh"):
        for pat in patterns:
            if pat in cmdline and proc_pid != os.getpid():
                log(f"清理残留隧道进程 PID {proc_pid}: {cmdline[:80]}", log_file)
                pa.kill_process(proc_pid)
                break


def start_tunnel(local_port: int, remote_port: int, remote_host: str,
                 bind_all: bool, log_file: str) -> bool:
    """拉起 SSH 反向隧道"""
    bind = "0.0.0.0" if bind_all else "127.0.0.1"

    cmd = pa.build_ssh_command([
        "-f", "-N",  # 后台运行，不执行命令
        "-R", f"{bind}:{remote_port}:localhost:{local_port}",
        "-o", "StrictHostKeyChecking=no",
        remote_host,
    ])

    log(f"启动隧道: {' '.join(cmd[:6])}... (端口 {local_port}->{remote_port})", log_file)

    try:
        # Windows 下 -f 参数不可用，改用后台启动
        if pa.is_windows():
            # 移除 -f，用 CREATE_NEW_PROCESS_GROUP 后台运行
            cmd = [c for c in cmd if c != "-f"]
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception as e:
        log(f"隧道启动异常: {e}", log_file)
        return False

    time.sleep(3)
    if is_tunnel_running(local_port, remote_port):
        log(f"隧道启动成功 (PID 已确认)", log_file)
        return True
    else:
        log(f"隧道启动失败", log_file)
        return False


def main():
    parser = argparse.ArgumentParser(description="跨平台 SSH 隧道保活")
    parser.add_argument("--local-port", type=int, required=True, help="本地端口")
    parser.add_argument("--remote-port", type=int, required=True, help="远程端口")
    parser.add_argument("--remote-host", required=True, help="远程主机 (如 root@192.166.82.123)")
    parser.add_argument("--name", default="tunnel", help="隧道名称（用于日志）")
    parser.add_argument("--bind-all", action="store_true", default=True, help="绑定 0.0.0.0")
    parser.add_argument("--log-file", default="", help="日志文件路径")
    args = parser.parse_args()

    log_file = args.log_file or os.path.join(
        pa.get_console_dir() if hasattr(pa, 'get_console_dir') else pa.get_perpetua_dir(),
        f"tunnel_{args.name}_keepalive.log"
    )

    # 检查是否已在运行
    if is_tunnel_running(args.local_port, args.remote_port):
        # 静默退出（保活正常）
        sys.exit(0)

    log(f"{args.name} 隧道未运行，准备拉起", log_file)

    # 清理残留
    cleanup_stale(args.local_port, args.remote_port, log_file)
    time.sleep(2)

    # 拉起
    success = start_tunnel(
        args.local_port, args.remote_port,
        args.remote_host, args.bind_all, log_file
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
