#!/usr/bin/env python3
"""Perpetua 跨平台路径配置。

优先级：环境变量 PERPETUA_DATA_DIR > perpetua.ini [paths] data_dir >
Windows 默认 %PROGRAMDATA%/Perpetua/data > Linux 默认 /home/hatch/data。

生产 Linux 代码不动；新写代码一律经本模块取路径。
"""
import os
import sys
import configparser

IS_WINDOWS = (os.name == "nt")

_LINUX_DEFAULT = "/home/hatch/data"


def _windows_default():
    base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return os.path.join(base, "Perpetua", "data")


def _ini_data_dir():
    for cand in (os.path.join(_windows_default(), "perpetua.ini"),
                 os.path.join(_LINUX_DEFAULT, "perpetua", "perpetua.ini")):
        if os.path.exists(cand):
            try:
                cp = configparser.ConfigParser()
                cp.read(cand, encoding="utf-8")
                v = cp.get("paths", "data_dir", fallback="").strip()
                if v:
                    return v
            except Exception:
                pass
    return ""


def get_data_dir():
    v = os.environ.get("PERPETUA_DATA_DIR", "").strip()
    if v:
        return v
    v = _ini_data_dir()
    if v:
        return v
    return _windows_default() if IS_WINDOWS else _LINUX_DEFAULT


DATA_DIR = get_data_dir()
PERPETUA_DIR = os.path.join(DATA_DIR, "perpetua")
VPS_CONSOLE_DIR = os.path.join(PERPETUA_DIR, "vps_console")
LOG_DIR = os.path.join(PERPETUA_DIR, "logs")


def ensure_dirs():
    for d in (DATA_DIR, PERPETUA_DIR, VPS_CONSOLE_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)
    return DATA_DIR


def chmod_private(path):
    """密钥文件权限：Linux 下 0o600；Windows 下 os.chmod 仅支持只读位，
    此处跳过（Windows 靠服务账户 + NTFS ACL 隔离，见 README_WINDOWS.md）。"""
    if IS_WINDOWS:
        return False
    try:
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    print("IS_WINDOWS:", IS_WINDOWS)
    print("DATA_DIR:", DATA_DIR)
    print("PERPETUA_DIR:", PERPETUA_DIR)
    sys.exit(0)
