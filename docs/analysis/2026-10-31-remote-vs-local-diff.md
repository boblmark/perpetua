# 远程仓库 vs 本地工作区 · 深度对比

> 对比对象：`github.com/boblmark/perpetua` @ `af3ae58`（2026-10-31 00:31，main）
> 本地基准：`J:/project/Perpetua`（文档）+ `analysis/src/perpetua-vps-migration-20261016/code`（10-16 快照）
> 复现方式：本地镜像 `J:/project/Perpetua/repo/`（`git clone` 于 2026-10-31，`./sync-remote.sh` 可复现），全部结论可用行号/命令复核

---

## 0. 一句话结论

**远程是「代码真相源」，本地是「分析真相源」，两者各自领先一半，且已经漂移了两周。**
上一轮《空转闭环审计》基于 10-16 快照得出的 3 个死循环，**2 个已在远程修好，1 个仍在**；而远程的**目标函数与测量链**仍然是坏的——只是坏法和我上次说的不一样。

---

## 1. 规模与版本

| 维度 | 本地 | 远程 main | 差异 |
|---|---|---|---|
| Python 文件 | 179 | **347**（vendor 43） | +168 |
| Python 行数 | 41,417 | **82,012**（vendor 9,410） | **+98%** |
| 文档 md | 27（根目录） | 248 | +221 |
| 提交数 | 无 git | 129 | 全部 `auto-sync` |
| 最新提交 | 10-16（迁移包） | **10-31 00:31** | 领先 15 天 |
| `.git` 体积 | — | 45 MB | 工作树仅 7.5 MB → 历史占 83% |

**核心文件膨胀比**（同一文件，10-16 → 10-30）：

| 文件 | 本地 | 远程 | 倍数 |
|---|---|---|---|
| `auto_pipeline.py` | 1,521 | **3,198** | 2.10× |
| `dead_state_watchdog.py` | 470 | **1,601** | 3.41× |
| `queue_db.py` | 678 | 778 | 1.15× |
| `pre_upload_qc.py` | 1,301 | **1,301** | **1.00×（字节级相同）** |

> 最后一行是关键：两周内流水线涨了 2.1 倍，**QC 一行没动**。所有工程投入都在"让系统不卡"，没有一行在"让 QC 有预测力"。

---

## 2. 结构对比：远程多出了 5 层能力

本地文档描述的仍是「单频道 × 单平台 × 视频工厂」。远程已经变成**多租户 SaaS**：

| 新增层 | 位置 | 规模 | 说明 |
|---|---|---|---|
| 多平台分发矩阵 | `perpetua/distributor/` | 55 py / 11,186 行 | 11 个平台 uploader（B站/抖音/快手/小红书/视频号/微博/腾讯/百家号/虎扑/支付宝/TikTok/YouTube），Playwright 驱动 |
| 爆款雷达 | `perpetua/radar/` | 9 py / 1,193 行 | 25 个竞品池三档分层（tier1 500–5k 粉 / tier2 1w–10w / tier3 10w+），SQLite 仓库，**只读** |
| 多租户 + 计费 | `tenants/`、`billing/` | 232 行 | tenant manager + 计费 |
| VPS 控制台 | `perpetua/vps_console/` | 7 py / 4,761 行 | `console_server.py` 176 KB，含 `/api/exec`（见 §6.6） |
| MCP 服务 | `mcp_server/server.py` | 986 行 | 对外暴露 MCP 工具面 |
| 蜂群/议会 | `brain_review_*`（8 个目录） | — | 「四脑议会」决策留痕，代码注释里大量 `D2026101x-00x` 决议号 |

**架构定性**：从「一个频道的自动化脚本」长成了「一个带分发矩阵、租户、计费、控制台的平台」，但**内容质量层没有跟着长**。

---

## 3. 我上一轮审计的复核（重要更正）

上一轮我基于 10-16 快照判定 3 个永久空转。远程最新代码的实际情况：

| 编号 | 问题 | 远程状态 | 证据 |
|---|---|---|---|
| **F1** | `review_qid` 只写不清 → SUSPECT 永久锁死 | ✅ **已修** | `_maybe_auto_clear_stale_qid()`（L619）3h 无答案自动清 qid，上限 2 次，第 3 次转人工；`_guard_stale_qid_rewrite_boundary()`（L656）对 rewrite/boundary 另设守卫。注释标 `2026-10-16 P1-1（四脑议会 anti-idle）`、`Batch B 2026-10-29` |
| **F2** | `job_submitted` 无超时，看门狗不覆盖 | ✅ **已修** | `TRANSIENT` 加入 `job_submitted`（`dead_state_watchdog.py` L393）；`_sweep_stale_submitted()`（L844）认领超时清道夫；`_gen_poll_tick()` 72 轮升级；判龄改用 `submitted_at` 而非 `updated_at`（X1，2026-10-28） |
| **F3** | `ready_to_upload` 间隔门禁无次数上限 | ❌ **未修** | 见下 |

**F3 逐行核实**（`auto_pipeline.py` L2988–3003）：

```python
_ur = int(item.get("upload_retries", 0) or 0)
if _ur < 2:                       # ← 只对 transient（5xx/网络）计数
    ...
if retryable:                     # ← gateway:spacing / [gate1:错峰] 走这里
    pipeline_log(..., f"自动上传被间隔门禁拦下，下一轮重试", 0)
    # 无计数器、无上限、无时间戳
```

且 L2401 的驱动循环本身不带任何次数：

```python
for item in queue:
    if item.get("status") == "ready_to_upload" and item.get("video_file"):
        ok, _ = _auto_upload_private(item)
```

**结论：`spacing` 分支仍是每 20 分钟一次的永久重试。** 网关时间戳一旦损坏，就是无声的无限循环——和 10-16 版本完全一样。

> 我上次说「三个都是永久空转」——按 10-30 代码，**这个判断对 2 个已过期，对 1 个仍成立**。这是本地基准落后两周的直接代价。

---

## 4. 远程仍然坏的 6 件事（按危害排序）

### 4.1 测量链 100% 失明，但报告说「样本不足」

连续 4 天的进化报告（`evolution_reports/`）：

| 日期 | 发布 | 总播放 | GREEN | RED | 缺数 | 结论 |
|---|---|---|---|---|---|---|
| 10-27 | 2 | 175 | 0 | 0 | 1 | 样本不足 |
| 10-28 | 3 | 855 | 0 | 0 | **3** | 样本不足 |
| 10-29 | 4 | 2,055 | 0 | 0 | **4** | 样本不足 |
| 10-30 | 3 | 1,356 | 0 | 0 | **3** | 样本不足 |

**发布数 ≠ 0，缺数 = 全部。** 而 `derive_findings()`（`daily_evolution.py` L297）：

```python
if not green and not red and not watching:
    return ["样本不足（48h 窗口无发布），维持现有策略"]
```

`missing` 不在判断条件里 → **「测不到」被写成「没发布」**。

根因在 `analyze()`（L267–275）：

```python
if dur is None:      v["verdict"] = "缺数"      # 时长取不到
elif v["avd"] is None: v["verdict"] = "缺数"    # Analytics 取不到
```

而两个采集函数都是 `try/except → return {}`，异常只 `print("WARN: ...")` 到 stdout，**不进报告、不进 ledger、不告警**。所以：

> 「criteria.json 未变更（无新发现）」不是"没学到"，是**根本没读到**。反馈环断在第一步，不是第三步。

这是比"目标函数阈值太高"更硬的故障：阈值高只是梯度为 0，采集失败是**连样本都没有**。

### 4.2 目标函数被换掉了，但换成了一个更没意义的靶

旧：`VIRAL_VIEWS_THRESHOLD = 100_000`（历史极值 30,676 的 3.26 倍，0/513 达标）。
新口径（2026-10-11 起，写在每份报告抬头）：**teaser `AVD≥75% 且 views≥30` = GREEN**。

- 从「3.26 倍历史极值」跳到「30 播放」，不是校准，是**把靶子挪到地上**。
- `views≥30` 只能证明"被分发了"，不能区分"爆"和"没死"。
- 更关键：**GREEN 从来没出现过**（4 天 0 条），因为 AVD 拿不到。新靶子也没打中过。

我上次建议的 P90（当前 2,055 / 活跃期 2,345）在代码里**不存在**——`grep -r "P90\|percentile"` 只命中 `calibrate_weights.py` 的 Top10% 统计，不是判定口径。

### 4.3 13 个「学习/治理」模块是孤岛，只在冻结副本里

`pipeline/`（90 py，**最后提交 2026-10-13**）与 `perpetua/`（251 py，10-30 每天同步）是两个并存副本。以下 13 个文件**只存在于 10-13 的 `pipeline/`，活树 `perpetua/` 里没有**：

```
objective_function.py  evolution_engine.py  causal_db.py  evolution_freeze.py
daily_sop.py  kill_switch.py  firewalls.py  intent_firewall.py
signal_dashboard.py  dna_api.py  dna_platform.py  human_creativity.py
behavior_circuit_breaker.py
```

且它们的 import 只在彼此之间闭环（`causal_db → objective_function`、`evolution_engine → causal_db`、`daily_sop → evolution_engine`），**活流水线一行都不引用**。

> 也就是说：`objective_function.py`（我上次说"改一行常量"的那个文件）**根本不在生产树上**。它躺在两周期前的快照里，谁改它都不会影响线上。这是"学习闭环没接上"最机械的证据。

### 4.4 双副本必然导致改错文件

`pipeline/` 与 `perpetua/` 同名文件行数对比：`auto_pipeline.py` 1,167 vs 3,198、`dead_state_watchdog.py` 446 vs 1,601。**同名的两个文件，差 2.7 倍和 3.6 倍。**

`pipeline/` 里保留着 `objective_function.py` 这类"看起来很重要"的模块，任何人（包括 AI）搜到它都会以为那是生产口径。这是**结构性误导**，不是疏忽。

### 4.5 `hook_strength()` 重新引入了已被自己证伪的特征

`auto_pipeline.py` L236 新增钩子评分（0–100，用于排序）：

| 加分项 | 分值 | 项目自己的结论 |
|---|---|---|
| 冲突动词（slam/refus/block…） | +40 | ✅ 与 FE-OLS `verb_tier_s` RR=2.46 一致 |
| 反转/报应线索 | +30 | ✅ 与 `has_dash_twist` RR=1.31 一致 |
| **含数字** | **+10** | ❌ `own_data_calibration.md` §2.2「数字标题有害」；作战书 `has_number` p=0.9228 |
| 具体物件（coupon/scanner/gate…） | +10 | 未验证 |
| 长度 20–120 | +10 | 未验证 |

同一仓库里，`own_data_calibration.md` 说数字有害，`hook_strength()` 给数字加分。**两个模块对同一特征给出相反权重，且没有仲裁。**

### 4.6 仓库卫生与暴露面

| 问题 | 证据 | 影响 |
|---|---|---|
| 129 次提交全是 `auto-sync <时间戳>` | `git log` | 无变更语义，`git bisect` 失效，无法回溯"哪次改坏了" |
| 二进制 tarball 进 git | `perpetua/crons/cron_export_*.tar.gz` ×3（3 小时内 3 份） | `.git` 45 MB，工作树仅 7.5 MB；每夜 +3 份 |
| `.gitignore` 忽略 `*.json` | 但仍有 5 个 json 被强推 | 数据不进版本 → 结论不可复现 |
| **runonce 任务暴露内网信息** | `revert-exec-temp-allow-20261022__runonce@…md` 含 VPS 公网 IP、`ProxyCommand 198.19.x.x:3128`、SSH key 路径、`chat_id`、`device_id` | 公网仓库；虽有 key 无密码，但内网拓扑 + 跳板地址完整泄露（本文档推送版已脱敏，原值见仓库内该 runonce 文件） |
| `accounts.ini` 有 `cookies =` 字段 | `xhs_uploader/accounts.ini`（32 字节，值为空模板） | 目前未泄露真实 cookie，但**只要有人填了就自动进公网** |
| 控制台存在 `/api/exec` | `vps_console/console_server.py`；2026-10-22 曾临时放行单 IP，靠 runonce 回滚 | 远程命令执行面 + 靠定时任务回滚 = 单点失误即长期敞开 |

---

## 5. 本地独有的东西（远程没有）

| 资产 | 状态 |
|---|---|
| `爆款实验科学基础设施-v1.0.md` | 只本地 |
| `爆款公式与概率分析.md` | 只本地 |
| `播放量提升方案-v1.0.md`（六层 + 验收 + Kill 条件） | 只本地，**远程代码里能看到 L0 已落地**（见下） |
| `空转闭环审计-20261030.md` + `loop_guard.py` + 对抗测试 | 只本地，且**部分结论已过期**（§3） |
| `analysis/`（288 条竞品复算、ICC 方差分解、MH 分层脚本） | 只本地，可重跑 |
| `FEASIBILITY.md` / `channel-reputation-and-feasibility.md` | 只本地 |

**远程确实吸收了我上一轮方案的一部分**——`auto_pipeline.py` L2417 有明确注释：

```
L0（2026-10-30 用户批准播放量方案 L0-4）：模型侧 integrity/sealed 拒答是内容性拒答；
review_passed 重提走 stored prompt（不换动词），原样重提必再拒、纯烧配额，故直接走耗尽终局
```

即 **L0-4「封存短路」已上线**（同 prompt 被拒 → 不再重试，直接终局 + arena 手工兜底）。这是我上次列的"烧 3 倍配额"那条，已经闭环。

---

## 6. 两张表说清差异

### 6.1 谁该看哪个

| 你要回答的问题 | 看哪里 |
|---|---|
| 线上现在到底怎么跑 | **远程 `perpetua/`**（唯一可信） |
| 为什么播放量上不去 | 本地 `播放量提升方案-v1.0.md` + `analysis/*.py` |
| 目标函数是什么 | 远程 `daily_evolution.py`（不是 `pipeline/objective_function.py`） |
| 有没有死循环 | 远程 `perpetua/auto_pipeline.py`（3,198 行版） |
| 竞品数据怎么算的 | 本地 `analysis/mh_levers.py`、`variance_decomp.py` |

### 6.2 必须废弃的东西

| 资产 | 处置 |
|---|---|
| 本地 `perpetua-vps-migration-20261016/` | 标 `ARCHIVED`，只作历史对照，禁止作为改动基线 |
| 远程 `pipeline/`（10-13 副本） | 删除或改名 `_frozen_20261013/`，否则永远有人改错 |
| 远程 `crons/*.tar.gz` | 移出版本控制，只保留最新 1 份到对象存储 |
| `hook_strength()` 的数字加分 | 与 `own_data_calibration.md` 冲突，需仲裁后二选一 |

---

## 7. 如果只做三件事

| # | 动作 | 验收（可机械检查） | 工期 |
|---|---|---|---|
| **1** | 修测量链：`_fetch_durations` / `_analytics_avp` 失败时写 ledger + 告警，不再 `print` 后静默；`derive_findings` 把 `missing` 计入判断，措辞改为「N 条已发布但不可测」 | 次日报告 `缺数 ≤ 1` 且 GREEN+RED ≥ 2 | 1 天 |
| **2** | 删掉 `pipeline/` 副本（或改名冻结），把 `objective_function.py` 里唯一的真常量搬进 `perpetua/`，阈值改滚动 P90 | `grep -r "100_000" perpetua/` 为空；`is_viral` 有正负样本 | 半天 |
| **3** | F3：`retryable` 分支加 `upload_spacing_retries`，上限 6 次（≈2h）后转 `upload_gate_held` 人工放行 | 单条 spacing 重试次数可查、有上限 | 半天 |

---

## 8. 诚实边界

1. **远程是快照，不是全量**。`perpetua/` 由 auto-sync 从 `/home/hatch/data/perpetua` 同步，同步脚本白名单之外的文件我看不到（`crons/*.tar.gz` 显示调度器还有 `space_action` 类任务，其执行体不在仓库内）。
2. **§4.1 的"采集失败"是推断**。我确认了代码路径会把异常吞成 `{}`、报告会把 `missing` 排除在判断外、4 天数据 100% 缺数；但**没有拿到 `WARN:` 的原始 stdout**，无法区分是 duration 失败还是 AVD 失败（两者都会导致同样结果）。要定论，去 VPS 抓一次 `daily_evolution.py` 的 stdout。
3. **§3 的"已修"只证明代码写了，不证明线上在跑**。`dead-state-watchdog` 的 cron 已进 `_archive/`，改由 `systemd_units/dash-dead-state-watchdog.service` 承担——**该 unit 是否 enabled 我在仓库里看不到**。若未启用，F1/F2 的修复等于没有守夜人。
4. 本地 `analysis/src/` 已占 59 MB（含克隆），确认结论后可删。
