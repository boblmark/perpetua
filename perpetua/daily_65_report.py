#!/usr/bin/env python3
"""
65 项任务每日总结分析改进报告
用户要求：每天发送 65 项任务的工作总结、分析、改进报告

报告内容：
1. 执行概况：65 项中多少正常、多少异常、多少修复
2. 关键指标：发布数、健康状态、管线状态
3. 故障分析：今日故障、根因、修复动作
4. 改进建议：基于今日数据的优化点

运行：python3 /home/hatch/data/perpetua/daily_65_report.py
输出：Markdown 报告，写入 /home/hatch/data/perpetua/reports/daily_65_YYYY-MM-DD.md
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

REPORT_DIR = Path("/home/hatch/data/perpetua/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
CST = timezone(timedelta(hours=8))

# 频道 @karenvsai 的固定 ID（与 deep_dive_pull_48h.py / comment_sweep.py /
# post_publish_optimizer.py 中的同名常量一致）。取数本身走 yt.recent_videos
# 的 mine=true 路径，不依赖 .oauth.json 里的 channel_id 键。
CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"

def collect_metrics():
    """收集今日关键指标"""
    metrics = {}

    # 1. 发布数（YouTube API，public-only 口径，与 publish_health.py C11 一致）
    # 旧路径 daily_reconciliation.get_recent_public_videos 依赖 .oauth.json 里
    # 的 channel_id，但该文件根本没有 channel_id 键（2026-10-29 实测 keys 无
    # 此项），故恒返回 {"error": "no channel_id configured"}；本脚本旧代码
    # 又把 error 映射成 -1、明细写“今日无发布”，与事实矛盾。
    # 新路径用 yt.recent_videos（mine=true，不依赖 channel_id 配置），只计
    # privacyStatus==public 且 published 在 24h 内；private 预传不计。
    # API 失败时计 None（未测得），绝不再写 -1 哨兵。
    try:
        from yt import recent_videos
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        pub24 = []
        for v in recent_videos(max_n=20):
            if v.get("privacyStatus") != "public":
                continue
            try:
                pub_dt = datetime.fromisoformat(
                    (v.get("published") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if pub_dt >= cutoff:
                pub24.append({
                    "video_id": v.get("id"),
                    "title": v.get("title", ""),
                    "published_at": v.get("published", ""),
                    "url": f"https://youtu.be/{v.get('id')}",
                })
        metrics["publishes_24h"] = len(pub24)
        metrics["publish_videos"] = pub24
        metrics["publish_status"] = "measured"
    except Exception as e:
        metrics["publishes_24h"] = None
        metrics["publish_videos"] = []
        metrics["publish_status"] = "unknown"
        metrics["publish_error"] = str(e)
    
    # 2. 配额
    try:
        from quota_monitor import estimate_quota_usage
        # 简单调用，不 import 整个模块
        metrics["quota"] = "check_manually"
    except:
        pass
    
    # 3. 死状态
    try:
        import sqlite3
        db = sqlite3.connect("/home/hatch/data/ops_center.db")
        cur = db.cursor()
        # review_passed 无 video_file 的数量
        cur.execute("""
            SELECT COUNT(*) FROM event_bus 
            WHERE json_extract(payload, '$.status') = 'review_passed'
              AND (json_extract(payload, '$.video_file') IS NULL 
                   OR json_extract(payload, '$.video_file') = '')
        """)
        metrics["stuck_review_passed"] = cur.fetchone()[0]
        db.close()
    except Exception as e:
        metrics["stuck_review_passed"] = None
        metrics["stuck_error"] = str(e)

    return metrics

def generate_report():
    now_cst = datetime.now(CST)
    date_str = now_cst.strftime("%Y-%m-%d")
    
    metrics = collect_metrics()
    
    pubs = metrics.get("publishes_24h")
    if pubs is None:
        pubs_line = f"未测得（YouTube API 调用失败：{metrics.get('publish_error', '未知错误')}；不作无发布结论）"
    else:
        pubs_line = f"{pubs} 条（目标 2-3）"
    stuck = metrics.get("stuck_review_passed")
    stuck_line = "未知（队列读取失败）" if stuck is None else f"{stuck} 条 review_passed 无 video_file"

    report = f"""# 65 项任务每日报告 — {date_str}

## 执行概况
- 报告时间：{now_cst.strftime("%Y-%m-%d %H:%M")} CST
- 频道：@karenvsai（{CHANNEL_ID}）
- 任务总数：65 项（分钟级 27 + 小时级 9 + 每日 21 + 每周 8）

## 关键指标
- 过去 24h 发布：{pubs_line}
- 卡住待生成：{stuck_line}

## 发布明细
"""
    if metrics.get("publish_status") == "unknown":
        report += "（24h 公开数未测得：API 调用失败，见关键指标；此处不作“无发布”结论）\n"
    else:
        for v in metrics.get("publish_videos", []):
            report += f"- [{v['title'][:50]}]({v['url']}) — {v['published_at'][:16]}\n"
        if not metrics.get("publish_videos"):
            report += "（24h 内无公开视频——已实测，非未测得）\n"

    # 故障与修复：只写本脚本可测口径得出的项；无项时明言口径边界，
    # 不再留“（从当日日志提取）”这类空占位。
    faults = []
    if pubs is None:
        faults.append(f"- 24h 公开数未测得（YouTube API 调用失败：{metrics.get('publish_error', '未知错误')}）；本报告不作“无发布”结论，需人工或下轮复核。")
    elif pubs < 2:
        faults.append(f"- 过去 24h 公开 {pubs} 条，低于 2-3 条目标。")
    if stuck is None:
        faults.append("- 卡住待生成数未测得（队列读取失败）。")
    elif stuck > 0:
        faults.append(f"- 卡住待生成：{stuck} 条 review_passed 无 video_file。")
    faults_text = "\n".join(faults) if faults else (
        "本节说明：脚本可测范围内（24h 公开数、卡住待生成）今日无故障记录。"
        "此句仅覆盖上述两项口径，不等于全系统无故障；当日日志人工复核不在本脚本口径内。")

    improvements = []
    if pubs is None:
        improvements.append("- 先恢复 24h 公开数取数（失败原因见故障节），否则日报无法核验发布目标。")
    elif pubs < 2:
        improvements.append("- 发布低于目标：下一排期档前补齐预传/翻公开，避免 24h 窗口继续低于 2 条。")
    if isinstance(stuck, int) and stuck > 0:
        improvements.append("- 处理卡住的 review_passed 项（补 video_file 或按管线规则归档），避免待生成积压。")
    improvements_text = "\n".join(improvements) if improvements else (
        "本节说明：基于今日可测数据（发布达标且无卡住项），暂无新的改进项；无数据支撑的建议不编造。")

    report += f"""
## 故障与修复
{faults_text}

## 改进建议
{improvements_text}

---
*自动生成：daily_65_report.py*
"""
    
    # 写入文件
    report_file = REPORT_DIR / f"daily_65_{date_str}.md"
    report_file.write_text(report, encoding="utf-8")
    
    print(f"报告已生成：{report_file}")
    print(report)
    return str(report_file)

if __name__ == "__main__":
    generate_report()
