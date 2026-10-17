# 品牌简报（viralloop-brand-briefing）

## Purpose
为 @karenvsai（"Mark Bobl | Karen vs AI"，英文 AI 主题 Shorts 频道）生成一份结构化品牌简报，供内容团队 / 外部协作者快速对齐。所有结论来自频道自身 496 条真实视频数据，不是外部推断。

## Inputs
无。直接读数据文件：
- `/home/hatch/data/jev/criteria.json`（v11，gate_model=v2，阈值 58）
- `/home/hatch/data/perpetua/karma_verbs.json`
- `/home/hatch/data/perpetua/viral_prompt_template.md`
- `/home/hatch/data/sequel_candidates.json`（取 Top3 举例）

## Workflow
1. 读 criteria.json：取 `title_formula`、`score_criteria`、`key_findings`、`hard_constraints`。
2. 读 karma_verbs.json：取 tier_s / tier_b / banned 三档。
3. 读 sequel_candidates.json 前 3 条：作为"代表作"举例。
4. 组装输出（见 Output）。

## Output
按以下结构输出中文简报：
1. **品牌 voice**：Karen（永恒暴怒的中年女性） vs 冷静执法的 AI 设备；CCTV/监控美学；slapstick 即时报应喜剧；全英文。
2. **受众画像**：爱看"Karen 翻车"的泛娱乐观众；流量以搜索为主，新视频难进推荐流——前 3 秒决定生死。
3. **爆款公式**：`[emoji] Karen + 冲突动作 + 即时报应 + [emoji]`，陈述句，1-2 个话题标签；爆款 100% 用 emoji 且放开头；疑问句标题不利；高频词 viral/instant/karma/hoa。
4. **动词档位**：tier_s（TRAPPED/SLAPPED/SOAKED/TOWED…突然物理报应，好奇心最强）> tier_b（CAUGHT/EXPOSED/BUSTED…）> banned（DESTROYED/ANNIHILATED/OBLITERATED/DEMOLISHED，上传门禁直接拒）。
5. **禁忌清单**：标题禁中文、禁疑问句、禁 banned 词、禁剧集编号式数字（Episode 3）；动词强度必须匹配画面报应强度（标题党杀死完播率）。
6. **KPI 口径**：标题/选题过 58 分线（criteria v2）；Ask Studio ≥85；时长 9–20s 最佳；发布三档 10:00/12:30/00:00 CST。

## Rules
- 简报中的数字必须来自数据文件，禁止编造"行业平均"。
- 频道铁律必须列出：发布/删除/私享/花钱/对外消息必须人类明确批准；常规视频需 Ask Studio ≥85 + QC + 人工终审。
- jev 打分仅作参考，不作为门禁依据。

## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
