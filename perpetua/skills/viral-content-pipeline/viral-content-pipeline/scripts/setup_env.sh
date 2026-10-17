#!/usr/bin/env bash
# 一键重建采集环境（沙箱每次重置后运行）
#
# 背景：本沙箱的工作区快照【不保留】以下目录，因此每次新会话都需重建：
#   ~/.cache（含 xiaohongshu-mcp 的 713MB Chromium）
#   ~/.agent-reach-venv、~/.agent-reach/tools、~/.local（被排除或超出快照容量）
# 只有 /home/user 下的常规目录（如 collector/）会持久保留。
#
# 用法：bash collector/setup_env.sh [--browser]
#   --browser  额外安装浏览器路线（下载 ~713MB Chromium，仅小红书需要时用）
set -u
say(){ printf '\n\033[1;34m▸ %s\033[0m\n' "$*"; }

say "1/5 安装 Agent Reach"
python3 -m venv ~/.agent-reach-venv 2>/dev/null
# shellcheck disable=SC1091
source ~/.agent-reach-venv/bin/activate
pip install -q "https://github.com/Panniantong/agent-reach/archive/main.zip" && echo "  ✅ agent-reach $(agent-reach --version 2>/dev/null | tail -1)"

say "2/5 安装文档生成依赖（python-docx / playwright / openpyxl / Pillow / numpy）"
pip install -q python-docx openpyxl pillow numpy pymupdf playwright reportlab 2>&1 | tail -2
python3 -m playwright install chromium --with-deps 2>/dev/null || python3 -m playwright install chromium 2>&1 | tail -2
echo "  ✅ 文档层依赖就绪（PDF 渲染用 playwright chromium）"

say "3/5 安装 XHS-Downloader（小红书笔记级取数 · 纯 HTTP · 无需 Cookie）"
if [ ! -d /tmp/XHS-Downloader ]; then
  git clone --depth 1 -q https://github.com/JoeanAmier/XHS-Downloader.git /tmp/XHS-Downloader
fi
pip install -q -r /tmp/XHS-Downloader/requirements.txt && echo "  ✅ XHS-Downloader 就绪（/tmp/XHS-Downloader）"

say "4/5 安装 gh CLI（GitHub 官方命令行；需 GH_TOKEN 才能用）"
if [ ! -x "$HOME/.local/bin/gh" ]; then
  mkdir -p "$HOME/.local/bin"
  curl -sL --max-time 300 "https://github.com/cli/cli/releases/latest/download/gh_$(curl -s https://api.github.com/repos/cli/cli/releases/latest | python3 -c 'import json,sys;print(json.load(sys.stdin)["tag_name"][1:])')_linux_amd64.tar.gz" -o /tmp/gh.tgz \
    && tar xzf /tmp/gh.tgz -C /tmp \
    && cp /tmp/gh_*_linux_amd64/bin/gh "$HOME/.local/bin/" && chmod +x "$HOME/.local/bin/gh"
fi
export PATH="$HOME/.local/bin:$PATH"
echo "  $(gh --version 2>/dev/null | head -1 || echo 'gh 未安装')"

if [ "${1:-}" = "--browser" ]; then
  say "5/5 浏览器路线（小红书 · 备用）"
  mkdir -p ~/.agent-reach/tools && cd ~/.agent-reach/tools
  V=v2.5.5
  for f in xiaohongshu-mcp-linux-amd64 xiaohongshu-login-linux-amd64; do
    [ -f "$f" ] || curl -sL --max-time 600 -o "$f" "https://github.com/xpzouying/xiaohongshu-mcp/releases/download/$V/$f"
    chmod +x "$f"
  done
  echo "  ✅ 二进制就绪；首次运行 xiaohongshu-login 会下载 ~150MB 浏览器（耐心等待，勿中断）"
  echo "  ⚠️ 注意：首次解压必须让其完整跑完，中断会导致 chrome 二进制截断（Bus error / missing section headers）"
else
  say "5/5 跳过浏览器路线（如需请加 --browser）"
fi

say "补齐 Chromium 系统库（无 root 环境）"
bash "$(dirname "$0")/fix_chromium_libs.sh" 2>&1 | tail -4 || echo "  （跳过：二进制未就绪）"

say "环境就绪。可选：Xvfb 用于无头带界面流程"
echo "  Xvfb :99 -screen 0 1400x1000x24 -nolisten tcp &   # 需要时启动"
echo
echo "验证命令："
echo "  source ~/.agent-reach-venv/bin/activate && agent-reach doctor"
echo "  python3 collector/step10b_xhs_http.py collector/xhs_probe.json   # 小红书取数自检"
