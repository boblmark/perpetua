#!/usr/bin/env python3
"""Perpetua 每日自我反思进化系统。

每天 23:30 运行（cron: daily-evolution）：
1. 拉取近 48h 发布视频的播放/点赞/评论（YouTube Data API，只读）
   + 时长（contentDetails）+ AVD/观看分钟（YouTube Analytics，只读）
2. 归因分析（2026-10-11 D20261010-023 起：YPP 长视频口径，Shorts 旧口径废弃）：
   - teaser 类（<90s）：T+48h 判定 — AVD(averageViewPercentage)≥75%
     且 48h views≥30（VvS 无 Analytics 口径，以 views≥30 为分发证明 proxy；
     沿用 teaser_validate.py GREEN 双门）；缺 Analytics 数则判"缺数"
   - 长视频类：T+14d 才有结论（5000 曝光 + CTR≥8% + APV≥40% + 150 小时 + 30 订阅），
     48h 窗口内只记"观察中"，报告当前累计观看小时与距 150h 目标的缺口
3. 进化动作：criteria.json 版本+1（备份旧版）、必要时更新 viral_prompt_template.md
4. 输出中文进化报告：evolution_reports/YYYY-MM-DD.md

只读 YouTube 数据，不修改任何视频。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json, os, re, sys, shutil, statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
sys.path.insert(0, "/home/hatch/data")

DATA = Path("/home/hatch/data")
PERPETUA = DATA / "perpetua"
JEV_CRITERIA = DATA / "jev" / "criteria.json"
TEMPLATE_MD = PERPETUA / "viral_prompt_template.md"
REPORT_DIR = PERPETUA / "evolution_reports"
HISTORY = DATA / "youtube" / "all_videos.json"

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]"
)
VIRAL_WORDS = ["viral", "instant", "karma", "hoa", "gets", "caught", "cam",
               "soaked", "locked", "trapped", "towed", "muted", "busted", "exposed"]
PHYSICAL_KARMA = ["soak", "lock", "trap", "tow", "spray", "mute", "burst",
                  "slam", "splash", "flood", "shut"]

# --- YPP 长视频口径（D20261010-023，2026-10-11 重定向）---
TEASER_MAX_SEC = 90          # <90s 判为 teaser 类
TEASER_AVD_GREEN = 75.0     # teaser T+48h：averageViewPercentage ≥ 75%
TEASER_VIEWS_GREEN = 30     # teaser T+48h：views ≥ 30（VvS proxy，分发证明）
LONGFORM_T14_HOURS = 150.0  # 正片 T+14d：150 观看小时


def title_features(title):
    t = title.lower()
    return {
        "emoji": bool(EMOJI_RE.search(title)),
        "karen": "karen" in t,
        "viral_words": [w for w in VIRAL_WORDS if w in t],
        "physical_karma": any(w in t for w in PHYSICAL_KARMA),
        "question": title.strip().endswith("?"),
        "length": len(title),
    }


def _iso8601_to_seconds(s):
    """PT1H2M3S -> 秒数；解析失败返回 None。"""
    import re as _re
    m = _re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s or "")
    if not m:
        return None
    h, mi, sec = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float(sec or 0)


def _fetch_durations(vids):
    """Data API contentDetails 取时长（秒）；失败返回 {}。"""
    if not vids:
        return {}
    try:
        from yt import api_call
        out = {}
        for i in range(0, len(vids), 50):
            chunk = vids[i:i + 50]
            r = api_call("GET", "/youtube/v3/videos",
                         params={"part": "contentDetails",
                                 "id": ",".join(chunk)})
            for v in r.get("items", []):
                sec = _iso8601_to_seconds(
                    v.get("contentDetails", {}).get("duration"))
                if sec is not None:
                    out[v["id"]] = sec
        return out
    except Exception as e:
        print(f"WARN: 时长拉取失败: {e}")
        return {}


def _analytics_avp(vids):
    """Analytics averageViewPercentage（0-100）；失败返回 {}（判缺数）。"""
    try:
        sys.path.insert(0, "/home/hatch/data/youtube")
        from slot_review import _analytics_avg_view_pct
        return _analytics_avg_view_pct(vids)
    except Exception as e:
        print(f"WARN: Analytics AVD 拉取失败: {e}")
        return {}


def _analytics_watch_minutes(vids):
    """Analytics estimatedMinutesWatched（诊断口径≠合格）；失败返回 {}。"""
    if not vids:
        return {}
    try:
        from yt import _token
        import urllib.request, urllib.parse
        token, _ = _token()
        out = {}
        for i in range(0, len(vids), 20):
            batch = vids[i:i + 20]
            params = {"ids": "channel==MINE",
                      "startDate": "2020-01-01",
                      "endDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                      "metrics": "estimatedMinutesWatched",
                      "dimensions": "video",
                      "filters": "video==" + ",".join(batch)}
            url = ("https://youtubeanalytics.googleapis.com/v2/reports?"
                   + urllib.parse.urlencode(params))
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {token}"})
            rows = json.load(urllib.request.urlopen(req, timeout=30)).get("rows", [])
            for vid, mins in rows:
                out[vid] = float(mins)
        return out
    except Exception as e:
        print(f"WARN: Analytics 观看分钟拉取失败: {e}")
        return {}


def fetch_recent(days=2):
    """拉取近 N 天发布的视频（只读），附时长。"""
    from yt import recent_videos
    videos = recent_videos(25)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    out = []
    for v in videos:
        pub = v.get("published", "")[:10]
        if pub >= cutoff:
            out.append({
                "id": v["id"], "title": v["title"], "published": pub,
                "views": int(v.get("views", 0) or 0),
                "likes": int(v.get("likes", 0) or 0),
                "comments": int(v.get("comments", 0) or 0),
            })
    durs = _fetch_durations([v["id"] for v in out])
    for v in out:
        v["duration_sec"] = durs.get(v["id"])
    return out


def channel_baseline():
    """频道历史基线（均值/中位数）。"""
    if not HISTORY.exists():
        return {"mean": 1500, "median": 1000, "n": 0}
    d = json.load(open(HISTORY))
    views = [int(v.get("views", 0) or 0) for v in d]
    if not views:
        return {"mean": 1500, "median": 1000, "n": 0}
    return {
        "mean": sum(views) / len(views),
        "median": statistics.median(views),
        "n": len(views),
    }


def analyze(videos, baseline):
    """归因分析（YPP 长视频口径）。

    teaser 类（<90s）：T+48h 判定 — AVD≥75% 且 views≥30 为 GREEN，
      任一不达标为 RED；Analytics 无数则判"缺数"。
    长视频类：48h 窗口内只记"观察中"，附当前累计观看小时（诊断口径）。
    时长未知：判"缺数"。
    """
    vids = [v["id"] for v in videos]
    avp = _analytics_avp(vids)
    wmin = _analytics_watch_minutes(vids)
    green, red, watching, missing = [], [], [], []
    for v in videos:
        v["features"] = title_features(v["title"])
        v["avd"] = avp.get(v["id"])
        v["watch_hours"] = round(wmin.get(v["id"], 0) / 60, 2)
        dur = v.get("duration_sec")
        if dur is None:
            v["vclass"] = "unknown"
            v["verdict"] = "缺数"
            missing.append(v)
        elif dur < TEASER_MAX_SEC:
            v["vclass"] = "teaser"
            if v["avd"] is None:
                v["verdict"] = "缺数"
                missing.append(v)
            elif v["avd"] >= TEASER_AVD_GREEN and v["views"] >= TEASER_VIEWS_GREEN:
                v["verdict"] = "GREEN"
                green.append(v)
            else:
                v["verdict"] = "RED"
                red.append(v)
        else:
            v["vclass"] = "longform"
            v["verdict"] = "观察中"
            watching.append(v)
    findings = derive_findings(green, red, watching, baseline)
    return green, red, watching, missing, findings


def derive_findings(green, red, watching, baseline):
    """从 GREEN/RED 对比中提炼数据驱动发现（标题特征逻辑保留）。"""
    findings = []
    if not green and not red and not watching:
        return ["样本不足（48h 窗口无发布），维持现有策略"]
    def rate(lst, key):
        if not lst:
            return 0.0
        return sum(1 for v in lst if v["features"][key]) / len(lst)
    # emoji
    if green and red:
        ge, re_ = rate(green, "emoji"), rate(red, "emoji")
        if ge - re_ >= 0.3:
            findings.append(
                f"GREEN emoji 使用率 {ge:.0%} vs RED {re_:.0%}，差距显著——继续强制标题 emoji")
    # Karen
    if green and red:
        gk, rk = rate(green, "karen"), rate(red, "karen")
        if gk - rk >= 0.3:
            findings.append(
                f"GREEN 含 Karen {gk:.0%} vs RED {rk:.0%}——Karen 仍是核心 IP，RED 多偏离主线")
    # 物理报应
    if green:
        pk = rate(green, "physical_karma")
        if pk >= 0.5:
            findings.append(
                f"GREEN {pk:.0%} 标题含物理报应词（soak/lock/trap/tow）——具象化报应继续加码")
    # 疑问句
    if red:
        q = rate(red, "question")
        if q >= 0.3:
            findings.append(
                f"RED {q:.0%} 是疑问句标题——疑问句继续禁用")
    # 标题长度
    if green and red:
        gl = sum(v["features"]["length"] for v in green) / len(green)
        rl = sum(v["features"]["length"] for v in red) / len(red)
        if abs(gl - rl) > 15:
            findings.append(
                f"GREEN 平均标题 {gl:.0f} 字符 vs RED {rl:.0f} 字符——"
                + ("标题宜更精炼" if gl < rl else "标题可更具体"))
    # 达标样本
    if green:
        top = max(green, key=lambda v: v["views"])
        findings.append(
            f"当日最佳「{top['title'][:30]}…」AVD {top['avd']:.0f}% / {top['views']} 播放——复用其标题结构")
    if red:
        findings.append(
            f"{len(red)} 条 RED（teaser 未达 AVD≥75%+views≥30）："
            + ("检查钩子/前3秒与发布时间" if len(red) >= 2 else "单条波动，继续观察"))
    # 长视频观察
    for v in watching:
        findings.append(
            f"长视频观察中「{v['title'][:30]}…」当前累计 {v['watch_hours']} 小时"
            f"（诊断口径），距 T+14d 目标 {LONGFORM_T14_HOURS:.0f}h 缺口 "
            f"{max(0, LONGFORM_T14_HOURS - v['watch_hours']):.1f}h")
        break  # 只记一条，避免报告臃肿
    return findings[:4] if len(findings) > 4 else findings


def evolve_criteria(findings, date_str):
    """criteria.json 版本+1（备份旧版），写入新发现。"""
    if not findings or findings == ["样本不足（48h 窗口无发布），维持现有策略"]:
        return None
    backup = JEV_CRITERIA.with_suffix(f".json.bak.{date_str}")
    shutil.copy2(JEV_CRITERIA, backup)
    c = json.load(open(JEV_CRITERIA))
    c["version"] = c.get("version", 3) + 1
    c["updated"] = date_str
    c["notes"] = (f"v{c['version']}：每日进化 {date_str} 自动更新；"
                  + (c.get("notes", "") or ""))
    existing = set(c.get("key_findings", []))
    added = 0
    for f in findings:
        tag = f"[进化 {date_str}] {f}"
        if tag not in existing:
            c.setdefault("key_findings", []).append(tag)
            added += 1
    atomic_write_json(JEV_CRITERIA, c)
    return {"version": c["version"], "added": added, "backup": str(backup)}


def maybe_update_template(findings, date_str):
    """如发现涉及 prompt 结构的新规律，追加到模板附录。"""
    triggers = ["物理报应", "标题", "时长", "钩子", "CCTV", "循环"]
    hit = [f for f in findings if any(t in f for t in triggers)]
    if not hit:
        return None
    entry = (f"\n## 进化附录 {date_str}\n\n"
             f"每日复盘发现（自动写入）：\n"
             + "".join(f"- {f}\n" for f in hit))
    with open(TEMPLATE_MD, "a", encoding="utf-8") as fh:
        fh.write(entry)
    return len(hit)


def build_report(date_str, videos, green, red, watching, missing, baseline,
                 findings, evo_result, tpl_result):
    total_views = sum(v["views"] for v in videos)
    total_likes = sum(v["likes"] for v in videos)
    total_comments = sum(v["comments"] for v in videos)
    lines = [
        f"# Perpetua 每日进化报告 · {date_str}\n",
        "## 口径（2026-10-11 起：YPP 长视频口径）",
        "- teaser 类（<90s）：T+48h 判定 — AVD≥75% 且 views≥30 为 GREEN，否则 RED；"
        "VvS 无 Analytics 口径，以 views≥30 为分发证明 proxy",
        "- 长视频类：T+14d 结论（5000 曝光 + CTR≥8% + APV≥40% + 150 小时 + 30 订阅），"
        "48h 窗口内只记观察中",
        "- 旧口径（爆款=2x 均值 / 哑火<50 播放）已废弃",
        "\n## 昨日战绩",
        f"- 发布 {len(videos)} 条，总播放 {total_views}，点赞 {total_likes}，评论 {total_comments}",
        f"- teaser：GREEN {len(green)} 条 / RED {len(red)} 条；"
        f"长视频观察中 {len(watching)} 条；缺数 {len(missing)} 条",
        f"- 频道参考基线：均值 {baseline['mean']:.0f} / 中位数 {baseline['median']:.0f}"
        f"（{baseline['n']} 条历史，仅作参考，不再用于判定）",
    ]
    if green:
        lines.append("\n### teaser GREEN（达标）")
        for v in sorted(green, key=lambda x: -x["views"])[:5]:
            lines.append(f"- 「{v['title'][:45]}」AVD {v['avd']:.0f}% / {v['views']} 播放"
                         f" 👍{v['likes']} 💬{v['comments']}")
    if red:
        lines.append("\n### teaser RED（未达标）")
        for v in red[:5]:
            avd_s = f"{v['avd']:.0f}%" if v["avd"] is not None else "缺数"
            lines.append(f"- 「{v['title'][:45]}」AVD {avd_s} / {v['views']} 播放（{v['published']}）")
    if watching:
        lines.append("\n### 长视频观察中（T+14d 未到）")
        for v in watching[:5]:
            gap = max(0, LONGFORM_T14_HOURS - v["watch_hours"])
            lines.append(f"- 「{v['title'][:45]}」累计 {v['watch_hours']} 小时"
                         f"（诊断口径），距 150h 目标缺口 {gap:.1f}h")
    if missing:
        lines.append("\n### 缺数（Analytics/时长不可用）")
        for v in missing[:5]:
            lines.append(f"- 「{v['title'][:45]}」{v['views']} 播放（{v['published']}）")
    lines.append("\n## 关键发现")
    for i, f in enumerate(findings, 1):
        lines.append(f"{i}. {f}")
    lines.append("\n## 进化动作")
    if evo_result:
        lines.append(f"- criteria.json → v{evo_result['version']}（新增 {evo_result['added']} 条发现，旧版备份 {evo_result['backup']}）")
    else:
        lines.append("- criteria.json 未变更（无新发现）")
    if tpl_result:
        lines.append(f"- viral_prompt_template.md 追加进化附录（{tpl_result} 条）")
    else:
        lines.append("- prompt 模板未变更")
    lines += [
        "\n## 明日建议",
        "1. teaser GREEN 的标题结构复用到明日选题（emoji+Karen+物理报应动词）",
        "2. RED teaser 检查前 3 秒钩子与发布时间，不删重发",
        "3. 长视频继续攒观看小时：选题优先能带来真实完整观看的主题（搜索/订阅/playlist 流量）",
        "4. 选题优先 Ask Studio 当日热点 + 历史爆款续集清单（sequel_candidates.json）",
    ]
    return "\n".join(lines) + "\n"


def main(dry_run=False, backtest_date=None):
    date_str = backtest_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if backtest_date:
        # 回测：用历史数据模拟，不调 API、不写正式报告
        return backtest(backtest_date)
    try:
        videos = fetch_recent(2)
    except Exception as e:
        print(f"拉取 YouTube 数据失败: {e}，用空数据继续")
        videos = []
    baseline = channel_baseline()
    green, red, watching, missing, findings = analyze(videos, baseline)
    if dry_run:
        print(f"[dry-run] 视频 {len(videos)} 条，"
              f"teaser GREEN {len(green)} / RED {len(red)} / "
              f"长视频观察中 {len(watching)} / 缺数 {len(missing)}")
        for f in findings:
            print(" -", f)
        return
    evo_result = evolve_criteria(findings, date_str)
    tpl_result = maybe_update_template(findings, date_str)
    report = build_report(date_str, videos, green, red, watching, missing,
                          baseline, findings, evo_result, tpl_result)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rp = REPORT_DIR / f"{date_str}.md"
    rp.write_text(report, encoding="utf-8")
    print(f"报告已生成: {rp}")
    print(f"GREEN {len(green)} / RED {len(red)} / 观察中 {len(watching)} / "
          f"缺数 {len(missing)} / criteria {evo_result}")


def backtest(date_str):
    """用历史数据回测逻辑：取指定日期前后 2 天发布的视频模拟复盘。"""
    d = json.load(open(HISTORY))
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    videos = []
    for v in d:
        try:
            pub = datetime.strptime(v.get("published", "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if abs((pub - target).days) <= 2:
            videos.append({
                "id": v["id"], "title": v["title"], "published": v.get("published", "")[:10],
                "views": int(v.get("views", 0) or 0),
                "likes": int(v.get("likes", 0) or 0),
                "comments": int(v.get("comments", 0) or 0),
            })
    baseline = channel_baseline()
    green, red, watching, missing, findings = analyze(videos, baseline)
    print(f"[回测 {date_str}] 样本 {len(videos)} 条 | "
          f"GREEN {len(green)} | RED {len(red)} | "
          f"观察中 {len(watching)} | 缺数 {len(missing)}")
    print(f"基线均值 {baseline['mean']:.0f}（仅参考，不再用于判定）")
    for v in sorted(green, key=lambda x: -x["views"])[:3]:
        avd_s = f"{v['avd']:.0f}%" if v["avd"] is not None else "缺数"
        print(f"  GREEN: 「{v['title'][:50]}」AVD {avd_s} / {v['views']} 播放")
    for v in red[:3]:
        avd_s = f"{v['avd']:.0f}%" if v["avd"] is not None else "缺数"
        print(f"  RED: 「{v['title'][:50]}」AVD {avd_s} / {v['views']} 播放")
    for v in watching[:3]:
        print(f"  观察中: 「{v['title'][:50]}」累计 {v['watch_hours']} 小时")
    print("发现:")
    for f in findings:
        print(" -", f)
    # 验证 criteria 不被回测污染
    print("[回测] 未修改 criteria.json / 模板 / 报告 ✓")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backtest", metavar="YYYY-MM-DD")
    a = ap.parse_args()
    main(dry_run=a.dry_run, backtest_date=a.backtest)
