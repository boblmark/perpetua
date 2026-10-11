#!/usr/bin/env python3
"""Perpetua 统一入口（编译用）：单二进制，多子命令。

用法：
  perpetua mcp              启动 MCP 服务器
  perpetua trend            运行一次趋势检测
  perpetua pipeline-status  显示流水线状态
  perpetua version          显示版本
"""
import sys, os

# 确保能找到各模块
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = "/home/hatch/data"
for p in [f"{DATA}/mcp_server", f"{DATA}/perpetua/tenants", f"{DATA}/perpetua"]:
    if p not in sys.path:
        sys.path.insert(0, p)

VERSION = "1.0.0"

def cmd_mcp():
    os.chdir(f"{DATA}/mcp_server")
    sys.path.insert(0, f"{DATA}/mcp_server")
    # 延迟导入，避免其他子命令被拖慢
    import runpy
    runpy.run_path(f"{DATA}/mcp_server/server.py", run_name="__main__")

def cmd_trend():
    import runpy
    runpy.run_path(f"{DATA}/trend_spike_detector.py", run_name="__main__")

def cmd_pipeline_status():
    sys.path.insert(0, f"{DATA}/perpetua")
    from pipeline import status_all
    import json
    print(json.dumps(status_all(), ensure_ascii=False, indent=2))

def cmd_version():
    print(f"Perpetua v{VERSION} by ViralLoop")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmds = {
        "mcp": cmd_mcp,
        "trend": cmd_trend,
        "pipeline-status": cmd_pipeline_status,
        "version": cmd_version,
    }
    fn = cmds.get(sys.argv[1])
    if not fn:
        print(f"未知命令: {sys.argv[1]}")
        print(__doc__)
        sys.exit(1)
    fn()

if __name__ == "__main__":
    main()
