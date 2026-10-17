
# 内容指导（viralloop-content-guide）

## Purpose
判断一个趋势/话题是否适合 @karenvsai 频道做，并给出具体的内容角度。频道公式：Karen vs AI 设备的 slapstick 即时报应喜剧。

## Inputs
- `topic`：趋势/话题描述（中文或英文均可，输出用英文标题、中文解释）。

## Workflow
1. 读 `/home/hatch/data/perpetua/karma_verbs.json`（动词档位）和 `/home/hatch/data/jev/criteria.json` 的 `score_criteria`。
2. 适配度评估（0–100）：话题能否自然长出"Karen vs 某 AI 设备"的冲突？能→高分；硬蹭→低分并直说。
3. 推荐 2–3 个角度：每个角度指定 AI 设备（必须是日常自动化摩擦点：自助结账机、智能门铃、停车咪表、加油泵…）+ tier_s/tier_b 动词 + 一句话场景。
4. 避坑点：对照禁忌清单逐项检查。

## Output
- **适配度**：分数 + 一句话理由
- **推荐角度**（2–3 个）：设备 / 动词（标注 tier）/ 场景一句话
- **避坑点**：如"别用疑问句标题""别碰 banned 词 DESTROYED""AI 设备别选太抽象的"
- 适配度 <50 直接建议放弃，别硬做。

## Rules
- AI 设备必须是具体、日常的自动化设备，拒绝抽象概念。
- 动词优先 tier_s；banned 词（DESTROYED/ANNIHILATED/OBLITERATED/DEMOLISHED）永不推荐。
- 不承诺发布排期；是否立项由选题流程决定。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
