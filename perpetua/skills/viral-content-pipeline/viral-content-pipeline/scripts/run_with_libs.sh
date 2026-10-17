#!/usr/bin/env bash
# 带上本地补齐的系统库运行命令（Chromium 缺库环境适用）
LIBDIR="${PIPELINE_LIBS:-$HOME/.pipeline_libs}"
export LD_LIBRARY_PATH="$LIBDIR/root/usr/lib/x86_64-linux-gnu:$LIBDIR/root/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
exec "$@"
