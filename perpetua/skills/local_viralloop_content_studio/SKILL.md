# ViralLoop 内容工作室（viralloop-content-studio）

为 @karenvsai（英文 AI 主题 Shorts 频道 "Mark Bobl | Karen vs AI"）做全链路内容：品牌对齐、选题评估、钩子、文案、打分、翻新、排期。按请求挑对应章节执行。本工作室只产出内容，不做任何发布动作。

## 对齐品牌基线

- 用 `muse.read` 读这四个数据文件再动手：`/home/hatch/data/jev/criteria.json`（标题公式、打分规则、阈值 58）、`/home/hatch/data/perpetua/karma_verbs.json`（动词三档）、`/home/hatch/data/perpetua/viral_prompt_template.md`（模板）、`/home/hatch/data/sequel_candidates.json`（爆款代表作）。

- 记住频道 voice：Karen（永恒暴怒的中年女性）对战冷静执法的 AI 设备，slapstick 即时报应喜剧，CCTV 监控美学，全英文。

- 用爆款公式写一切标题：`[emoji] Karen + 冲突动作 + 即时报应 + [emoji]`。用陈述句，配 1 到 2 个话题标签。爆款标题全部以 emoji 开头，疑问句标题数据上无效。

- 动词只用 tier_s 优先、tier_b 次之。tier_s 是 TRAPPED、SLAPPED、SOAKED、TOWED 这类突然物理报应词。banned 词 DESTROYED、ANNIHILATED、OBLITERATED、DEMOLISHED 永不出现，命中即上传门禁直接拒。

- 守住禁忌清单：标题禁中文、禁疑问句、禁 banned 词、禁剧集编号式数字。动词强度必须匹配画面报应强度，标题党会杀死完播率。

- 简报里的每个数字必须来自数据文件，不编造行业平均。KPI 口径：标题过 58 分线，Ask Studio 不低于 85，时长 9 到 20 秒最佳。

- 列出频道铁律：发布、删除、私享、花钱、对外消息必须人类明确批准。jev 打分只作参考，不代替门禁。

## 评估选题

- 先给适配度打分（0 到 100）：这个话题能不能自然长出 "Karen vs 某 AI 设备" 的冲突。能自然长出来就高分，硬蹭就低分并直说。

- 给每个选题想 2 到 3 个角度。每个角度指定一个具体日常的自动化设备（自助结账机、智能门铃、停车咪表、加油泵这类），配一个 tier_s 或 tier_b 动词，加一句话场景。

- 拒绝抽象概念设备。banned 词永不推荐。动词优先 tier_s。

- 对照禁忌清单逐项列出避坑点，例如别用疑问句标题、别碰 banned 词、设备别选太抽象。

- 适配度低于 50 直接建议放弃，不硬做。不承诺发布排期，是否立项由选题流程决定。

## 写开场钩子

- 读 `/home/hatch/data/perpetua/karma_verbs.json` 后生成 10 个前 3 秒钩子，按预期效果排序。频道平均观看只有 7 到 20 秒，前 3 秒定生死。

- 每条钩子第一帧冲突已经在进行中，零铺垫。感官钩子优先于叙事，写视觉反差或动作突变。

- 每条配不超过 6 个词的全大写屏幕大字，例如 `AI REFUSED HER EXPIRED COUPON`。前 3 名必须用 tier_s 动词，banned 词禁用，疑问句式钩子降级。

- 每条标注所用动词和 tier，加一句话好奇心缺口，说明观众会好奇什么。

- 钩子必须是具体可拍的画面，不写"更刺激的"这类空话。

## 写文案并打分

- 写 3 个英文标题，严格走爆款公式。对每个标题做纯度自检：英文、含 Karen 或 AI、无 banned 词、非疑问句。任一项不过就重写该标题，只呈现通过的版本。

- 写 1 段描述：1 句场景加 3 到 4 个精准标签，参考爆款词 viral、instant、karma、hoa、cam。

- 写 1 条置顶评论：英文，用问句向观众提问以激发评论。标题禁疑问句，置顶评论可以用问句破 0 评。

- 按 criteria.json 的打分规则给标题打分。先查 banned 词，命中直接 0 分。逐项加减：emoji 开头加分，含 Karen 加分，tier_s 动词加分、tier_b 小加分，含爆款关键词加分，疑问句减分，剧集编号式数字减分、具象故事数字加分。

- 有脚本时检查标题承诺与内容是否一致，不一致减分。标题党杀死完播率。

- 输出分数、是否过 58 分线、1 到 2 条可执行的改进建议，例如把 emoji 挪到开头或把动词换成 tier_s 的 SOAKED。

- 打分只判选题门槛，不等于发布许可。

## 翻新旧爆款并排期

- 读 `/home/hatch/data/sequel_candidates.json` 定位原片（给 video_id 则直接定位，给话题则按关键词匹配最接近的爆款）。记下原片标题和播放量作参考，不照抄"加个 2"。

- 输出 3 个重塑角度：续集（同一冲突升级，换设备或加码报应）、反转（角色或结果反转）、跨界（把笑点机制嫁接到另一个宇宙，宇宙清单见 `/home/hatch/data/perpetua/series.json`）。

- 每个角度给一句话新钩子加一个 tier_s 优先的动词。世界观连续不等于内容重复，场景、AI 设备、笑点机制三者至少换其一。

- 每个角度附 90 天去重提醒：确认设备、动词、钩子与近 90 天视频无超过 60% 重叠。超过 60% 打回，本工作室只提醒，不代做去重判定。

- 排期时先按分数降序排选题。读 `/home/hatch/data/youtube/publish_slots.json` 取当前发布档位，把全周最高分放进流量最高的档位。

- 最高档位候选低于 70 分就宁可空着，不降低标准凑数。其余选题按分数依次填进剩下档位。

- 周五和周一加权：数据上这两天最易爆，把次高分优先排这两天。时区统一用 Asia/Shanghai。

- 逐天呈现排期：每天列出各档位对应的选题标题和分数，空档位明确标空并写一句原因。

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Alternatives for better results

- 适配度低于 50 的话题直接放弃，把精力留给高分选题，硬做低分题是浪费生成配额。

- 动新选题前先翻 sequel_candidates.json 的爆款清单，续集和跨界的起跑线高于凭空想题。

- 写文案前先跑一遍打分规则自查，banned 词和疑问句在动笔阶段就拦掉，比写完返工便宜。
