#!/usr/bin/env python3
"""从频道历史数据反推爆款规律"""
import json, re
from collections import Counter
from datetime import datetime

videos = json.load(open("/home/hatch/data/youtube/all_videos.json"))
# 按播放量排序
videos.sort(key=lambda v: -v["views"])
n = len(videos)
print(f"=== 频道全量分析：{n} 个视频 ===")
total_views = sum(v["views"] for v in videos)
print(f"总播放：{total_views:,}")

# 爆款定义：播放量 Top 10%
top_n = max(10, n // 10)
top = videos[:top_n]
rest = videos[top_n:]
top_views = sum(v["views"] for v in top)
print(f"Top {top_n}（前10%）贡献播放：{top_views:,}（{top_views/total_views:.0%}）")
print(f"Top10% 平均播放：{top_views/top_n:,.0f} vs 其余平均：{sum(v['views'] for v in rest)/len(rest):,.0f}")

def feats(vs):
    titles = [v["title"] for v in vs]
    return {
        "n": len(vs),
        "avg_views": sum(v["views"] for v in vs) / len(vs),
        "avg_likes": sum(v["likes"] for v in vs) / len(vs),
        "avg_title_len": sum(len(t) for t in titles) / len(titles),
        "emoji_rate": sum(1 for t in titles if any(ord(c) > 0x1F300 for c in t)) / len(vs),
        "caps_rate": sum(1 for t in titles if re.search(r'[A-Z]{3,}', t)) / len(vs),
        "question_rate": sum(1 for t in titles if '?' in t or '？' in t) / len(vs),
        "exclaim_rate": sum(1 for t in titles if '!' in t or '！' in t) / len(vs),
        "karen_rate": sum(1 for t in titles if 'karen' in t.lower()) / len(vs),
        "hashtag_n": sum(len(re.findall(r'#\w+', t)) for t in titles) / len(vs),
    }

print("\n=== 爆款组 vs 普通组 特征对比 ===")
ft, fr = feats(top), feats(rest)
for k in ft:
    if k == "n": continue
    flag = " ←差异显著" if abs(ft[k]-fr[k]) > (fr[k]*0.3 if fr[k] else 0.1) and k != "avg_views" else ""
    print(f"  {k}: 爆款 {ft[k]:.2f} vs 普通 {fr[k]:.2f}{flag}")

# 关键词分析
print("\n=== 爆款标题高频词 ===")
words = Counter()
for v in top:
    for w in re.findall(r'[a-zA-Z]{3,}', v["title"].lower()):
        if w not in ("the","and","for","with","karen"): words[w] += 1
print(" ", words.most_common(15))

print("\n=== 普通组标题高频词（对比） ===")
words2 = Counter()
for v in rest[:top_n]:
    for w in re.findall(r'[a-zA-Z]{3,}', v["title"].lower()):
        if w not in ("the","and","for","with","karen"): words2[w] += 1
print(" ", words2.most_common(15))

# 发布时间分析
print("\n=== 爆款发布时间分布（UTC小时） ===")
hours = Counter()
for v in top:
    try:
        h = int(v["published"][11:13]) if len(v["published"]) > 10 else -1
        hours[h] += 1
    except: pass
# published 只有日期，跳过小时分析，改按星期
print("  （playlist API 只返回日期，小时级分析需补充）")
dows = Counter()
for v in top:
    try:
        d = datetime.strptime(v["published"], "%Y-%m-%d").strftime("%a")
        dows[d] += 1
    except: pass
print("  爆款星期分布:", dict(dows))

# 时长分析（Shorts vs 长视频）
print("\n=== 时长分布 ===")
def is_short(v):
    d = v["duration"]
    # PT#S / PT#M#S 解析
    m = re.match(r'PT(?:(\d+)M)?(?:(\d+)S)?', d)
    if not m: return None
    secs = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return secs <= 65
short_views = [v["views"] for v in videos if is_short(v)]
long_views = [v["views"] for v in videos if is_short(v) == False]
if short_views:
    print(f"  Shorts({len(short_views)}个) 平均播放: {sum(short_views)/len(short_views):,.0f}")
if long_views:
    print(f"  长视频({len(long_views)}个) 平均播放: {sum(long_views)/len(long_views):,.0f}")

print("\n=== Top 5 爆款 ===")
for v in videos[:5]:
    print(f"  {v['views']:>8,} 播放 | {v['title'][:70]}")
