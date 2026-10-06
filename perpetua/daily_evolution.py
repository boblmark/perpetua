#!/usr/bin/env python3
"""Perpetua 每日自我反思进化系统。

每天 23:30 运行（cron: daily-evolution）：
1. 拉取近 48h 发布视频的播放/点赞/评论（YouTube Data API，只读）
2. 归因分析：爆款（>2x 频道均值）vs 哑火（<50 播放），对比标题/时间/话题特征
3. 进化动作：criteria.json 版本+1（备份旧版）、必要时更新 viral_prompt_template.md
4. 输出中文进化报告：evolution_reports/YYYY-MM-DD.md

只读 YouTube 数据，不修改任何视频。
"""
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


def fetch_recent(days=2):
    """拉取近 N 天发布的视频（只读）。"""
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
    """归因分析：爆款 vs 哑火。"""
    mean = baseline["mean"]
    viral, flop, normal = [], [], []
    for v in videos:
        v["features"] = title_features(v["title"])
        if v["views"] >= mean * 2:
            v["verdict"] = "爆款"
            viral.append(v)
        elif v["views"] < 50:
            v["verdict"] = "哑火"
            flop.append(v)
        else:
            v["verdict"] = "一般"
            normal.append(v)
    findings = derive_findings(viral, flop, baseline)
    return viral, flop, normal, findings


def derive_findings(viral, flop, baseline):
    """从爆款/哑火对比中提炼数据驱动发现。"""
    findings = []
    if not viral and not flop:
        return ["样本不足（无爆款也无哑火），维持现有策略"]
    def rate(lst, key):
        if not lst:
            return 0.0
        return sum(1 for v in lst if v["features"][key]) / len(lst)
    # emoji
    if viral and flop:
        ve, fe = rate(viral, "emoji"), rate(flop, "emoji")
        if ve - fe >= 0.3:
            findings.append(
                f"爆款 emoji 使用率 {ve:.0%} vs 哑火 {fe:.0%}，差距显著——继续强制标题 emoji")
    # Karen
    if viral and flop:
        vk, fk = rate(viral, "karen"), rate(flop, "karen")
        if vk - fk >= 0.3:
            findings.append(
                f"爆款含 Karen {vk:.0%} vs 哑火 {fk:.0%}——Karen 仍是核心 IP，哑火多偏离主线")
    # 物理报应
    if viral:
        pk = rate(viral, "physical_karma")
        if pk >= 0.5:
            findings.append(
                f"爆款 {pk:.0%} 标题含物理报应词（soak/lock/trap/tow）——具象化报应继续加码")
    # 疑问句
    if flop:
        q = rate(flop, "question")
        if q >= 0.3:
            findings.append(
                f"哑火 {q:.0%} 是疑问句标题——疑问句继续禁用")
    # 标题长度
    if viral and flop:
        vl = sum(v["features"]["length"] for v in viral) / len(viral)
        fl = sum(v["features"]["length"] for v in flop) / len(flop)
        if abs(vl - fl) > 15:
            findings.append(
                f"爆款平均标题 {vl:.0f} 字符 vs 哑火 {fl:.0f} 字符——"
                + ("标题宜更精炼" if vl < fl else "标题可更具体"))
    # 播放量级
    if viral:
        top = max(viral, key=lambda v: v["views"])
        findings.append(
            f"当日最佳「{top['title'][:30]}…」{top['views']} 播放 "
            f"（{top['views']/baseline['mean']:.1f}x 频道均值）——复用其标题结构")
    if flop:
        findings.append(
            f"{len(flop)} 条哑火（<50 播放）："
            + ("检查是否私享/标签缺失/发布时间" if len(flop) >= 2 else "单条波动，继续观察"))
    return findings[:3] if len(findings) > 3 else findings


def evolve_criteria(findings, date_str):
    """criteria.json 版本+1（备份旧版），写入新发现。"""
    if not findings or findings == ["样本不足（无爆款也无哑火），维持现有策略"]:
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
    json.dump(c, open(JEV_CRITERIA, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
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


def build_report(date_str, videos, viral, flop, normal, baseline,
                 findings, evo_result, tpl_result):
    total_views = sum(v["views"] for v in videos)
    total_likes = sum(v["likes"] for v in videos)
    total_comments = sum(v["comments"] for v in videos)
    lines = [
        f"# Perpetua 每日进化报告 · {date_str}\n",
        "## 昨日战绩",
        f"- 发布 {len(videos)} 条，总播放 {total_views}，点赞 {total_likes}，评论 {total_comments}",
        f"- 爆款 {len(viral)} 条（>{baseline['mean']:.0f} 均值 2x），"
        f"哑火 {len(flop)} 条（<50 播放），一般 {len(normal)} 条",
        f"- 频道基线：均值 {baseline['mean']:.0f} / 中位数 {baseline['median']:.0f}（{baseline['n']} 条历史）",
    ]
    if viral:
        lines.append("\n### 爆款")
        for v in sorted(viral, key=lambda x: -x["views"])[:5]:
            lines.append(f"- 「{v['title'][:45]}」{v['views']} 播放 👍{v['likes']} 💬{v['comments']}")
    if flop:
        lines.append("\n### 哑火")
        for v in flop[:5]:
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
        "1. 爆款标题结构复用到明日选题（emoji+Karen+物理报应动词）",
        "2. 哑火视频按 zero_view_alert 流程跟进（换标题/补标签），不删重发",
        "3. 选题优先 Ask Studio 当日热点 + 历史爆款续集清单（sequel_candidates.json）",
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
    viral, flop, normal, findings = analyze(videos, baseline)
    if dry_run:
        print(f"[dry-run] 视频 {len(videos)} 条，爆款 {len(viral)}，哑火 {len(flop)}")
        for f in findings:
            print(" -", f)
        return
    evo_result = evolve_criteria(findings, date_str)
    tpl_result = maybe_update_template(findings, date_str)
    report = build_report(date_str, videos, viral, flop, normal, baseline,
                          findings, evo_result, tpl_result)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rp = REPORT_DIR / f"{date_str}.md"
    rp.write_text(report, encoding="utf-8")
    print(f"报告已生成: {rp}")
    print(f"爆款 {len(viral)} / 哑火 {len(flop)} / criteria {evo_result}")


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
    viral, flop, normal, findings = analyze(videos, baseline)
    print(f"[回测 {date_str}] 样本 {len(videos)} 条 | 爆款 {len(viral)} | 哑火 {len(flop)} | 一般 {len(normal)}")
    print(f"基线均值 {baseline['mean']:.0f}")
    for v in sorted(viral, key=lambda x: -x["views"])[:3]:
        print(f"  爆款: 「{v['title'][:50]}」{v['views']} 播放")
    for v in flop[:3]:
        print(f"  哑火: 「{v['title'][:50]}」{v['views']} 播放")
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
