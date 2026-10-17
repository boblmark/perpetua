"""X 数据构建（来源：公开推文指标接口 api.fxtwitter.com，值为真实公开数字）。

限制说明：X 时间线无法在登出态枚举，只有拿到具体推文 ID 才能取数，
因此本表为「按已知推文 ID 采集」，样本量受可发现的推文 ID 数限制。
views/likes/retweets/replies/bookmarks 均为真实值；X 无播放量以外的后台指标。
"""
import json,re,time
rows=json.load(open("/home/user/collector/x_raw.json"))
out=[]
KW=re.compile(r"AI|ai|人工智能|video|funny|meme|generate",re.I)
for r in rows:
    txt=r.get("text") or ""
    out.append({
        "platform":"x",
        "account_name":r.get("author"),
        "account_display":r.get("author_name"),
        "account_followers":r.get("followers"),
        "video_url":r.get("url"),
        "title":(txt[:180] or "(无正文/媒体帖)"),
        "cover_desc":"N/A",
        "views":r.get("views"),
        "likes":r.get("likes"),
        "comments":r.get("replies"),
        "shares":r.get("retweets"),
        "collects":r.get("bookmarks"),
        "quotes":r.get("quotes"),
        "danmaku":"N/A",
        "published_at":r.get("created_at"),
        "duration_sec":"N/A",
        "hashtags":",".join(sorted(set(re.findall(r"#(\w+)",txt)))) or "N/A",
        "is_viral":1 if (r.get("views") or 0)>0 else 0,   # 稍后按播放量中位数切分
        "topic_category":"AI/科技内容" if KW.search(txt) else "其他",
        "hook_type":"陈述开场",
        "format_notes":"X 单条推文指标（views/likes/retweets/replies/bookmarks）；无账号级抽样（时间线不可枚举）",
        "lang":r.get("lang"),"collected_at":time.strftime("%Y-%m-%d %H:%M",time.localtime()),
    })
# 按播放量中位数切分为高播放组 / 中位组（X 无法做账号级抽样）
vals=sorted((r.get("views") or 0) for r in out)
med=vals[len(vals)//2] if vals else 0
for r in out:
    v=r.get("views") or 0
    r["is_viral"]=1 if v>med else 0
    r["format_notes"]="X 单条推文指标（views/likes/retweets/replies/bookmarks）；无账号级抽样（时间线不可枚举）；" + ("高播放组" if v>med else "中位组")+f"（全体中位={med:,}）"
json.dump({"rows":out},open("/home/user/collector/x_rows.json","w"),ensure_ascii=False,indent=1)
print("x rows:",len(out),"| median views:",med,"| viral:",sum(1 for r in out if r["is_viral"]==1))
