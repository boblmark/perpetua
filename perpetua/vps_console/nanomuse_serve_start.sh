#!/bin/bash
# nanoMuse 主控制台启动脚本：加载三个 LLM API 资产
# 由 keepalive 调用，不直接手动运行

PORT=18739

# 加载三个 API 资产（用户 2026-10-11 划拨）
# 1. agnes-2.5-flash（主用）
if [ -f /home/hatch/data/llm_assets/agnes.env ]; then
    set -a
    source /home/hatch/data/llm_assets/agnes.env
    set +a
    # 映射到 nanoMuse 识别的环境变量
    export NANOMUSE_LLM_BASE_URL="$LLM_BASE_URL"
    export NANOMUSE_LLM_API_KEY="$LLM_API_KEY"
    export NANOMUSE_LLM_MODEL="$LLM_MODEL"
fi

# 2 & 3. gemini-auto 和 local-gemma 作为备用（存入环境，应用层按需取）
if [ -f /home/hatch/data/llm_assets/gemini-auto.env ]; then
    set -a
    source /home/hatch/data/llm_assets/gemini-auto.env
    set +a
    export NANOMUSE_LLM_FALLBACK1_BASE_URL="$LLM_BASE_URL"
    export NANOMUSE_LLM_FALLBACK1_API_KEY="$LLM_API_KEY"
    export NANOMUSE_LLM_FALLBACK1_MODEL="$LLM_MODEL"
fi

if [ -f /home/hatch/data/llm_assets/local-gemma.env ]; then
    set -a
    source /home/hatch/data/llm_assets/local-gemma.env
    set +a
    export NANOMUSE_LLM_FALLBACK2_BASE_URL="$LLM_BASE_URL"
    export NANOMUSE_LLM_FALLBACK2_API_KEY="$LLM_API_KEY"
    export NANOMUSE_LLM_FALLBACK2_MODEL="$LLM_MODEL"
fi

# NO_PROXY 修括号 IPv6 问题 (2026-10-12: httpx 解析 [::1] 括号格式会崩，必须无括号)
# 用 env 直接设置，确保 Python 进程看到正确值，不受父 shell 环境污染
cd /home/hatch/data/nanomuse-migration/nanomuse
exec env NO_PROXY="localhost,127.0.0.1,::1" no_proxy="localhost,127.0.0.1,::1" /home/hatch/data/nanomuse-migration/nanomuse-venv/bin/python -m nanomuse serve --port "$PORT"
