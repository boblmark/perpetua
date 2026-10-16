#!/usr/bin/env python3
"""指挥官对话队列处理器：处理控制台发给 muse 的异步消息。

每 2 分钟由 cron 运行一次：
1. 读 commander_chat_queue.json
2. 对 status=pending 的消息生成回复
3. 回复策略：
   - 先试关键词（复用 console_server 的 chat_keyword 逻辑简化版）
   - 复杂问题：生成基于当前系统状态的回复（读 snapshot、队列等）
4. 写回队列，status=done
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/hatch/data/perpetua")
QPATH = BASE / "commander_chat_queue.json"
SNAPSHOT = BASE / "vps_console" / "snapshot.json"


def load_snapshot():
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def try_keyword_reply(msg: str) -> str | None:
    """简单的关键词回复，覆盖常见查询。"""
    m = msg.lower()
    snap = load_snapshot()
    if any(k in msg for k in ["热点", "trend"]):
        try:
            r = subprocess.run(
                ["python3", str(BASE / "trend_spike_detector.py")],
                capture_output=True, text=True, timeout=60, cwd=str(BASE))
            out = (r.stdout or "")[-800:]
            return f"热点检测已执行：\n{out or '(无输出)'}"
        except Exception as e:
            return f"热点检测执行失败：{e}"
    if "ypp" in m:
        subs = snap.get("subscriberCount", 0)
        wh = snap.get("watchHoursDiag", 0)
        return (f"YPP 进度（长视频路径）：订阅 {subs}/1000（还差 {1000-subs}）；"
                f"观看小时 {wh:.0f}/4000 诊断值（非 qualified，以 Studio Eligibility 为准）。")
    if any(k in msg for k in ["健康", "health"]):
        hs = snap.get("health", [])
        lines = [f"{'✓' if h.get('healthy') else '✗'} {h.get('name')}: {h.get('detail')}" for h in hs]
        return "系统健康：\n" + "\n".join(lines) if lines else "健康数据暂无。"
    if any(k in msg for k in ["队列", "queue"]):
        try:
            qpath = BASE / "ask_studio" / "queue.json"
            q = json.loads(qpath.read_text(encoding="utf-8")) if qpath.exists() else {}
            items = q.get("queue", q if isinstance(q, list) else [])
            n = len(items) if isinstance(items, list) else 0
            return f"Ask Studio 队列：{n} 个待处理问题。"
        except Exception:
            return "队列数据读取失败。"
    if any(k in msg for k in ["配额", "quota"]):
        return f"今日配额：{snap.get('quotaUsed', 0)} / {snap.get('quotaTotal', 10)}（每日 00:00 重置）。"
    if "热备" in msg or "hotstandby" in m or "nano" in m:
        try:
            r = subprocess.run(
                [sys.executable, str(BASE / "muse_or_nano.py"), "--status"],
                capture_output=True, text=True, timeout=60)
            st = json.loads(r.stdout.strip())
            eff = st.get("effective_backend", "?")
            healthy = st.get("musemain_health", {}).get("healthy")
            return (f"热备状态：当前后端={eff}，muse-main 健康={'是' if healthy else '否'}。"
                    f"降级守护运行中（真实模式）。回切需人工确认。")
        except Exception as e:
            return f"热备状态查询失败：{e}"
    return None


def generate_reply(msg: str) -> str:
    """生成回复：先关键词，兜底给通用回复。"""
    kw = try_keyword_reply(msg)
    if kw:
        return kw
    # 兜底：说明这是异步通道，建议的方式
    return (
        "收到。这个问题需要主 agent 深入处理，已记录。\n\n"
        "目前控制台对话支持即时查询：YPP 进度、系统健康、热备状态、配额、热点检测、Ask Studio 队列。\n"
        "复杂操作（如发布、删除、改配置）请在主聊天里直接跟我说，我来执行。"
    )


def main():
    if not QPATH.exists():
        return
    try:
        queue = json.loads(QPATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"队列读取失败: {e}", file=sys.stderr)
        return
    changed = False
    for item in queue:
        if item.get("status") == "pending":
            msg = item.get("message", "")
            try:
                reply = generate_reply(msg)
            except Exception as e:
                reply = f"处理出错：{e}"
            item["reply"] = reply
            item["status"] = "done"
            item["replied_at"] = datetime.now(timezone.utc).isoformat()
            changed = True
            print(f"已回复 {item.get('qid')}: {msg[:50]}")
    if changed:
        QPATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
