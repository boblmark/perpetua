# AI Brain Council（四脑议会）

> 2026-10-09 起为四脑：Ask Studio / LMArena / AI Studio + DeepSeek 红队。
> 旧称"三脑议会"保留为触发词，但调度时四脑默认全上，缺一即为事故（2026-10-10 漏红队教训）。

## Purpose

病毒爆款视频是数字工程化：把未知变量变成可控常量，再写进管线。

- 你是四脑之间的总线：四脑互不相识、无共享记忆，你负责带实时数据去问、给每个大脑提它最擅长的问题、把输出锻造成可写进系统的常量（模板条文、QC 阈值、cron 规则），而不是建议文档。
- 四脑之间没有直连：浏览器是传输层，你在它们之间传话、对比、判决。
- 铁律：大脑只输出常量，不输出建议。合格输出是"0.00s 音量 100%、0.80s 设备打断、禁 meta 标题"；不合格输出是"建议改进一下开头"，打回重问。

## The four brains

- Ask Studio（YouTube Studio 内置）：传感器。负责频道真实数据诊断（留存曲线、流量来源、swipe 比），输出瓶颈在哪。
- LMArena（arena.ai）：陪审团。负责多模型横评（重大决策用 Side-by-Side 指定模型，匿名 Battle 陪审团质量有波动），输出哪个方案赢。
- AI Studio（aistudio.google.com）：总工程师。负责长上下文深度推理，把结论写成可粘贴的 MUST/NEVER 条文。
- DeepSeek 红队（chat.deepseek.com 网页版优先）：泼冷水。只输出 KILL / WEAKEN / WATCH verdict，不给建设性建议。

- 登录：四脑用 Google 账号 bat08738@gmail.com，登录态在浏览器 profile 里；过期先用 Secure Vault 密码自动重登，3 次失败再找用户。
- AI Studio 注意：默认选中的 Gemini 3 Flash Preview 是付费档，不可用；必须用免费档（Gemini 3.8 Flash 或同类），不建 API key、不开付费。

## Run the pipeline

标准四步链：真实数据 → Ask Studio 找瓶颈 → LMArena 横评 2-N 个解法 → AI Studio 落可执行规格 → DeepSeek 红队 verdict → 管线执行 → 数据回流 → 下一轮诊断。

- 只用 `browser.spawn_task` 调度，由主 agent 亲自跑，禁止委派给 subagent（subagent 没有 live browser 能力）。每脑的具体配方在 `references/browser-recipes.md`。
- 每次调用必须带实时数据：给 Ask Studio 带近 7 天留存/播放数据，给 LMArena 带 Ask Studio 诊断加待横评方案，给 AI Studio 带前两步结论加要落笔的位置。
- 串行调度防状态污染：等 A 完成再调 B，把 A 的结论喂进 B 的 prompt。大脑互不相识，全靠你传话。
- prompt 必须自包含（浏览器任务看不到你的上下文）：写清背景事实、待评审对象原文或摘要、输出格式（KEEP/MODIFY/DROP、具体命令、拒绝空话）。
- 要求 verbatim 带回全文，存档到文件（如 `lmarena.md`），不只放上下文里。
- 你做收敛判决：多个大脑、不同路径、独立得出同一个答案，且红队未出 KILL，才敢写进管线。"多脑一致"是你对比判定的，不是它们达成的共识。
- 每次会诊产出：`brief_*.md`（发给每脑的 prompt，可复现）、`<brain>.md`（各脑 verbatim 回答）、`verdict.md`（你的综合判决，含分歧处理）。
- 评审不等于批准：大脑的结论是输入，最终决策权在用户，Tier 3 尤其如此。

## Escalate when the channel degrades

- worker 派发的浏览器任务回报"登录页/未登录"：一律视为槽位疑似故障，不得计入失败、不触发告警、不 BLOCK 任务；只走"疑似 + 主 agent 独立只读复核"流程。
- Ask Studio worker 通道连败：2 轮失败就升级，由主 agent 亲自用浏览器跑（先例：worker 连败 26 轮，主 agent 绕行一次成功）。
- 竞品爆款触发：用户立规矩，Dash 直接亲自打开 arena.ai 送陪审团拆解，不排队、不委派。
- 红队走网页版优先，API 为备用；网页登录态掉线属用户 opt-in 重登，不自动点。

## Close the loop（议会闭环清单，2026-10-10 决议，强制）

议会任务结束返回前，主持 agent 必须逐项执行，缺一即"未闭环"：

- 结论落盘：`brain_council/<council_id>/synthesis.md`（含逐条结论 + 落地清单）。
- 决策登记：结论中每条决策级条目追加到 `~/MEMORY.md` 顶部 `## 议会决策`，格式 `- [DYYYYMMDD-NNN] 一句话（主题，日期 议会）`，ID 全局唯一递增。
- 机器门：`grep -q "^- \[D<id>\]" ~/MEMORY.md` 逐条校验；失败则重写，仍失败标"未闭环"。
- 用户拍板项（如有）：结论状态标"草案/待拍板"，不得按草案改生产系统；用户拍板后补登记。
- NotebookLM 双备份（重要结论）。

- 协议全文：`/home/hatch/data/brain_council/decision_memory_protocol.md`；看门狗：`decision-watchdog` cron 每小时校验登记处。

## Honest limits

- 重大决策用 Side-by-Side 指定模型，匿名 Battle 陪审团质量有波动。
- AI Studio 免费档有额度，重度使用可能要上付费（需用户批准）。
- 四脑无共享记忆，提问时必须把前序结论完整复述。
- 大脑输出是高置信建议不是真理，最终仍以频道自有数据回流验证为准。
- 浏览器 RPA 脆弱（网站改版就挂）、慢（分钟级）、需要登录态；你是单点瓶颈。
- handoff 在 worker 长转中可能延迟送达（20-40 分钟批量），不要对 completed 任务无限等待；steer 一次让它直接输出结果。

## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.

## Websites

- https://arena.ai：陪审团横评。`browser.spawn_task` 时带上 Ask Studio 诊断加 2-N 个待横评方案，重大决策用 Side-by-Side 指定模型，不点投票按钮，verbatim 带回全文。
- https://aistudio.google.com：总工程师。URL 预置免费模型，只给它前两步结论加要落笔的模板位置，要求输出可粘贴的 MUST/NEVER 条文。
- https://studio.youtube.com：Ask Studio 传感器。问题里必须带近 7 天实时数据，要求 verbatim 带回全文。
- https://chat.deepseek.com：红队。只问它 KILL / WEAKEN / WATCH verdict，不问它建设性建议。

## Alternatives for better results

- 只需一次快速判断时，单派一脑（Ask Studio 做数据诊断、LMArena 陪审团做拆解）即可，不必开全议会。
- 阈值类结论先走 `qc_gate_calibration` 做证据分级，再写进管线。
- 48h 无有效数据时，诚实判"维持策略"，不硬凑结论（2026-10-16 每日进化议会先例：原报告被 Ask Studio 实证证伪后改判）。