# F3 / F4 / F5 · 上传侧重试上限补丁

**基线**：`af3ae58`（2026-10-31）· `perpetua/auto_pipeline.py`（3,198 行）
**补丁**：`analysis/patches/f3_f4_f5_upload_retry_cap.patch`（189 行 diff，`git apply --check` 通过）
**测试**：`analysis/patches/test_upload_retry_cap.py`（跑真实模块，非仿真）

---

## 1. 三条路径的共同缺陷

`collect_results()` 每 20 分钟跑一轮，把所有非终态条目重新驱动一遍。以下三条分支
**只打日志、不计数**，故障持续时条目永远不离开非终态：

| 编号 | 位置 | 触发条件 | 现状 |
|---|---|---|---|
| **F3** | `_auto_upload_private` L2996–3000 | 网关返回 `gateway:spacing` / `[gate1:错峰]` | `retryable=True` → 状态留 `ready_to_upload`，无计数器 |
| **F4** | `collect_results` L2380–2387 | `_enqueue_private_flip` 返回 `throttle_deferred` | `throttle_defer_count` **只加不比**（全仓仅 2 处 `+1`、2 处 `pop`，无任何比较） |
| **F5** | `collect_results` L2395–2398 | `_enqueue_private_flip` 抛异常 | 只 `pipeline_log`，连计数都没有 |

看门狗兜底不住：`TRANSIENT` 集合不含 `ready_to_upload` / `uploaded_no_queue`，
落到 C4 分支（L492–496）——**>168h 只告警、不改状态**。即"7 天后有人知道，但机器继续转"。

---

## 2. 改法

### F3：按"等了多久"判，不按"试了几次"判

```python
MAX_UPLOAD_SPACING_HOURS = 6.0     # 4h 间隔门 + 2h 缓冲
MAX_UPLOAD_SPACING_RETRIES = 40    # 仅防时钟异常（20min 一轮时 = 13h）

_now = now_iso()
if not item.get("upload_spacing_first_at"):
    item["upload_spacing_first_at"] = _now
_age_h = 距首次拦截的小时数
_give_up = (_age_h >= MAX_UPLOAD_SPACING_HOURS) or (_sr > MAX_UPLOAD_SPACING_RETRIES)
```

**为什么不能用次数**：`teaser_validate.py` L350 写明 `[gate1:错峰]` 是
"**4 小时/120 分钟发布间隔门：时间到了自然解除**"。这是合法等待，不是故障。
第一版补丁用 `MAX=6`（6×20min=2h），**比合法窗口还短**——正常等 3 小时的视频
会在第 7 轮被判"卡死"转人工。已改成时长判定，次数上限只作时钟异常的兜底。

`_upload_gate_ok()` 增加一行读取 `upload_spacing_exhausted` → 后续轮次直接返回
`False`，走**已有的**"上传关卡拦截"分支（写 `upload_gate_held` / `upload_gate_held_at`），
由 Q9 在 24h 升级。**不新增状态、不新增消费者**。

### F4 / F5：把内联块抽成 `_retry_enqueue_privateq(item)`

抽函数不是为了好看，是因为内联块无法测试。抽出后两条分支各自计数：

```python
MAX_THROTTLE_DEFERS = 8   # ≈2.7h
MAX_ENQUEUE_FAILS   = 6   # ≈2h
```

达上限统一走 `_fail_upload_permanent()` → `upload_permanently_failed`。
该状态已在 `_TERMINAL`（L325）里，**立即释放话题坑位**，不会占坑。
通知里带 `video_id` —— 视频已上传成功，只是排期链路失败，人工据此到后台排期，
**绝不可当作未上传重传**（这正是 U5 修过的 bug）。

---

## 3. 测试结果

```
[T1] 原始 F3：40 轮全部重传，状态永远停在 ready_to_upload，无停止标记
[T2] 补丁 F3：第 19 轮（=6h）停止，上传调用 19 次后归零，转 upload_gate_held
[T3] 补丁 F3：spacing 持续 3.3h 后自然解除 → 第 11 轮正常上传成功，未转人工
[T4] 补丁 F4：第 8 轮进终态，video_id 保留，入队调用恰 8 次
[T5] 补丁 F5：第 6 轮进终态
[T6] 节流 3 次后恢复 → uploaded_private，throttle_defer_count 清零
[T7] AST：_TERMINAL 含 upload_permanently_failed（占坑会释放）
[T8] AST：collect_results 真的调用了 _retry_enqueue_privateq（抽取没接错线）
PASS — 三条路径补丁后均有界收敛；原始 F3 无界；6h 窗口内不误杀合法等待
```

测试直接 `exec_module` 加载 `auto_pipeline.py`（stub 掉 `fcntl`/`queue_db`），
注入 `_do_upload` / `_enqueue_private_flip` / **可控时钟**（每 tick 前进 20 分钟）
后调用真实函数——不是仿真模型。

**T3 是反向用例**：只测"故障持续会放弃"，会把任何过早放弃的实现都判成通过。
用 cap=6 的旧设计跑 T3 会在第 7 轮（2h）误转人工——已实测确认，见 §7.1。

---

## 4. 上线

```bash
cd <部署目录>
cp auto_pipeline.py auto_pipeline.py.bak-$(date +%Y%m%d-%H%M)
git apply --check /path/to/f3_f4_f5_upload_retry_cap.patch   # 先干跑
git apply /path/to/f3_f4_f5_upload_retry_cap.patch
python3 -c "import ast;ast.parse(open('auto_pipeline.py').read())"   # 语法闸
```

**灰度**：只改上传段，不动 review/生成段。建议先观察 24h，看
`publish` 日志里是否出现"第 N/6 次"与"停止自动重试转人工放行"两种新行。

**回滚**：`cp auto_pipeline.py.bak-* auto_pipeline.py`。新增字段都是可选键，
旧代码读到会忽略，**回滚不需要清队列**。

---

## 5. 为什么没直接改 `repo/`

`repo/` 是 VPS 的镜像，`github_sync.sh` 每次用 `rsync -a --delete` 从
`<部署目录>` 全量覆盖 `perpetua/`。在镜像上改代码，下一次
auto-sync 就被抹掉，还会在本地制造 merge 冲突。**代码改动只能在 VPS 源头做**，
本地产出补丁 + 测试。

---

## 6. 仍未覆盖

| 项 | 说明 |
|---|---|
| `job_submitted` 无 `job_id` 的条目 | `collect_results` L2406 与 `_sweep_stale_submitted` L859 都 `if not job_id: continue`，这类条目无人认领，只能等 C4 的 7 天告警 |
| `teaser_generating` | `dead_state_watchdog` L639 有分支，超时逻辑未逐行核 |
| 并发写 | `load_queue()` → 改 → `save_queue()` 非事务，两进程同跑会丢更新（`_acquire_collect_lock` 只锁 collect 自身） |

**状态图里的 `arena_manual ↔ job_submitted` 环是误报**：`state_graph.py` 的边是
函数级"读了 A 又写了 B"的共现，不是真实跃迁。逐点核对后，`arena_manual` 只有
两个写入点（L919、L965），出口是 `ingest_arena_manual.py` → `ready_to_upload`，
**没有任何代码把 `arena_manual` 改回 `job_submitted`**。这条不用改。

---

## 7. 自审：第一版测试的 9 个问题

第一版测试跑出全 PASS，但它证明的东西比看上去少。逐条自查后修了 6 条、留 3 条
写成已知边界。

### 7.1 【致命】故障模型不真实，把错误设计判成通过

第一版把 spacing 建模成"**永久**拒绝"，于是"第 7 轮放弃"看起来收敛得很好。
但真实系统里 spacing 是 **4 小时发布间隔门，到点自然解除**（`teaser_validate.py` L350）。
测试用一个不存在的故障模式，验证了一个会误杀正常流量的设计。

实测反证（cap=6 变体 + 3.3h 后解除）：

```
第7轮(已等 120min): exhausted=True retries=7
第11轮(已等 200min): status=ready_to_upload exhausted=True
→ 旧设计 2h 就判死，3.3h 的合法等待被误杀
```

**修复**：补丁改时长判定（6h = 4h 门 + 2h 缓冲），测试加 T3 反向用例。
教训：**测试的故障模型必须来自生产代码的语义，不能来自想象。**

### 7.2 【高】只测"会停"，不测"不该停时不停"

单向断言。任何"第一轮就放弃"的实现也能全 PASS。
**修复**：T3 断言 3.3h 等待后必须成功上传、不得出现 `upload_spacing_exhausted`。

### 7.3 【高】静态检查是字面子串匹配，会假阴性

原断言 `"throttle_defer_count\") < " not in src`。若原始代码写成
`if int(item.get("throttle_defer_count", 0) or 0) < 3:`，字面不匹配 → 判定"无上限"
→ **漏报真实的上限存在**。实测确认。

**修复**：删掉文本匹配，改行为断言；只保留两条 AST 结构断言（`_TERMINAL` 成员、
调用点接线），因为它们查的是结构而非写法。

### 7.4 【高】用例无异常隔离

任一用例抛异常，进程带 traceback 退出，后续用例不跑、summary 不打印。
对"证明不会卡死"的测试来说，**静默中断 = 假绿**。
**修复**：`@case` 装饰器，异常记 FAIL 并继续。

### 7.5 【中】时钟不可控，测不出时间窗

第一版没有时间维度（当时按次数判），改成时长判定后必须注入时钟。
**修复**：`Clock` 类，每 tick 前进 20 分钟，tick 内 `now_iso()` 返回同一值。

### 7.6 【中】导入污染 `sys.path`，懒加载 import 落到真实模块

`auto_pipeline.py` 模块级执行 `sys.path.insert(0, BASE)` 等三行。实测导入后：

```
导入前 sys.path[:3] = ['<工作区>/analysis/patches', ...]
导入后 sys.path[:3] = ['<部署目录>', '<部署目录>',
                        '...\\analysis\\patches\\preview']
```

函数内 `import pipeline_state` 这类懒加载会解析到 `repo/perpetua` 下的**真实模块**，
可能写真实文件。当前靠"反正会抛异常被 except 吞掉"兜底——**是运气，不是隔离**。
本次已确认没有落盘（目标目录未被创建），但这是隐患，未修。

### 7.7 【中】基线会漂移，但测试把它当常量

`ORIGINAL` 指向 `repo/`，而 `repo/` 每 30–60 分钟被 auto-sync 覆盖。明天上游若修了
F3，T1 会 FAIL，但 FAIL 的含义变成"基线变了"而不是"代码有 bug"。
**修复**：打印原始文件 sha256 + 显式提示；预留 `EXPECTED_ORIG_SHA`，不匹配只 WARN。

### 7.8 【低】F4/F5 的"原始行为"没有动态验证

原逻辑内联在 `collect_results` 里（3,000 行函数），无法单独调用。测试只能证明
**补丁后的函数**收敛，不能证明**原始内联块**发散——后者的证据只有源码阅读：
`throttle_defer_count` 全仓仅 `+1` 与 `pop`，无比较。这是覆盖缺口，不是错误。

### 7.9 【低】文件位置与仓库约定不一致

`repo/perpetua/` 下已有 `test_dispatcher_nano_bridge.py`、`test_graded_assertions.py`。
本测试放在 `analysis/patches/`，将来随补丁进 VPS 时需要一起搬过去，否则没人跑。
