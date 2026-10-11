# 7×24 无人值守巡检基建 · 三脑深度评审（2026-10-09）

> 评审对象：Perpetua 爆款病毒视频流水线的 7×24 无人值守巡检基建
> （30+ cron + 看门狗脚本 + 自动修复脚本 + 状态文件）
> 用户原话："这是我们爆款病毒视频流水生产线的基建！非常关键"

## 评审状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| STAGE 0 基建审计 | ✅ 完成 | 本文件 §二，代码实测 F1–F8 |
| STAGE 1 Ask Studio（传感器） | ⏳ 待浏览器调度 | 提问包见 §四 Brief 1，parent 用 browser.spawn_task 投喂 |
| STAGE 2 LMArena（陪审团） | ⏳ 待浏览器调度 | 提问包见 §四 Brief 2（依赖 STAGE 1 结论填空） |
| STAGE 3 AI Studio（总工程师） | ⏳ 待浏览器调度 | 提问包见 §四 Brief 3（依赖 STAGE 1+2 结论填空） |
| STAGE 4 共识常量落地 | ⏳ 待 STAGE 1–3 | 三脑独立同结论才写进管线 |

**为什么 STAGE 1–3 未执行**：本轮协调员为通用 subagent，无 live browser
操作权限，不能发起 browser.spawn_task。三脑（Ask Studio / LMArena /
AI Studio）均需浏览器会话，必须由 parent（main agent）调度。
提问包已写成"复制即用"形态，parent 按 §四顺序串行投喂即可。

---

## 一、评审对象快照（实时数据包，2026-10-09 07:45 CST）

### Cron 规模（~/workspace/goals/karenvsai/crons/，共 33 个）

- **半小时级 11**：ask-studio-queue-processor、dead-state-watchdog、
oa-watchdog(5分钟)、pending-pickup-watchdog、perpetua-pipeline-collect(20分钟)、
perpetua-pipeline-orchestrator、private-flip-scheduler(10分钟)、
published-video-watchdog、comment-auto-reply、oa-voice-reminder、
ask-studio-health-check（已禁用，用户亲手验证后禁用）
- **小时级 6**：bypass-audit-watch(2h)、facebook-cli-watch、
facebook-vm-monitor(6h)、post-publish-optimizer(6h)、trend-spike-watch、
zero-view-watch(2h)
- **天级 11**：ai-trend-radar、ask-studio-daily、daily-evolution、
facebook-reels-browser-post、perpetua-deep-dive-weekly、
perpetua-pipeline-1000/am/pm、pipeline-failed-cleanup、retention-closed-loop、
sequel-candidates-refresh、youtube-align-daily
- **其他**：viralloop-page-retry(4h)、https-ready-notify、zbj-quota-monitor、
MCP任务自动处理(10分钟)
- **周/月**：comment-topic-miner、lmarena-weekly-jury、verb-pool-weekly-review、
youtube-align-weekly、aistudio-monthly-spec

### 昨晚真实事故（2026-10-08 夜 ~ 10-09 凌晨，北京时间）

1. **03:19 zero_view_alert 误公开**：停车咪表视频 gxYpY6BHYwc（原定 12:30
public，private_queue.json 状态 waiting）被 zero_view_alert.py 当成隔离视频，
因 private 状态下有 4 次播放，按 v2"有播放则主动恢复"策略自动转 public。
定时发布被提前 9 小时执行。
2. **H3 5/5 生成但 0 上传**：5 条全部 QC 不合格（开场静态/循环差/音频弱），
orchestrator 只报告 GENERATE_NEEDED，无真实执行者认领重生成。
3. **Veo 文件取不回**：浏览器任务生成成功但 browser task 无文件系统访问，
MP4 落在任务侧，链路设计时没考虑文件回传。
4. **instant_queue 两个 pending_instant 死状态**（后文件被清空，清理来源不明）。
5. **✅ 成功案例**：VM 06:10 重启，看门狗 06:11 自动拉起 MCP/隧道/console。
6. **relay 127.0.0.1:18080 夜间多次掉线**，靠 jev_keepalive.sh 恢复，根因未查清。

### 历史评审上下文（避免重复造轮子）

- 2026-10-08 AI Studio 已产出 **14 条 MUST/NEVER**
（brain_review_pipeline/aistudio_specs.md），其中 #3（终审 TTL）、
#6（原子写）、#12（dead-man's-switch）、#14（拒绝风暴）已落地进
dead_state_watchdog.py；**#5（幂等 videoId 持久化）、#7（读容忍损坏）、
#8（cron 单飞/stale-safe 锁）未见落地**。
- 2026-10-08 Ask Studio 7×24 机制诊断（askstudio_724_mechanism.md）：
30 分钟轮询已足够（数据小时级刷新）；本频道 Search 流量 74.7%，
看门狗应优先看 Search 占比变化而非 Shorts feed。

---

## 二、基建审计发现（代码实测，非推测）

### F1. zero_view_alert.py 豁免机制残缺 —— 03:19 事故的直接根因（已验证代码）

文件：`/home/hatch/data/youtube/zero_view_alert.py`（217 行）

- `EXEMPT_VIDEOS = {"d0CHRz8ubjk"}` **只在删除阶段（满 24h）检查**，
auto-restore 分支（`elif views > 0:` → PUT public）**不检查豁免**。
即使用户豁免的私享视频在隔离期产生播放，也会被自动翻公开。
- Pass 1 隔离逻辑**不查 `private_queue.json`**：任何 >1h 的非公开视频
（不在 quarantine/alerted 中）直接进隔离。这是 gxYpY6BHYwc 被误判的
精确代码路径：private + 4 views → quarantine → views>0 → auto-restore public。
- `private_queue.json` 当前仍有脏状态：gxYpY6BHYwc `status=waiting`、
`scheduled_at=2026-10-09T04:30:00+00:00`（12:30 CST），但视频实际已于
03:19 转 public。12:30 private_flip.py 会尝试重复翻转（幂等但状态错误，
且会写错误日志）。

### F2. pipeline_orchestrator.py 是只读扫描器（70 行，零执行）

文件：`/home/hatch/data/perpetua/pipeline_orchestrator.py`

- docstring 声称"主动推进管线"，实际代码只 `log()` actions，
`sys.exit(0)`，**无执行器、无状态写回、无超时处理**。
- cron 描述写"只做状态盘点和记录，不自动触发重量级操作"——
**docstring 与 cron 描述互相矛盾**，这就是用户批评"被动"的精确所指：
系统里没有一个组件真正拥有"生成/重生成"的执行权。

### F3. 全系统无 run fencing（已 grep 验证）

- `grep -rln "flock|lockfile|fcntl" /home/hatch/data/perpetua/*.py
/home/hatch/data/youtube/*.py` → **零命中**。
- 最小 cron 间隔 5 分钟（oa-watchdog）；脚本运行时间无记录。
重叠执行时两个实例可同时读写同一 JSON（如 quarantine.json）。

### F4. JSON 写语义不一致（同一批状态文件两种语义）

- `dead_state_watchdog.py` 用 `atomic_json.atomic_write`
（临时文件 + fsync + 原子 rename，AI Studio 规格 #6）。
- `zero_view_alert.py` 用普通 `save_json`（`Path.write_text`，非原子，
崩溃可致半写文件）。
- `private_flip.py` 用普通 `write_text`。
- 读侧：`tolerant_read` 只在 watchdog 用，另两处裸 `json.loads`。

### F5. 豁免/意图分散在三处，无统一"意图注册表"

| 注册表 | 位置 | 覆盖意图 |
|---|---|---|
| EXEMPT_VIDEOS（代码硬编码） | zero_view_alert.py | 用户私享（仅删除阶段有效） |
| quarantine.json（运行时） | /home/hatch/data/youtube/ | 隔离观察中 |
| private_queue.json（排期） | /home/hatch/data/youtube/ | 定时待发 |

三种"为什么是 private"的意图（用户私享 / 定时待发 / 异常隔离）
没有统一注册表和优先级，脚本之间互不可见对方的意图。

### F6. instant_queue 死状态已消失，清理来源不明

- `/home/hatch/data/ask_studio/instant_queue.json` 当前 `items: []`。
- 摘要中记录的两个 `pending_instant`（iq_20261008025840…、
iq_20261008135740…）已不在文件中，**无清理日志**。
状态变更无审计轨迹 → 出问题无法归因。

### F7. 10-08 规格落地缺口

已落地：#3、#6（部分）、#12、#14。
**未落地**：#5（上传成功→videoId 立即持久化，崩溃幂等）、
#7（读状态容忍损坏 JSON）、#8（共享状态读写序列化 + cron 单飞）。
#8 正是 F3 的缺失项。

### F8. 成功模式（应保留并推广）

- oa-watchdog / infra watchdog：VM 06:10 重启 → 06:11 自动拉起
MCP + ws_poller + SSH 隧道 + console。**检测→执行→验证闭环完整**，
是全系统唯一跑通的自愈链。
- jev_keepalive.sh 对 relay 18080 掉线的恢复有效，但**根因未查清**
（属于"症状自愈"，非"根因修复"）。

---

## 三、待三脑确认的候选常量（审计推导，⚠️ 非共识，需三脑独立验证）

> 以下为协调员从代码审计推导的候选条文，**不是**三脑结论。
> 三脑独立同结论才可转正；分歧点如实记录。

- C1: 任何自动修改视频可见性（privacyStatus）的脚本，执行前 MUST
查询统一意图注册表；命中 `intentional_private` 或 `scheduled_private`
时 MUST 跳过。
- C2: 豁免检查 MUST 覆盖脚本的**每一个**写分支（隔离/恢复/删除），
不得只在删除分支检查（F1 的精确教训）。
- C3: 定时待发（private_queue.json waiting）的视频，对 zero_view_alert
MUST 不可见（预过滤），而非事后补救。
- C4: 所有 cron 脚本 MUST 实现 stale-safe 单飞锁（AI Studio #8）；
锁超时 > 2× cron 间隔。
- C5: 所有状态 JSON MUST 原子写 + 容忍损坏读（AI Studio #6/#7），
全系统统一，不得各写各的。
- C6: 任何状态变更（豁免/清理/过期）MUST 写审计日志
（who/when/before→after），F6 类"无声清理"不得再发生。
- C7: orchestrator 的 docstring 与 cron 描述 MUST 一致；
"扫描器"和"执行器"是两个角色，不得由一个无执行权的组件冒充。
- C8: Tier 3 级自动操作（删视频/翻公开）MUST 有熔断器：
单轮自动操作 ≥N 次或 1h 内 ≥M 次 → 自动停掉该 cron 并告警，
人工确认后恢复。

---

## 四、三脑提问包（复制即用，parent 串行投喂）

### Brief 1 — Ask Studio（传感器）

**browser.spawn_task 参数**

- **initial_url**: `https://studio.youtube.com`
- **task**（完整，复制即用）：见下方 "Task 正文"

**Task 正文**

```
In YouTube Studio (already signed in), open the Ask Studio panel and ask
this exact question. Wait for the complete answer and bring it back verbatim.

Question:

"Context: I run a fully automated 7x24无人值守 short-video production pipeline
for my Shorts channel 'Mark Bobl | Karen vs AI'. 33 cron jobs handle: trend
scanning, AI video generation (Veo/H3), QC gates, scheduled publishing
(2/day at 12:30/00:00 CST), zero-view alerts, dead-state watchdogs,
comment auto-reply, retention telemetry.

REAL INCIDENTS from last night (2026-10-08 night ~ 10-09 morning, Beijing time):
1. At 03:19, my zero_view_alert.py script auto-flipped a scheduled-private
video to PUBLIC 9 hours early. The video was queued for 12:30 release
(private_queue.json status=waiting), but the script treated 'scheduled
private' as 'abandoned private' because it had 4 views, and its v2 policy
says 'views>0 during quarantine = auto-restore to public'. Root cause:
no exemption registry, no scheduled-private recognition.
2. 5 AI videos generated overnight ALL failed QC (static openings, bad loops),
0 uploaded. My pipeline_orchestrator.py only SCANS and logs 'GENERATE_NEEDED'
— it has no real executor. Nothing claimed the regen work.
3. A browser task generated a Veo video successfully but the file was never
retrieved (browser task has no filesystem access) — the handoff chain was
designed without file return.
4. VM rebooted at 06:10, watchdog auto-recovered MCP/tunnel/console at 06:11
— this one worked.

My questions (I need DIAGNOSIS, not advice):
1. For 7x24 unattended content production pipelines, what inspection/self-healing
architecture patterns are common in the industry? What is each pattern's
characteristic failure mode?
2. Under what conditions does auto-remediation flip from 'stopping the bleeding'
to 'causing the accident'? What circuit-breaker mechanisms exist for this?
3. Diagnosis: where is the single biggest risk in my infrastructure as described?

Output requirement: give me DIAGNOSTIC CONCLUSIONS (where the bottleneck/risk
is, in concrete terms). Do NOT give generic advice like 'strengthen monitoring'.
Every claim must be tied to one of my 4 real incidents above."
```

**存档**：回答存 `brain_review_patrol_20261009/askstudio.md`，
提问原文存 `brief_1_askstudio.md`。

---

### Brief 2 — LMArena（陪审团）

> ⚠️ 先完成 STAGE 1，把 Ask Studio 的诊断结论填入下方处再投喂。
> 串行投喂，防状态污染。

**browser.spawn_task 参数**

- **initial_url**: `https://arena.ai`
- **模式**: Side-by-Side，指定具名强模型（禁匿名 Battle，重大决策）
- **task**（完整，复制即用）：见下方 "Task 正文"

**Task 正文**

```
You are an impartial architecture jury. Compare the following 3 architecture
proposals SIDE BY SIDE for fixing my 7x24 unattended inspection infrastructure.
Deliver a VERDICT (which wins and why) — not suggestions.

BACKGROUND (real system, real incidents):
- 33 cron jobs, no unified state machine, no run fencing (verified: zero
flock/lockfile usage across all scripts).
- Real incidents last night: (1) auto-remediation script published a video
9h early (no exemption registry); (2) orchestrator is a read-only scanner
with no executor; (3) generated video file lost between browser task and
filesystem; (4) dead states with no owner.
- Prior review (2026-10-08) produced 14 MUST/NEVER specs; 4 landed
(dead-man's-switch, approval TTL, reject-storm alert, atomic writes);
3 NOT landed (idempotent videoId persistence, corruption-tolerant reads,
cron single-flight locks).



PROPOSAL A — Central orchestrator: one unified state machine + execution
engine; crons become dumb triggers; every state change goes through the
state machine; run fencing built in.

PROPOSAL B — Distributed watchdogs + event bus: keep existing crons, add
unified event log, exemption registry, circuit breakers per auto-remediation
script.

PROPOSAL C — Incremental hardening: no architecture change; only add
exemption mechanisms, timeout alerts, human confirmation points.

YOUR VERDICT MUST CONTAIN:
1. WINNER: A / B / C (exactly one).
2. WHY: 3 concrete reasons, each tied to a specific real incident above.
3. KILL CRITERIA: under what measurable condition would you REVERSE this
verdict (e.g. "if X happens, switch to Y").
4. FIRST 3 COMMITS: the first 3 concrete code/config changes to implement.

Reject vague praise. If a proposal cannot survive incident #1 (the 03:19
early-publish), say so explicitly and eliminate it.
```

**存档**：回答存 `brain_review_patrol_20261009/lmarena.md`，
提问原文存 `brief_2_lmarena.md`。

---

### Brief 3 — AI Studio（总工程师）

> ⚠️ 先完成 STAGE 1+2，把结论填入处再投喂。
> **必须选免费档**：URL 用
> `https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash`
> （Gemini 3 Flash Preview 是付费档，不可用；不建 API key、不开付费）

**browser.spawn_task 参数**

- **initial_url**: `https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash`
- **task**（完整，复制即用）：见下方 "Task 正文"

**Task 正文**

```
You are the staff engineer. Convert the following review conclusions into
PASTE-READY engineering specs. Output must be copy-pasteable into code/config —
NOT an advice document.

INPUTS:



CODE-VERIFIED FACTS (from my infra audit, treat as ground truth):
- zero_view_alert.py: EXEMPT_VIDEOS checked ONLY in the delete branch (24h),
NOT in the auto-restore branch (views>0 → PUT public). Exemption bypass
is a real code path, not hypothetical.
- private_queue.json still has gxYpY6BHYwc status=waiting for 12:30, but the
video went public at 03:19 — stale state; flip script will retry idempotently
but log wrong state.
- pipeline_orchestrator.py (70 lines): docstring says "actively drives",
code only logs actions and sys.exit(0). Zero executors in the system.
- Zero flock/lockfile/fcntl usage across all cron scripts (grep-verified).
- JSON writes: atomic_write in watchdog only; plain write_text in
zero_view_alert.py and private_flip.py (crash → half-written file).
- Exemption/intent scattered across 3 places with no unified registry:
EXEMPT_VIDEOS (hardcoded), quarantine.json (runtime), private_queue.json
(scheduled). Scripts cannot see each other's intent.
- Already-landed specs from prior review: dead-man's-switch (24h zero
uploads → alert), approval TTL (24h → auto-expire), reject-storm alert,
atomic writes (partial). NOT landed: idempotent videoId persistence,
corruption-tolerant reads, cron single-flight locks.

DELIVERABLES (paste-ready, numbered, no prose advice):
1. MUST/NEVER clauses for the patrol infrastructure, e.g.:
MUST-<number>: <one sentence, verifiable>. / NEVER-<number>: <one sentence>.
Cover at minimum: exemption registry checks on EVERY mutating branch;
scheduled-private invisibility to quarantine scripts; single-flight locks;
atomic writes + tolerant reads everywhere; audit log on every state change;
circuit breaker thresholds for Tier-3 auto-ops (delete/flip-public).
2. STATE MACHINE SPEC: states enum for a video lifecycle entry
(scheduled_private / intentional_private / quarantined / public /
deleted …), allowed transitions, and for EACH state: owner executor +
timeout + timeout action. Table format.
3. CIRCUIT BREAKER SPEC: exact conditions to auto-disable a cron
(counts + time windows as numbers), what alert fires, and the exact
recovery procedure (who re-enables, what verification first).
4. CONFLICT RESOLUTION: where the new specs conflict with the 4 already-landed
specs, state KEEP/MODIFY/DROP for each landed spec with one-line reason.

QUALITY GATE: if any clause is not directly implementable (no vague verbs
like "ensure", "strengthen", "consider"), it will be sent back. Use numbers,
file paths, and function names from the facts above.
```

**存档**：回答存 `brain_review_patrol_20261009/aistudio.md`，
提问原文存 `brief_3_aistudio.md`。

---

## 五、STAGE 4 落地任务（待 STAGE 1–3 完成后执行）

1. 三脑输出分别存档（`askstudio.md` / `lmarena.md` / `aistudio.md`，
目录 `brain_review_patrol_20261009/`）。
2. 判定共识：三脑独立同结论 → 转正为管线常量，写入代码/配置；
分歧点如实记录，parent 裁决。
3. 无论三脑结论如何，以下审计发现的 **P0 代码修复** 可立即执行
（不依赖三脑，属于已验证的 bug）：
- [] zero_view_alert.py：auto-restore 分支加豁免检查（F1）
- [] zero_view_alert.py：Pass 1 预过滤 private_queue.json waiting 项（F1）
- [] private_queue.json：清理 gxYpY6BHYwc 脏状态 waiting→published（F1）
- [] 统一 JSON 原子写 + 容忍读（F4，落地 AI Studio #6/#7）
- [] cron 单飞锁（F3，落地 AI Studio #8）
- [] 状态变更审计日志（F6）
4. GUI 同步：巡检基建变更同步到 Perpetua 控制台（用户立规矩）。

---

## 附：文件索引

- 本报告：`/home/hatch/data/perpetua/brain_review_patrol_20261009.md`
- 历史评审：`/home/hatch/data/perpetua/brain_review_pipeline/aistudio_specs.md`
（14 条 MUST/NEVER）、`askstudio_724_mechanism.md`
- 事故脚本：`/home/hatch/data/youtube/zero_view_alert.py`
- 扫描器：`/home/hatch/data/perpetua/pipeline_orchestrator.py`
- 看门狗：`/home/hatch/data/perpetua/dead_state_watchdog.py`
- 翻转器：`/home/hatch/data/youtube/private_flip.py`

---

## §五 范围追加（2026-10-09 07:58 用户指令）：判断层机制

### 背景
用户指出：本次评审发现的所有问题都是人工发现、人工发起三脑。现有自动化只检查"跑没跑"，不判断"做得对不对"。03:19 自动发布事故中，脚本按 v2 策略"正常执行"，无任何组件负责判断该操作是否正确。

### 追加的评审对象：判断层（Judgment Layer）
1. **动作审计账本**：所有自动 Tier 2+ 操作（改可见性、删视频、发视频）写带上下文的日志：谁干的、为什么、前一个状态是谁置的
2. **事故定义**：从"没跑"升级到"打架了"——A 脚本 1 小时前设 private，B 脚本现在翻 public；或同一视频 24 小时内被两个不同机制反向操作两次 → 自动记为 incident
3. **自动升级**：incident 按 blast radius 打分，Tier 3 级别自动生成三脑提问包（先备好待用户确认，或授权后直接开议会）
4. **并入 deep-dive**：23:49 每日复盘强制加"今日 incident 回顾"节，有 incident 必须走根因分析

### 三脑分工（追加）
- **LMArena**：把判断层作为第 4 个评估维度——三种架构方案（中央编排器/分布式+事件总线/渐进加固）哪种最能容纳"意图冲突检测"？还是有更好的模式？
- **AI Studio**：在 MUST/NEVER 之外，追加输出：incident ledger 的 schema 规格、意图冲突检测规则（带数字阈值）、自动升级的分级标准与触发动作
- **Ask Studio**（已投喂，如诊断未覆盖可在 STAGE 4 补问）："意图冲突"作为诊断框架是否成立

### 预期收益（用户确认）
1. 想法→工程规格（经三脑验证的常量，而非 Dash 的聊天建议）
2. 防 Dash 盲区（缺口本就是 Dash 设计时漏的，补救方案需独立评审）
3. 一次评审完整架构（避免二次搬运上下文、结论打架）

---

## §六 P0 修复落地记录（2026-10-09 08:06，用户授权先行）

> 用户指令：6 项 P0 修复不依赖三脑评审，先行落地。每项均已实测。

### 修复 1：zero_view_alert.py auto-restore 分支加豁免检查 ✅
- **改动**：`/home/hatch/data/youtube/zero_view_alert.py`，Pass 2 `elif views > 0:` 分支开头加 `if vid in EXEMPT_VIDEOS` 检查，命中则跳过 PUT public、移出隔离、记 `exempted_skip_restore`。
- **实测**：mock API 构造豁免视频 `d0CHRz8ubjk`（隔离中、私享、有 5 次播放）→ PUT 调用 0 次，inbox 记录 `exempted_skip_restore`。PASS。

### 修复 2：Pass 1 预过滤 private_queue.json waiting 项 ✅
- **改动**：Pass 1 前读取 `private_queue.json`，`status=waiting` 的 video_id 进本轮跳过集合；命中时 `continue` + 打印 `skip scheduled-private {id}` + 审计日志。
- **实测**：精确复现 03:19 事故条件（`gxYpY6BHYwc` waiting + private + 4 播放）→ 未进隔离、无告警。PASS。

### 修复 3：private_queue.json 脏状态清理 ✅
- **改动**：备份 `private_queue.json.bak-20261009-000623`；`gxYpY6BHYwc` 的 `status` 由 `waiting` 改为 `published`，加 `note` 说明"2026-10-09 03:19 被 zero_view_alert 提前公开（原定12:30 CST排期）"。
- **实测**：cat 确认 status=published，备份文件存在。PASS。

### 修复 4：全系统统一原子写 + 容忍读 ✅
- **改动**：新建 `/home/hatch/data/perpetua/json_safe.py`，复用既有 `atomic_json.py`（不重复造轮子），提供 `atomic_write_json` / `tolerant_read_json` 统一接口。`zero_view_alert.py` 的 `save_json`/`load_json`、`private_flip.py` 的 `save_queue`/`load_queue`/`send_inbox` 全部切换。
- **实测**：`py_compile` 全过；`atomic_write_json` 写入校验正确；`tolerant_read_json` 对正常/缺失/损坏三种输入分别返回正确值/default。PASS。

### 修复 5：cron 单飞锁 ✅
- **改动**：`json_safe.py` 新增 `run_lock(name)`（`fcntl.flock` 上下文管理器，锁文件 `/tmp/perpetua_locks/{name}.lock`，拿不到锁打印提示后 `sys.exit(0)`）。已接入 4 个高频脚本：`zero_view_alert.py`、`private_flip.py`、`pipeline_orchestrator.py`、`dead_state_watchdog.py`（后两个已备份 `.bak-20261009-000623`）。
- **实测**：后台持有 `test_lock_xyz` 锁时，前台同名 `run_lock` 打印"另一实例正在运行，本轮跳过"并 exit 0。PASS。

### 修复 6：状态变更审计日志 ✅
- **改动**：`json_safe.py` 新增 `audit_log(action, video_id, old_status, new_status, actor, extra)`，JSON Lines 追加到 `/home/hatch/data/perpetua/audit.log`。`zero_view_alert.py` 7 处埋点（skip_scheduled_private / quarantined / recovered / exempted_skip_restore / exempted_skip_delete / auto_restored_public / auto_delete_nonpublic）；`private_flip.py` 3 处埋点（flip_to_public / emergency_flip / queue_add）。
- **实测**：mock 跑一次 zero_view_alert（新视频进隔离），`audit.log` 新增 1 行，JSON 解析通过，含 ts/action/video_id/old→new/actor 全字段。PASS。

### 备注
- 实测过程中临时覆写了 `quarantine.json` / `zero_view_alerted.json`（运行时自愈文件，下轮扫描自动重建），测试后已重置为空。
- `audit.log` 为新建文件，测试行已保留（首条真实审计记录）。

---

## 七、STAGE 4 共识判定（2026-10-09 08:20）

### 三脑共识（独立同结论 → 转正为管线常量）
1. **中央编排器（方案 A）**：Ask Studio 的熔断器全是中心化原语 → LMArena 主席裁决 A 胜出 → AI Studio 按 A 落规格。三脑独立收敛。
2. **三态可见性标签**：Ask Studio 处方 → AI Studio MUST-2 落地（MANAGED_SCHEDULED_DRAFT/QUARANTINED_LOW_VIEW/STABLE_LIVE），NEVER-5 禁二进制。
3. **判断层**：用户提议 → LMArena 确认 A 最适配（"没有门的判断只是评论，不是控制"）→ AI Studio 输出 J-1 schema + 6 条检测规则 + 4 档升级。
4. **方案 C 死刑**：三脑一致淘汰——人工确认点在 7x24 无人值守中无法存活。

### 分歧点（记录，主席已裁决）
- LMArena 内部分歧：Claude 投 B（担心 A 的大爆炸重写风险），GPT 投 A。主席裁决 A，理由：B 的豁免注册表只修读者不修歧义；Claude 自己的 kill criteria（≥3 竞争真源）是 90 天滞后指标，不应等 90 天再选诊断已要求的结构。分阶段实施回答迁移风险：先 gate 危险动作（可见性翻转/发布）。

### 反转条件（熔断评审结论本身）
- 实施 2 周末 >20% Tier-2+ 操作绕过跃迁门 → 转 B
- orchestrator 连续 3 天 >15min/天不可用 → 转 B

### 落地任务清单
- [x] 6 项 P0（§六，2026-10-09 08:08 完成实测）
- [x] Commit 1（2026-10-09 08:35 实测）：pipeline_state.py（VideoState 7 状态、16 条跃迁、transition() 10 步、8 拒绝码、seq+prev_hash 链式审计）；zero_view_alert.py 写路径迁移（隔离/恢复/删除走 gated_mutation，豁免改读 exemption_registry.json）。实测 18/18（门）+ 11/11（迁移）
- [x] Commit 2（2026-10-09 08:40 实测）：executor.py（命令队列、MUST-7 幂等键、executed_commands.json、worker）；pipeline_orchestrator.py 改为分发器。实测 10/10（发射去重、worker 执行、执行后重放去重、门→执行器联动）
- [x] Commit 3（2026-10-09 08:42 实测）：artifact_receipt.json（sha256+byte_size）；MUST-8 门验证。实测 5/5（正常通过、篡改拒绝、无 receipt 拒绝 + R-SINK-5）
- [x] 判断层（2026-10-09 08:45 实测）：judgment.py（J-1 13 字段、6 条规则、severity 公式、4 档升级 LOG_ONLY/INBOX_ALERT/REVIEW_BRIEF/HALT_ACTOR）。实测 10/10（每条规则触发一次）
- [x] 熔断器（2026-10-09 08:47 实测）：circuit_breaker.py（CB-1~CB-4、trip/is_open/enable_cron、NEVER-3 人工重开）。实测 7/7
- [x] 冲突决议落地（2026-10-09 09:55 实测，用户原话"必须补，7×24 基石底座"）：
  - **任务 1：approval TTL lease 暂停**（aistudio.md "approval TTL MODIFY（lease 持有时暂停）"）
    - 新建 approval_lease.py：pause_lease/resume_lease（幂等）/effective_age_hours（挂钟年龄-累计暂停）/enforce_pause_limits（防滥用）
    - 触发点：pipeline_state.transition() 在 Tier-3 自动操作被 QUIET_WINDOW/BREAKER_OPEN 拒绝时 pause，跃迁成功时 resume；executor.process_queue() 命令失败（外部依赖未就绪）时 pause，成功时 resume；每次 pause/resume 写 audit.log（lease_paused/lease_resumed）
    - dead_state_watchdog.check_approval_ttl() 改用有效年龄；暂停中的条目不计 TTL；单次暂停超 12h（= 8h 静默窗口 + 50% 裕量，工程常量见模块 docstring）→ 按过期处理 + inbox 告警（lease_pause_expired）
    - 实测 14/14 + 集成验证：伪造 QUIET_WINDOW 下 cron:private_flip 翻转被拒 → awaiting_approval 条目 lease 自动暂停；25h 挂钟 - 5h 暂停 = 20h 有效年龄（<24h 不过期）
  - **任务 2：reject-storm → CB-3**（aistudio.md "reject-storm MODIFY（阈值换 CB-3）"）
    - circuit_breaker.py：record_rejection()（每次 gate 拒绝调用；QUIET_WINDOW/EXEMPT 是正常控制流不计入，否则每夜静默窗口误触发）；滑动窗口 60min≥10 或 24h≥25（AI Studio CB-3 原文常量）→ trip_reject_storm()
    - trip_reject_storm()：J-1 记 CB-3 incident（force_severity=4，judgment.py 新增 force_severity 参数 + resolve_incident()）；逐个 trip Tier-3 cron（zero_view_alert/private_flip，scope 精确到 cron——人工与管线 worker 不受影响）；CB-3 已开时不重复熔断（防 incident 刷屏）
    - CB-3 冷却期 30min：熔断后立即重开需 force=True 显式确认（半开试探语义）；NEVER-3 不变（只能人工）；recover_tier3_all() 一键人工恢复 + 关闭 incident + 清风暴窗口
    - 实测 21/21：9 次未达阈值 → 第 10 次熔断；Tier-3 transition 被 BREAKER_OPEN 拒绝；human/intake_worker 通道正常；冷却期内重开被拒；force 恢复后 incident resolved；非人工重开被 NEVER-3 拒绝
  - 回归：18/18（门）+ 10/10（执行器，3 次复跑稳定）+ 10/10（判断层）+ 11/11（zero_view_alert 迁移）+ 21/21（private_flip 迁移）；16 跃迁 MUST-1 全覆盖不受影响
  - 备份：pipeline_state.py / circuit_breaker.py / judgment.py / executor.py / dead_state_watchdog.py 均有 .bak-20261009-014652-lease-cb3
- [x] private_flip.py 写路径迁移（2026-10-09 09:25 实测）：MUST-1 全覆盖，巡检架构最后一个缺口关闭。
  - pipeline_state.py：INTENTIONAL_PRIVATE→STABLE_LIVE 跃迁 actor 加 `cron:private_flip`（tier3 标记；QUIET_WINDOW 自动生效）。备份 pipeline_state.py.bak-20261009-pf
  - private_flip.py（/home/hatch/data/youtube/，备份 .bak-20261009-gate）：check_and_flip/emergency_flip 经 `gated_flip_to_public()` 走 transition()；幂等键 `private_flip:{vid}:{scheduled_at}:{actor}`，duplicate=True 时不调 YouTube API；API 失败 → _admin_revert 回滚 gate 状态 + 清幂等索引（下轮可真实重试）；豁免检查保留（注册表+硬编码兜底，与 zero_view_alert 一致）；emergency 用 `human:emergency` actor（用户显式动作，不受静默窗口限制）
  - 实测 21/21（隔离环境 mock API）：正常翻转→published+gate STABLE_LIVE；重复翻转幂等不调 API；QUIET_WINDOW 拒绝保持 waiting；豁免跳过；emergency 静默窗口仍可翻；API 失败回滚+下轮重试成功
  - cron 路径确认：private-flip-scheduler（每 10 分钟）执行 `python3 /home/hatch/data/youtube/private_flip.py`，即本次修改文件；生产空跑验证通过（无 waiting 项静默结束）

### 评审产物
- 审计报告：brain_review_patrol_20261009.md（§一~§七）
- 三脑原文：brain_review_patrol_20261009/{askstudio,lmarena,aistudio}.md
