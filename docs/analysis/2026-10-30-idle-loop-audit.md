# 空转永久闭环 · 全量代码审计与防护

**审计对象**：`perpetua-vps-migration-20261016.tar.gz` → `code/`（179 个 .py，6.9 MB）  
**审计日**：2026-10-30  
**核心文件**：`auto_pipeline.py`（1521 行）、`queue_db.py`（678）、`dead_state_watchdog.py`（470）、`teaser_validate.py`、`pre_upload_qc.py`（1301）  
**产出**：`analysis/state_graph.json`（机械提取的状态图）、`patches/loop_guard.py`、`patches/test_no_idle_loop.py`

> ⚠️ **快照时效**：本包是 10-16 版本；生产环境 10-21 已加 `prompt_qc`（`auto_pipeline.py` 从 71,886 → 74,586 字节）。  
> 下文行号以 10-16 快照为准，**补丁一律按函数名定位，不按行号**。

> 🔴 **2026-10-31 结论更正（按 `af3ae58` / 10-31 代码复核）**：本文 3 个"永久空转"里 **2 个已在生产修复**，不要按本文去改。
>
> | 编号 | 本文结论 | 10-31 实际 | 修复点 |
> |---|---|---|---|
> | F1 `review_qid` 只写不清 | 永久锁死 | ✅ 已修 | `_maybe_auto_clear_stale_qid()` L619（3h 无答案自动清，上限 2 次）；rewrite/boundary 另有 `_guard_stale_qid_rewrite_boundary()` |
> | F2 `job_submitted` 无超时 | 静默永冻 | ✅ 已修 | `TRANSIENT` 已含该状态；`_sweep_stale_submitted()` L844；`_gen_poll_tick()` 72 轮升级 |
> | F3 `ready_to_upload` spacing 无上限 | 永久 20 分钟重试 | ❌ **仍成立** | `retryable` 分支（L2996）依旧无计数器 |
>
> `loop_guard.py` 的四要素不变量（执行者+超时+重试上限+进度指纹）仍然有效，可作为后续巡检规则保留。详见 `远程仓库对比-20261031.md` §3。



---

## 0. 结论先行

| 项          | 结果                                                        |
| ---------- | --------------------------------------------------------- |
| 机械提取状态数    | **35**                                                    |
| 真正会永久空转的状态 | **3 个**（`selected` / `job_submitted` / `ready_to_upload`） |
| 有界但纯浪费的循环  | 2 个（`review_passed` 重提、`qc` 重生成）                          |
| 对抗性仿真（现状）  | **6 个故障场景中 3 个 400 tick 不收敛**                             |
| 对抗性仿真（补丁后） | **6/6 全部收敛，最长 12 tick**                                   |

**根因不是"某个 bug"，是缺少一条不变量**：

> **任何非终态必须同时具备：执行者 + 超时 + 重试上限 + 进度指纹。四者缺一，就是潜在死循环。**

现有代码对 `review_timeout` 做了①②③，对 `generate_failed` 做了③，对 `job_submitted` **一个都没做**。

---

## 1. 三个真实的永久空转（附证据）

### F1 🔴 `review_qid` 只写不清 → SUSPECT 永久锁死

**证据链**

| 位置                     | 代码                                                                                 | 含义                   |
| ---------------------- | ---------------------------------------------------------------------------------- | -------------------- |
| `review_pending`       | `_pickup_only = bool(item.get("review_qid"))`                                      | 有 qid 就只捡答案，**永不重送** |
| `_fresh_review_answer` | `if not ga.evidence_fresh(ans_at, ga.TTL["review_answer"]): return ... ga.SUSPECT` | 答案 >60min 即判 SUSPECT |
| `_fresh_review_answer` | `if ans_dt < sub_dt: return ... ga.SUSPECT`                                        | 时钟偏移即判 SUSPECT       |
| `review_pending`       | SUSPECT 分支：`_suspect_review(...)` → `continue`                                     | **不清 qid、不计数、不归档**   |
| 全仓 grep                | `review_qid` 仅在 `rewrite_failed_loop` L629 被赋值，**无任何清除点**                          | 一旦脏，永久脏              |

**触发条件**（任一）

1. 管线停摆 >60 分钟（10-23 已有 80 分钟空转实证）→ 所有待审答案集体超 TTL
2. VPS 与 Ask Studio 时钟偏移 > 答案生成耗时
3. `prompt_reviewed.json` 的 `submitted_at` 与 `queue.json` 的 `answered_at` 不同源

**后果**：item 永久停在 `selected`。每轮 `review` 跑一次 → 读同一 qid → SUSPECT → escalate P2 → `continue`。  
**日志看起来一直在"工作"，实际零进度。** 这就是"空转永久闭环"的教科书形态。

---

### F2 🔴 `job_submitted` 无超时，且看门狗不覆盖

**证据链**

| 位置                                         | 代码                                                                                                                                        |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `dead_state_watchdog.check_pipeline_stuck` | `TRANSIENT = {"review_timeout","review_error","generate_failed","qc_failed","qc_error","selected","generating"}` — **不含 `job_submitted`** |
| `collect_musemain_results`                 | `if not muse_jid or not jid: continue` — 空 muse_jid 永久跳过                                                                                  |
| `collect_results`                          | `if not os.path.exists(rp): continue` — 结果文件永不出现则永不前进                                                                                     |
| 全仓                                         | 无任何 `job_submitted` 的 age 检查                                                                                                              |

**触发条件**

1. `muse_or_nano.route()` 返回 `backend="muse-main"` 但 `job_id` 为空（响应解析失败）
2. 后端任务丢失/队列被清
3. 生成成功但 done 文件写入失败（磁盘满）

**后果**：item 永久 `job_submitted`。看门狗认为它"不在监控范围"，连告警都没有。**静默永冻，比 F1 更危险。**

---

### F3 🔴 `ready_to_upload` 自环，无次数上限

**证据链**

| 位置                     | 代码                                                                                                               |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `collect_results`      | `for item in queue: if status=="ready_to_upload" and video_file: _auto_upload_private(item)` — 每 20 分钟一轮，**无计数** |
| `_auto_upload_private` | `retryable = "gateway:spacing" in res` → 保持 `ready_to_upload`                                                    |

**触发条件**：D1 网关的 last-upload 时间戳损坏/不前进，或 120 分钟间隔门禁的计算基准被其它进程反复刷新。

**后果**：每 20 分钟尝试一次，永久。**唯一"自救"是有人看日志**——但日志每轮都写"被间隔门禁拦下，下一轮重试"，看起来完全正常。

---

## 2. 两个有界但纯浪费的循环

### F4 🟠 生成失败重试不改 prompt

`collect_results` 的失败分支：

```python
retry = item.get("retry_count", 0)
if retry < 2:
    item["retry_count"] = retry + 1
    if isinstance(item.get("review_score"), (int, float)):
        item["status"] = "review_passed"   # ← prompt 一个字没改
```

`retry_count` 有上限（2），所以**不是无限循环**；但三次提交的是**同一个 SHA1**，  
后端必然三次都返回 `sealed_prompt_resubmission_blocked`。

- 实测代价：`video_quota.json` 记 3.0，实际只试了 1 条；80 分钟墙钟空转（作战书 §三已实证）
- 代码注释 L1482 自认："换动词重试从未实现"

### F5 🟠 QC 重生成同样不改 prompt

`collect_results` 的 QC 分支：`qc_retry += 1` → `status = "review_passed"` → 重提同一 prompt。  
上限 2 次，有界，但**同样零信息增益**。生成是随机的，重提同 prompt 只是重掷骰子，  
正确做法是**并行 3 条择优**（`viral_engineering_v2.md` §3.2 已论证），不是串行重掷。

---

## 3. 其余隐患（不致命，但会让队列慢性腐烂）

| #  | 问题                                | 位置                             | 后果                                                                                      |
| -- | --------------------------------- | ------------------------------ | --------------------------------------------------------------------------------------- |
| H1 | `auto_resubmitted` 自增但**从不作终止条件** | `dead_state_watchdog` L263     | 只用于 `select_topics` 释放 topic → 同一 topic 可被重新选中，产生第二条 item，僵尸并存                          |
| H2 | 失败项永不清理                           | 全仓                             | `review_timeout`/`generate_failed`/`qc_failed` 永久留在队列；`load_queue` 线性增长，每轮 collect 全量遍历 |
| H3 | 路由异常即判 `generate_failed`，但任务可能已提交 | `submit_jobs` L835-840         | 孤儿任务占额度，产出无人认领                                                                          |
| H4 | `review_budget_consume` 读-改-写无锁   | `auto_pipeline` L504-519       | 两个 review 并发时超扣预算                                                                       |
| H5 | `SHIM_TIMEOUT_HOURS = 720`        | `queue_db.py` L72              | event_bus 行可挂 30 天才被 sweep                                                              |
| H6 | `selected` 的 6h 静默跳过              | `dead_state_watchdog` L254-257 | 只要 `review_triggered_at` 被反复刷新，永远不告警（F1 的帮凶）                                            |

---

## 4. 状态机全表（35 状态 × 四条件）

✓=具备，✗=缺失，—=不适用

| 状态                                   | 执行者                 | 超时             | 重试上限          | 终态出口                             | 判定                |
| ------------------------------------ | ------------------- | -------------- | ------------- | -------------------------------- | ----------------- |
| `selected`                           | review_pending      | ✗（6h 静默跳过反而掩盖） | ✗             | 有（→review_passed/failed/timeout） | **F1**            |
| `review_passed`                      | submit_jobs         | ✗              | retry_count=2 | 有                                | 有界浪费 F4           |
| `review_failed`                      | rewrite_failed_loop | ✗              | rounds=2      | 有                                | 可接受               |
| `rewrite_round1/2`                   | review_pending      | ✗              | rounds=2      | 有                                | 可接受               |
| `review_timeout`                     | watchdog            | ✓ 2h           | ✗             | 有                                | 但复位不清 qid → 回到 F1 |
| `review_error`                       | watchdog            | ✓ 2h           | ✗             | 仅告警                              | 半闭环               |
| `job_submitted`                      | collect\_*          | **✗**          | ✗             | **无**                            | **F2**            |
| `generated`                          | collect_results     | —              | —             | 有                                | 瞬时态               |
| `qc_passed`                          | —                   | —              | —             | 立即改写                             | 瞬时态               |
| `ready_to_upload`                    | collect_results     | **✗**          | **✗**         | 有                                | **F3**            |
| `uploaded_private`                   | flip scheduler      | ✗（外部脚本）        | ✗             | —                                | 快照外，未审计           |
| `upload_failed`                      | —                   | —              | —             | 终态                               | ✓                 |
| `qc_failed` / `qc_error`             | watchdog            | ✓ 2h           | qc_retry=2    | 终态                               | ✓                 |
| `generate_failed`                    | watchdog            | ✓ 2h           | retry=2       | 终态                               | ✓                 |
| `teaser_validation`                  | teaser_validate     | ✗              | —             | 有                                | 待补                |
| `teaser_generating`                  | teaser_validate     | **✗**          | ✗             | 有                                | 同 F2 形态           |
| `teaser_awaiting_check`              | 人工                  | ✗              | —             | 有                                | 设计如此              |
| `archived` / `uploaded` / `rejected` | —                   | —              | —             | 终态                               | ✓                 |

---

## 5. 防护设计：`loop_guard.py`

不重写业务逻辑，只加一条**横切不变量**。三个函数：

```python
tick(item, state, max_attempts, ttl_hours, run_id)   # 计数 + 判龄，返回 proceed/retry/fail/expire
reset(item, state)                                    # 进度实质变化时清零
check_progress(item, max_same=3)                      # 进度指纹：连续 3 次实质状态不变 → 判空转
```

**为什么需要"进度指纹"**：超时和计数都是**你预先想到的**循环才能拦住。  
指纹是兜底——不管从哪条路径绕回来，只要 `(status, prompt_sha1, qid, job_id, 计数器)` 连续 3 轮完全一致，  
就判定它在空转，强制终局。**这是"绝不会"的唯一技术保证。**

指纹刻意**排除 `updated_at`**：时间戳每轮都变，会掩盖空转（这正是现有代码看起来"一直在动"的原因）。

---

## 6. 补丁（按函数名定位，最小改动）

### P1 · 修 F1（必做）

`review_pending` 的 SUSPECT 分支，把 `continue` 改成：

```python
if fverdict == (ga.SUSPECT if ga else "SUSPECT"):
    n = int(item.get("suspect_count", 0)) + 1
    item["suspect_count"] = n
    _suspect_review(topic, qid, "stale_or_qid_mismatch", f"...(n={n})")
    # 关键：清掉脏 qid，下一轮允许重新送审拿新答案
    item.pop("review_qid", None)
    item.pop("review_triggered_at", None)
    if n >= 3:
        item["status"] = "archived"
        item["archive_reason"] = "review_suspect_x3"
        pipeline_log("select", "error", f"SUSPECT 连续3次→归档: {topic}", 0)
    else:
        pipeline_log("select", "ok", f"SUSPECT 第{n}次，已重置待重送: {topic}", 0)
    changed = True
    continue
```

**验证点**：清 qid 后，下一轮走 `_pickup_only=False` 分支，重新扣预算送审；若仍 SUSPECT，  
3 次后归档。**任何情况下 ≤3 轮离场。**

### P2 · 修 F2（必做）

`dead_state_watchdog.check_pipeline_stuck`：

```python
TRANSIENT = {"review_timeout", "review_error", "generate_failed",
             "qc_failed", "qc_error", "selected", "generating",
             "job_submitted", "teaser_generating"}      # ← 新增两个
...
if st in ("job_submitted", "teaser_generating") and age_h >= 4:
    it["status"] = "generate_failed"
    it["generate_error"] = f"job_timeout_{age_h:.1f}h"
    it["updated_at"] = now().isoformat()
    changed = True
    auto_fixed.append(f"{topic}（{st} {age_h:.1f}h 无结果 → generate_failed）")
    continue
```

**超时选 4h 的依据**：H3 单条 10s 视频正常 5–20 分钟出片；80 分钟是已知最坏重试窗口；  
4h 留 3 倍余量，不会误杀。

### P3 · 修 F3（必做）

`_auto_upload_private` 的 spacing 分支：

```python
retryable = "gateway:spacing" in res
if retryable:
    n = int(item.get("upload_attempt", 0)) + 1
    item["upload_attempt"] = n
    if n >= 3:
        item["status"] = "upload_failed"
        item["upload_result"] = f"spacing_x{n}: {res[:200]}"
        pipeline_log("publish", "error",
                     f"间隔门禁连续{n}次拦截→放弃: {item['topic']}", 0)
        notify_inbox("auto_upload_failed",
                     f"【间隔门禁连续 {n} 次】{item['title'][:60]}", {"topic": item["topic"]})
        return False, False
    pipeline_log("publish", "ok",
                 f"间隔门禁拦截（第{n}/3次），下一轮重试: {item['topic']}", 0)
```

### P4 · 修 F4（必做）

`collect_results` 生成失败分支，在 `retry_count += 1` 之前加：

```python
err = str(res.get("error", ""))
if "integrity_sealed" in err or "sealed_prompt_resubmission_blocked" in err:
    # 同 prompt 重提必然再被拒：直接终局，不烧配额
    item["status"] = "generate_failed"
    item["generate_error"] = err[:200]
    pipeline_log("generate", "error",
                 f"prompt 已封存，禁止原样重提: {item['topic']}", 0)
    changed = True
    continue
```

**收益**：单条被拒从"烧 3 次配额 + 80 分钟"降到"烧 1 次 + 20 分钟"。

### P5 · 修 F5（建议）

QC 重生成改为**并行 3 候选择优**，而不是串行重掷同一 prompt。短期若不动架构，  
至少把 `qc_retry` 从 2 降到 1——同一 prompt 重掷两次的期望收益接近 0，但成本是 2 倍。

### P6 · 兜底：全局巡检（强烈建议）

新增 `loop_watchdog.py`，每 30 分钟跑一次：

```python
from loop_guard import sweep
POLICY = {
    "selected":          (3, 6),
    "job_submitted":     (2, 4),
    "ready_to_upload":   (3, 8),
    "teaser_generating": (2, 6),
    "review_passed":     (3, 12),
}
alerts = sweep(queue, run_id=run_id, policies=POLICY)
for topic, st, action, reason in alerts:
    # action=fail → archived；expire → 对应超时态
```

这一层**不依赖任何业务知识**，即使以后新增状态忘了写超时，也会被指纹抓出来。

---

## 7. 验证：对抗性仿真（已跑通）

`patches/test_no_idle_loop.py`，5 条 item × 最多 400 tick，逐场景注入单一故障：

| 故障场景            | 现状收敛  | tick | 现状终态              | 补丁收敛 | tick | 补丁终态              |
| --------------- | ----- | ---- | ----------------- | ---- | ---- | ----------------- |
| 答案永久过期（SUSPECT） | **否** | 400  | `selected`        | 是    | 3    | `archived`        |
| 后端永不返回          | **否** | 400  | `job_submitted`   | 是    | 12   | `generate_failed` |
| 同 prompt 被封存    | 是     | 2    | `generate_failed` | 是    | 2    | `generate_failed` |
| 网关永久 spacing    | **否** | 400  | `ready_to_upload` | 是    | 9    | `upload_failed`   |
| QC 永久不通过        | 是     | 2    | `qc_failed`       | 是    | 2    | `qc_failed`       |
| 全故障叠加           | **否** | 400  | `selected`        | 是    | 3    | `archived`        |

```
结论： PASS — 每个故障场景在补丁后均有限 tick 内落到终态
```

**这组数字就是"绝不会空转永久闭环"的证明**：3 条现存死路全部闭合，且新增路径由指纹兜底。

> 诚实边界：这是**状态机模型仿真**，不是对生产代码的集成测试。  
> 它证明的是"控制流在有界步数内必然离场"，不证明"补丁在真实环境无副作用"。  
> 上线仍需按 §8 灰度。

---

## 8. 上线顺序（幂等、可回滚）


| 步 | 动作 | 回滚 | 验证 |
|---|---|---|---|
| 1 | 备份 `auto_pipeline.py` / `dead_state_watchdog.py` 到 `.bak-20261030-loopguard` | `cp` 回去 | `diff` 仅新增块 |
| 2 | 上 P2（看门狗超时）| 单文件回滚 | 造一条 5h 前的 `job_submitted`，跑一次看门狗 → 应变 `generate_failed` |
| 3 | 上 P3（upload_attempt）| 单文件回滚 | 把 `upload_attempt` 手动置 3 → 跑 collect → 应 `upload_failed` |
| 4 | 上 P1（SUSPECT 清 qid）| 单文件回滚 | 造一条 `review_qid=脏` 的 selected → 跑 review → 应重置或归档 |
| 5 | 上 P4（封存短路）| 单文件回滚 | 用 `run-once --test-topic` 造一条，观察是否只烧 1 次配额 |
| 6 | 上 P6（全局巡检，**shadow 模式**：只告警不处置）| 停 cron | 跑 7 天，对比告警与真实卡死 |

**禁止一次全上**。P1 改变了 `review` 的预算消耗节奏（会多送审），必须单独观察一天。

---

## 9. 这套方案**没有**覆盖的部分

| 未覆盖 | 原因 | 建议 |
|---|---|---|
| `youtube/private_flip.py` | 不在本快照（在 `/home/hatch/data/youtube/`） | 单独审计 `waiting` 状态是否有超时 |
| `vps_console` 前端轮询 | 只读，不写状态 | 低风险 |
| `muse_or_nano.route()` 内部 | 依赖外部 SDK | 需单独看它是否幂等（提交失败是否会重试双发） |
| 并发写 `pipeline_queue` | SQLite 有 WAL + busy_timeout，但 `load→改→save` 非事务 | 建议改 `queue_db` 提供 `update(topic, mutator)` 原子接口 |
| 磁盘满 / 权限 | 会让 done 文件写失败 → 触发 F2 | P2 的超时能兜住，但会丢失成品 |

---

## 10. 一句话

> 现有系统不是"有 bug"，是**缺一条不变量**：非终态必须有执行者、超时、重试上限、进度指纹。
> 三个状态缺了这条不变量，就产生了三个"看起来在跑、实际零进度"的闭环。
> `loop_guard.py` 把这条不变量变成代码，`test_no_idle_loop.py` 把它变成可复跑的证据。
