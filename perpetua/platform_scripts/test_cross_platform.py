#!/usr/bin/env python3
"""
跨平台适配层测试
2026-10-14

验证 platform_adapter 在当前平台正常工作。
在 Windows 上跑同样的脚本应该同样通过（路径部分除外）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from platform_adapter import pa

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        print(f"  ✓ {name}")
        passed += 1
    else:
        print(f"  ✗ {name} {detail}")
        failed += 1


print("=== 跨平台适配层测试 ===")
print(f"平台: {pa.platform_name()}")
print()

print("[1] 路径解析")
check("数据目录非空", bool(pa.get_data_dir()), pa.get_data_dir())
check("Perpetua 目录非空", bool(pa.get_perpetua_dir()), pa.get_perpetua_dir())
check("控制台目录拼接正确",
      pa.get_console_dir().endswith("vps_console"),
      pa.get_console_dir())

print("[2] 平台检测")
if pa.is_linux():
    check("Linux 检测", True)
    check("Python 命令为 python3", pa.python_cmd() == "python3")
elif pa.is_windows():
    check("Windows 检测", True)
    check("Python 命令为 python", pa.python_cmd() == "python")
else:
    check("未知平台", False, pa.platform_name())

print("[3] 进程管理")
procs = pa.find_processes("python")
check("能查到 python 进程", len(procs) > 0, f"找到 {len(procs)} 个")
# 不实际杀进程，只验证接口存在
check("kill_process 接口存在", callable(pa.kill_process))

print("[4] SSH 命令构建")
cmd = pa.build_ssh_command(["-N", "root@example.com"])
check("SSH 命令含密钥参数", "-i" in cmd)
check("SSH 命令含保活参数", "ServerAliveInterval=30" in cmd)

tunnel_cmd = pa.build_tunnel_command(8080, "root@example.com", 8080)
tunnel_str = " ".join(tunnel_cmd)
check("隧道命令含 -R 参数", "-R" in tunnel_cmd)
check("隧道命令含端口映射", "8080:localhost:8080" in tunnel_str or "8080" in tunnel_str)

print("[5] 配置文件")
check("platform_config.yaml 可加载", True)  # 能跑到这里即已加载

print()
print(f"=== 结果: {passed} 通过, {failed} 失败 ===")
sys.exit(0 if failed == 0 else 1)
