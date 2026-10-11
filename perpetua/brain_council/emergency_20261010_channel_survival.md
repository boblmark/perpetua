# 紧急议会 · 频道生死议题 · 2026-10-10 00:07 CST

> 用户原话："赶紧召开紧急议会讨论此主题，这决定我们频道的生死关头"
> 议题来源：arena agent 会话 https://arena.ai/agent/01a1214b-d0ea-70f3-a719-5ccac10dbcdf
> + 用户同时上传的《KarenVsAI 深度诊断报告 + 30 天 YPP 作战方案》（897 行）及 README（分析模型可复现包）

## ⚠️ 执行状态声明（先读）

1. **arena 会话本体未能读取**：`browser.open` 抓取该 URL 只返回登录页标题（需 arena.ai 登录态）；
   且本 subagent 无 `browser.spawn_task` 权限（live 浏览器任务只能由 parent/root 发起）。
   → **议题内容按用户同时上传的 YPP 诊断文档认定**（上传时间 00:07，与"讨论此主题"同一消息，
   合理推定该文档即 arena 会话的产出或其附件）。
   → **Parent 待办**：用浏览器任务打开该 arena 会话，核对本文议题摘要与会话原文是否一致；
   若不一致，以会话原文为准重开议题。
2. **三脑会诊未能实际召开**：Ask Studio / LMArena / AI Studio 均需 `browser.spawn_task`，
   本 subagent 无权限。本文件 = **议会执行包**：议题摘要 + 事实核验 + 三脑提问包（已备好数据，
   parent 可直接发射）+ 待共识常量候选 + 分歧点 + 拍板项。
3. **criteria.json 未动**（仍为 v20）：铁律"三脑同结论才写进管线"——三脑未跑，
   任何新常量只列候选、不写入。

---

## 一、议题摘要：YPP 诊断文档核心结论

### 频道体检（2026-10-09 实测抓取，451 条全量）

- 订阅 533 / 总观看 737,417 / Shorts 423 条 / 长视频 28 条（总计仅 69.4 分钟内容）
- **分发崩塌 99.6%**：历史基线均观看 1,789 → 最近 20 条均观看 6.5；10 月 6–8 日 13 条全部个位数
- **频道死过两次**：6 月前已有一轮崩塌（序号 16–24），沉寂 4 个月，10 月重启即再崩塌
- 95.7% 的 Shorts 卡在 5,000 观看以下，从未有一条突破 5 万（Shorts 冷启动测试池天花板）
- 观看→订阅转化率 0.072%（健康基准 0.5–2%），差 7–28 倍

### 六大病灶

1. **批量近重复内容**：10-06 一天 8 条，4 条同一创意换皮；8 组标题簇同构重复 → 触发 YouTube
   "inauthentic content"（非原创/批量生产）政策红线，YPP 人工审核 30 秒驳回
2. **工程测试产物被公开发布**：`geminigen PLAN...` / `E2E Asset Publish Feedback...` / 中文 B2B 视频
   → "无人监管的自动化倾倒"铁证
3. **主题彻底失焦**：451 条横跨 12 个互不相关题材 → 算法无法建立主题画像，只能给最低档试探曝光
4. **元数据违规**：简介里写 "Keywords:" 罗列关键词（垃圾元数据政策明确违规形态）
5. **赛道错配**：AI 生成的 Karen instant karma 在 YouTube 无验证需求（情绪价值来自"这是真的"，
   AI 前提崩塌）；但"AI 视频 + 真人吐槽/解说"赛道实测有效（@dandingles 等，单条 14.9 万–226 万）
6. **脉冲式批量倾倒 + 长期空窗**：3 天 13 条、多条间隔 4–8 秒 → 自动化指纹，spam 信号

### YPP 门槛测算

- 唯一活路 = Tier 2 长视频路径：1,000 订阅 + 4,000 合格观看小时（Shorts 路径需 3 万–10 万倍增长，物理上不存在）
- 缺口：+467 订阅 / +约 3,960 观看小时 → 30 天需日均 132 小时
- **2027-02-01 门槛翻倍**：8,000 小时 / 2,000 万 Shorts 观看；1 月 31 日前提交的申请按旧门槛审
- 基准情景（10 集 × 3,000 观看 × AVD 9 分钟）→ 4,500 小时，Tier 2 数字达标，概率自估 25–40%

### 30 天作战方案（Phase 0/1/2/3）

- **核心转向**：从"用 AI 伪装成现实的 Karen 短剧"转向"用真人吐槽 AI 生成的荒诞视频"的 20–30 分钟长视频
  节目《AI UNHINGED》（固定环节 Karen vs AI + AI FAIL SCORE 打分 + UGC 投稿）
- Phase 0（Day 1–3）：频道急诊——删 4 条工程残留、12 条崩塌视频只留 1 条、27 条跑题设不公开、
  **关闭所有自动上传脚本**、Day 2–8 完全停发 Shorts、重写简介/关键词/品牌、素材库分类
- Phase 1（Day 4–10）：2 集试片 + Day 10 Go/No-Go（≥3,000 观看 & AVD ≥6 分钟 → 加速）
- Phase 2（Day 11–24）：每周 2–3 集；Phase 3（Day 25–30）：冲刺 + 合规自查 + 提交申请
- Plan B：纪录片式 / AI 工具评测 / Karen 连续剧
- **主持人层是唯一硬门槛**：A 真人出镜 / B 真人配音（最推荐） / C AI 语音+严格 4 条约束 / D 现状（❌）

---

## 二、事实核验（本 subagent 独立 web 验证，2026-10-10 00:15 CST）

| 文档主张 | 核验结果 |
|---|---|
| 2027-02-01 YPP 门槛翻倍（8,000 小时 / 2,000 万 Shorts） | ✅ 确认。多源一致（air.io、gsmdome，抓取时间为近 2 天内更新）。补充细节：**以 1 月 31 日 23:59 UTC 前送达的申请时间为准**按旧门槛审；被驳回后重申请按新门槛。 |
| 2025-07-15 "repetitious" 更名 "inauthentic content" 并明确覆盖模板化 AI 内容 | ✅ 确认。多源一致（auditsocials、aiclipviral、layer3labs、akool）。补充细节：YouTube 官方口径是"澄清而非新禁令"——批量+同质+无原创贡献三者叠加才触发；**AI 本身不是原罪**。 |
| "Shorts 观看时长一分不计入 4,000 小时" | ✅ 为长期稳定的官方规则，多源一致，无需再验。 |
| "2026-08-10 YouTube 官方宣布门槛翻倍"（具体日期） | ⚠️ 未能核验到该具体日期的官宣记录；实质内容（翻倍+日期+申请时间规则）已确认。日期不影响决策。 |
| 竞品数据（@dandingles 32 万订阅等） | ⏭️ 未逐条核验；属公开快照，量级合理，议会引用时标注"文档自述数据"。 |

---

## 三、与深复盘根因的交叉（deep_dive_2026-10-09.md R1–R6）

| 深复盘根因 | YPP 文档对应 | 关系 |
|---|---|---|
| R1 分发层系统性失效（38 条/8 天全灭） | 结论四"分发已死"+崩塌时间线 | ✅ 同结论，不同证据链（Data API vs 全量抓取+RSS）。**双源独立同结论** |
| R3 同主题 72h 三次重复 | 病灶 1（47 TIMES 三版本） | ✅ 同结论 |
| R4 标题公式偏离/测试标题 | 病灶 2（工程残留标题） | ✅ 同结论，YPP 文档挖得更深（3 条工程残留 + 政策含义） |
| R6 秒级批量 = spam 信号 | 病灶 6（4–8 秒间隔） | ✅ 同结论 |
| R2 zero_view_alert 提前公开（已 P0 修复） | — | 深复盘独有，YPP 文档未覆盖 |
| R5 auto_pin 首评死状态 | — | 深复盘独有 |
| — | 病灶 3 主题失焦（12 题材）/ 病灶 4 简介 Keywords / 病灶 5 赛道错配 | YPP 文档独有，**深复盘未覆盖**——这是本次议题的新增信息量 |

**新增关键判断**：深复盘把问题框在"分发层失效 + 管线 bug"里；YPP 文档把框放大到"**政策合规性（inauthentic content）+ 赛道错配 + 变现路径错误**"。
两者不矛盾，但 YPP 文档的结论更严重：即使分发明天恢复，451 条历史内容也会让 YPP 人工审核驳回。
→ **议会必须回答的不是"怎么让 Shorts 恢复播放"，而是"频道要不要换引擎"。**

---

## 四、三脑提问包（已备好，待 parent 用 browser.spawn_task 发射）

### 4.1 Ask Studio（传感器）——频道级健康诊断

> 调用方式：browser.spawn_task → studio.youtube.com（注意：2026-10-09 23:49 曾被重定向到 Google
> 登录页；先试，失败则走 Secure Vault 自动重登，3 次失败跳过并注明）

**携带数据**：频道 @karenvsai（533 订阅）；近 20 条 Shorts 均观看 6.5（基线 1,789）；
连续 4 个 48h 窗口 38 条全灭、最高单条 12 播放；10-06 批次 72h+ 仍死寂；
10 月 6–8 日 13 条中有多条间隔 4–8 秒批量发布；1 个有效版权警告 + 1 个社区准则警告。

**问题（原文粘贴）**：
"My channel @karenvsai: 533 subs. Last 20 Shorts averaged 6.5 views vs historical baseline 1789
per video (99.6% distribution collapse). 38 videos over 8 days, max 12 views each, zero likes,
zero real comments. Videos published 72+ hours ago still dead — beyond your 6-48h normal
cold-start window. On Oct 6-8 I published 13 videos, several only 4-8 seconds apart.
Diagnose in order of likelihood: (1) Is this channel-level suppression/shadowban or
recommendation-pool exclusion? (2) How do I check in Studio whether the channel has a
quality flag? (3) Rank the causes: batch-publishing spam signal vs repetitive-template
content vs topic confusion. (4) Give me 3 concrete fixes for this week, each as a
measurable rule I can put into my publishing system."

**期望输出形态**：根因排序（带概率）+ 可验证的 Studio 检查路径 + 3 条可测量的规则。

### 4.2 LMArena（陪审团）——Side-by-Side 指定模型横评

> 必须用 Side-by-Side（Battle 匿名质量波动大，属重大决策）

**携带**：Ask Studio 的诊断结论（4.1 返回后填入）+ 以下 5 个方案全文。

**五个待横评方案**：

- **方案 A（YPP 文档主张）**：全面转向《AI UNHINGED》20–30 分钟长视频（真人吐槽 AI 荒诞视频），
  Shorts 降级为引流切片；Phase 0 先做频道清洗（删工程残留、跑题设不公开、重写简介），
  Day 2–8 停发 Shorts；目标 114 天内 1,000 订阅 + 4,000 小时。
- **方案 B（Plan B-1）**：AI 纪录片式长视频（15–25 分钟），AI 素材做 B-roll + 原创解说讲信息量主题，
  合规性最强。
- **方案 C（Plan B-2）**：AI 工具评测/教程（10–20 分钟），CPM 最高（$8–20），搜索流量稳定。
- **方案 D（深复盘主张）**：不换引擎，修复管线（分发诊断+去重+标题门禁+auto_pin），继续 Shorts，
  等分发恢复。
- **方案 E（暂停派）**：分发恢复前暂停一切发布，只做清洗和素材库建设，避免继续消耗额度并加深
  自动化指纹。

**问题（原文粘贴）**：
"My YouTube channel (533 subs, AI comedy niche) suffered 99.6% distribution collapse:
last 20 Shorts averaged 6.5 views vs 1789 baseline. I have 423 existing AI video clips.
YouTube doubles YPP thresholds on 2027-02-01 (8000h/20M Shorts views); applications
submitted by Jan 31 2027 are judged on the old bar (4000h/10M). I have ~114 days.
<Ask Studio 诊断结论填入>
Compare the 5 plans above side by side. For each: (1) probability of reaching
1000 subs + 4000 qualified watch hours by Jan 31 2027, (2) biggest single risk,
(3) one measurable kill-criterion (when to abandon it). Then rank them and name
ONE winner with the single strongest reason. Output constants only, no vague advice."

**期望输出形态**：每方案 3 个常量（概率/最大风险/kill 线）+ 唯一优胜者 + 最强理由。

### 4.3 AI Studio（总工程师，免费档 Gemini 3.8 Flash）——落成可粘贴条文

> 注意：默认选中的 Gemini 3 Flash Preview 是付费档，必须手动切免费档

**携带**：4.1 诊断 + 4.2 优胜方案全文。

**问题（原文粘贴）**：
"Based on the diagnosis and the winning plan above, write the final operating spec
for my YouTube channel as paste-ready rules. Two sections only:
MUST (numbered, each with a measurable threshold, e.g. 'NEVER publish 2 videos
within 4 hours of each other') and NEVER (numbered, each naming the exact
forbidden pattern). Cover: publishing cadence, title formula, content mix
(long-form vs Shorts), metadata (description/tags), AI disclosure, and review
gates. No explanations, no advice paragraphs — rules only."

**期望输出形态**：MUST / NEVER 两节条文，可直接写入 criteria.json 与上传门禁。

---

## 五、待共识后写入的常量候选（未写入 criteria.json）

以下来自 YPP 文档 + 深复盘，**需三脑共识后才写入**（铁律）：

1. `publish_cadence_hard_cap`：任何一天最多 1 条长视频 + 2 条 Shorts，任意两条发布时间间隔 ≥ 4 小时
2. `no_batch_publish`：禁止间隔 < 60 秒的连续发布（spam 指纹）
3. `cooling_off_window`：批量倾倒事件后 7 天停发 Shorts（让抑制信号衰减）
4. `theme_purity_100`：公开视频 100% 与"AI 荒诞 / Karen vs AI"主题相关；跑题内容一律不公开
5. `no_keywords_in_description`：简介/描述中禁止 "Keywords:" 段落与关键词堆砌
6. `eng_residue_zero`：标题含 `geminigen`/`PLAN`/时间戳/`E2E`/测试字样的视频禁止公开（D1 网关已部分覆盖，需扩展）
7. `script_similarity_cap`：长视频脚本两两相似度 < 20%（如转长视频）
8. `ai_disclosure_mandatory`：100% AI 内容视频勾选 Altered content 披露
9. `ypp_deadline_20270131`：2027-01-31 23:59 UTC 前必须提交 YPP 申请（按旧门槛审）；被驳回=90 天等待=窗口关闭

---

## 六、已识别的分歧 / 冲突点（议会必须裁决）

1. **"关闭所有自动上传脚本" vs 现有管线政策**：YPP 文档 Phase 0 要求立即停用自动发布、每条人工点发布；
   用户现行政策是"取消人工终审、QC→自动上传 private→排期翻 public"。**直接冲突，需用户拍板**，
   不可由议会或 agent 自行决定。
2. **删除 12 条崩塌视频 vs 设 private**：文档主张"彻底删除"（保留 1 条）；深复盘此前对重复视频用
   private 处理。删除是不可逆操作（Tier 3 级），需用户逐条批准。
3. **Shorts 定位**：文档判 Shorts 路径"物理上不存在"但保留其引流价值；深复盘仍在优化 Shorts 管线。
   若采纳转向，Shorts 管线的投入产出比需重估。
4. **主持人层阻塞**：整个 30 天方案唯一的硬门槛（A/B/C 决策），用户未决策前 Phase 1 无法启动。
   这是当前真正的关键路径。
5. **概率分歧**：文档自估 30 天 Tier 2 达标概率 25–40%；而频道当前分发为 0（连续 8 天全灭），
   基准情景要求"每条 3,000 观看"——从 6.5 到 3,000 是 460 倍跳跃。议会需对此做独立判断，
   不采信单方自估。
6. **"7 天停发" vs 现有排期**：private_queue 当前排期与"Day 2–8 完全停发"冲突，需先清空/暂停排期。

---

## 七、需用户拍板项（深复盘 4 项 + 本议题新增）

**深复盘遗留**：
1. 分发层系统性失效是否做频道级健康诊断（Ask Studio 问题包已备好，见 §4.1）
2. 分发恢复前是否暂停发布（LMArena 方案 E 即此选项）
3. Marvis 连续三天未回复复盘，是否调整协作机制
4. auto_pin 首评死状态是否授权排查修复

**本议题新增**：
5. **是否立项 30 天 YPP 作战**（接受"换引擎"战略转向，还是继续 Shorts 管线）
6. **主持人层决策 A/B/C**（真人出镜 / 真人配音 / AI 语音+严格约束）——唯一的硬门槛阻塞项
7. **Phase 0 清洗清单是否执行**：删除 4 条（3 工程残留 + 希特勒扑克）+ 12 条崩塌视频删到只剩 1 条
   + 27 条跑题设不公开（删除类操作需逐条明确批准）
8. **是否暂停自动发布管线**（与现行"取消人工终审"政策直接冲突，需用户亲定）

---


### 2026-10-10 08:10 来源核验（Parent 待办 #1 闭环）
- arena 会话 https://arena.ai/agent/01a1214b-d0ea-70f3-a719-5ccac10dbcdf 经浏览器实测**无法加载**
 （已登录 bat08738@gmail.com，非登录墙；页面持续报 "Something went wrong / We couldn't load this chat"，
  三次重试均失败；判定为会话已删除/过期/非本账号所有）。
- 改按议会指定的第二权威来源核验：用户 2026-10-10 00:07 上传的 897 行《KarenVsAI 深度诊断报告 +
  30 天 YPP 作战方案》（本地：workspace/user/files/KarenVsAI______30_YPP_____13_1li3.md）。
- 核验结论：**5/5 MATCH**——
  (a) 533订阅/73.7万总观看/缺467订阅+3960小时 ✅（L56, L17）；
  (b) "分发量崩塌 99.6%"、最近20条均播 6.5 ✅（L43, L41）；
  (c) "Shorts 路径彻底判死…这条路在物理上不存在"（3万倍/10万倍）✅（L336）；
  (d) 转向"真人吐槽 AI 荒诞视频"20-30分钟长视频、节目名 AI UNHINGED ✅（L395, L409）；
  (e) 2027-02-01 翻倍（4000→8000h）、30天Phase作战、25-40%概率 ✅（L23, L382）。
- 结论：议题摘要的实质断言全部有用户上传文档支撑；arena 会话原文不可考，
  但不影响决议的事实基础（决议所引用的数字/判断均出自该文档）。

---

## 八、Parent 待办（浏览器任务清单）

1. 用 browser task 打开 https://arena.ai/agent/01a1214b-d0ea-70f3-a719-5ccac10dbcdf，
   核对 §一 议题摘要与会话原文是否一致；不一致则以原文为准并通知用户。
2. 按 §4.1–4.3 顺序发射三脑任务（Ask Studio → LMArena Side-by-Side → AI Studio），
   每次携带前序结论。
3. 三脑返回后：提取同结论的常量 → 写入 criteria.json（备份）→ 回填本文件"共识清单"节；
   分歧点与 §七 拍板项一并报用户。
4. Ask Studio 那步若遇 Google 登录重定向：走 Secure Vault 自动重登，3 次失败跳过并注明。

---
*报告生成：2026-10-10 00:20 CST · subagent 紧急议会执行包 · arena 会话本体未读（登录墙）·
三脑未实际召开（待 parent 发射浏览器任务）· criteria.json 未动（v20)*

---

## 九、最终决议（2026-10-10 00:35 CST，三脑跑完）

### 三脑结论
- **Ask Studio（传感器）**：无 shadowban、无新增处罚；根因排序：批量连发（主）> 模板疲劳（次）> 话题混乱（轻）；3 条可测量规则（1-2条/24h、间隔8-12h绝不<6h；前3秒钩子唯一、stayed-to-watch>70%；12h留存复盘门）
- **LMArena 陪审团（GPT-5.2-high vs Claude-sonnet-5-high，Side-by-Side）**：未达成一致。GPT 选 C（工具评测，22%），Claude 选 A（AI UNHINGED，35%）；共识：D≤5%、E≤2% 判死，长视频是唯一活路（Shorts 零有效小时）
- **AI Studio（总工程师，免费档 Gemini 3.8 Flash）**：MUST 9 条 + NEVER 8 条（全部落在共识区）；A-vs-C 决策分叉：3 条选择标准 + 硬死线 2026-10-14 23:59 UTC；kill 线：A→2026-12-15 累计≥1000h，C→2026-12-08 累计≥1900h

### 已写入管线的共识常量（criteria.json v20→v21，备份 criteria.json.bak.council-20261010）
1. upload_spacing_hard：间隔≥6h（目标8-12h），24h≤2条Shorts
2. hook_uniqueness：前3秒100%不重复，stayed-to-watch>70%
3. retention_gate_12h：12h留存复盘后才发下一条
4. metadata_hygiene：禁Keywords段落/堆砌，标题≤60字符，AI披露100%
5. eng_residue_zero：工程残留0条公开
6. ypp_longform_only：长视频是唯一YPP路径

### 未达成共识 → 交用户拍板
- **A vs C**：喜剧节目（留住观众，需主持人层）vs 工具评测（高CPM，有品牌错配风险）；3 条选择标准见 AI Studio 分叉节；死线 2026-10-14 23:59 UTC
- 深复盘遗留：Marvis 失联机制、auto_pin 首评修复（§七.3/.4）
- YPP 文档新增：是否立项30天作战、Phase 0 清洗清单（删除类需逐条批准）、是否暂停自动发布管线（与现行政策冲突）

*决议生成：2026-10-10 00:35 CST · 三脑实质召开完成 · criteria v21*

### 2026-10-10 00:40 用户决策：Plan A
- 用户亲选 A（《AI UNHINGED》20-30分钟真人吐槽喜剧长视频）；Kill 线：2026-12-15 累计≥1000 有效观看小时，否则转 C
- 待定：主持人形态 A/B/C（真人出镜/真人配音/AI语音+约束）

### 2026-10-10 00:42 用户决策：主持人形态 = AI 语音+严格约束
- 4 条硬约束：脚本100%独立（相似度<20%）/ 固定主持人人格 / 原创编辑判断 / 真人手写本周观察独白30-60秒
- 音色：拟锁定 Karen（avocado_v2:Karen），全季不换
