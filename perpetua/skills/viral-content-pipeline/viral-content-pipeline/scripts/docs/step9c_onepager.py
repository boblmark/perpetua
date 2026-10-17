# -*- coding: utf-8 -*-
"""生成 爆款方法论_一页纸.pdf —— 单页 A4，供投屏/会议对表使用。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kb_common import ROWS, ANALYSIS, num, fmt
OUT_DIR = os.environ.get("PIPELINE_OUT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(OUT_DIR, "爆款方法论_一页纸.pdf")
PNG = os.path.join(OUT_DIR, "爆款方法论_一页纸.png")
HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_onepager.html")

ACCENT = "1F3864"
ACCENT2 = "2F5597"
TODAY = "2026-10-14"


def g(lst, **kw):
    for d in lst:
        if all(d.get(k) == v for k, v in kw.items()):
            return d
    return None


def pct(v, d=2):
    return "—" if v is None else f"{v:.{d}f}%".replace(".00%", "%")


def build():
    A = ANALYSIS
    inter = []
    for plat, cn in [("bilibili", "B站"), ("tiktok", "TikTok"), ("douyin", "抖音"), ("kuaishou", "快手"), ("x", "X")]:
        v = g(A["interaction"], 平台=plat, 组别="爆款组")
        c = g(A["interaction"], 平台=plat, 组别="对照组")
        if plat == "douyin":
            inter.append([cn, f'收藏/点赞 {pct(v.get("收藏/点赞 (%)"))}', f'收藏/点赞 {pct(c.get("收藏/点赞 (%)"))}', v["样本数"]])
        else:
            inter.append([cn, pct(v.get("点赞/播放 (%)")), pct(c.get("点赞/播放 (%)")), v["样本数"]])

    dur = []
    for plat, cn in [("tiktok", "TikTok"), ("douyin", "抖音"), ("bilibili", "B站"), ("kuaishou", "快手")]:
        if plat == "douyin":
            # 抖音不公开播放量 → 按点赞中位数选最优档
            ds2 = [x for x in A["duration"] if x["平台"] == plat]
            if not ds2:
                continue
            best = max(ds2, key=lambda x: x.get("点赞中位数") or 0)
            dur.append([cn, best["时长档"], "不公开", fmt(best.get("点赞中位数")) + " 赞"])
            continue
        ds = [x for x in A["duration"] if x["平台"] == plat and x.get("播放量中位数")]
        if not ds:
            continue
        best = max(ds, key=lambda x: x["播放量中位数"])
        dur.append([cn, best["时长档"], fmt(best["播放量中位数"]), "—"])

    tags = {}
    for t in A["top_tags"]:
        tags.setdefault(t["平台"], []).append(t["标签"])
    tag_line = "　".join(f"<b>{cn}</b> " + " / ".join(tags.get(p, [])[:5])
                        for p, cn in [("bilibili", "B站"), ("tiktok", "TikTok"), ("douyin", "抖音"), ("kuaishou", "快手")])

    return inter, dur, tag_line


def render():
    inter, dur, tag_line = build()
    tr_inter = "".join(
        f"<tr><td class='k'>{r[0]}</td><td class='v'>{r[1]}</td><td class='v'>{r[2]}</td><td class='n'>{r[3]}</td></tr>"
        for r in inter)
    tr_dur = "".join(
        f"<tr><td class='k'>{r[0]}</td><td class='v'>{r[1]}</td><td class='v'>{r[2] or '—'}</td><td class='v'>{r[3]}</td></tr>"
        for r in dur)

    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
@page {{ size: A4 portrait; margin: 8mm 8mm 7mm 8mm; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: "Noto Sans CJK SC", sans-serif; color: #1a1a1a; font-size: 7.4pt; line-height: 1.36; }}
.hd {{ border-left: 3.5pt solid #{ACCENT2}; padding-left: 7px; margin-bottom: 6px; }}
.hd .t {{ font-size: 15pt; font-weight: 700; color: #{ACCENT}; line-height: 1.1; }}
.hd .s {{ font-size: 7.2pt; color: #666; margin-top: 2px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }}
.card {{ border: 0.6pt solid #C9D3E4; border-radius: 3px; padding: 5px 6px; break-inside: avoid; }}
.card.full {{ grid-column: 1 / -1; }}
.card h2 {{ font-size: 8.6pt; color: #{ACCENT}; margin-bottom: 3px; padding-bottom: 2px; border-bottom: 0.8pt solid #{ACCENT2}; }}
.card h2 span {{ float: right; font-size: 6.6pt; color: #888; font-weight: 400; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ font-size: 6.6pt; color: #fff; background: #{ACCENT2}; padding: 2px 3px; text-align: left; border: 0.4pt solid #cfd8e6; }}
td {{ font-size: 7pt; padding: 2px 3px; border: 0.4pt solid #D8E0EC; }}
td.k {{ font-weight: 700; color: #333; white-space: nowrap; }}
td.v {{ font-family: "Noto Sans Mono CJK SC", monospace; white-space: nowrap; }}
td.n {{ color: #999; font-size: 6.4pt; white-space: nowrap; }}
tr:nth-child(even) td {{ background: #F5F8FC; }}
ul {{ padding-left: 11px; }}
li {{ margin-bottom: 2px; }}
.key {{ background: #FFF2CC; border: 0.6pt solid #E8C36A; border-radius: 3px; padding: 4px 6px; margin-top: 3px; break-inside: avoid; }}
.key b {{ color: #7F4F00; }}
.yes {{ color: #1E6B33; font-weight: 700; }}
.no {{ color: #B03030; font-weight: 700; }}
.act {{ display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }}
.act > div {{ border-radius: 3px; padding: 4px 6px; }}
.do {{ background: #EAF5EC; border: 0.6pt solid #A9D4B4; }}
.dont {{ background: #FBEAEA; border: 0.6pt solid #E4ACAC; }}
.act h3 {{ font-size: 7.8pt; margin-bottom: 2px; }}
.do h3 {{ color: #1E6B33; }} .dont h3 {{ color: #B03030; }}
.ft {{ margin-top: 5px; padding-top: 3px; border-top: 0.6pt solid #C9D3E4; font-size: 6.4pt; color: #888; text-align: center; }}
.tagline {{ font-size: 6.8pt; color: #444; line-height: 1.5; }}
</style></head><body>

<div class="hd">
  <div class="t">竞品爆款方法论 · 一页纸</div>
  <div class="s">采集日 {TODAY} ｜ 288 条真实视频行（B站 80 / TikTok 140 / 抖音 27 / 快手 24 / X 17）｜ 全部数字可用原视频链接逐条复核，无估算、无编造</div>
</div>

<div class="grid">

  <div class="card">
    <h2>① 互动率基准 <span>点赞/播放，组内中位数</span></h2>
    <table>
      <thead><tr><th>平台</th><th>爆款组</th><th>对照组</th><th>n</th></tr></thead>
      <tbody>{tr_inter}</tbody>
    </table>
    <div class="key"><b>爆款赢在绝对触达，不在单位互动效率。</b>
    B站 3.40% vs 3.40% 几乎相同；快手对照组反而更高（5.68% vs 4.40%）。
    别把互动率当爆款预测器 —— 预算和时间花在复制选题、时长与形态上。</div>
  </div>

  <div class="card">
    <h2>② 时长策略 <span>各平台表现最好的时长档</span></h2>
    <table>
      <thead><tr><th>平台</th><th>表现最好档位</th><th>播放中位</th><th>点赞中位</th></tr></thead>
      <tbody>{tr_dur}</tbody>
    </table>
    <div class="key"><b>TikTok 1-3 分钟中位播放 930 万</b>，是 ＜30 秒档（77.3 万）的 12 倍；
    <b>抖音 ≥10 分钟 4/4 全进爆款组</b>，点赞中位 90,771 是 1-3 分钟档的约 10 倍。<br>
    排产：AI 短剧/漫剧按「3 分钟以上 + 多集连载」做；单点搞笑与拟人动物按 15-60 秒做。</div>
  </div>

  <div class="card">
    <h2>③ 选题母题 <span>四个都有真实爆款佐证</span></h2>
    <ul>
      <li><b>老 IP / 老题材 AI 翻新</b> —— 悟空 VS 如来 630万、清朝御厨千层宝塔肉 236万</li>
      <li><b>AI 拟人动物 + 单场景短梗</b> —— cat story 1.36亿、橙猫造摩托 8040万</li>
      <li><b>现实职场/生活反差</b> —— 老员工换身份应聘 113万</li>
      <li><b>AI 连续短剧（按集更新 + 合集收口）</b> —— 抖音《The Accident》EP01 点赞 20万；B站《癫佬外传》合集 832万</li>
    </ul>
    <div class="key"><b>各平台主力构成：</b>B站 剧情/其他 72%、AI 制作 28% ｜ TikTok AI 类合计 ~86%（动物拟人 14%、整活 14%）｜ 抖音 AI 生成/数字人 <b>78%</b> ｜ 快手 搞笑整活 <b>79%</b></div>
  </div>

  <div class="card">
    <h2>④ 标题公式 <span>唯一站得住的一条</span></h2>
    <div class="key" style="margin-top:0"><b>标题里带一个具体数字</b>（时长/价格/人数/集数/倍数）—— B站 67%(n=6)、抖音 62%(n=13)、快手 60%(n=5)，三平台全部高于各自基线。</div>
    <ul style="margin-top:3px">
      <li><span class="no">✕ 不是公式：</span>疑问句（TikTok 31%、抖音 38% <b>低于</b>基线）</li>
      <li><span class="no">✕ 不是公式：</span>「第N集」（B站 44%、抖音 38% 低于基线）</li>
      <li><span class="no">✕ 不是公式：</span>emoji（≈基线，样本仅 2-3 条）</li>
      <li><span class="yes">✓ 是标配：</span>话题标签（与基线持平，但不挂就少一条流量入口）</li>
    </ul>
  </div>

  <div class="card full">
    <h2>⑤ 封面与标签 <span>推翻两个常见假设</span></h2>
    <div style="display:grid;grid-template-columns:1.05fr 1fr;gap:6px">
      <div>
        <div class="key" style="margin-top:0"><b>封面「必须写大字」不成立。</b>
        B站 带字 48% vs 无字 54%；TikTok 带字 47% vs 无字 57% —— <b>无文字组反而略高</b>。
        封面真正起作用的是「一眼看懂画面里的关系」（如《当员工重新应聘 / 自己现在的岗位》→ 113万播放）。<br><br>
        <b>B站真实 OCR 文本示例（实测提取）：</b><br>
        「内容由AI生成 / @阿猫阿狗原创 / 剧情演绎 / 无不良引导」<br>
        「别闲了 / 内容AI生成仅供娱乐」<br>
        「盖饭 / 10元一份」<br>
        <span style="color:#666">→ AI 内容普遍在封面做合规标注，已成为该品类的默认动作。</span><br><br>
        <b>像素级实测（271 张原图）：28 项组间检验仅 1 项达 p&lt;0.05</b>，且 B站与快手在饱和度上方向相反。
        封面视觉与能否爆<b>没有稳定关系</b> —— 别在"爆款配色"上花时间；唯一硬信息是画幅比（TikTok 139/140 竖屏、B站 68/80 横屏）。
        人工复核：封面墙.png。</div>
      </div>
      <div>
        <div style="font-size:6.9pt;line-height:1.5"><b>标签数量中位：</b>B站 6 个、TikTok 5 个、抖音 5 个、快手 4 个<br>
        <b>高频标签：</b><br><span class="tagline">{tag_line}</span><br>
        <b>注意：</b>TikTok 的 weirdcore / surreal 这类<b>风格词</b>占位很高，说明该平台对 AI 荒诞美学有明确标签流量；
        抖音/快手高热标签几乎全是<b>平台官方活动</b>（ai创作大赛、笑演星计划）—— 挂当季官方话题是普遍动作，不是可选项。</div>
      </div>
    </div>
  </div>

  <div class="card full">
    <h2>⑥ 行动清单</h2>
    <div class="act">
      <div class="do">
        <h3>✓ 照做</h3>
        <ul>
          <li>AI 短剧/漫剧：3 分钟以上、按集连载、做合集收口</li>
          <li>标题塞进一个具体、可核对的信息（价格/时长/人数/倍数）</li>
          <li>发布挂当季平台官方活动话题</li>
          <li>老 IP、老题材用 AI 翻新，降低理解成本</li>
          <li>封面先让人看懂"关系"，其次才是美观</li>
        </ul>
      </div>
      <div class="dont">
        <h3>✕ 别做</h3>
        <ul>
          <li>用互动率预测爆款（同账号两组几乎相同）</li>
          <li>为了"悬念"硬把标题写成疑问句</li>
          <li>以为封面写大字就能提升转化</li>
          <li>把「第N集」当流量密码（真正跑量的是合集）</li>
          <li>拿本表当阈值标准 —— 288 条是抽样，只做方向校准</li>
        </ul>
      </div>
    </div>
  </div>

</div>

<div class="ft">
  数据底座：competitor_viral_20261014.xlsx（288 行，5 平台可采）｜ 样片库_20261014.xlsx（39 条精选）｜ 封面墙.png（人工复核）｜ 详版：爆款方法论_20261014.pdf（7 页）<br>
  未采集、未推断任何后台指标（完播率 / 留存 / 点击率 / 流量来源）｜ 小红书、微信视频号、Facebook Reels 无公开取数路径，本轮为 0 —— 证据见 FEASIBILITY.md
</div>
</body></html>"""
    open(HTML, "w", encoding="utf-8").write(html)
    return HTML


if __name__ == "__main__":
    h = render()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=3)
        pg.goto("file://" + h, wait_until="load")
        pg.pdf(path=PDF, format="A4", print_background=True,
               margin={"top": "8mm", "bottom": "7mm", "left": "8mm", "right": "8mm"})
        pg.screenshot(path=PNG, full_page=True)
        b.close()
    import pymupdf
    print("saved", PDF, "页数:", len(pymupdf.open(PDF)))
    print("saved", PNG)
