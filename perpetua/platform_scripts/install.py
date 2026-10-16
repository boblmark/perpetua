#!/usr/bin/env python3
"""
Perpetua 跨平台一键安装入口
2026-10-14 新增

自动检测平台并调用对应的安装脚本：
- Linux → bash install.sh
- Windows → powershell install_windows.ps1

用法：
    python3 install.py [--target <目录>] [--package-dir <包目录>]
"""

import argparse
import os
import platform
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PERPETUA_DIR = os.path.dirname(HERE)


def main():
    parser = argparse.ArgumentParser(description="Perpetua 跨平台一键安装")
    parser.add_argument("--target", default="", help="目标目录")
    parser.add_argument("--package-dir", default=HERE, help="部署包目录")
    args = parser.parse_args()

    system = platform.system().lower()
    print(f"检测到平台: {system}")

    if system == "windows":
        ps1 = os.path.join(HERE, "install_windows.ps1")
        if not os.path.exists(ps1):
            print(f"错误：未找到 {ps1}")
            sys.exit(1)
        cmd = [
            "powershell", "-ExecutionPolicy", "Bypass",
            "-File", ps1,
        ]
        if args.target:
            cmd += ["-Target", args.target]
        if args.package_dir:
            cmd += ["-PackageDir", args.package_dir]
        print(f"执行: {' '.join(cmd)}")
        sys.exit(subprocess.call(cmd))
    else:
        # Linux / macOS：调用 bash install.sh
        # 找包根目录的 install.sh
        candidates = [
            os.path.join(args.package_dir, "install.sh"),
            os.path.join(PERPETUA_DIR, "..", "install.sh"),
            "/root/perpetua-deploy-full/install.sh",
        ]
        sh = None
        for c in candidates:
            if os.path.exists(c):
                sh = c
                break
        if not sh:
            print("错误：未找到 install.sh")
            print(f"尝试过的路径: {candidates}")
            sys.exit(1)
        cmd = ["bash", sh]
        if args.target:
            cmd += ["--target", args.target]
        print(f"执行: {' '.join(cmd)}")
        sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
