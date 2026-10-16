#!/usr/bin/env python3
"""
Perpetua 跨平台适配层
2026-10-14 新增：Windows 支持

提供统一的平台抽象，上层代码不再直接写 Linux 强绑定调用：
- 路径：get_data_dir() / get_perpetua_dir()
- 进程：find_process() / kill_process()（跨平台替代 pgrep/pkill）
- 权限：secure_file()（Linux chmod 600 / Windows icacls）
- 服务：install_service() / start_service()
- SSH：build_ssh_command()

用法：
    from platform_adapter import pa
    data_dir = pa.get_data_dir()
    pa.secure_file("/path/to/.token")
"""

import os
import sys
import platform
import subprocess
import yaml

_SYSTEM = platform.system().lower()  # 'linux' / 'windows' / 'darwin'
IS_WINDOWS = _SYSTEM == "windows"
IS_LINUX = _SYSTEM == "linux"

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "platform_config.yaml")
_config = None


def _load_config():
    global _config
    if _config is not None:
        return _config
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f)
    except FileNotFoundError:
        _config = {}
    return _config


def _platform_section():
    cfg = _load_config()
    if IS_WINDOWS:
        return cfg.get("windows", {})
    return cfg.get("linux", {})


def _expand(path: str) -> str:
    """展开 ~ 和 Windows 环境变量"""
    if not path:
        return path
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    return path


class PlatformAdapter:
    """跨平台适配器单例"""

    # ---- 路径 ----
    def get_data_dir(self) -> str:
        return _expand(_platform_section().get("data_dir", ""))

    def get_perpetua_dir(self) -> str:
        return _expand(_platform_section().get("perpetua_dir", ""))

    def get_console_dir(self) -> str:
        return os.path.join(self.get_perpetua_dir(), "vps_console")

    def get_ssh_key(self) -> str:
        return _expand(_platform_section().get("ssh_key", ""))

    # ---- Python ----
    def python_cmd(self) -> str:
        return _platform_section().get("python_cmd", "python3" if IS_LINUX else "python")

    def pip_cmd(self) -> str:
        return _platform_section().get("pip_cmd", "pip3" if IS_LINUX else "pip")

    # ---- 进程管理（替代 pgrep/pkill）----
    def find_processes(self, name_pattern: str):
        """跨平台查找进程，返回 [(pid, cmdline), ...]"""
        try:
            import psutil
        except ImportError:
            return self._find_processes_fallback(name_pattern)

        results = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info["cmdline"] or [])
                if name_pattern in cmdline and proc.pid != os.getpid():
                    results.append((proc.pid, cmdline))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return results

    def _find_processes_fallback(self, name_pattern: str):
        """无 psutil 时的降级方案"""
        results = []
        if IS_WINDOWS:
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True).stdout
            for line in out.splitlines():
                if name_pattern.lower() in line.lower():
                    parts = line.split('","')
                    if len(parts) >= 2:
                        try:
                            results.append((int(parts[1].strip('"')), line))
                        except ValueError:
                            pass
        else:
            out = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                if name_pattern in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            results.append((int(parts[1]), line))
                        except ValueError:
                            pass
        return results

    def kill_process(self, pid: int, force: bool = True):
        """跨平台杀进程"""
        try:
            import psutil
            proc = psutil.Process(pid)
            proc.kill() if force else proc.terminate()
            return True
        except ImportError:
            pass
        except Exception:
            return False

        if IS_WINDOWS:
            r = subprocess.run(["taskkill", "/F" if force else "", "/PID", str(pid)],
                               capture_output=True)
            return r.returncode == 0
        else:
            import signal
            try:
                os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
                return True
            except ProcessLookupError:
                return False

    # ---- 文件权限（替代 chmod 600）----
    def secure_file(self, path: str) -> bool:
        """收紧文件权限为仅所有者可读写"""
        path = _expand(path)
        if not os.path.exists(path):
            return False
        if IS_WINDOWS:
            # Windows: 用 icacls 只保留当前用户权限
            username = os.environ.get("USERNAME", "")
            cmds = [
                ["icacls", path, "/inheritance:r"],
                ["icacls", path, "/grant:r", f"{username}:(R,W)"] if username else None,
            ]
            for cmd in cmds:
                if cmd:
                    subprocess.run(cmd, capture_output=True)
            return True
        else:
            os.chmod(path, 0o600)
            return True

    # ---- SSH 命令构建 ----
    def build_ssh_command(self, extra_args: list) -> list:
        """构建跨平台 SSH 命令（含 ProxyCommand）"""
        section = _platform_section()
        ssh_exe = section.get("ssh_exe", "ssh")
        key = self.get_ssh_key()
        proxy = section.get("ssh_proxy_command", "")

        cmd = [ssh_exe, "-i", key]
        if proxy:
            cmd += ["-o", f"ProxyCommand={proxy}"]
        # 保活参数（跨平台通用）
        cmd += ["-o", "ServerAliveInterval=30",
                "-o", "ServerAliveCountMax=3",
                "-o", "ExitOnForwardFailure=yes"]
        cmd += extra_args
        return cmd

    def build_tunnel_command(self, local_port: int, remote_host: str,
                             remote_port: int,
                             bind_all: bool = True) -> list:
        """构建 SSH 反向隧道命令"""
        bind = "0.0.0.0" if bind_all else "127.0.0.1"
        return self.build_ssh_command([
            "-N",
            "-R", f"{bind}:{remote_port}:localhost:{local_port}",
            remote_host,
        ])

    # ---- 服务管理 ----
    def service_manager(self) -> str:
        return _platform_section().get("service_manager", "")

    # ---- 工具 ----
    def platform_name(self) -> str:
        return _SYSTEM

    def is_windows(self) -> bool:
        return IS_WINDOWS

    def is_linux(self) -> bool:
        return IS_LINUX


# 单例
pa = PlatformAdapter()


if __name__ == "__main__":
    print(f"平台: {pa.platform_name()}")
    print(f"数据目录: {pa.get_data_dir()}")
    print(f"Perpetua 目录: {pa.get_perpetua_dir()}")
    print(f"Python: {pa.python_cmd()}")
    print(f"服务管理: {pa.service_manager()}")
