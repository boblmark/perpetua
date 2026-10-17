
# 爆款钩子（viralloop-viral-hooks）

## Purpose
为一条 Shorts 生成 10 个 ranked 的前 3 秒钩子（对应视频模板 Block C：0–2 秒冷碰撞开场）。频道数据：平均观看仅 7–20 秒，前 3 秒定生死。

## Inputs
- `topic`：话题描述；或 `device`：指定的 AI 设备（二选一必填）。

## Workflow
1. 读 `/home/hatch/data/perpetua/karma_verbs.json`。
2. 生成 10 个钩子，按预期效果排序。每条钩子遵守：
   - 第 1 帧冲突已在进行中（Karen 已经在吼，或设备已经反击），零铺垫；
   - 感官钩子优先于叙事：视觉反差/动作突变；
   - 配 ≤6 个词的大字幕（全大写，如 `AI REFUSED HER EXPIRED COUPON`）；
   - 用 tier_s 动词（TRAPPED/SLAPPED/SOAKED/TOWED…）优先，tier_b 次之，banned 词禁用。
3. 每条标注：所用动词 + tier + 一句话"好奇心缺口"（观众会好奇什么，如"她怎么被困住的？"）。

## Output
Ranked 列表（1–10），每条格式：
`#n [动词·tier_s] 钩子描述 / 屏幕大字：XXX / 好奇心缺口：一句话`

## Rules
- 前 3 名必须用 tier_s 动词。
- 钩子必须是具体可拍的画面，不写"更刺激的""更有趣的"这类空话。
- 不碰 banned 词；疑问句式钩子降级（数据不支持）。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
