# 多版本并行生成流程 · 设计文档

> 日期：2026-10-07
> 状态：**设计稿，待用户批准后实现**
> 依据：`viral_engineering_v2.md` §3.2（arxiv 3R 模型 + "迭代不优化，只是重掷骰子"）
> 目标：YouTube 2027 年原生 3 版本 A/B 测试上线前，先把"一次 N 个并行→选最优"练起来。

---

## 1. 为什么改

现状（mcp-media-job-processor）：
```
选题 → 1 个 prompt → 生成 → loop_check 不过 → 同一 prompt 重生成（最多 2 次串行）
```

问题：
- **串行重试 = 对同一个骰子连掷 3 次**，每次期望值相同，不提高上限。
- 同一 prompt 的失败模式高度相关（loop 不过往往是 prompt 结构问题，重生成大概率同样不过）。
- Medium 黑盒分析："Iteration doesn't refine — it rerolls the dice"（迭代不优化，只是重掷骰子）。

新方案：
```
选题 → 3 个差异化 prompt 变体 → 3 个并行生成 → 各自质检打分 → 取最高分进上传
```

- **并行 = 同时掷 3 个不同的骰子，取最大值**，期望值严格高于单次。
- 3 个变体是**不同的钩子/结构**（不是微调），覆盖不同的爆款路径。

---

## 2. 流程图（文字版）

```
┌─────────────────────────────────────────────────────────────┐
│ ① 选题输入（Marvis job：topic + 候选标题）                    │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ ② 生成 3 个 prompt 变体                                      │
│    build_variant_prompts(topic, title, karma_verb_pool)      │
│    → V1 / V2 / V3（见 §3 差异化规则）                        │
│    固定不变：Block A（格式锁）、B（人设）、G（音频规则）       │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ 3 个并行生成                                              │
│    media.generate_video(V1) ─┐                               │
│    media.generate_video(V2) ─┼─→ 并行，可同时在跑             │
│    media.generate_video(V3) ─┘                               │
│    输出：/home/hatch/data/<job_id>_v1.mp4 等                 │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ 每个版本独立后处理 + 打分                                  │
│    postprocess_video.py（loop 验证 + 字幕烧录）               │
│    → pre_upload_qc 打分（见 §4 评分规则）                     │
│    → score_v1 / score_v2 / score_v3（0–100）                 │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 择优                                                      │
│    winner = 最高分版本                                       │
│    - winner → 走现有上传门禁（youtube_upload 硬门禁）→        │
│      inbox pending_pickup（Marvis 取货）                      │
│    - 落选 2 个 → 归档 /home/hatch/data/archive/              │
│      附 score_report.json（分数 + 落选原因）                  │
│    - 若 3 个全被硬门禁 disqualify → needs_regen，整批重来     │
│      （最多 1 轮；再不过转人工）                             │
└─────────────────────────────────────────────────────────────┘
```

**关键约束**：
- 日上传上限不变：**2 条/天**（P0 政策）。多版本只改变"每条上传视频的生成方式"，不增加上传量。
- 热点 URGENT 通道：4 小时时限内若 3 并行来不及，允许降级为单版本直发（需在 job payload 标注 `urgent: true`）。

---

## 3. Prompt 变体差异化规则

### 3.1 变体维度（只动变量部分）

| Block | V1 | V2 | V3 | 固定？ |
|---|---|---|---|---|
| A 格式锁 | 相同 | 相同 | 相同 | ✅ 固定（verbatim） |
| B 人设 | 相同 | 相同 | 相同 | ✅ 固定（Karen + AI 设备 + 可选路人） |
| C 0–2s 钩子 | **Karen 已在怒吼**（mid-rant 入场） | **机器已反击**（先给结果，倒叙结构） | **路人手机视角**（POV 入场，临场感） | ❌ 差异化 |
| D 2–6.5s 升级 | 口头升级（音量/指责升级） | 物理升级（拍打/踢机器） | 群众升级（路人围观起哄） | ❌ 差异化 |
| E 6.5–7.5s 高潮 | S-tier 动词 A（如 TRAPPED） | S-tier 动词 B（如 SOAKED） | S-tier 动词 C（如 LOCKED） | ❌ 差异化 |
| F 7.5–9s 循环收尾 | Karen 定格愤怒脸 | 机器屏幕淡定文字 | 路人哄笑定格 | ❌ 差异化 |
| G 音频规则 | 相同 | 相同 | 相同 | ✅ 固定 |

### 3.2 变体生成规则（硬性）

1. **3 个高潮动词必须互不相同**，且全部来自 `karma_verbs.json` 的 S-tier（优先）或 B-tier；banned 词（DESTROYED 等）禁用。
2. **3 个钩子入场方式必须互不相同**（mid-rant / aftermath-first / POV 三选三，不重复）。
3. **同一选题的 3 个变体标题也差异化**（上传时只用 winner 的标题，但归档时 3 个标题都保留，供将来 A/B 用）。
4. **But/Therefore 张力检查**（v2 §2.10）：每个变体的 D 段必须含转折（but/however/突然/却），没有 → 该变体作废重出。
5. **去重门禁前置**：3 个变体的核心桥段与 90 天历史重叠 >60% 的变体直接剔除（不等生成完再查）。

### 3.3 变体生成方式

`viral_prompt.py` 新增 `build_variant_prompts(topic, title, karma_verbs)`：
- 输入：选题 topic、候选标题、动词池（S-tier 优先）
- 输出：`[{"variant": "v1", "prompt": "...", "hook_type": "mid-rant", "karma_verb": "TRAPPED", "title": "..."}, ...]`（3 个）
- 逻辑：调 `build_viral_prompt()` 3 次，每次传入不同的 hook/escalation/climax 参数组合。

---

## 4. 评分择优规则

### 4.1 硬淘汰（disqualify，不参与评分）

以下任一出现，该版本直接出局（不是低分，是没资格参选）：
- `blackframe` = fail（有黑帧/白闪）
- `resolution` = fail 且自动裁剪不可行
- `duration` < 9.0s（无法修复）
- `probe` = fail（文件损坏）

### 4.2 评分维度与权重（总分 0–100）

基于 `pre_upload_qc.py` 现有 10 项检查的输出：

| 维度 | 来源 check | 计分方式 | 权重 | 依据 |
|---|---|---|---|---|
| 循环质量 | loop（similarity 原始值） | similarity×100（如 0.87→87） | 35 | 循环率 r=0.82，最强信号 |
| 首帧钩子 | firstframe | pass=100 / warn=50 / fail=0 | 20 | 第一帧决定 3 秒生死 |
| 高潮时机 | climax | pass=100 / warn=50 | 15 | 6.5–7.5s 窗口 |
| 安全区 | safezone | pass=100 / warn=50 | 10 | 文字不被 UI 遮挡 |
| 结尾干脆 | tailcut | pass=100 / warn=50 | 10 | 无拖尾保留存 |
| 音频质量 | audioclip | pass=100 / warn=50 | 5 | 无削波 |
| 时长甜点 | duration | 10s=100 / 9或11s=80 / 其余按线性 | 5 | 9–11s 达标区间 |

- `subtitles` 不计分（whisper 缺失时合规跳过，不应惩罚）。
- 总分 = Σ(维度分 × 权重) / 100。
- **平分决胜**：总分相同 → 循环 similarity 高者胜 → 再相同 → 首帧分高者胜。

### 4.3 评分函数

新增 `score_video.py`（或进 `pre_upload_qc.py` 加 `qc_score()`）：
- 输入：`run_qc()` 的 result dict（含 checks 列表和 loop similarity）
- 输出：`{"score": 87.5, "breakdown": {...}, "disqualified": false, "dq_reason": null}`
- 纯计算，无副作用，可单元测试。

---

## 5. 落选版本归档

路径：`/home/hatch/data/archive/<job_id>/`
```
<job_id>/
  v1.mp4 / v2.mp4 / v3.mp4        # 3 个版本原片（含字幕烧录版）
  score_report.json                # 3 个版本的分数明细 + winner 标注 + 落选原因
  prompts.json                     # 3 个 prompt 变体全文（供复盘/复用）
```

`score_report.json` 格式：
```json
{
  "job_id": "...",
  "topic": "...",
  "winner": "v2",
  "winner_score": 87.5,
  "versions": [
    {"variant": "v1", "score": 72.0, "disqualified": false,
     "lose_reason": "首帧 warn（-10），高潮时机 warn（-7.5）",
     "file": "v1.mp4", "title": "...", "karma_verb": "TRAPPED"},
    ...
  ],
  "scored_at": "ISO时间"
}
```

**归档的二次利用**：
- YouTube 2027 原生 A/B 上线后，归档的 v1/v3 可直接作为对照版本上传测试。
- 落选版本若 winner 发布后 48h 播放 <50，可考虑换标题发落选版（需过全部上传门禁）。

---

## 6. 成本估算

| 方案 | 每次选题生成次数 | 说明 |
|---|---|---|
| 现状 | 1 + 最多 2 次串行重生成 | 平均约 1.3 次（loop 通过率约 70% 估算） |
| 新方案 | **固定 3 次** | 并行，无串行重试 |

- **增量成本**：约 2.3 倍生成费用（3 / 1.3）。
- **日产量 2 条** → 每天 6 次生成（现状约 2.6 次）。
- ⚠️ **media.generate_video 的单次费用未知**，需用户确认是否接受 2.3x 成本。如费用敏感，可降级为 **2 并行**（期望值仍高于单次，成本 1.5x）。

---

## 7. 需要改的文件（精确到函数）

| # | 文件 | 改动 | 函数/位置 |
|---|---|---|---|
| 1 | `/home/hatch/data/perpetua/viral_prompt.py` | 新增变体生成器 | 新增 `build_variant_prompts(topic, title, karma_verbs)`；复用现有 `build_viral_prompt()` |
| 2 | `/home/hatch/data/perpetua/score_video.py` | **新建**评分模块 | `qc_score(qc_result) -> dict`；`rank_versions(results) -> ranked list` |
| 3 | `/home/hatch/data/perpetua/multi_version.py` | **新建**编排器 | `run_multi_version(job_id, topic, title, generate_fn)`：变体生成→并行生成→后处理→打分→择优→归档 |
| 4 | `/home/hatch/data/perpetua/postprocess_video.py` | 加纯打分模式 | `run_postprocess()` 加 `score_only=True` 参数（跳过"打回重生成"语义，只返回质检结果供打分） |
| 5 | mcp-media-job-processor 定时任务 body | 替换生成逻辑 | 把"生成→loop 不过→同 prompt 重生成 2 次"整段替换为"调 multi_version.py 跑 3 并行择优" |
| 6 | （可选）`/home/hatch/data/perpetua/pre_upload_qc.py` | 评分函数放这里也行 | `run_qc()` 后加 `qc_score(result)`（若不新建 score_video.py） |

**不改的**：
- `youtube_upload` 硬门禁（winner 仍要过全部 10+6 门禁）。
- `bypass_audit.py`（事后审计不变）。
- inbox / webhook 取货流程（winner 的文件名写入 `pending_pickup`，与现在一致）。

---

## 8. 并行生成的实现方式（待定）

`media.generate_video` 是 agent 侧工具调用，不是 shell 命令。三种实现选项：

- **A. Worker 内串行调用**：job processor 的 worker 一次调 3 次 `media.generate_video`。最简单，但"并行"是假的（排队执行），省不了时间，只省 prompt 差异化。
- **B. 派 3 个 subagent 并行生成**：每个 subagent 调一次 `media.generate_video`。真并行，但 subagent 调度开销大。
- **C. 若 media 后端支持批量**：一次请求带 3 个 prompt。需确认 media 工具是否支持。

**建议**：先按 A 实现（差异化 prompt 的收益已拿到 80%），B/C 待验证 media 能力后再定。

---

## 9. 待用户决策

1. **成本**：接受 3x（约 2.3x 实际增量）生成费用吗？还是降级 2 并行？
2. **并行方式**：A（worker 内串行调 3 次，简单）还是 B（3 subagent 真并行）？
3. **URGENT 降级**：热点 4 小时通道是否允许单版本直发？
4. **归档保留期**：落选版本保留多久？（建议 90 天，与去重窗口对齐，到期自动清理）
