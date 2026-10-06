#!/usr/bin/env python3
"""对已拉取的 488 条历史视频做回溯分析：
1. 播放量分布（看长尾形态）
2. 用现有 virality_score 算法给每条历史标题重新打分
3. 算「分数区间 vs 实际播放」相关性 —— 验证打分器是否有效
4. 词频对比：Top10% vs Bottom10% 的标题差异
输出: /home/hatch/data/youtube/backtest_report.md
"""
import json
import re
import sys
import statistics
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/hatch/data/youtube")
from virality_score import score as vscore  # noqa

SRC = Path("/home/hatch/data/youtube/uploads_full.jsonl")
OUT = Path("/home/hatch/data/youtube/backtest_report.md")

rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
rows = [r for r in rows if r["views"] > 0 or True]  # 全保留

lines = []
def w(s=""):
    lines.append(s)

n = len(rows)
views = sorted(r["views"] for r in rows)
w("# 频道历史回溯分析报告")
w()
w(f"- 样本量：**{n}** 条")
w(f"- 播放量：min={views[0]} / p25={views[n//4]} / median={views[n//2]} / "
  f"p75={views[3*n//4]} / p90={views[int(n*0.9)]} / max={views[-1]}")
w(f"- 总播放：{sum(views):,} / 均值：{sum(views)/n:,.0f}")
w(f"- **0 播放视频数：{sum(1 for v in views if v == 0)}** "
  f"({sum(1 for v in views if v == 0)/n*100:.1f}%)")
w(f"- **<10 播放：{sum(1 for v in views if v < 10)}** "
  f"({sum(1 for v in views if v < 10)/n*100:.1f}%)")
w()

# ---- 用现有算法给历史标题打分 ----
scored = []
for r in rows:
    s = vscore({"title": r["title"], "hook": "", "topic_heat": "medium",
                "duration": 10})
    r["_score"] = s["score"]
    r["_grade"] = s["grade"]
    scored.append(r)

# 分数区间 vs 播放
w("## 一、现有 virality_score 对历史数据的预测力")
w()
buckets = {}
for r in scored:
    b = (r["_score"] // 10) * 10
    buckets.setdefault(b, []).append(r)
w("| 分数区间 | 条数 | 平均播放 | 中位播放 | 最高播放 |")
w("|---|---|---|---|---|")
for b in sorted(buckets):
    g = buckets[b]
    vs = sorted(x["views"] for x in g)
    w(f"| {b}-{b+9} | {len(g)} | {statistics.mean(vs):,.0f} | "
      f"{statistics.median(vs):,.0f} | {max(vs):,} |")
w()

# 相关系数
xs = [r["_score"] for r in scored]
ys = [r["views"] for r in scored]
def pearson(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0

def spearman(a, b):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0] * len(v)
        for pos, i in enumerate(s):
            rk[i] = pos
        return rk
    return pearson(rank(a), rank(b))

w(f"- **Pearson r = {pearson(xs, ys):.4f}**")
w(f"- **Spearman ρ = {spearman(xs, ys):.4f}**")
w()
w("> 判读：ρ > 0.3 才算有弱相关；接近 0 说明**打分器与实际播放无关**。")
w()

# ---- Top / Bottom 词频对比 ----
srt = sorted(scored, key=lambda r: r["views"], reverse=True)
top = srt[:max(1, n // 10)]
bot = srt[-max(1, n // 10):]

STOP = set("the a an and or of to in for with on at is are you your i it this that "
           "my we our vs shorts short ai".split())
def words(rs):
    c = Counter()
    for r in rs:
        for wd in re.findall(r"[a-z0-9]{3,}", r["title"].lower()):
            if wd not in STOP:
                c[wd] += 1
    return c

cw_top, cw_bot = words(top), words(bot)
w("## 二、Top 10% vs Bottom 10% 标题词频差异")
w()
w(f"（Top = 播放前 {len(top)} 条，Bottom = 后 {len(bot)} 条）")
w()
w("| 词 | Top 出现 | Bottom 出现 | 差值 |")
w("|---|---|---|---|")
allw = set(list(cw_top)[:0]) | set(cw_top) | set(cw_bot)
merged = sorted(allw, key=lambda k: -(cw_top.get(k, 0) - cw_bot.get(k, 0)))
for k in merged[:20]:
    t, b_ = cw_top.get(k, 0), cw_bot.get(k, 0)
    w(f"| `{k}` | {t} | {b_} | {t-b_:+d} |")
w()
w("**Top 独有词**：" + ", ".join(f"`{k}`({v})" for k, v in cw_top.most_common(15)))
w()
w("**Bottom 独有词**：" + ", ".join(f"`{k}`({v})" for k, v in cw_bot.most_common(15)))
w()

# ---- Top 20 明细 ----
w("## 三、播放 Top 20")
w()
w("| 播放 | 标题 | 旧分 | 发布 |")
w("|---|---|---|---|")
for r in srt[:20]:
    w(f"| {r['views']:,} | {r['title'][:60]} | {r['_score']} | {r['published']} |")
w()

# ---- Bottom 20 ----
w("## 四、播放 Bottom 20")
w()
w("| 播放 | 标题 | 旧分 | 发布 |")
w("|---|---|---|---|")
for r in srt[-20:][::-1]:
    w(f"| {r['views']:,} | {r['title'][:60]} | {r['_score']} | {r['published']} |")
w()

OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
print(f"\n# -> {OUT}")
