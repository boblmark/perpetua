#!/usr/bin/env python3
"""跨平台冒烟验收（替代 Linux 版 verify.sh）。

检查项：
  1. 数据目录与关键子目录存在
  2. 本地服务端口可连（18736/18737/18739/8080/8734/8735，按配置）
  3. dispatcher 健康（http://127.0.0.1:8740，如可达）
  4. 关键 Python 模块可 import（windows_compat.config / tunnel_py / sched_win）
  5. 隧道 worker 进程存在（可选 --check-tunnels）

用法：verify.py [--dry-run] [--check-tunnels]
退出码：0 全过；1 有失败（明细打印）。
"""
import argparse
import importlib
import os
import socket
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

PORTS = {
    18736: "perception WS", 18737: "perception UI", 18739: "nanoMuse 主控制台",
    8080: "OA/控制台", 8734: "MCP", 8735: "nanoMuse MCP",
}


def check_port(port, timeout=3):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-tunnels", action="store_true")
    a = ap.parse_args()

    from config import get_data_dir, IS_WINDOWS
    data_dir = get_data_dir()
    results = []

    def rec(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    print(f"[verify] 平台: {'Windows' if IS_WINDOWS else 'Linux'}")
    print(f"[verify] DATA_DIR={data_dir}")
    if a.dry_run:
        print("[dry-run] 仅列出检查项，不实际探测")
        for p, d in PORTS.items():
            print(f"  [dry-run] 端口 {p}（{d}）")
        print("  [dry-run] 数据目录/模块 import/隧道进程")
        return 0

    # 1. 目录
    for sub in ("", "perpetua", os.path.join("perpetua", "vps_console"),
                os.path.join("perpetua", "logs")):
        p = os.path.join(data_dir, sub)
        rec(f"目录 {sub or '.'}", os.path.isdir(p), p)

    # 2. 端口（WARNING 级别：服务未起不算硬失败，单独标注）
    for port, desc in PORTS.items():
        ok = check_port(port)
        rec(f"端口 {port}（{desc}）", ok, "未监听（服务未起）" if not ok else "")

    # 3. dispatcher
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8740/", timeout=5)
        rec("dispatcher 8740", r.status in (200, 401), f"HTTP {r.status}")
    except Exception as e:
        rec("dispatcher 8740", False, f"不可达: {str(e)[:60]}")

    # 4. 模块 import
    for mod in ("config", "tunnel_py", "sched_win", "cred_proxy_win"):
        try:
            importlib.import_module(mod)
            rec(f"import {mod}", True)
        except Exception as e:
            rec(f"import {mod}", False, str(e)[:80])

    # 5. 隧道进程
    if a.check_tunnels:
        sys.path.insert(0, HERE)
        import tunnel_py
        tunnels = tunnel_py.load_tunnels()
        for name in sorted(tunnels):
            pids = tunnel_py.worker_pids(name, tunnels)
            rec(f"隧道 {name}", bool(pids), f"pids={pids}" if pids else "未运行")

    fails = [r for r in results if not r[1]]
    # 端口/dispatcher 未起是 WARNING，不计入硬失败（服务可能稍后起）
    hard = [r for r in fails if not r[0].startswith(("端口", "dispatcher", "隧道"))]
    print(f"[verify] {len(results) - len(fails)}/{len(results)} 通过，"
          f"硬失败 {len(hard)}")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
