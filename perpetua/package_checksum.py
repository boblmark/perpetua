#!/usr/bin/env python3
"""安装包/同步漂移检测的唯一校验口径。
覆盖安装包实际装运的全部代码：顶层 .py、vps_console、platform_scripts、平台配置。
排除日志/备份/缓存等非源码（2026-10-14 修复误报漂移的教训）。
用法：python3 package_checksum.py  -> 打印 sha256 hex
"""
import hashlib
import glob
import os

SRC = "/home/hatch/data/perpetua"
EXTS = {".py", ".html", ".js", ".css", ".sh", ".md", ".txt", ".yaml", ".yml", ".service", ".json"}
PATS = (
    SRC + "/*.py",
    SRC + "/*.sh",
    SRC + "/vps_console/*",
    SRC + "/platform_scripts/*",
    SRC + "/platform_config.yaml",
    SRC + "/requirements.txt",
    SRC + "/WINDOWS_TEST_CHECKLIST.md",
)

def checksum():
    files = set()
    for pat in PATS:
        for f in glob.glob(pat):
            if os.path.isfile(f) and os.path.splitext(f)[1].lower() in EXTS:
                files.add(f)
    h = hashlib.sha256()
    for f in sorted(files):
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest(), len(files)

if __name__ == "__main__":
    digest, n = checksum()
    print(digest)
