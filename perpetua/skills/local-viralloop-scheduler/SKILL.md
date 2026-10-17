
# 发帖排期（viralloop-scheduler）

## Purpose
把一周的选题按频道发布策略排进 7 天 × 3 档的时间表。频道档位（CST）：10:00 / 12:30 / 00:00。

## Inputs
- `topics`：选题列表，每条含标题/话题 + 分数（post-score 的分数；无分数先用 viralloop-post-score 打）。

## Workflow
1. 按分数降序排选题。
2. 10:00 档（赌高分档）：只放全周最高分的选题；该档位候选 <70 分→宁可空着，不填。
3. 12:30 和 00:00 档：按分数依次填其余选题。
4. 周五/周一加权：数据上周五/周一最易爆，把次高分优先排这两天。
5. 输出 7 天表；空档位明确标"空"。

## Output
Markdown 表格：日期（周几）| 10:00 | 12:30 | 00:00，每格填选题标题（+分数），空档写"— 空 —"。
附一行说明：10:00 档空缺原因（如"本周无 ≥70 分选题"）。

## Rules
- 10:00 档 <70 分宁可空着，不降低标准凑数。
- 本 skill 只出排期表，不执行发布；每条视频发布前仍需走 Ask Studio ≥85 + QC + 人工终审，发布必须人类明确批准。
- 时区统一用 CST（Asia/Shanghai）。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
