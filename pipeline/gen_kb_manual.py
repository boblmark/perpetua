#!/usr/bin/env python3
"""生成 kb.viralloopapp.com 使用说明书（单文件 HTML，图片 base64 内嵌）。"""
import base64, io, os
from PIL import Image

SRC = os.path.expanduser("~/workspace/user/media_library/browser_screenshots")
OUT = os.path.expanduser("~/workspace/your_files/kb-viralloopapp-com-使用说明书.html")

# (文件名, 章节用图)
SHOTS = [
    ("bb/bbd35c396109e8c1c9e857c08e7e336a24f3daa134f33398b549c8d9c6c48636.png", "landing"),
    ("ce/ce72751a54c41f380788747cad7af518a03a258678b5656d2ec9d86b8f6752dd.png", "explorer"),
    ("80/80d2cfe8a9f2167a44b43a864649047cf6cf39b7f01cf773e5228b087d02d748.png", "search_en"),
    ("8f/8f6ecc4a83c484babd14c9ee586ae99ee58222e4300b7f6c61a2c85fbff30f78.png", "search_zh"),
    ("e1/e1429b66a0e090368a87d66a38693785253bdf6399dc1aeab6985acaa67f66a4.png", "analyze"),
    ("03/03fb71ddd3b78ef464ad33d51689e4297b8713a54ca74e7e99addbc28608a7a0.png", "decisions"),
    ("cc/cc131a4e9c703315fc6a7d403e2b73d9e5a4f1f7b86895e77f6f79c38c80c214.png", "enrich"),
    ("a2/a2ca3c3c16630c9129e285ff505193ccc3901eef2c03f1faddc8df08bdfe2c3b.png", "manage"),
    ("45/45af2d8e438792ce0fc0a49d2e4641d8b836f46c61b7b71a24378a9736f3b354.png", "onto_zh"),
    ("ca/ca9ab8a384ee661b3dfec771d5b8b3d66b4fb410045a45d995eca3128ee5baee.png", "onto_en"),
    ("8a/8a513d5f31eb1b773581e4fe04d6a7b11cffe4ca40d352d0534eecde99e66987.png", "analyze_en"),
]

def b64img(path):
    im = Image.open(path).convert("RGB")
    if im.width > 1280:
        im = im.resize((1280, int(im.height * 1280 / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

imgs = {}
for rel, key in SHOTS:
    imgs[key] = b64img(os.path.join(SRC, rel))
    print("img ok:", key)

def shot(key, cap):
    return f'<figure><img src="{imgs[key]}" alt="{cap}"><figcaption>{cap}</figcaption></figure>'

def sec(num, title, body):
    return f'<section><h2>{num}. {title}</h2>{body}</section>'

html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kb.viralloopapp.com 使用说明书（附端到端验证报告）</title>
<style>
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:960px;margin:0 auto;
padding:24px 16px;background:#0b0f16;color:#dbe4f0;line-height:1.7}
h1{font-size:26px;border-bottom:2px solid #2dd4bf;padding-bottom:12px}
h2{font-size:20px;color:#5eead4;margin-top:40px;border-left:4px solid #2dd4bf;padding-left:10px}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:14px}
th,td{border:1px solid #334155;padding:8px 10px;text-align:left}
th{background:#16202e;color:#5eead4}
figure{margin:20px 0}img{width:100%;border:1px solid #334155;border-radius:8px}
figcaption{font-size:13px;color:#94a3b8;margin-top:6px}
.note{background:#16202e;border:1px solid #f59e0b;border-radius:8px;padding:12px 14px;margin:14px 0;font-size:14px}
.ok{color:#4ade80}.warn{color:#fbbf24}
ul{padding-left:20px}li{margin:6px 0}
.cover{background:#101826;border:1px solid #2dd4bf;border-radius:12px;padding:20px;margin-bottom:24px}
.cover p{margin:6px 0;color:#94a3b8}
a{color:#5eead4}
</style></head><body>
"""

html += """
<h1>📚 kb.viralloopapp.com 使用说明书</h1>
<div class="cover">
<p><b>站点：</b><a href="https://kb.viralloopapp.com">https://kb.viralloopapp.com</a>（Semantica 知识库 · Semantic Intelligence）</p>
<p><b>验证日期：</b>2026-10-11（新用户第一视角，浏览器实地走访 10 个界面 + 后端 API 实测）</p>
<p><b>数据集：</b>15 个知识节点 / 16 条关系 / 3 种图谱模式 · 数据集在线</p>
<p><b>阅读方式：</b>每个功能一节，配真实界面截图；先看"验证结论"了解整体状态，再按需查功能用法。</p>
</div>

<h2>✅ 端到端验证结论（10 项全过）</h2>
<table>
<tr><th>#</th><th>功能</th><th>验证结果</th><th>说明</th></tr>
<tr><td>1</td><td>落地页</td><td class="ok">正常</td><td>渲染完整，无报错；注意 hero 文案暂为英文（见备注）</td></tr>
<tr><td>2</td><td>知识探索（图谱）</td><td class="ok">正常</td><td>15 nodes · 16 edges 力导向图谱正常渲染，可平移缩放</td></tr>
<tr><td>3</td><td>搜索</td><td class="ok">正常</td><td>英文关键词 "Veo" 返回 1 结果（score 96）；中文词"视频发布"无匹配（节点标签以英文为主，非故障）</td></tr>
<tr><td>4</td><td>分析（推理引擎）</td><td class="ok">正常</td><td>事实/规则输入框、快捷模板、运行推理按钮齐全；本次只读验证未实际执行推理</td></tr>
<tr><td>5</td><td>决策</td><td class="warn">空数据</td><td>页面正常，当前图谱中无决策记录——是数据集为空，不是程序 bug</td></tr>
<tr><td>6</td><td>增强（导入/导出）</td><td class="ok">正常</td><td>拖拽导入区、JSON/CSV 导出按钮齐全；只读验证未实际导入导出</td></tr>
<tr><td>7</td><td>管理（PROV-O 谱系/总览）</td><td class="ok">正常</td><td>节点谱系追踪、图谱统计（NODES 15 / EDGES 16 / DENSITY 7.619%）正常</td></tr>
<tr><td>8</td><td>本体中心</td><td class="warn">空数据</td><td>页面正常，尚未加载任何本体（ontology）——是数据集为空，不是程序 bug</td></tr>
<tr><td>9</td><td>中英切换</td><td class="ok">正常</td><td>侧栏底部 EN/中文按钮，切换可靠（实测往返两次）</td></tr>
<tr><td>10</td><td>后端 API</td><td class="ok">正常</td><td>/api/search 返回文档片段+向量/BM25 排名；/api/graph/nodes 返回节点（curl 实测）</td></tr>
</table>
<div class="note">📌 <b>给新用户的提醒：</b>① 落地页 hero 区（"Navigate knowledge like a living system." 等）暂未汉化，属已知待修；② 搜索用英文关键词效果最好；③ 决策/本体中心当前是空的，等数据接入后才有内容。</div>
"""

html += sec("1", "落地页：第一次打开看到什么", f"""
<p>打开 <b>kb.viralloopapp.com</b> 首先看到深色 hero 页：顶部 "SYSTEM ONLINE · Semantica v2" 状态条，中间大标题，两个按钮——</p>
<ul>
<li><b>Open Semantica Explorer</b>：进入知识图谱主界面（第 2 节）；</li>
<li><b>Run Reasoning</b>：跳到分析·推理引擎（第 4 节）。</li>
</ul>
<p>hero 下方是实时统计条（15 Knowledge nodes / 16 Relationships mapped / 3 Graph modes / Active Dataset online），右侧有一张示例实体档案卡（NSRP1）。再往下是 WORKSPACES 区，主工作区卡片一点即进图谱。</p>
<p>左侧图标侧栏在所有页面常驻：知识探索 / 分析 / 决策 / 增强 / 管理 / 本体中心，点图标即切换功能。</p>
{shot("landing", "图 1-1：落地页（英文模式）。hero、统计条、示例实体卡、WORKSPACES 区")}
""")

html += sec("2", "知识探索：可视化知识图谱", f"""
<p>点 <b>Open Semantica Explorer</b> 或侧栏"知识探索"进入。顶部显示 <b>15 nodes · 16 edges（15 active）</b>，中央是力导向图谱画布：每个节点是一个知识文档（如 veo-primary_2026-10-09、KB 统一索引、EP1 完整制作剧本），节点颜色按文档类型区分（图例在搜索框下方）。</p>
<p><b>你能做的：</b></p>
<ul>
<li>鼠标拖拽平移、滚轮缩放查看图谱；</li>
<li>顶部搜索框输入关键词定位节点（见第 3 节）；</li>
<li>切换视图模式：<b>Full Graph</b>（全图）/ <b>Grouped View</b>（分组）/ <b>Focus</b>（聚焦）；</li>
<li>CAMERA 按钮组控制视角，LAYOUT → Run 重新布局；</li>
<li>ANALYSIS 工具：Effects（影响分析）、Neighbors（邻居）、Temporal（时序）；</li>
<li>底部 <b>TEMPORAL SCRUBBER（1970–2026）</b> 时间轴可拖动，按时间过滤节点。</li>
</ul>
{shot("explorer", "图 2-1：知识探索·图谱主界面（中文模式）。15 节点 16 边，力导向布局，底部时间轴")}
""")

html += sec("3", "搜索：在图谱里找内容", f"""
<p>图谱顶部搜索框（"搜索命令、节点或概念"）输入关键词后点 <b>Search</b>：</p>
<ul>
<li>搜 <b>Veo</b> → 返回 1 条结果 <b>veo-primary_2026-10-09</b>（DOCUMENT，score 96），结果面板可 Dismiss；输入时还有 typeahead 联想下拉。</li>
<li>搜 <b>视频发布</b> → 无结果面板。原因是节点标签以英文为主，中文词匹配不到——不是搜索坏了，换英文关键词即可。</li>
</ul>
<p>后端另有混合检索 API（<b>/api/search</b>，向量 + BM25 融合），实测 <b>q=Veo</b> 可返回文档片段与向量/BM25 各自排名，供程序调用。</p>
{shot("search_en", "图 3-1：搜索 Veo 返回 1 条结果（score 96）")}
{shot("search_zh", "图 3-2：搜索中文词无匹配（节点标签以英文为主）")}
""")

html += sec("4", "分析：推理引擎（Reasoning Playground）", f"""
<p>侧栏"分析"进入推理引擎。左侧是输入区，右侧是"推理结果"面板：</p>
<ul>
<li><b>快捷模板</b>：Drug Candidate / Gene – Disease / Pathway Activation，一点即填示例；</li>
<li><b>事实（Facts）</b>：每行一条 <b>predicate(subject, object)</b> 形式，如 inhibits(Metformin, mTOR)；</li>
<li><b>规则（Rules）</b>：<b>IF _ AND _ THEN _</b> 语法，如 IF inhibits(...) AND causes(...) THEN candidate(...)；</li>
<li><b>将推断事实写入图谱</b>开关（默认开）：推理出的二元事实会作为边写回图谱；</li>
<li>点 <b>运行推理</b> 执行，右下角小按钮可重置。</li>
</ul>
<p>顶部还有 <b>SPARQL Querying</b> 页签，可对图谱写 SPARQL 查询。本次为只读验证，未实际提交推理任务。</p>
{shot("analyze", "图 4-1：分析·推理引擎（中文模式）。左侧事实/规则输入，右侧结果面板待命中")}
""")

html += sec("5", "决策：决策链审查（当前无数据）", f"""
<p>侧栏"决策"进入 DECISION INTELLIGENCE。正常情况下这里会列出决策记录，选中一条可查看其因果链、上下文与先例匹配。</p>
<div class="note">⚠️ 当前图谱中 <b>0 条决策记录</b>，页面显示 "No decisions" 空状态。这是数据集为空，不是功能故障——页面本身渲染正常，筛选框（按 ID、分类、结果筛选）可用。</div>
{shot("decisions", "图 5-1：决策页空状态（数据为空，页面正常）")}
""")

html += sec("6", "增强：导入 / 导出知识", f"""
<p>侧栏"增强"进入 KNOWLEDGE AUDIT，顶部页签：<b>Import and Export</b>（导入与导出）/ Diff and Merge（差异合并）/ Entity Resolution（实体对齐）/ Registry（注册表）。</p>
<ul>
<li><b>导入实体与关系</b>：把 .json / .csv 文件拖进虚线框（或点"拖拽或点击浏览文件"），再点"上传到图谱"；</li>
<li><b>导出图谱快照</b>：选 JSON 或 CSV 格式，点"下载导出"，得到含全部节点属性、边权重、实体元数据的标准快照包。</li>
</ul>
<p>本次只读验证未实际导入/导出。</p>
{shot("enrich", "图 6-1：增强·导入与导出（中文模式）")}
""")

html += sec("7", "管理：谱系追踪与图谱总览", f"""
<p>侧栏"管理"进入 GRAPH GOVERNANCE，三个页签：</p>
<ul>
<li><b>PROV-O Lineage</b>：输入 Node ID 点 Trace，查看该节点的 W3C PROV-O 血缘图；可导出 JSON/MD；</li>
<li><b>KG Overview（图谱总览）</b>：NODES 15 / EDGES 16 / DENSITY 7.619%，类型分布（document 100%），可点击的关联节点列表；</li>
<li><b>Ontology Summary（本体摘要）</b>：当前 "0 vocabulary schemes loaded"，需经 Vocabulary Browser 导入 .ttl/.rdf。</li>
</ul>
{shot("manage", "图 7-1：管理·PROV-O 谱系查看器（输入节点 ID 后追踪血缘）")}
""")

html += sec("8", "本体中心：Schema 治理（当前无数据）", f"""
<p>侧栏"本体中心"进入 SCHEMA GOVERNANCE：Registry（注册表）/ Editor（编辑器）/ Versions（版本）/ Alignments（对齐）/ Health（健康）/ SHACL 页签，支持按格式过滤（All / OWL / SKOS / INTERNAL / EXTERNAL），右上角 Entity Search 与 + Load Ontology。</p>
<div class="note">⚠️ 当前 <b>0 个本体已加载</b>（"No ontologies loaded yet"），属数据集为空。需要时点 <b>+ Load Ontology</b> 从 URL 导入、上传文件或新建本体。</div>
{shot("onto_zh", "图 8-1：本体中心（中文模式，空状态）")}
{shot("onto_en", "图 8-2：本体中心（英文模式，空状态）——中英切换示例")}
""")

html += sec("9", "中英切换：在哪，怎么用", f"""
<p>语言切换按钮在<b>左侧栏最底部</b>：中文模式下显示 <b>EN</b>，英文模式下显示 <b>中文</b>。点一下即整站切换（侧栏、标题、页签名、表单、说明文字），会短暂显示 "Loading workspace…" 后刷新。</p>
<p>实测往返切换两次均可靠。默认语言为中文。</p>
{shot("analyze_en", "图 9-1：英文模式下的分析页（左下角切换按钮显示中文）")}
<div class="note">📌 已知待修：落地页 hero 文案（"Navigate knowledge like a living system." 等）尚未进翻译字典，中文模式下仍显示英文，不影响功能使用。</div>
""")

html += """
<section><h2>10. 给新用户的 3 分钟上手路径</h2>
<ol>
<li>打开 <b>kb.viralloopapp.com</b>，看 hero 统计确认数据集在线；</li>
<li>点 <b>Open Semantica Explorer</b>，在图谱里拖一拖、缩一缩，熟悉 15 个节点；</li>
<li>在图谱搜索框试搜 <b>Veo</b>，看结果定位；</li>
<li>去<b>分析</b>页点一个快捷模板（如 Drug Candidate），了解推理输入格式（先别点运行推理，除非你确定要写回图谱）；</li>
<li>去<b>管理 → KG Overview</b> 看图谱统计，确认数据规模；</li>
<li>需要换英文时点左下角 <b>EN</b>。</li>
</ol>
<p style="color:#94a3b8;font-size:13px">验证方式：2026-10-11 新用户视角浏览器实地走访（只读，未创建/删除/上传/修改任何数据，未提交推理任务）＋ curl 实测 /api/search 与 /api/graph/nodes。截图均为本次真实界面。</p>
</section>
</body></html>
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote", OUT, os.path.getsize(OUT), "bytes")
