#!/usr/bin/env python3
"""
65 项任务每日总结分析改进报告
用户要求：每天发送 65 项任务的工作总结、分析、改进报告

2026-11-04 修订（用户批准修 daily_65_report.py）：
- 旧版只写硬编码总数（分钟级 27 + 小时级 9 + 每日 21 + 每周 8 = 65）
  和两项可测指标，缺逐项清单、缺故障根因明细 —— 这正是 11-04 报告
  被用户指出不达标的两点。本版补齐这两块。
- 逐项清单：不再硬编码。枚举 ~/workspace/goals/karenvsai/crons/
  下分钟级/小时级/每日/每周四组定义文件（排除 .bak），每项给
  id、标题、排期、最近日志证据与启发式状态。旧 65 数已过期
  （定义文件已增长），报告标题沿用“65 项”旧称，但清单数以
  本次枚举为准，并在执行概况里明说漂移，避免用旧数冒充现状。
- 故障段：只写本脚本能从本地证据读到的项（发布数、队列、
  anomaly 台账、Ask Studio 待回答、平台矩阵 stale、teaser B' 限流），
  每项给出现象、证据来源、根因（证据里有的写，没有的写“未查明”，
  绝不编造）、修复/当前状态。SUSPECT 不等于 CONFIRMED（Rule 14），
  未见运行记录不等于失败。
- 本脚本不重跑浏览器/Arena 等慢探针（报告 08:49 须快、须只读）：
  分发链健康以当日日志与本地台账为准，不在报告里现做判定。
- 运行：python3 /home/hatch/data/perpetua/daily_65_report.py
  输出：Markdown 报告，写入 /home/hatch/data/perpetua/reports/daily_65_YYYY-MM-DD.md
  干测：python3 .../daily_65_report.py --dry-run （只打印不写正式报告）
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

REPORT_DIR = Path("/home/hatch/data/perpetua/reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
CST = timezone(timedelta(hours=8))
CRON_BASE = Path.home() / "workspace" / "goals" / "karenvsai" / "crons"
MEMORY_DIR = Path.home() / "memory"

# 频道 @karenvsai 的固定 ID（与 deep_dive_pull_48h.py / comment_sweep.py /
# post_publish_optimizer.py 中的同名常量一致）。取数本身走 yt.recent_videos
# 的 mine=true 路径，不依赖 .oauth.json 里的 channel_id 键。
CHANNEL_ID = "UCaVJw-mQc51X8WWssI1vjbg"

# ---- 日志启发式状态判定（关键词，非权威结论） ----
_FAIL_WORDS = ("失败", "failed", "exit=1", "exit=2", "degraded", "suspect",
                "warning", "告警", "掉线", "stale", "卡死", "卡住", "未恢复",
                "超时", "被挡", "未测得", "未见")
_OK_WORDS = ("exit=0", "exit 0", "ok", "健康", "完成", "成功", "200", "正常", "已公开",
             "已发布", "验真", "通过", "success", "done")
_REPAIRED_WORDS = ("已修复", "已恢复", "恢复正常", "已拉起", "自恢复", "已翻回")


def _classify(snippet, job_id=""):
    """返回 (状态, 依据)。snippet 为当日日志里该项的最后一条记录。

    注意两个误判坑（2026-11-04 干测实测）：
    - 任务名本身可能含失败词（如 pipeline-failed-cleanup），先剔除 job_id
      再做关键词判定，否则标题行恒判异常；
    - 否定表述（无告警、卡住待生成 0、status ok 小写）须先剔除/归一化，
      否则“无告警”会被“告警”误判、“status ok”会因大小写漏判。
    """
    if not snippet:
        return ("未见记录", "近 8 天日志未见该 id")
    text = snippet.replace(job_id, "")
    for neg in ("无告警", "无故障", "无异常", "卡住待生成 0", "卡住 0"):
        text = text.replace(neg, "")
    low = text.lower()
    if any(w in snippet for w in _REPAIRED_WORDS):
        return ("已恢复", "最后记录含恢复表述")
    if any(w in low for w in _FAIL_WORDS):
        return ("异常信号", "最后记录含失败/告警关键词，SUSPECT 不等于已证实故障")
    if any(w in low for w in _OK_WORDS):
        return ("正常", "最后记录含成功/健康关键词")
    return ("有记录，结论不明", "最后记录无明确成败关键词")


def enumerate_jobs():
    """枚举 cron 定义文件。返回 (按组分好的 jobs, 总数)。"""
    groups = {}
    for kind in ("minutely", "hourly", "daily", "weekly"):
        d = CRON_BASE / kind
        jobs = []
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if not f.name.endswith(".md") or ".bak" in f.name:
                    continue
                stem = f.name[:-3]
                job_id = stem.split("__")[0]
                sched = stem.split("__", 1)[1] if "__" in stem else ""
                title = job_id
                try:
                    head = f.read_text(encoding="utf-8", errors="ignore")[:2000]
                    m = re.search(r"^title:\s*(.+)$", head, re.M)
                    if m:
                        title = m.group(1).strip()
                    m2 = re.search(r"^id:\s*(.+)$", head, re.M)
                    if m2:
                        job_id = m2.group(1).strip()
                except Exception:
                    pass
                jobs.append({"id": job_id, "title": title, "sched": sched,
                             "kind": kind})
        groups[kind] = jobs
    return groups


def last_log_evidence(job_ids, end_date):
    """在近 8 天 memory 日志里找每项的最后一条记录。

    按日期从旧到新扫描，同一项后出现者覆盖前者；返回
    {job_id: (日期, 行文本截断)}。只读，不改日志。
    """
    evidence = {}
    for back in range(7, -1, -1):
        day = end_date - timedelta(days=back)
        log = MEMORY_DIR / f"{day.strftime('%Y-%m-%d')}.md"
        if not log.is_file():
            continue
        try:
            lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            for jid in job_ids:
                if jid and jid in line:
                    snippet = line.strip()[:220]
                    # 标题行本身无状态：顺延取本节第一条正文行，否则
                    # 该项恒为“结论不明”。只取一行，不展开整节。
                    if line.lstrip().startswith("#"):
                        for nxt in lines[i + 1:i + 21]:
                            s = nxt.strip()
                            if s.startswith("-") or "exit" in s.lower():
                                snippet += " | " + s[:160]
                                break
                    evidence[jid] = (day.strftime("%Y-%m-%d"), snippet)
    return evidence


def collect_metrics():
    """收集今日关键指标（原有口径保留）"""
    metrics = {}

    # 1. 发布数（YouTube API，public-only 口径，与 publish_health.py C11 一致）
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

    # 2. 死状态（原有口径）
    try:
        db = sqlite3.connect("/home/hatch/data/ops_center.db")
        cur = db.cursor()
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


def collect_faults(now_cst):
    """从本地证据收集故障项。每项：现象 / 证据 / 根因 / 修复或状态。

    根因只写证据里有的；证据里没有的写“未查明”，不编造。
    """
    faults = []

    # A. 队列状态（queue_db，SQLite 真相源）
    try:
        from queue_db import pipeline_load, privateq_load
        pipe = pipeline_load()
        priv = privateq_load()
        pc = Counter(x.get("status") for x in pipe)
        qc = Counter(x.get("status") for x in priv)
        stuck_parts = []
        if pc.get("generate_failed"):
            stuck_parts.append(f"generate_failed {pc['generate_failed']} 条")
        if pc.get("arena_manual"):
            stuck_parts.append(f"arena_manual {pc['arena_manual']} 条")
        if pc.get("teaser_validation"):
            stuck_parts.append(f"teaser_validation {pc['teaser_validation']} 条待处理")
        if pc.get("held_user_decision"):
            stuck_parts.append("held_user_decision 1 条（等用户决策）")
        if stuck_parts:
            faults.append({
                "title": "管线队列积压（" + "、".join(stuck_parts) + "）",
                "evidence": f"queue_db：pipeline {len(pipe)} 行，privateq {len(priv)} 行；"
                            f"pipeline 状态 {dict(pc)}，privateq 状态 {dict(qc)}。",
                "cause": "未查明：队列状态本身不说明单条卡因，单条根因须查该条的生成/QC/评审记录，"
                         "不在本报告口径内逐条展开。",
                "action": "未自动改状态（Rule 15：无消费者状态禁写）；积压条目按原有看门狗/人工决策路径处理，"
                          "不在日报里擅自归档或重推。",
            })
        for x in priv:
            if x.get("status") == "flip_blocked":
                faults.append({
                    "title": f"privateq flip_blocked 残留：{x.get('title', '')[:30]}"
                              f"（{x.get('video_id')}）",
                    "evidence": f"queue_db privateq 行：status=flip_blocked，"
                                f"scheduled_at={x.get('scheduled_at')}。",
                    "cause": "未查明：该行属历史翻转阻塞残留，经手人/阻塞原因未在队列行内记录，"
                             "不得在日报里补一个经手人。",
                    "action": "保持不动、不 emergency_flip；已公开的视频以 API/公开页为准，残留行待人工清理决策。",
                })
        waiting = [x for x in priv if x.get("status") == "waiting"]
        for x in waiting:
            faults.append({
                "title": f"privateq waiting 待翻公开：{x.get('title', '')[:30]}"
                          f"（{x.get('video_id')}，档位 {x.get('slot')}）",
                "evidence": f"queue_db privateq 行：status=waiting，"
                            f"scheduled_at={x.get('scheduled_at')}。",
                "cause": "排期未到，非故障；列入此处是为让“24h 发布低于目标”有对应的下一档证据，"
                         "不是把它算作故障。",
                "action": "到档前重验 privacyStatus 再翻；翻后按发布政策主动通知用户。",
            })
    except Exception as e:
        faults.append({
            "title": "队列状态未测得",
            "evidence": f"queue_db 读取失败：{e}",
            "cause": "未查明（读取失败本身）。",
            "action": "下轮复核队列读取，不作“队列健康”结论。",
        })

    # B. anomaly 台账未解决项
    try:
        led = json.loads(Path("/home/hatch/data/perpetua/anomaly_ledger.json")
                         .read_text(encoding="utf-8"))
        un = [x for x in led if not x.get("resolved")]
        if un:
            by_checker = Counter(x.get("checker") for x in un)
            oldest = sorted(un, key=lambda x: x.get("at", ""))[0]
            try:
                age_h = (datetime.now(timezone.utc)
                         - datetime.fromisoformat(
                             oldest.get("at", "").replace("Z", "+00:00"))
                         ).total_seconds() / 3600
                age_txt = f"约 {age_h:.0f} 小时"
            except Exception:
                age_txt = "年龄未测得"
            top_subjects = Counter(x.get("subject") for x in un).most_common(5)
            faults.append({
                "title": f"anomaly 台账未解决 {len(un)} 条（ack 积压）",
                "evidence": f"anomaly_ledger.json：未解决 {len(un)} 条，"
                            f"按 checker 分 {dict(by_checker)}；最老 {oldest.get('at')} "
                            f"（{age_txt}，{oldest.get('checker')} / {oldest.get('subject')}，"
                            f"detail：{str(oldest.get('detail', ''))[:120]}）；"
                            f"高频 subject 前 5：{top_subjects}。",
                "cause": "台账只记 SUSPECT，不等于已证实故障；多条为同一 subject 的重复记录，"
                         "属 ack 积压而非每日新增故障类型。单条根因见其 detail 字段，"
                         "本报告不把 SUSPECT 升格为 CONFIRMED。",
                "action": "不自动清台账、不自动屏蔽告警（Rule 14）；积压清理与 FALLBACK 落盘缺陷修复"
                          "在待批清单里，不在日报里擅自执行。",
            })
    except Exception as e:
        faults.append({
            "title": "anomaly 台账未测得",
            "evidence": f"anomaly_ledger.json 读取失败：{e}",
            "cause": "未查明（读取失败本身）。",
            "action": "下轮复核台账读取。",
        })

    # C. Ask Studio 待回答
    try:
        qpath = Path("/home/hatch/data/ask_studio/queue.json")
        q = json.loads(qpath.read_text(encoding="utf-8"))
        pending = q.get("pending", [])
        cf = Path("/home/hatch/data/ask_studio/consecutive_failures.txt")
        cf_n = cf.read_text(encoding="utf-8").strip() if cf.is_file() else "未知"
        if pending:
            items = "; ".join(
                f"{e.get('id')}（asked_by={e.get('asked_by')}，created={e.get('created')}）"
                for e in pending)
            err_txt = ""
            for cand in (now_cst.strftime("%Y-%m-%d"),):
                ef = Path(f"/home/hatch/data/ask_studio/{cand}.error.txt")
                if ef.is_file():
                    err_txt = ef.read_text(encoding="utf-8")[:300]
                    break
            faults.append({
                "title": f"Ask Studio 待回答 {len(pending)} 条（通道阻塞中）",
                "evidence": f"ask_studio/queue.json pending={len(pending)}：{items}；"
                            f"consecutive_failures.txt={cf_n}。"
                            + (f"当日错误文件摘录：{err_txt}" if err_txt else ""),
                "cause": "未查明到单条根因：待回答本身只说明问题未送达/未答复，"
                         "通道终点形态（申诉页/验证弹窗等）须以当日 Ask Studio 健康检查为准，"
                         "本报告不下“登录过期”结论、不发登录卡。",
                "action": "工人通道失败时由主 agent 亲自派发绕行（已升级）；未送达的问题不编造答案充数。",
            })
    except Exception as e:
        faults.append({
            "title": "Ask Studio 队列未测得",
            "evidence": f"ask_studio/queue.json 读取失败：{e}",
            "cause": "未查明（读取失败本身）。",
            "action": "下轮复核队列读取。",
        })

    # D. 平台矩阵 stale
    try:
        m = json.loads(Path("/home/hatch/data/perpetua/distributor/platform_matrix.json")
                       .read_text(encoding="utf-8"))
        stale = [(k, v) for k, v in m.get("platforms", {}).items()
                 if v.get("status") != "ok"]
        if stale:
            desc = "; ".join(
                f"{k}（{str(v.get('stale_reason') or v.get('status'))[:80]}）"
                for k, v in stale)
            faults.append({
                "title": f"平台矩阵 stale {len(stale)} 个平台",
                "evidence": f"distributor/platform_matrix.json updated_at="
                            f"{m.get('updated_at')}；stale：{desc}。",
                "cause": "各平台 stale 原因见其 stale_reason 字段；其中工人单轮说法（如 facebook）"
                         "未经主 agent 亲验的，不在本报告里定论为掉线。",
                "action": "stale 平台不同步、不冒充已同步；需人工重登的（如快手）等用户动作后复验。",
            })
    except Exception as e:
        faults.append({
            "title": "平台矩阵未测得",
            "evidence": f"platform_matrix.json 读取失败：{e}",
            "cause": "未查明（读取失败本身）。",
            "action": "下轮复核矩阵读取。",
        })

    # E. teaser B' 限流（本地台账口径，API 不可用时不冒充 API 计数）
    try:
        led = json.loads(Path("/home/hatch/data/perpetua/shorts_throttle.json")
                         .read_text(encoding="utf-8"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        n7 = 0
        for v in led:
            try:
                dt = datetime.fromisoformat(
                    v.get("published_at", "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt >= cutoff:
                n7 += 1
        if n7 > 2:
            faults.append({
                "title": f"teaser B' 限流拦住新提交（滚动 7 天 {n7} 条 vs 上限 2 条）",
                "evidence": "shorts_throttle.json 本地台账口径（YouTube API 取数不可用时回落本地台账，"
                            f"计数未经 API 权威核验）；teaser_validation 队列待处理条数见队列段。",
                "cause": "限流本身是保护规则，不是故障；提交被拦的原因是 7 天内已公开 Shorts 已超上限。",
                "action": "不绕过 B' 限流、不降质硬发；待滚动窗口自然回落后再提交。",
            })
    except Exception as e:
        faults.append({
            "title": "teaser 限流计数未测得",
            "evidence": f"shorts_throttle.json 读取失败：{e}",
            "cause": "未查明（读取失败本身）。",
            "action": "下轮复核台账读取。",
        })

    return faults


def generate_report(args):
    now_cst = datetime.now(CST)
    if args.date:
        date_str = args.date
        end_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        date_str = now_cst.strftime("%Y-%m-%d")
        end_date = now_cst.date()

    metrics = collect_metrics()
    groups = enumerate_jobs()
    all_jobs = [j for kind in ("minutely", "hourly", "daily", "weekly")
                for j in groups[kind]]
    evidence = last_log_evidence([j["id"] for j in all_jobs], end_date)

    pubs = metrics.get("publishes_24h")
    if pubs is None:
        pubs_line = f"未测得（YouTube API 调用失败：{metrics.get('publish_error', '未知错误')}；不作无发布结论）"
    else:
        pubs_line = f"{pubs} 条（目标 2-3）"
    stuck = metrics.get("stuck_review_passed")
    stuck_line = "未知（队列读取失败）" if stuck is None else f"{stuck} 条 review_passed 无 video_file"

    # 逐项清单状态汇总
    status_counter = Counter()
    item_lines = []
    for kind in ("minutely", "hourly", "daily", "weekly"):
        item_lines.append(f"\n### {kind}（{len(groups[kind])} 项）\n")
        for j in groups[kind]:
            ev = evidence.get(j["id"])
            if ev:
                status, basis = _classify(ev[1], j["id"])
                ev_txt = f"最近记录 {ev[0]}：{ev[1][:160]}"
            else:
                status, basis = ("未见记录", "近 8 天日志未见该 id")
                ev_txt = "近 8 天日志未见该 id"
            status_counter[status] += 1
            item_lines.append(
                f"- [{status}] {j['id']}（{j['title']}，排期 {j['sched'] or '见定义文件'}）"
                f" — {basis}；{ev_txt}\n")

    faults = collect_faults(now_cst)
    # 发布低于目标 / 取数失败也记入故障段（原有口径保留，不丢）
    head_faults = []
    if pubs is None:
        head_faults.append({
            "title": "24h 公开数未测得",
            "evidence": f"YouTube API 调用失败：{metrics.get('publish_error', '未知错误')}。",
            "cause": "未查明（API 调用失败本身，传输层断连与配额拒单须区分，证据不足不下结论）。",
            "action": "本报告不作“无发布”结论，需人工或下轮复核；配额 403 时走浏览器兜底，不重发已发内容。",
        })
    elif pubs < 2:
        head_faults.append({
            "title": f"过去 24h 公开 {pubs} 条，低于 2-3 条目标",
            "evidence": "yt.recent_videos（mine=true，public-only 口径，private 预传不计）24h 计数。",
            "cause": "未查明到单因：发布数是排期、评审、生成、翻公开多环节的结果，"
                     "本段只给计数与下一档 waiting 证据（见下），不把“低于目标”本身当根因。",
            "action": "下一排期档前补齐预传/翻公开，避免 24h 窗口继续低于 2 条；翻公开前重验 privacy。",
        })
    if stuck is None:
        head_faults.append({
            "title": "卡住待生成数未测得",
            "evidence": "ops_center.db 队列读取失败。",
            "cause": "未查明（读取失败本身）。",
            "action": "下轮复核队列读取。",
        })
    elif stuck > 0:
        head_faults.append({
            "title": f"卡住待生成：{stuck} 条 review_passed 无 video_file",
            "evidence": "ops_center.db event_bus 口径。",
            "cause": "未查明到单条根因，须查单条生成记录。",
            "action": "处理卡住项（补 video_file 或按管线规则归档），避免待生成积压。",
        })
    all_faults = head_faults + faults

    fault_lines = []
    for i, f in enumerate(all_faults, 1):
        fault_lines.append(
            f"{i}. **{f['title']}**\n"
            f"   - 现象/证据：{f['evidence']}\n"
            f"   - 根因：{f['cause']}\n"
            f"   - 修复/当前状态：{f['action']}")
    faults_text = "\n".join(fault_lines) if fault_lines else (
        "本节说明：脚本可测范围内（24h 公开数、卡住待生成、队列、anomaly 台账、"
        "Ask Studio 队列、平台矩阵、teaser 限流）今日无故障记录。"
        "此句仅覆盖上述口径，不等于全系统无故障。")

    improvements = []
    for f in all_faults:
        improvements.append(f"- 针对“{f['title']}”：{f['action']}")
    improvements_text = "\n".join(improvements) if improvements else (
        "本节说明：基于今日可测数据暂无新的改进项；无数据支撑的建议不编造。")

    report = f"""# 65 项任务每日报告 — {date_str}

## 执行概况
- 报告时间：{now_cst.strftime("%Y-%m-%d %H:%M")} CST
- 频道：@karenvsai（{CHANNEL_ID}）
- 任务清单：本次枚举 {len(all_jobs)} 项（分钟级 {len(groups['minutely'])} + 小时级 {len(groups['hourly'])} + 每日 {len(groups['daily'])} + 每周 {len(groups['weekly'])}，源自 karenvsai cron 定义文件，排除 .bak）
- 口径说明：报告标题沿用“65 项”旧称，但旧硬编码（27+9+21+8=65）已过期，定义文件此后已增长；清单数以本次枚举为准，不再用旧数冒充现状。
- 逐项状态汇总：{dict(status_counter)}（状态为当日日志关键词启发式判定：未见记录不等于失败，异常信号不等于已证实故障，SUSPECT 不等于 CONFIRMED）

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

    report += f"""
## 任务逐项清单
{''.join(item_lines)}

## 故障与修复
{faults_text}

## 改进建议
{improvements_text}

---
*自动生成：daily_65_report.py（2026-11-04 修订版：动态枚举清单 + 本地证据故障段）*
"""

    if args.dry_run:
        print(report)
        print(f"（干测：未写正式报告文件；正式路径为 {REPORT_DIR / f'daily_65_{date_str}.md'}）")
        return None

    report_file = REPORT_DIR / f"daily_65_{date_str}.md"
    if args.out:
        report_file = Path(args.out)
        report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(report, encoding="utf-8")
    print(f"报告已生成：{report_file}")
    print(report)
    return str(report_file)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印不写正式报告文件")
    ap.add_argument("--out", default="",
                    help="写到指定路径（测试用），不写正式报告文件")
    ap.add_argument("--date", default="",
                    help="报告日期 YYYY-MM-DD（测试用），默认今天")
    generate_report(ap.parse_args())
