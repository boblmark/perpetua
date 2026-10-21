#!/bin/bash
# 安装/重装 Dash 核心服务 systemd units（2026-10-20）。
# 用途：整机被平台替换后 /etc/systemd/system 可能被清空，此脚本一键恢复。
# 纳入 Rule 11 舰队恢复清单：换机后跑一遍本脚本。
# 注意：只 enable 不 start —— 服务若已在运行，start 会造成端口冲突；
# systemd 接管发生在下次进程死亡（Restart=always）或下次开机。
set -e
SRC=/home/hatch/data/perpetua/systemd_units
for f in "$SRC"/dash-*.service "$SRC"/dash-*.timer; do
    [ -e "$f" ] || continue
    name=$(basename "$f")
    cp "$f" /etc/systemd/system/"$name"
    chmod 644 /etc/systemd/system/"$name"
done
systemctl daemon-reload
for f in "$SRC"/dash-*.service; do
    name=$(basename "$f")
    systemctl enable "$name" >/dev/null 2>&1 || systemctl enable "$name"
done
# timers 不占端口、触发的 oneshot 均为幂等探针/看门狗：enable 的同时 start，
# 否则"已启用但从未启动"就是死状态（Rule 4）。2026-10-21 第一批迁出后补。
for f in "$SRC"/dash-*.timer; do
    [ -e "$f" ] || continue
    name=$(basename "$f")
    systemctl enable --now "$name" >/dev/null 2>&1 || systemctl enable --now "$name"
done
# credential-proxy 需要出网代理环境（systemd 不继承 agent shell 环境）：
# 从当前 shell 环境重建 env drop-in（只写值、不回显）。2026-10-21 补。
DROPIN_DIR=/etc/systemd/system/dash-credential-proxy.service.d
mkdir -p "$DROPIN_DIR"
{
    echo "[Service]"
    for v in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY no_proxy NO_PROXY all_proxy ALL_PROXY; do
        if [ -n "${!v}" ]; then
            printf 'Environment="%s=%s"\n' "$v" "${!v}"
        fi
    done
} > "$DROPIN_DIR/env.conf"
chmod 600 "$DROPIN_DIR/env.conf"
systemctl daemon-reload

echo "installed+enabled:"
systemctl list-unit-files 'dash-*' --no-legend
