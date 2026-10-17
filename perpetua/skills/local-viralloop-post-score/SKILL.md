
# 贴文评分（viralloop-post-score）

## Purpose
用频道自己的数据规则给标题（+可选脚本）打分，判断是否达到发布门槛，给出具体改进建议。

## Inputs
- `title`：待评标题（必填）。
- `script`（可选）：脚本/钩子描述，用于评估"标题与内容一致性"。

## Workflow
1. 读 `/home/hatch/data/jev/criteria.json`（v11，gate_model=v2，`gate_threshold`=58）和 `/home/hatch/data/perpetua/karma_verbs.json`。
2. 先查 banned 词（DESTROYED/ANNIHILATED/OBLITERATED/DEMOLISHED）：命中→直接 0 分，判不过。
3. 逐项打分（对照 `score_criteria`）：
- 含 emoji 且放开头：+
- 含 Karen：+（优先于 AI；AI 仅系列有效，普通提及扣分）
- 动词 tier_s：+ / tier_b：小+
- 含爆款关键词（viral/instant/karma/gets/caught/cam/hoa）：+
- 疑问句：−（数据：疑问句无效果）
- 有剧集编号式数字（Episode 3）：−；具象故事数字（15 DOGS）：+
- 有 script 时：标题承诺与内容是否一致，不一致 −（标题党杀死完播率）
4. 汇总：总分 / 是否 ≥58 / 一句话改进建议（只给最关键的 1–2 条）。

## Output
- **分数**：X / 100（或按 criteria 实际量纲）
- **结论**：过线 / 不过线
- **改进建议**：1–2 条可执行的（如"把 emoji 挪到开头""动词换成 tier_s 的 SOAKED"）

## Rules
- banned 词直接 0 分，无商量（上传门禁也会拒）。
- jev 模型分仅作参考，不参与门禁判定；门禁以本规则为准。
- 本 skill 只打分，不决定发布；58 分是选题门槛，不是发布许可。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
