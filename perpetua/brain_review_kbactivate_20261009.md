# 知识库激活机制审计报告（2026-10-09）

## 审计方法
全部实测：读代码、grep 调用关系、ls/wc 验证。零推测。

---

## 一、已有激活链（workings，5 条）

### A1. 留存回流链（最完整）
`retention_telemetry.py`（D4，每日 03:49）→ `retention_telemetry.jsonl`（39KB）
→ `feature_extractor.py`（D5，Top-3 特征提取）
→ `dynamic_constraints.json`（D6）
→ `viral_prompt.py:276-282`（D6 闭环注入，把 Top-3 特征作为加权指令注入 prompt）
- 调用方：仅 `viral_prompt.py`（grep 确认另只有 feature_extractor 自引用）
- 状态：✅ 跑通，知识→决策的完整闭环

### A2. 哑火回流链
`post_publish_optimizer.py:189`（写）→ `dud_feedback.jsonl`（14 行，10-08 22:10）
→ `viral_prompt.py:298`（读，连续 3 条哑火→钩子强化指令）+ `console_server.py:785`（读，展示）
- 状态：✅ 跑通

### A3. 标准进化链
`daily_evolution.py`（23:30）→ `criteria.json` 版本+1（备份旧版）
→ 读者：`mcp_server/server.py`（上传门禁）、`viral_prompt.py`、`content_tools.py`
- 状态：✅ 跑通

### A4. Ask Studio 问答链（半残）
`mcp_server/server.py:1682` `ask_studio()`（入队）→ 30 分钟 browser 问 → 答案写回
→ `ask_studio_answer()` 可查 → `prompt_review.py:203` 只取**分数**做候选排序
- 状态：⚠️ 分数被用了，但答案里的诊断文字（如 deepdive_20261008.md 的"严格 1-2 条/天，间隔 6-8 小时"）是 markdown blob，无结构化抽取

### A5. 续集清单链
`sequel_candidates_refresh.py`（每日 07:49）→ `sequel_candidates.json`
→ 读者：`content_tools.py`、`mcp_server/server.py`
- 状态：✅ 跑通

---

## 二、断裂点（B1–B7，全部实测）

### B1. deep_dive 报告写了没人读（最严重）
- `deep_dive_2026-10-06.md`、`deep_dive_2026-10-07.md`、`deep_dive_2026-10-08.md` 每日生成
- `grep -rln "deep_dive" --include="*.py" perpetua/` = **0 命中**
- 结论：深度复盘的产出是纯人类阅读文档，零代码消费。复盘发现的问题靠人手动改代码。

### B2. NotebookLM 零自动化
- `grep -rn "notebooklm\|notebook.google" --include="*.py" perpetua/ youtube/` = **0 命中**（排除 venv）
- 唯一调用方：人类用浏览器。今天三脑结论漏写已证明：无自动化 = 靠自觉 = 会漏。

### B3. 三脑结论不可机读
- 5+ 个 `brain_review_*/` 目录，36+ 文件
- `grep -rln "brain_review" --include="*.py" perpetua/` = 仅 1 命中，且是 `pipeline_state.py:4` 的**注释引用**（"规格：.../aistudio.md"），非代码依赖
- 结论：历史 verdict（如 v5.1→v5.2 的 KEEP/MODIFY/DROP）躺在 markdown 里，后续决策无法程序化引用。

### B4. prompt 模板版本硬编码
- `viral_prompt.py:36-68`：V51_CLOSEUP_OPENING、V52_MOTION_RAMP、V52_CLIMAX_RULES 是代码常量
- 无 git、无版本号文件、无变更日志。模板进化 = 手工改代码。
- 三脑裁决的 KEEP/MODIFY/DROP 没有落成可追踪的版本记录。

### B5. Ask Studio 诊断文字未结构化
- `ask_studio/answers/deepdive_20261008.md` 含具体可执行结论："严格 1-2 条/天，间隔 6-8 小时"、"naAGOU2rVb0 设为 Private"
- 但 `prompt_review.py` 只提取分数，诊断文字无人解析。10-08 的"1-2 条/天"是人手动执行的，不是从知识库自动生效的。

### B6. 记忆系统与管线双轨并行
- `~/MEMORY.md`（86 行）+ `~/memory/2026-10-*.md` 日报：只有 Dash（agent）经 `memory_search` 读取
- **零 pipeline 脚本**读取记忆系统。两套知识体系互不相通。

### B7. 单向街：复盘不回流
- deep_dive 的发现（如"批量发布导致观众疲劳"）没有进入 `dynamic_constraints.json` 或 `criteria.json`
- 只有 D4/D5/D6 链（留存数据）在自动回流；深度分析的结论靠人工搬运。

---

## 三、Brief LMArena（陪审团）

> parent 用 browser.spawn_task 投喂，URL https://arena.ai，Side-by-Side 具名强模型。

**Task 正文**

```
You are an impartial architecture jury. Compare 3 knowledge-activation architecture proposals SIDE BY SIDE for my AI video production operation. The goal: knowledge must be CALLED by the pipeline, not lie dead in docs. Deliver a VERDICT (which wins and why) — not suggestions.

BACKGROUND (all numbers code-verified):
WORKING activation chains (knowledge → action, verified by grep):
- A1: retention telemetry → feature extraction → dynamic_constraints.json → viral_prompt.py injects Top-3 data-driven directives into prompts (daily closed loop, WORKS)
- A2: post-publish optimizer → dud_feedback.jsonl → viral_prompt.py hook-boost on 3+ consecutive duds (WORKS)
- A3: daily_evolution → criteria.json v+1 → MCP upload gate (WORKS)
- A4: Ask Studio Q&A → prompt_review.py uses ONLY the score; diagnostic text ("strictly 1-2/day, 6-8h apart") stays as markdown blob, manually executed by human (HALF-BROKEN)
- A5: sequel candidates refresh → sequel_candidates.json → content tools (WORKS)

BREAKAGE points (verified):
- B1: deep_dive_*.md reports written daily, ZERO code readers (grep = 0 hits). Deep review findings never programmatically consumed.
- B2: NotebookLM knowledge base has ZERO automation (grep = 0 hits in pipeline code). Today a 3-brain review's conclusions were not auto-written — user had to point it out.
- B3: 5+ brain_review_*/ dirs, 36+ files; only 1 code reference and it's a COMMENT, not a dependency. Historical verdicts not machine-readable.
- B4: prompt template v5.2 constants hardcoded in viral_prompt.py; no version tracking, no changelog. Template evolution = manual code edits.
- B5: Ask Studio diagnostic insights stay as markdown; "1-2/day" was human-executed, not auto-enforced from KB.
- B6: agent memory system (MEMORY.md + daily logs) read ONLY by the agent via semantic search; ZERO pipeline scripts read it. Two parallel knowledge systems.
- B7: one-way street — deep_dive findings don't flow into dynamic_constraints.json or criteria.json. Only raw telemetry auto-flows back.

PROPOSAL A — Pull mode (kb_context.py): every pipeline stage explicitly queries KB before acting. New module kb_context.py with API get_context(task_type, device, ...) returning relevant KB snippets (past QC failures for this device, applicable brain-review verdicts, active constraints). Call points added to: topic generation, prompt generation, QC, review, publish. Mirrors the existing A1 pattern (dynamic_constraints → viral_prompt) generalized to all stages.

PROPOSAL B — Push mode (event-driven): KB watches pipeline events and pushes relevant knowledge to active tasks. New knowledge write → auto conflict-check vs existing KB → push alerts on contradiction. Pipeline stage start → event bus → KB pushes context cards. Anomaly (3rd QC fail) → auto-query NotebookLM for historical resolutions. Knowledge is active, stages are passive receivers.

PROPOSAL C — Hybrid + usage metrics: pull for the 5 deterministic pipeline stages (A's kb_context.py at fixed call points) + push for anomalies and new-knowledge conflicts (B's event triggers) + usage ledger logging every KB read (which entry, by whom, for what decision). Entries with 90 days zero-use enter review queue (prune or fix the caller).

YOUR VERDICT MUST CONTAIN:
1. WINNER: A / B / C (exactly one).
2. WHY: 3 concrete reasons, each tied to a specific breakage (B1–B7) above.
3. KILL CRITERIA: under what measurable condition would you REVERSE this verdict.
4. FIRST 3 COMMITS: the first 3 concrete file/config changes to implement.
5. Explicitly address: which proposal best fixes B1 (deep_dive zero readers) AND B5 (Ask Studio text not structured)? If none does structurally, say so.

Reject vague praise. Side-by-Side with named strong models, no anonymous Battle.
```

**存档**：回答存 `brain_review_kbactivate_20261009/lmarena.md`。

---

## 四、Brief AI Studio（总工程师）

> ⚠️ 先完成 LMArena，把判决结论填入 INPUTS 再投喂。
> URL: https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash（必须免费档）

**Task 正文**

```
You are the staff engineer. Convert the following review conclusions into PASTE-READY engineering specs. Output must be copy-pasteable into code/config — NOT an advice document. Use the FREE tier model only. No API keys, no billing.

INPUTS:

[LMARENA VERDICT — fill in after Stage 2: winner, 3 reasons, kill criteria, first 3 commits]

CODE-VERIFIED FACTS (treat as ground truth):
- viral_prompt.py:276-282 reads dynamic_constraints.json and injects Top-3 directives (pattern to generalize).
- viral_prompt.py:298 reads dud_feedback.jsonl (14 lines) for hook-boost on 3+ duds in 7 days.
- prompt_review.py:203 uses ask_studio score only; diagnostic markdown not parsed.
- deep_dive_*.md: 0 Python readers (grep-verified). Written daily, consumed by humans only.
- NotebookLM: 0 automation hits in pipeline code (grep-verified).
- brain_review_*/: 5+ dirs, 36+ files; 1 code reference which is a comment, not a dependency.
- V51/V52 template constants hardcoded in viral_prompt.py:36-68; no version file, no changelog.
- MEMORY.md (86 lines) + memory/2026-10-*.md: read only by agent semantic search; 0 pipeline script readers.
- Working writers: feature_extractor.py → dynamic_constraints.json; post_publish_optimizer.py:189 → dud_feedback.jsonl; daily_evolution.py → criteria.json (v+1 with backup); sequel_candidates_refresh.py → sequel_candidates.json.

DELIVERABLES (paste-ready, numbered, no prose advice):
1. KB_CONTEXT API SPEC: function signature for get_context(task_type, device=None, video_key=None, ...) — inputs, outputs (list of {entry_id, snippet, relevance_score, source}), relevance ranking rule with numbers, max snippet budget (tokens/chars), cache TTL. Which pipeline stages call it and at what exact code points (file:line style).
2. CALL-POINT INVENTORY: table of every pipeline stage (topic_gen / prompt_gen / qc / review / publish / post_publish) × what KB it must pull before acting × the exact insertion point. Mark which already exist (A1/A2/A3/A5) vs new.
3. STRUCTURED EXTRACTION SPEC: how Ask Studio markdown answers get parsed into machine-readable constants (field schema, extraction trigger, validation rule, fallback when parse fails). Must cover the B5 example: "严格 1-2 条/天，间隔 6-8 小时" → which fields, which consumer enforces it.
4. CONFLICT DETECTION RULES: numeric thresholds for new-knowledge vs existing-KB contradiction (e.g. new directive contradicts an active constraint → flag). Where the check runs (write path), what happens on conflict (block / warn / version-fork).
5. USAGE METRICS SCHEMA: JSONL record fields for every KB read (timestamp, entry_id, reader, task_type, decision_influenced). The 90-day zero-use review rule as executable logic (query + action).
6. MCP EXPOSURE PLAN: which KB query capabilities get exposed via MCP tools for Marvis/other agents (tool names, inputs, outputs). Must not expose raw memory files or credentials.
7. TEMPLATE VERSIONING: how v5.2-style prompt constants move out of hardcoded Python into versioned spec files (file layout, version field, changelog format, migration path for current V51/V52 constants).

QUALITY GATE: no vague verbs ("ensure", "strengthen", "consider"). Use numbers, file paths, function names, and field names from the facts above.
```

**存档**：回答存 `brain_review_kbactivate_20261009/aistudio.md`。

---

## 五、待 parent 执行
1. 串行投喂：LMArena（Brief 三）→ 填判决 → AI Studio（Brief 四）
2. 共识判定后转正常量，落地实施
3. 落地后按常态规则：结论自动写入 NotebookLM

---

## 六、共识判定（2026-10-09 08:42）

### 收敛：C（混合+使用度量），三阶段无分歧
- 审计实测 5 条激活链 + 7 个断裂点 → LMArena 两模型独立全票 C → AI Studio 按 C 输出 7 大规格
- 核心机制：kb_context.py 拉取（5 确定性阶段）+ 异常推送 + 使用账本（死知识自报）
- 诚实边界：正则抽取不能语义保证，失败时保留旧常量（已编码进规格）

### 落地任务
- [x] Commit 1：kb_context.py + kb_sources.yaml + prompt_review.py:203 调用点 + publish_cadence.json 转换（实测：6 task_type 全过；抽取器成功/失败双路径过；prompt_review 编译过）
- [x] Commit 2：kb_usage_ledger.jsonl + 装饰器 + kb_prune_queue.py（实测：3 次调用记 13 行账本；prune 在测试数据上正确识别零用条目）
- [x] Commit 3：deep_dive_extractor.py + deep_dive_findings.json + QC 调用点（实测：4 个文件抽出 31 条 findings；qc 上下文含 deep_dive 条目；entry_id 模板 bug 已修）
- [x] 回归：A1（viral_prompt dynamic_constraints 内联读取）未破坏；prompt_review 导入正常
- [x] 本次结论按常态规则写入 NotebookLM（2026-10-09 08:49 确认：「三脑评审 2026-10-09：知识库激活机制决策」已落库）

### MCP 本地暴露落地（2026-10-09 09:0x，用户授权"动手"）
- [x] server.py 加 5 个 tool（备份 server.py.bak-20261009-kb；venv 补 pyyaml，否则 kb 源只剩 1 个 fallback）
  - kb_query：question→task_type 关键词粗映射，调 get_context，账本记 mcp:external_kb_query
  - kb_get_entry / kb_list_sources（不暴露源路径）/ kb_usage_stats（近 N 天按源/阶段统计）
  - kb_propose_finding：CJK bigram 去重（>0.5 直接返回已有解法），否则写 staging/proposals.jsonl（status=pending）
- [x] kb/staging/ + promote_proposal.py（list/approve→deep_dive_findings.json 打 source_agent 标签/reject+原因；幂等，防重复处理）
- [x] MCP 协议实测：tools/list 见 5 个 kb 工具（总数 40→45）；initialize→tools/list→tools/call 全链走 Mcp-Session-Id；kb_query/kb_list_sources/kb_propose_finding 三调全过
- [x] cron kb-staging-review（每天 09:30 Asia/Shanghai）：staging_review_cron.py 扫 pending，新增写 inbox 通知（for=user，seen.json 去重）；实测通知+去重双路径过
- [x] agent-onboarding.md：加 KB 工具章节 + 工具数 22→45（原数字已过期）
- [x] 审核策略：全人工（用户决策：先跑两周看提案质量，再定是否放自动）
- 安全红线遵守：只读工具不暴露 MEMORY/日报全文/staging/凭据；提案只写 staging；全部外部调用写账本

### brain_council 通用工具落地（2026-10-09 09:15，用户授权"动手"）
- [x] server.py：brain_council job_type（备份 server.py.bak-20261009-braincouncil）
  - 校验：question 必填；brains 非法值拒绝（可用 lmarena/aistudio/ask_studio）；depth standard|deep
  - ask_studio 护栏：brains 含 ask_studio 但问题与 YouTube/视频无关 → 拒绝（它是 YouTube Studio 传感器，别的项目用不上）
  - 缺省双脑 ["lmarena","aistudio"]；幂等复用 submit_job 现有 idempotency_key 机制
  - 实测：9 个校验用例全过；协议层（tools/call）非法/合法/幂等三路径全过
- [x] cron mcp-media-job-processor 加 section C：brain_council 处理器
  - 防并发认领（processing + 90 分钟死任务接管）；单脑超时 20 分钟，失败记 brains_failed 继续
  - lmarena（arena.ai 陪审团，deep 时 side-by-side 双模型）→ aistudio（免费档，落 MUST/NEVER 规格）→ ask_studio（仅显式指定+YouTube 相关）
  - 综合结论结构：评审链/判决/核心规格/反转条件/诚实边界；result.json 含 verdict/specs/reversal_conditions/honest_limits/raw_outputs
  - 会诊记录存档 brain_review_council/council_<job_id>.json
  - 超时提到 3600s（双脑×20分钟+综合）；其余 A/B 处理逻辑原样保留
- [x] MCP 协议回归：45 工具全在，老工具无缺失
- [x] agent-onboarding.md：brain_council 章节 + ask_dash vs brain_council 选型说明 + 工具数去硬编码
- [x] 端到端实测（2026-10-09 09:21 cron worker 真跑）：job job-20261009011449-3337a6 全链路走通
  - 认领机制 ok（processing + processing_started_at 09:21:38）；两脑逐个调度 ok
  - 双脑均失败 → 按规格记 brains_failed 并继续 → result.json status=failed，原因结构化（非崩溃非 hanging）
  - 失败根因是环境非代码：lmarena 未登录 arena.ai；aistudio 卡 Google 2FA（与今日 ask-studio-daily 同一根因，用户已被告 知需手工刷新会话）
  - 失败路径已实测验证；成功路径待用户刷新浏览器会话后重测（届时重跑一个 brain_council job 即可）
  - 测试 job 文件 + 幂等 key 已清理；mcp-server 单实例健康（45 工具）

### brain_council 成功路径重测（2026-10-09 09:44，登录恢复后）
- [ ] 未通过：job-20261009013544-192fe4，worker 09:44 真跑，双脑仍被 auth 墙挡下
  - lmarena：Direct 模式弹 "Log In or Create Account" 对话框，automation profile 未登录
  - aistudio：bat08738@gmail.com 密码过，但 Google 仍要 2-Step Verification（Authenticator/SMS/点按/passkey），worker 09:44 在 accounts.google.com/v3/signin/challenge/selection 按规则停下
  - 关键矛盾：用户 09:35 称三脑登录"刚验证通过"，但 09:44 worker 跑的 automation browser profile 依然掉线——**验证很可能发生在与 browser task 不同的浏览器 profile**（本机查无本地 Chrome/CDP 9222，browser task 的 profile 在 parent 侧基础设施）
  - 失败处理依然按规格正确执行（brains_failed 结构化、job failed、测试产物已清理）
  - 待 parent 侧：在 browser task 会话内重登 arena.ai + 走完 Google 2FA，然后重跑一个 brain_council job 验成功路径
