#!/usr/bin/env python3
"""Perpetua 编译入口：Nuitka 直接导入追踪依赖。

构建命令：
  python3 -m nuitka --onefile --include-package=mcp --include-package=starlette \\
      --include-package=uvicorn perpetua_build.py
"""
import sys
import os

# 数据目录（运行时确定，编译时不硬编码）
def get_data_dir():
    return os.environ.get("PERPETUA_DATA", "/home/hatch/data")

VERSION = "1.0.0"

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Perpetua v%s by ViralLoop" % VERSION)
        print("用法: perpetua <mcp|trend|pipeline-status|version>")
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    cmd = sys.argv[1]
    data_dir = get_data_dir()

    if cmd == "version":
        print(f"Perpetua v{VERSION} by ViralLoop")
    elif cmd == "mcp":
        # 直接导入 server 模块（Nuitka 可追踪）
        sys.path.insert(0, os.path.join(data_dir, "mcp_server"))
        os.chdir(os.path.join(data_dir, "mcp_server"))
        # server.py 在 __main__ 时启动 uvicorn，我们直接触发
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "perpetua_server",
            os.path.join(data_dir, "mcp_server", "server.py"))
        # 注意：Nuitka 下用 exec 方式运行，保持 __main__ 语义
        import runpy
        runpy.run_path(os.path.join(data_dir, "mcp_server", "server.py"),
                       run_name="__main__")
    elif cmd == "trend":
        import runpy
        runpy.run_path(os.path.join(data_dir, "trend_spike_detector.py"),
                       run_name="__main__")
    elif cmd == "pipeline-status":
        sys.path.insert(0, os.path.join(data_dir, "perpetua"))
        from pipeline import status_all
        import json
        print(json.dumps(status_all(), ensure_ascii=False, indent=2))
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
