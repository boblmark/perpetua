
# 文案撰写（viralloop-copywriter）

## Purpose
为一条 Shorts 写全套英文文案：标题、描述、置顶评论。全部走频道爆款公式并通过纯度自检。

## Inputs
- `topic`：话题/钩子描述（中文可）。
- 可选 `device`：指定的 AI 设备；不给则按话题挑一个日常自动化设备。

## Workflow
1. 读 `/home/hatch/data/perpetua/karma_verbs.json` 选动词（tier_s 优先）。
2. 写 3 个标题，严格走公式：`[emoji] Karen + 冲突动作 + 即时报应 + [emoji]`，陈述句，1–2 个话题标签（如 #instantkarma）。
3. 对每个标题做纯度自检表：英文 ✓ / 含 Karen 或 AI ✓ / 无 banned 词 ✓ / 非疑问句 ✓。任一项不过→重写该标题。
4. 写 1 段描述：1 句场景 + 3–4 个精准标签（参考爆款词 viral/instant/karma/hoa/cam）。
5. 写 1 条置顶评论：英文、向观众提问以激发评论（标题禁疑问句，但置顶评论可以用问句破 0 评）。

## Output
- 3 个标题 + 每个标题的 4 项自检结果（✓/✗）
- 1 段描述（含标签）
- 1 条置顶评论
- 自检不过的标题必须重写后呈现，不展示废案。

## Rules
- 标题纯度是硬规则：英文、必须含 Karen 或 AI、中文/偏题直接拒。
- banned 词（DESTROYED/ANNIHILATED/OBLITERATED/DEMOLISHED）出现在标题里=上传门禁直接拒，绝不输出。
- 标题用陈述句，不用疑问句（数据：疑问句标题无效果）。
- 本 skill 只产出文案，不触发发布；发布必须人类明确批准。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
