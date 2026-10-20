#!/bin/bash
# 安装/重装 Dash 核心服务 systemd units（2026-10-20）。
# 用途：整机被平台替换后 /etc/systemd/system 可能被清空，此脚本一键恢复。
# 纳入 Rule 11 舰队恢复清单：换机后跑一遍本脚本。
# 注意：只 enable 不 start —— 服务若已在运行，start 会造成端口冲突；
# systemd 接管发生在下次进程死亡（Restart=always）或下次开机。
set -e
SRC=/home/hatch/data/perpetua/systemd_units
for f in "$SRC"/dash-*.service; do
    name=$(basename "$f")
    cp "$f" /etc/systemd/system/"$name"
    chmod 644 /etc/systemd/system/"$name"
done
systemctl daemon-reload
for f in "$SRC"/dash-*.service; do
    name=$(basename "$f")
    systemctl enable "$name" >/dev/null 2>&1 || systemctl enable "$name"
done
echo "installed+enabled:"
systemctl list-unit-files 'dash-*' --no-legend
