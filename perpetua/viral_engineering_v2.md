# 爆款病毒视频工程化 · 第二轮深度研究

> 日期：2026-10-07
> 第一轮：`/home/hatch/data/perpetua/viral_variables_research.md`（13 个变量，VVSA 60-65% 权重模型）
> 本轮重点：别人是怎么把爆款"工程化"的——具体可量化的指标、自动化流程、A/B 测试框架，以及**模型能力边界与后处理方案**（用户追加方向）。

---

## 一、第一轮回顾（已落地，不重复）

- 10 个发布前门禁：错峰、标题主语、emoji 开头、元数据、纯度、去重、人工终审、动词白名单等
- 6 个播放中门禁：无缝循环验证、烧录字幕、安全区、高潮时机、动词分级、音频规范
- 核心认知转变：算法 90%+ 权重在"播放中"（VVSA 60-65%、APV 25%、循环率 r=0.82），元数据 <1%

---

## 二、本轮新发现：按可落地性排序

### P0（本周可做，工作量小）

#### 2.1 首帧静音测试（Mute First-Frame Test）
- **是什么**：把视频静音，只看第一帧——如果第一帧讲不清概念，钩子就是坏的。先修画面，再修文字。
- **数据支撑**：5 个顶级创作者共识原则 C6（Jenny Hoyos 10M/条均值、Logan Smith、heyDominik、MrBeast、Colin and Samir 交叉验证，3+ 来源才算共识）。
  来源：https://github.com/s3yed/appie-kit/blob/HEAD/skills/misc/viral-shorts-course/SKILL.md
- **能否做成门禁**：✅ 可。用 OpenCV 抽首帧 → 规则检查：画面中央 1/3 是否有明确主体（人物/动作），首帧亮度/对比度是否达标。进 `pre_upload_qc.py` 加一个 check。
- **工作量**：0.5 天。

#### 2.2 可读性 ≤5 年级硬过滤（Readability Gate）
- **是什么**：标题+描述的可读性分数必须 ≤5 年级（Flesch-Kincaid）。"business/profit/strategy" 这类词瞬间把分数推到 8 年级。
- **数据支撑**：Jenny Hoyos 爬了数千条 Shorts 转录文本，最爆的全部 ≤5 年级；MrBeast 脚本是 1 年级。
  来源：同上 S3YED 共识库 A2。
- **能否做成门禁**：✅ 可。`textstat` 库一行代码算 Flesch-Kincaid，进 `youtube_upload` 门禁（标题+描述）。
- **工作量**：0.5 天。**我们完全没想到的维度**——之前只查了"有没有 Karen"，没查"观众能不能 1 秒读懂"。

#### 2.3 结尾零拖尾（Abrupt End）
- **是什么**：高潮结束后立即切断，不许有 outro、渐黑、"下期见"。任何高潮后的内容都是 retention 坟场。
- **数据支撑**：3+ 创作者共识 C4（Jenny Hoyos、MrBeast："Video endings must always be abrupt to protect retention"）。
- **能否做成门禁**：✅ 可。已在高潮时机门禁里部分覆盖（7.5s 后最多 2s），再加一条：最后 1 秒音频能量骤降检测（无拖尾音乐）。
- **工作量**：0.5 天（复用音频能量曲线逻辑）。

#### 2.4 分享诱因设计（Screenshot Test）
- **是什么**：Jenny Hoyos 的未完全证实但强烈的直觉——**分享率可能比完播率更重要**。一条 20% 分享/播放比的视频配 92% 划走率照样爆了。设计问题："观众会截图发给朋友吗？"
- **数据支撑**：单源（Jenny Hoyos，标注为 hunch），但 valabilid 的实证显示爆款 hooks 分布：好奇心缺口 5、提问 3、具体承诺 1、惊喜 1（22M–119M 播放样本）。
  来源：S3YED A1；https://github.com/valebid/-hooksignals-site/blob/HEAD/docs/phase2-validation-report.md
- **能否做成门禁**：⚠️ 半可。prompt 里加"截图时刻"要求（一个值得暂停截图的画面/文字）；量化分享率需要发布后数据回流。
- **工作量**：1 天（prompt 模板更新 + 分享率追踪进 daily_evolution）。

### P1（下周，工作量中等）

#### 2.5 速度特征（Velocity Features）——打分模型升级
- **是什么**：别只看绝对播放，看**速度**：`likes_per_day`、`views_growth_rate`、`views_acceleration`。"Cumulative views lie; daily velocity tells you whether momentum is building."
- **数据支撑**：music-virality 项目（41-43 个工程特征，XGBoost，PR-AUC 选型），6 大特征家族：互动比率、速度、频道权威、内容格式、发布时间信号、标题信号、动量/轨迹。
  来源：https://github.com/bhattacharjeeshayan860-netizen/music-virality/blob/HEAD/README.md
- **能否做成门禁**：✅ 可。v2 模型下一版加入：发布后 1h/6h/24h 的速度特征，用于"追投/补发/下线"决策（之前 P2-5 已规划）。
- **工作量**：2 天（含数据管道）。

#### 2.6 12 维可审计打分（替代黑盒）
- **是什么**：viral-clip-agent 的做法——12 个维度各 0-10 打分（都是"判断"），组合是**纯算术**（加权和+结构惩罚）。分数可审计、可复现、反馈循环调权重不用动 prompt。
- **数据支撑**：https://github.com/kksingh000/viral-clip-agent/blob/HEAD/docs/architecture.md —— "if the answer is computable, compute it"（能算的就别让模型猜）。
- **能否做成门禁**：✅ 可。把我们 v2 的线性模型重构成"维度打分 + 算术组合"，每个维度可解释。Ask Studio/LLM 只负责维度判断，不负责最终分数。
- **工作量**：3 天。这是 v3 模型的方向。

#### 2.7 YouTube 原生 A/B 测试（2027 上线，提前布局）
- **是什么**：YouTube 2026-09 官宣：2027 年创作者可上传 **3 个不同剪辑版本**的 Shorts，平台分流测试，按 watch time 选优。Test & Compare 已有 4000 万+次标题/缩略图实验。
- **数据支撑**：TechCrunch 2026-09-23；memeburn 详解。
  来源：https://techcrunch.com/2026/09/23/youtube-adds-new-creator-tools-like-video-a-b-testing-dynamic-thumbnails-and-live-dubbing/
- **能否做成门禁**：⏳ 等平台上线。但现在就可以准备：每次生成 2-3 个版本（见 3.2），手工分时段发测 watch time。
- **工作量**：现在 0（等 2027）；手工版 1 天。

#### 2.8 Niche Profile（垂直档案）
- **是什么**：Verticals v3 的核心创新——流水线每个阶段都读一个 niche profile（脚本语气、视觉风格、字幕美学、音乐情绪、缩略图策略）。换 niche = 换 profile，不是换 prompt。
- **数据支撑**：https://github.com/georgedobreff/youtube-shorts-pipeline —— 15 个 niche 开箱即用，~$0.11/条。
- **能否做成门禁**：✅ 可。把我们散在各处的 Karen vs AI 约定收敛成一个 `niche_profile.json`（人设、口头禅、视觉规范、音频规范、禁忌），所有生成/校验都读它。多租户时每个租户一份。
- **工作量**：2 天。**我们部分想到但没系统化**——现在规则散在 5-6 个文件里。

### P2（本月，战略级）

#### 2.9 频道信任分运营
- **是什么**：永不删重发（已执行 ✅）、保持发布节奏稳定、避免 spam 信号。算法给频道打长期信任分。
- **能否做成门禁**：✅ 已有 bypass_audit 部分覆盖。再加：删除/私享操作需要二次确认并记审计。
- **工作量**：1 天。

#### 2.10 But/Therefore 张力检查
- **是什么**：共识 C3——"And/Then 是被动的，But/Therefore 才是张力"。剧本里没有"but/however"大概率无聊。
- **能否做成门禁**：✅ 可。prompt 生成后检查：3 段 beats 里是否有转折词（but/however/突然/却）。没有 → 打回重写 prompt。
- **工作量**：0.5 天。**完全没想到的维度**——我们检查了主语、动词，没检查叙事张力结构。

---

## 三、模型能力边界与后处理方案（用户追加专题）

### 3.1 核心结论： prompt 能解决的 vs 必须后处理的

综合多个来源（fmssylvester 的实测、mersivmedia 的一致性管线、Medium 黑盒分析、Wan 3.0 工作流、LinkedIn OREoS 工厂），画出边界线：

| 要求 | Prompt 可解？ | 必须后处理？ | 依据 |
|---|---|---|---|
| 镜头运动、构图、氛围 | ✅ | | "Camera movement is mathematically easier for the AI to compute than organic human anatomy" — fmssylvester |
| 简单动作（走、挥手、转头） | ✅ | | 2-3 秒短片段成功率高 |
| 复杂多步动作（系鞋带→起身→跳跃） | ❌ | ✅ 切分+拼接 | "AI will melt. It cannot process sequential physical logic yet" |
| 精确手部动作、微表情 | ❌ | ✅ 避开或重拍 | 硬伤，2026 年仍无解 |
| 文字渲染（字幕、招牌） | ❌ | ✅ 外部烧录 | "notoriously bad at text rendering" |
| 首尾帧一致（无缝循环） | ❌ | ✅ OpenCV 验证+打回 | 时间连贯性 3-6 秒后崩 |
| 精确到 0.5s 的时机 | ❌ | ✅ 音频能量分析验证 | "A single text prompt cannot guarantee Act 2 starts at second 3.2" — OREoS |
| 角色一致性（多镜头） | ⚠️ 部分 | ✅ 每镜头 re-anchor | mersivmedia："re-anchor every shot"，validator 禁止链式传递 |
| 音频 Foley 打点 | ❌ | ✅ 后期混音 | 模型给的是整体氛围 |

**黄金法则**（mersivmedia）：
> "Structural constraints beat prompt phrasing. When a property keeps failing, stop rewriting the prompt and change what the system can express."
> （结构约束胜过 prompt 措辞。当一个属性反复失败，别再改 prompt，改系统能表达什么。）
> "Make the failure **impossible to express** rather than unlikely to occur."
> （让失败**无法表达**，而不是不太可能发生。）

这正是我们门禁哲学的学术背书：**prompt 负责"尽量讲清楚"，门禁负责"让失败无法通过"**。

### 3.2 多候选生成 + 择优：学术背书 + 落地建议

**学术方案**（arxiv 3R 模型）：
1. Retrieval：意图编码 + 检索相关知识
2. Refinement：LLM 生成 N 个 refined prompts
3. Generation：N 个候选视频并行生成
4. Ranking：29 个加权 VQA 问题打分，取最高
5. Enhancement：超分/平滑后处理
- 来源：https://arxiv.org/pdf/2603.01509

**我们的落地版本**（建议）：
- 每次生成 3 个候选（不是 29 个 VQA，太重）
- 用现有 6 个播放中门禁做自动打分：循环分 + 时长 + 分辨率 + 首帧测试 + 音频能量
- 取最高分进上传流程，其余归档
- 成本：3x 生成费用；收益：把"碰运气"变成"掷 3 次骰子取最大"
- **工作量**：2 天（改 mcp-media-job-processor 并行生成 + 评分择优）

**注意**：Medium 黑盒分析警告 "Iteration doesn't refine — it rerolls the dice"（迭代不优化，只是重掷骰子）。所以**不要**"生成→微调 prompt→再生成"循环，要"一次 N 个并行→选最优"。我们的 loop_check 打回重生成（最多 2 次）符合这个逻辑，但建议改成 3 并行而非 2 串行。

### 3.3 生成后自动修复流水线：别人都在做

| 项目 | 做法 | 来源 |
|---|---|---|
| etch181/skill quality-gates | 5 阶段渲染后验证：ffprobe（分辨率/编码/fps/时长/声道）→ 抽 5 帧查亮度（黑帧/白闪）→ volumedetect（削波/过静）→ SRT 时间轴检查 → 交付规格对比。CI 集成，returncode 决定上传。 | https://github.com/etch181/skill/blob/HEAD/quality-gates/SKILL.md |
| winaid/youtube | Gemini QA 管线 + `applyQualityFixes()` 自动修复；QA <30 硬拦截不让进 Kling 生成。 | https://github.com/winaid/youtube/commit/66689ba117ba8d84f513c13b76f9ec95075b7d1f |
| hkk009008 content pipeline | 质量门控后处理：光流分析 → 抖动自动触发 RIFE 补帧；口型同步路由；色彩分级映射情绪。ComfyUI 动态节点注入。 | pipeline skill 文档 |
| isaiahdupree ai-video-platform | 每 clip 生成后 FFmpeg 后处理：1.4x 加速 + -25dB 环境噪 + 底部 8% 裁掉烧录字幕区。有明确验收标准。 | https://github.com/isaiahdupree/ai-video-platform/blob/HEAD/docs/video-research/PRD-90-PERCENT-WIN-RATE-PIPELINE.md |
| pmb2/hermes-starter | QA 管线：词结巴检测、n-gram 重复、jiwer WER 对脚本、静音间隙 >1.5s/削波。exit 0/1。 | https://github.com/pmb2/hermes-starter/blob/HEAD/skills/creative/ai-video-pipeline/SKILL.md |

**结论**：我们的 `pre_upload_qc.py` 方向是对的，行业都在做。建议补充 etch181 的 5 阶段里的**黑帧检测**和**音频削波检测**（我们还没有）。

### 3.4 ComfyUI 质检节点：结构验证，非语义保证

- ComfyUI-Minimax-H3-Prompt-Engineer：prompt 工程节点自带质量控制（task schema、镜头时长、引用边界、配乐配对验证；失败修一次）。
  来源：https://github.com/colorAi/ComfyUI-Minimax-H3-Prompt-Engineer
- 关键提醒（basil-hayden 项目）："This is structural validation, not a semantic guarantee. A VLM can misidentify visual details."（这是结构验证，不是语义保证。）
- **对我们的意义**：门禁分两层——结构层（时长/分辨率/循环/字幕，代码可验）+ 语义层（笑点/张力，LLM 判断）。不要指望一层解决所有问题。

### 3.5 时间连贯性边界：3-6 秒

- Medium 黑盒分析："Temporal coherence breaks down after 3–6 seconds, leading to morphing or flicker."
- Wan 3.0 工作流："A four-second generation should not be expected to tell a ten-second story." / "Shorter sequences are usually more reliable than shorter prompts."
- **对我们的意义**：9-11 秒一镜到底是高风险结构。长期方向：2-3 个 3-4 秒片段拼接（每段独立验证循环/质量），用硬切转场。这是 P3 级别的架构升级，先记录。

### 3.6 本节落地清单

| # | 动作 | 工作量 | 优先级 |
|---|---|---|---|
| 1 | pre_upload_qc 加黑帧检测 + 音频削波检测（抄 etch181） | 0.5 天 | P0 |
| 2 | 生成策略改 3 并行择优（替代 2 次串行重生成） | 2 天 | P1 |
| 3 | 门禁分层文档化：结构层（代码）vs 语义层（LLM） | 0.5 天 | P1 |
| 4 | 调研 3-4s 分段拼接架构（长期） | 调研 1 天 | P3 |

---

## 四、完全没想到的维度（汇总）

1. **可读性 ≤5 年级**（2.2）——标题的"秒懂度"从没量化过
2. **But/Therefore 张力结构**（2.10）——检查了主语动词，没检查叙事转折
3. **Niche Profile 系统化**（2.8）——规则散在 6 个文件，没收敛成单一档案
4. **分享率可能 > 完播率**（2.4）——一直在优化留存，没设计分享诱因
5. **黑帧/音频削波检测**（3.6-1）——质检缺了最基础的"坏帧"检查
6. **3 并行择优 > 2 串行重试**（3.2）——"重掷骰子"应该并行掷，不该串行碰运气

---

## 五、建议执行顺序

**本周 P0**（共约 2 天）：
1. 首帧静音测试进 pre_upload_qc（0.5 天）
2. 可读性门禁进 youtube_upload（0.5 天）
3. 黑帧+削波检测进 pre_upload_qc（0.5 天）
4. 结尾拖尾音频检测（0.5 天）

**下周 P1**（共约 7 天）：
5. 3 并行择优生成（2 天）
6. Niche Profile 收敛（2 天）
7. 速度特征进 v2 模型（2 天）
8. 分享率追踪（1 天）

**本月 P2**：
9. 12 维可审计打分 v3 模型（3 天）
10. But/Therefore 张力检查（0.5 天）
11. 分段拼接架构调研（1 天）
