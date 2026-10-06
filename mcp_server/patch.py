#!/usr/bin/env python3
"""把 virality_score 工具切到 v2 数据驱动版，并新增 youtube_audit 工具。"""
import re
import shutil
from pathlib import Path

P = Path("/home/hatch/data/mcp_server/server.py")
src = P.read_text(encoding="utf-8")
orig = src

# ---------- 1) virality_score 切换到 v2 ----------
old_vs = '''@mcp.tool()
def virality_score(title: str, hook: str = "", topic_heat: str = "medium", duration: int = 10) -> str:
    """给 Short 选题打爆款分（0-100）。低于60分建议回炉。
    topic_heat: high/medium/low。返回分数、等级与优化建议。"""
    try:
        r = subprocess.run(
            ["./venv/bin/python", "virality_score.py", json.dumps({
                "title": title, "hook": hook,
                "topic_heat": topic_heat, "duration": duration,
            })],
            cwd=str(HERE), capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"'''

new_vs = '''@mcp.tool()
def virality_score(title: str, hook: str = "", topic_heat: str = "medium", duration: int = 10) -> str:
    """给 Short 选题打爆款分（0-100）。低于58分建议回炉。

    数据驱动版（v2）：权重从本频道 481 条历史视频的实际播放量回归得出，
    而非人工关键词表。实测 Spearman ρ=0.32（v1 规则版 ρ≈0）。Top50 命中率
    28.6% vs v1 的 4.1%，Top50 平均播放 4,203 vs 825。
    topic_heat: high/medium/low。返回分数、等级、命中的有效特征与优化建议。"""
    try:
        r = subprocess.run(
            ["python3", "/home/hatch/data/youtube/virality_score_v2.py", json.dumps({
                "title": title, "hook": hook,
                "topic_heat": topic_heat, "duration": duration,
            })],
            cwd=str(HERE), capture_output=True, text=True, timeout=20,
        )
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"'''

assert old_vs in src, "virality_score block not found"
src = src.replace(old_vs, new_vs)

# ---------- 2) 新增 youtube_audit ----------
anchor = '''@mcp.tool()
def youtube_stats() -> str:'''

new_tool = '''@mcp.tool()
def youtube_audit(days: int = 30, refresh: bool = False) -> str:
    """复盘最近 N 天视频的真实表现，并对比当时的爆款预测分。

    这是闭环的回流环节：拉取真实播放数据 -> 与 virality_score 预测并列 ->
    计算预测准确率 -> 给出下一轮选题修正建议。
    refresh=True 时重新全量拉取频道历史（较慢，约 20s）。
    """
    try:
        args = ["python3", "/home/hatch/data/youtube/audit.py", str(days)]
        if refresh:
            args.append("--refresh")
        r = subprocess.run(args, cwd=str(HERE), capture_output=True,
                           text=True, timeout=120)
        return r.stdout.strip() or r.stderr.strip() or "[error] no output"
    except Exception as e:
        return f"[error] {e}"


@mcp.tool()
def youtube_stats() -> str:'''

assert anchor in src, "youtube_stats anchor not found"
src = src.replace(anchor, new_tool, 1)

P.write_text(src, encoding="utf-8")
print(f"server.py updated: {len(orig)} -> {len(src)} bytes")

# 语法检查
import py_compile
py_compile.compile(str(P), doraise=True)
print("syntax OK")
