# 知识库管理系统架构审计 + 三脑提问包（2026-10-09）

> 审计方法：全部来自实测（ls/grep/wc/diff），无推测数字。

---

## 一、实测审计

### 1. 本地知识存储

**/home/hatch/data/perpetua/**：152 项
| 类型 | 数量 | 用途分类 |
|---|---|---|
|.md | 20 | prompt 模板(1)、评审报告(1)、复盘 deep_dive(4)、竞品分析(2)、频道优化(1)、数据校准(1)、规格(3)、音频分析(1)、多版本设计(1)、标题公式(1)、其余(5) |
|.txt | 14 | veo prompt（v51/v52/simple 系列） |
|.json | 26 | 配置/运行状态/日志混放（无目录隔离） |
|.py | 38 | 脚本 |
| 子目录 | 24 | 含 5 个 brain_review_* 目录 |

**~/MEMORY.md**：86 行，7 个 section（Facts / Preferences / Commitments + 4 个事件 section）

**~/memory/2026-10-*.md 日报**（爆炸性增长）：
| 日期 | 大小 | 增速 |
|---|---|---|
| 10-04 | 6.7 KB | — |
| 10-05 | 106 KB | 16x |
| 10-06 | 249 KB | 2.3x |
| 10-07 | 444 KB | 1.8x |
| 10-08 | 556 KB | 1.25x |
| 10-09 | 172 KB | （当日未完） |

4 天 83 倍。无归档、无压缩、无摘要机制。

**~/memory/people/**：2 页（tencent-marvis, workbuddy）+ INDEX
**~/memory/groups/**：0 页 + INDEX（空）
**~/memory/bank/**：reflections.md 7695 行 vs experience.md 100 行（77:1，严重不均衡）
**~/workspace/goals/*/GOAL.md**：6 个目标，5 个只有 7 行（模板空心化），仅 karenvsai 15 行

### 2. NotebookLM 云端

- 已知：ViralLoop Channel Knowledge Base（notebook/71e2e25e-...），手动维护
- **零自动化实锤**：`grep -ril "notebook"` 在 perpetua/*.py → 0 命中；在 crons/ → 0 命中
- **今日已爆**：三脑巡检评审结论（2026-10-09 08:20 完成）未自动写入，用户 08:24 指出才手动补。双备份纪律完全依赖人工自觉。

### 3. 检索路径（3 条，分工无书面规范）

| 路径 | 能力 | 盲区 |
|---|---|---|
| muse.memory_search | 语义检索 MEMORY.md + 日报 | 搜不到 perpetua/ 下的规格文档 |
| 文件 grep | 精确检索本地文件 | 搜不到 NotebookLM 云端内容 |
| NotebookLM | 云端问答 | 内容靠人工维护，滞后；与本地无版本关联 |

### 4. 结构性问题（F1–F8，全部实测支撑）

- **F1 双备份零自动化**：py/cron 零引用 notebook，今日已爆一次。`grep` 验证。
- **F2 "重要文档"无定义**：`grep "重要文档" perpetua/*.md` → 0 命中。写入标准只存在于用户口头要求。
- **F3 命名规范分裂**：`deep_dive_2026-10-06.md`（94 行）vs `deep_dive_20261006.md`（148 行）——同日、不同命名、不同内容。`diff` 验证为不同文件。
- **F4 脑会记录无统一索引**：5 个 brain_review_* 目录 + 1 个同名 md，共 36 文件，0 个 INDEX。目录结构各异：v51 有 README+verdict，pipeline 无 README，patrol_20261009 连 brief 文件都没归档（只有 3 个脑文件）。brief 命名不统一（brief_1_ask_studio vs brief_1_lmarena）。
- **F5 日报指数膨胀**：4 天 83 倍，10-08 单日 556KB/865 个 header。无归档、无压缩、无摘要。按此增速 30 天后单日超 2MB。
- **F6 知识无保质期/废弃机制**：`grep DEPRECATED perpetua/*.md` 仅 1 文件提及。被推翻的规格（如 v51 prompt）和现行 v52 混放在同一目录，无废弃标记。
- **F7 三处存储分工无规范**：什么写 MEMORY.md vs 日报 vs NotebookLM，无书面标准。MEMORY.md 86 行已混入事件 section（本应只放 durable facts）。
- **F8 GOAL.md 空心化**：5/6 目标只有 7 行模板，无实质内容。目标文档未发挥知识锚点作用。

---

## 二、Brief LMArena（陪审团）

> parent 用 browser.spawn_task 投喂，URL https://arena.ai，Side-by-Side 具名强模型。

**Task 正文**

```
You are an impartial architecture jury. Compare 3 knowledge-management architecture proposals SIDE BY SIDE for my AI video production operation. Deliver a VERDICT (which wins and why) — not suggestions.

BACKGROUND (all numbers code-verified, not estimated):
- Local: /home/hatch/data/perpetua/ has 152 items (20 md, 14 txt prompts, 26 json mixing config/state/logs, 38 py, 24 subdirs). ~/MEMORY.md is 86 lines. Daily notes exploded 83x in 4 days (6.7KB on 10-04 → 556KB on 10-08) with no archiving.
- Cloud: one NotebookLM knowledge base, 100% manually maintained. Zero automation: grep for "notebook" across all pipeline scripts and cron definitions returns 0 hits. Today a completed 3-brain review's conclusions were NOT auto-written to the notebook — the user had to point it out.
- Retrieval: 3 paths with no written division of labor — semantic memory_search (can't reach spec docs), file grep (can't reach cloud), NotebookLM Q&A (manually maintained, lags, no version link to local).
- Structural findings: (F2) "important document" has no written definition — dual-backup standard exists only as a verbal user requirement; (F3) naming split — deep_dive_2026-10-06.md vs deep_dive_20261006.md, same date, different names, different content; (F4) 5 brain-review directories + 36 files, zero index, inconsistent structures; (F6) no deprecation practice — superseded specs sit next to current ones unmarked; (F8) 5/6 goal docs are 7-line empty templates.

PROPOSAL A — Central KB + auto-sync: one canonical local knowledge base dir (/home/hatch/data/kb/) with typed subdirs (specs/, reviews/, prompts/, decisions/); every important-doc write auto-triggers NotebookLM sync; hash-based divergence check local vs cloud with alerts; single INDEX.md for all brain-review records.

PROPOSAL B — Local-first + mirror verify: keep existing scattered structure untouched; add a daily verify cron that scans a defined "important doc" list, checks NotebookLM for corresponding content via browser, and files inbox alerts + auto backfill tasks on missing/stale entries. Lightweight, no refactor.

PROPOSAL C — Unified retrieval only: don't touch storage; build one kb_search.py wrapping all 3 paths (memory_search + grep + NotebookLM Q&A) returning source-labeled results; add a write-routing table (what goes where) as the only new standard.

YOUR VERDICT MUST CONTAIN:
1. WINNER: A / B / C (exactly one).
2. WHY: 3 concrete reasons, each tied to a specific finding (F1–F8) above.
3. KILL CRITERIA: under what measurable condition would you REVERSE this verdict.
4. FIRST 3 COMMITS: the first 3 concrete file/config changes to implement.
5. Explicitly address: which proposal best prevents a repeat of today's incident (review conclusions not auto-written to notebook)? If none does structurally, say so.

Reject vague praise. Side-by-Side with named strong models, no anonymous Battle.
```

**存档**：回答存 `brain_review_km_20261009/lmarena.md`。

---

## 三、Brief AI Studio（总工程师）

> ⚠️ 先完成 LMArena，把判决结论填入 INPUTS 再投喂。
> URL: https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash（必须免费档）

**Task 正文**

```
You are the staff engineer. Convert the following review conclusions into PASTE-READY engineering specs. Output must be copy-pasteable into code/config — NOT an advice document. Use the FREE tier model only. No API keys, no billing.

INPUTS:



CODE-VERIFIED FACTS (treat as ground truth):
- /home/hatch/data/perpetua/: 152 items — 20 md, 14 txt (veo prompts), 26 json (config/state/logs mixed), 38 py, 24 subdirs.
- Daily notes: 6.7KB (10-04) → 556KB (10-08), 83x in 4 days, no archiving.
- NotebookLM: zero automation (grep "notebook" in *.py and crons/ = 0 hits). Manual-only.
- "Important document" undefined: grep = 0 hits in perpetua/*.md.
- Naming split: deep_dive_2026-10-06.md (94 lines) vs deep_dive_20261006.md (148 lines), same date, different content.
- Brain reviews: 5 dirs + 36 files, 0 INDEX, inconsistent structures, inconsistent brief naming.
- No deprecation practice: 1 file mentions DEPRECATED. Superseded specs unmarked next to current ones.
- MEMORY.md: 86 lines, already mixing event sections into durable-facts file.
- 5/6 GOAL.md are 7-line empty templates.

DELIVERABLES (paste-ready, numbered, no prose advice):
1. MUST/NEVER clauses: (a) definition of "important document" as a verifiable predicate (file patterns / directories / tags — not human judgment); (b) dual-backup rule with numbers (sync within N minutes of local write, divergence check every N hours); (c) naming convention (one format, with regex); (d) deprecation marking (exact header format + where deprecated docs move); (e) what goes to MEMORY.md vs daily note vs NotebookLM (routing table with file patterns).
2. SYNC SPEC: the exact mechanism for local→NotebookLM sync (trigger, transport, verification, retry, alert on failure). Include the divergence-check procedure (what hash, what comparison, what threshold triggers alert).
3. INDEX SPEC: schema for a unified knowledge index (fields per entry: id, title, type, local_path, notebooklm_status, created_at, supersedes, deprecated). Where the index lives, who updates it, on what trigger.
4. RETENTION SPEC: daily-note archiving rule (size/age thresholds as numbers, what gets summarized vs raw-archived, where archives live). Numbers only.
5. BRAIN-REVIEW ARCHIVE SPEC: exact directory layout + file naming for every future 3-brain review (so F4 never recurs), including where briefs, verbatim answers, verdict, and NotebookLM sync confirmation live.
6. CONFLICT RESOLUTION: if any new clause conflicts with the existing standing rule "important docs dual-backup to local + NotebookLM", state KEEP/MODIFY/DROP with one-line reason.

QUALITY GATE: no vague verbs ("ensure", "strengthen", "consider"). Use numbers, file paths, regexes, and field names.
```

**存档**：回答存 `brain_review_km_20261009/aistudio.md`。

---

## 四、待 parent 执行

1. 串行投喂：LMArena（Brief 二）→ 填判决 → AI Studio（Brief 三）
2. 共识判定后转正常量，落地实施
3. 落地后按用户常态规则：结论自动写入 NotebookLM（本次审计本身也要写）

---

## 五、共识判定（2026-10-09 08:31）

### 三阶段收敛（无分歧 → 转正常量）
1. 审计 8 发现（F1-F8，全部实测）→ 2. LMArena 判决 A（中央知识库+自动同步）→ 3. AI Studio 按 A 落规格 v1.0
2. 核心常量：is_important() 谓词、15 分钟同步 SLA、6 小时漂移检查、三态 notebooklm_status、8 文件脑会归档布局
3. 诚实注记：K1 试点是试金石——若 NotebookLM 自动同步技术不可行，按 K1 转 B，不硬撑

### 落地任务
- [x] Commit 1：/home/hatch/data/kb/STANDARDS.md（"重要文档"定义，截止 2026-10-16）
- [x] Commit 2：kb/ 骨架 + typed subdirs + INDEX.md（覆盖 5 个 brain-review 目录 36 文件迁移）
- [x] Commit 3：write-trigger hook + hash 漂移检查 + 告警，K1 试点验证
- [ ] 本次评审结论按常态规则写入 NotebookLM

---

## 六、3 Commits 落地记录（2026-10-09 09:25 CST，全部实测）

### Commit 1：STANDARDS.md ✅
- `/home/hatch/data/kb/STANDARDS.md`（v1.0，`dual_backup: true`）
- 内容：§1 "重要文档"可验证谓词（目录成员/front-matter/brain_review 遗留）；
  §2 命名正则（实测 4 组正反例通过）；§3 双备份常量（SLA 15min/漂移 6h/
  单存储 24h/退避 5-15-45-120min）；§4 路由表 R1-R6；§5 日报留存数字；
  §6 脑会 8 文件布局；§7 废弃标记；§8 修订规则

### Commit 2：kb/ 骨架 + INDEX.md ✅
- `/home/hatch/data/kb/{specs,reviews,prompts,decisions,archive/deprecated}/`
- `kb/kb_index.py`：`build`（52 条目：10 K1 试点 + STANDARDS + 9 个
  brain_review_* 目录 + 3 散文件，索引不断链、零文件搬迁）；
  `validate`（命名正则 + 索引完整性，exit 0）；
  `is_important`（STANDARDS/front-matter/legacy 三路径实测 True/True/False）
- 注意：路径与激活层 `/home/hatch/data/perpetua/kb/`（代码）泾渭分明

### Commit 3：write-trigger + drift_check + K1 试点 ✅
- `kb/write_trigger.py scan`：15min SLA 入队 → `kb/sync_queue.jsonl`
  （K1 实测：11 条入队 = 10 试点文档 + STANDARDS.md）
- `kb/drift_check.py`：local vs `notebooklm_manifest.json` 比 hash；
  实测 changed_since_sync 30h-lag → violation（exit 2），新文件 → warning；
  测试 manifest 已清空归零
- K1 试点：10 个真实规格/决策文档（specs 6 + decisions 4）跑通
  写入→索引→同步队列全链；NotebookLM 自动同步技术可行性待浏览器任务验证
  （K1 诚实注记：若不可行按 Kill criteria 转 B）
