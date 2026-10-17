
# 内容重塑（viralloop-repurpose）

## Purpose
把历史爆款翻新成新选题：同一世界观延续，但内容不重复（系列内同样受公式去重约束）。

## Inputs
- `video_id` 或 `topic`：二选一。若给 video_id，从清单里定位原片；若给话题，按关键词匹配最接近的爆款。

## Workflow
1. 读 `/home/hatch/data/sequel_candidates.json`，找到原片（标题/播放量/已建议的 sequel_concept 作参考，但不要照抄"加个 2"）。
2. 输出 3 个重塑角度：
   - **续集**：同一冲突升级（换设备或加码报应）；
   - **反转**：角色/结果反转（如这次 AI 设备先被 Karen 拆了再反杀）；
   - **跨界**：把该爆款的笑点机制嫁接到另一个宇宙（汽车宇宙/收银宇宙，见 `/home/hatch/data/perpetua/series.json`）。
3. 每个角度附：新钩子（一句话）+ 动词（tier_s 优先）。
4. 每个角度附去重检查提醒：90 天去重——确认设备/动词/钩子与近 90 天视频无 >60% 重叠。

## Output
- 原片：标题 + 播放量
- 3 个角度：类型 / 新钩子 / 动词(tier) / 去重提醒

## Rules
- 世界观连续 ≠ 内容重复：场景/AI 设备/笑点机制三者至少换其一。
- 去重是硬门槛：>60% 重叠打回，本 skill 只负责提醒，不代做去重判定。
- 重塑选题仍需走完整流程（Ask Studio ≥85 + QC + 人工终审），发布必须人类明确批准。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
