#!/usr/bin/env python3
"""
48 小时视频评估器（爆款加码 B 计划的 R1/R4 执行器，2026-10-12 用户已拍板）。

- R1（feed 份额北极星）：每条发布满 48h 的 Shorts，用 Shorts feed 播放份额
  + averageViewPercentage 两道门做主题评估。
- R4（两振出局）：主题首次 MISS → watchlist（只告警不拦截，允许 1 个变体验证）；
  同一主题连续第二次 MISS → blocklist（永久，除非人工移除）。
- 小样本贝叶斯收缩：views < 200 时 feed 份额做收缩估计（先验=频道基线 50%）。
- 配额熔断：Analytics API 403/quota 错误 → fail-open（记 warn 跳过本轮，
  绝不把 API 故障记成 MISS）。
- 幂等：已评估过的 video_id（state.evaluated_videos）跳过；每轮只评 48–96h 窗口。
- 每小时由 cron 安全调用一次。--dry-run 只打印判定，不写 state、不发 inbox。

诚实说明（照抄 retention_telemetry.py）：YouTube Analytics API 没有逐秒留存曲线，
只有 averageViewPercentage 等聚合指标；本脚本用 feed 份额 + 平均观看百分比做门。
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path("/home/hatch/data")
sys.path.insert(0, str(BASE / "youtube"))
sys.path.insert(0, str(BASE / "perpetua"))
import queue_db
import inbox

STATE = BASE / "perpetua" / "evaluator_48h_state.json"

# ---- 门（B 计划 R1）----
FEED_SHARE_GATE = 0.50   # Shorts feed 播放份额 < 50% → MISS
AVP_GATE = 70.0          # averageViewPercentage < 70 → MISS
EVAL_MIN_H, EVAL_MAX_H = 48, 96   # 只评估发布后 48–96h 的视频

# ---- 小样本贝叶斯收缩（R4 红队修订）----
SMALL_SAMPLE_N = 200
BAYES_ALPHA, BAYES_BETA = 50, 50  # 先验 = 频道基线 50%

# ---- 告警去重（AGENTS.md 铁律：dedup key 剥离时间戳/年龄等易变字段）----
ALERT_DEDUP_H = 12


class QuotaExceeded(Exception):
    """YouTube API 配额/权限故障 → fail-open，本轮跳过。"""


def _analytics_per_video_traffic(token, video_id, start, end):
    """Analytics API：单条视频按流量来源拆分的 views + 平均观看百分比。

    一次调用同时拿到 (a) 各流量来源 views（含 SHORTS=Shorts feed）、
    (b) 加权 averageViewPercentage、(c) 总 views，省配额。
    """
    params = {
        "ids": "channel==MINE",
        "startDate": start,
        "endDate": end,
        "metrics": "views,averageViewPercentage",
        "dimensions": "video,insightTrafficSourceType",
        "filters": "video==%s" % video_id,
        "maxResults": "50",
    }
    url = ("https://youtubeanalytics.googleapis.com/v2/reports?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        if e.code == 403 or "quotaExceeded" in body or "quota" in body.lower():
            raise QuotaExceeded("Analytics API 403/quota: " + body)
        raise
    rows = data.get("rows", [])
    total_views = 0
    feed_views = 0
    avp_weighted = 0.0
    for row in rows:
        # row: [videoId, trafficSourceType, views, averageViewPercentage]
        _vid, src, views, avp = row[0], row[1], int(row[2]), float(row[3])
        total_views += views
        avp_weighted += avp * views
        if src == "SHORTS":
            feed_views += views
    avg_pct = (avp_weighted / total_views) if total_views else 0.0
    return {"views": total_views, "feed_views": feed_views,
            "avg_view_pct": round(avg_pct, 2)}


def _norm_topic(topic):
    """主题归一化：小写去空格。"""
    return "".join(str(topic or "").lower().split())


def _load_state():
    if STATE.exists():
        try:
            d = json.loads(STATE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("evaluated_videos", [])
                d.setdefault("themes", {})
                d.setdefault("alerts", {})
                return d
        except Exception:
            pass
    return {"evaluated_videos": [], "themes": {}, "alerts": {}}


def _save_state(state):
    # 原子写：tmp + rename，避免 cron 并发写坏
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(STATE)


def _topic_index():
    """video_id → topic 索引（pipeline 队列走 SQLite 真相源，绝不读 JSON 死镜像）。"""
    idx = {}
    titles = {}  # 归一化标题 → topic（兜底匹配）
    for it in queue_db.pipeline_load():
        if not isinstance(it, dict):
            continue
        topic = (it.get("topic") or "").strip()
        if not topic:
            continue
        vid = it.get("video_id")
        if vid:
            idx[str(vid)] = topic
        t = _norm_topic(it.get("title", ""))[:60]
        if t and t not in titles:
            titles[t] = topic
    topics = sorted({it.get("topic", "").strip() for it in queue_db.pipeline_load()
                     if isinstance(it, dict) and (it.get("topic") or "").strip()})
    return idx, titles, topics




_STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "are",
              "was", "were", "her", "his", "its", "our", "your", "their",
              "has", "have", "had", "will", "would", "can", "into", "onto",
              "over", "under", "when", "then", "than", "also", "just", "out"}


def _words(s):
    """分词：小写、只留字母数字、去停用词和短词。"""
    return {w for w in re.findall(r"[a-z0-9]+", str(s).lower())
            if len(w) > 3 and w not in _STOPWORDS}


def _fuzzy_topic(title, topics):
    """关键词重叠兜底：topic 实词在标题中命中 ≥一半且 ≥2 个词才认领。

    保守阈值，宁可漏评（no_topic 跳过）也不错杀——错归因会写错 strikes。
    """
    tw = _words(title)
    if not tw:
        return None
    best, best_score = None, 0.0
    for topic in topics:
        kw = _words(topic)
        if not kw:
            continue
        hit = len(kw & tw)
        score = hit / len(kw)
        if hit >= 2 and score >= 0.5 and score > best_score:
            best, best_score = topic, score
    return best



def _candidates(now):
    """从 SQLite 发布队列取候选：有 published_at、年龄 48–96h。"""
    vid2topic, title2topic, all_topics = _topic_index()
    out = []
    skipped = []
    for it in queue_db.privateq_load():
        if not isinstance(it, dict):
            continue
        vid = it.get("video_id")
        pub = it.get("published_at")
        if not vid:
            continue
        if not pub:
            skipped.append({"video_id": vid, "reason": "no_published_at"})
            continue
        try:
            pub_dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            skipped.append({"video_id": vid, "reason": "bad_published_at"})
            continue
        age_h = (now - pub_dt).total_seconds() / 3600
        if age_h < EVAL_MIN_H:
            skipped.append({"video_id": vid, "reason": "too_young",
                            "age_h": round(age_h, 1)})
            continue
        if age_h > EVAL_MAX_H:
            skipped.append({"video_id": vid, "reason": "window_passed",
                            "age_h": round(age_h, 1)})
            continue
        topic = vid2topic.get(str(vid))
        if not topic:
            t = _norm_topic(it.get("title", ""))[:60]
            topic = title2topic.get(t)
        if not topic:
            # 关键词重叠兜底（保守阈值），并记录匹配方式供审计
            topic = _fuzzy_topic(it.get("title", ""), all_topics)
        if not topic:
            skipped.append({"video_id": vid, "reason": "no_topic"})
            continue
        out.append({"video_id": str(vid), "title": it.get("title", "")[:80],
                    "topic": topic, "published_at": pub_dt,
                    "age_h": round(age_h, 1),
                    "topic_match": ("direct" if vid2topic.get(str(vid))
                                    else "fuzzy")})
    return out, skipped


def _alert(state, theme, transition, title, message, urgent, dry_run,
           summary):
    """告警（去重 key 稳定：不含时间戳/年龄；同一主题 12h 只发一次）。"""
    key = "eval48h:%s:%s" % (transition, _norm_topic(theme))  # 稳定 key，无易变字段
    now = datetime.now(timezone.utc)
    last = state["alerts"].get(key)
    if last:
        try:
            age_h = (now - datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h < ALERT_DEDUP_H:
                summary["alerts_suppressed_dedup"].append(key)
                return
        except Exception:
            pass
    if dry_run:
        summary["alerts_dry_run"].append(
            {"key": key, "urgent": urgent, "title": title})
        return
    ntype = ("eval48h_theme_watch" if transition == "watchlist"
             else "eval48h_theme_block")
    inbox.append_notice({
        "type": ntype,
        "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": title,
        "message": message,
        "for": "user",
        "read": False,
        "urgency": "urgent" if urgent else "normal",
    })
    state["alerts"][key] = now.isoformat()
    summary["alerts_sent"].append(
        {"key": key, "urgent": urgent, "title": title})


def main():
    ap = argparse.ArgumentParser(description="48h 视频评估器（B 计划 R1/R4）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印判定，不写 state、不发 inbox")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    summary = {"ts": now.isoformat(), "dry_run": args.dry_run,
               "evaluated": [], "skipped": [], "pending": [],
               "transitions": [], "alerts_sent": [],
               "alerts_dry_run": [], "alerts_suppressed_dedup": [],
               "quota_stop": False, "api_errors": 0}

    state = _load_state()
    evaluated = set(state["evaluated_videos"])

    from yt import _token
    try:
        token, _ = _token()
    except Exception as e:
        summary["api_errors"] += 1
        summary["warn"] = "取 token 失败，fail-open 跳过本轮: %s" % e
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0

    cands, skipped = _candidates(now)
    summary["skipped"].extend(skipped)

    for c in cands:
        vid = c["video_id"]
        if vid in evaluated:
            summary["skipped"].append({"video_id": vid,
                                       "reason": "already_evaluated"})
            continue
        pub = c["published_at"]
        start = pub.strftime("%Y-%m-%d")
        # Analytics 数据有延迟，endDate 钳到昨天
        end = min(pub + timedelta(days=3),
                  now - timedelta(days=1)).strftime("%Y-%m-%d")
        if end < start:
            summary["pending"].append({"video_id": vid,
                                       "reason": "analytics_not_ready"})
            continue
        try:
            m = _analytics_per_video_traffic(token, vid, start, end)
        except QuotaExceeded as e:
            # 配额熔断：fail-open，记 warn，跳过本轮，不写 strikes
            summary["quota_stop"] = True
            summary["warn"] = "配额熔断 fail-open: %s" % e
            break
        except Exception as e:
            summary["api_errors"] += 1
            summary["skipped"].append(
                {"video_id": vid, "reason": ("analytics_error: %s" % e)[:120]})
            continue

        views = m["views"]
        feed_views = m["feed_views"]
        if views == 0:
            # 数据未到：判 MISS 但不进振数，标记 pending，下轮重试
            summary["pending"].append(
                {"video_id": vid, "topic": c["topic"], "reason": "views=0"})
            continue

        # 小样本贝叶斯收缩（R4）：views<200 用收缩估计再过门
        shrunk = views < SMALL_SAMPLE_N
        if shrunk:
            feed_share = ((feed_views + BAYES_ALPHA)
                          / (views + BAYES_ALPHA + BAYES_BETA))
        else:
            feed_share = feed_views / views
        feed_share = round(feed_share, 4)
        avp = m["avg_view_pct"]

        miss = (feed_share < FEED_SHARE_GATE) or (avp < AVP_GATE)

        theme_key = _norm_topic(c["topic"])
        th = state["themes"].setdefault(theme_key, {
            "topic": c["topic"], "strikes": 0, "last_result": None,
            "last_evaluated": None, "watchlisted_at": None,
            "blocklisted_at": None})
        th["last_evaluated"] = now.isoformat()
        th["last_result"] = "miss" if miss else "pass"

        rec = {"video_id": vid, "topic": c["topic"],
               "title": c["title"], "views": views,
               "feed_views": feed_views,
               "feed_share": feed_share, "shrunk": shrunk,
               "avg_view_pct": avp,
               "result": "miss" if miss else "pass"}
        summary["evaluated"].append(rec)
        evaluated.add(vid)

        if miss:
            th["strikes"] = int(th.get("strikes", 0)) + 1
            if th["strikes"] == 1:
                # 第一振：watchlist，只告警不拦截（允许 1 个变体验证）
                if not th.get("watchlisted_at"):
                    th["watchlisted_at"] = now.isoformat()
                summary["transitions"].append(
                    {"theme": c["topic"], "to": "watchlist",
                     "video_id": vid})
                _alert(state, c["topic"], "watchlist",
                       "【观察】主题「%s」首次 48h 未达标" % c["topic"],
                       "视频 %s（%s）：feed 份额 %s (门 %s)，平均观看 %s%% (门 %s)，"
                       "播放 %s。已进 watchlist：允许 1 个变体验证，"
                       "不拦截发布。再 MISS 一次即进 blocklist。"
                       % (vid, c["title"], feed_share, FEED_SHARE_GATE,
                          avp, AVP_GATE, views),
                       urgent=False, dry_run=args.dry_run, summary=summary)
            elif th["strikes"] >= 2 and not th.get("blocklisted_at"):
                # 第二振：blocklist，永久（除非人工移除）
                th["blocklisted_at"] = now.isoformat()
                summary["transitions"].append(
                    {"theme": c["topic"], "to": "blocklist",
                     "video_id": vid})
                _alert(state, c["topic"], "blocklist",
                       "【拉黑】主题「%s」连续两次 48h 未达标" % c["topic"],
                       "视频 %s（%s）：feed 份额 %s，平均观看 %s%%，播放 %s。"
                       "主题已进 blocklist（永久，除非人工移除）："
                       "新选题避开此主题。"
                       % (vid, c["title"], feed_share, avp, views),
                       urgent=True, dry_run=args.dry_run, summary=summary)
        else:
            # 达标：strikes 清零（blocklist 本身保留，需人工移除）
            th["strikes"] = 0

    if not args.dry_run:
        state["evaluated_videos"] = sorted(evaluated)
        _save_state(state)

    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
