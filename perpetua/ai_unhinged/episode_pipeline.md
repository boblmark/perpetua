# AI UNHINGED · 单集生产管线规格

> 版本：v1 草案 · 2026-10-10 · 待用户确认主持人设定后开工正片
> 目标：每集 22–26 分钟 · 每周 2–3 集（周二/五/日）

## 单集脚本结构

```
00:00–00:20  冷开场
             本集最炸的一个镜头，无铺垫硬切。
             [自动化] 从素材库按"视觉冲击力"排序取 top1
             [人工]   确认该镜头无政策风险后采用

00:20–00:50  主持人钩子
             "This week I generated 214 AI videos. 27 of them broke my brain.
              Number 19 made me question reality — stick around for it."
             必须给出"看到最后"的具体理由 + 具体编号。
             [人工]   每集重写编号与理由（禁止复用上一集文案）

00:50–01:50  "本周观察"独白（30–60 秒）
             [人工]   必须人工写初稿 → 用户亲审 → 才可合成
             这是 YPP 审核员可见的"人的证据"，不可跳过

01:50–07:00  BLOCK 1｜"PHYSICS GAVE UP"（AI 物理崩坏，6–8 个片段）
             每片段 25–40 秒：片段 → 吐槽 → AI FAIL SCORE 打分（1–10）

07:00–12:00  BLOCK 2｜"KAREN vs AI"（固定环节，存量 IP，5–6 个片段）
             [自动化] 从素材库 B_karen_vs_ai 分类取片
             [人工]   排序逻辑文档化（为什么这个顺序）

12:00–12:30  MID-ROLL 预留（变现后启用，目前留空）

12:30–18:00  BLOCK 3｜"AI TRIED TO FILM A MOVIE"（AI 叙事崩坏，5–7 个片段）

18:00–22:00  BLOCK 4｜"WORST OF THE WEEK / VIEWER SUBMISSIONS"（UGC 飞轮）

22:00–24:00  GRAND FINALE
             兑现开场承诺的 Number 19 + 下集预告 + 播放列表引导
             [人工]   下集预告文案每集重写

24:00–26:00  片尾：订阅卡 + AI 披露声明口播（固定模板，可复用）
```

## 每个片段的 3 层原创内容（缺一不可）

1. **播放前**（3–8 秒）：设置期待或提问
   "Okay, this one starts normal. Watch the shopping cart."
2. **播放中**（可选）：实时吐槽 / freeze frame 定格 / 红圈标注
3. **播放后**（5–15 秒）：AI FAIL SCORE 打分 + **具体理由** + 一个笑话或延伸
   [人工] 打分理由必须人工写——这是政策要求的"原创编辑判断"

## 片段来源

| 来源 | 说明 | 自动化程度 |
|---|---|---|
| 423 条存量库 | `/home/hatch/data` 检索（见下） | 自动检索 + 人工终选 |
| 每周新生成 | 按 BLOCK 主题缺口生成补充片段 | 半自动（走现有生成管线） |
| UGC 投稿 | BLOCK 4 专用（第 3 集起开放） | 人工筛选 |

存量库检索方式：`muse.exec` 在 `/home/hatch/data` 下按标题关键词/目录分类检索；
建议先建 `/home/hatch/data/perpetua/ai_unhinged/asset_index.json`
（片段路径 → 分类 → 笑点强度/视觉冲击力评分），避免每集重复全量扫描。

## TTS 分段合成

- 工具：`tts synthesize-script --speaker Karen=avocado_v2:Karen`
- **音色锁定**：`avocado_v2:Karen`，全季不换（见 `voice_lock.json`）
- 分段策略：按脚本结构分段合成（钩子/BLOCK1/…/片尾各一段），便于单段返工
- 文本规范：数字拼写出来（"two hundred fourteen"）、缩写展开，
  不得含舞台指示/Markdown（见 tts skill）
- [自动化] 合成执行 · [人工] 合成前校对脚本（错字=重录成本）

## 剪辑要求

| 要求 | 标准 |
|---|---|
| 视觉变化频率 | 每 3–5 秒必须有变化（切镜头/缩放/字幕/音效） |
| 笑点定格 | 关键笑点 freeze frame + 放大 + 音效 |
| 字幕 | 全程动态英文字幕（CapCut 自动生成 + 人工校对） |
| 背景音乐 | YouTube Audio Library 免版权，音量压到 **-22dB** 以下 |
| 片头 | 5 秒品牌动画（K monogram + glitch），每集必有 |
| AI FAIL SCORE | 1–10 打分动画组件，每集复用（品牌记忆点） |
| 禁止 | 水印、"subscribe"闪烁动画、片头 Logo 超过 2 秒 |

## 发布前 Checklist（人工逐项勾选）

- [ ] AI 披露：上传时勾选 "Altered or synthetic content"（强制）
- [ ] "本周观察"独白已用户亲审
- [ ] 每个 AI FAIL SCORE 打分有具体文字理由
- [ ] 本集脚本与往期脚本相似度 < 20%（跑检查）
- [ ] 口头禅 ≥1 句、running gag ≥1 个已植入
- [ ] 描述无 "Keywords:" 段落、无关键词堆砌；标签 ≤5 个
- [ ] 分类 Comedy/Film & Animation；Not made for kids；英文 SRT 字幕已备
- [ ] 片尾 End screen（最佳视频/订阅/播放列表）已设置

## 自动化 vs 人工 总览

| 环节 | 自动化 | 人工 |
|---|---|---|
| 素材检索初筛 | ✅ 脚本 | 终选确认 |
| 片段排序 | ✅ 初排 | 排序逻辑文档化 |
| 脚本撰写 | ✅ 初稿（模板） | **必须重写/编辑**（相似度<20% 硬约束） |
| "本周观察"独白 | ❌ | **人工写初稿 → 用户亲审** |
| AI FAIL SCORE 理由 | ❌ | **人工逐条写** |
| TTS 合成 | ✅ | 合成前校对 |
| 剪辑 | ✅ 模板化执行 | QC 终审 |
| 字幕 | ✅ 自动生成 | 人工校对 |
| 发布/AI 披露勾选 | ❌ | 人工（现行政策） |
