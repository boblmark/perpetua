# docs/analysis — 数据分析与审计（快照）

本目录是**本地分析层的推送快照**，由本地工作区同步而来，不是独立维护的副本。
更新方式：本地改完整体覆盖，不做双向合并。

## 文档

| 文件 | 内容 | 数据/代码基线 |
|---|---|---|
| [`2026-10-31-remote-vs-local-diff.md`](2026-10-31-remote-vs-local-diff.md) | 远程仓库与本地工作区的深度对比：规模、结构、审计结论复核、6 个仍坏项 | 代码 `af3ae58`（10-31） |
| [`2026-10-30-playback-growth-plan.md`](2026-10-30-playback-growth-plan.md) | 播放量提升六层方案（L0 止血 → L6 测量），含验收标准、Kill 条件、发布后处置 | 513 条历史视频 + 288 条竞品 |
| [`2026-10-30-viral-formula-and-probability.md`](2026-10-30-viral-formula-and-probability.md) | 爆款公式与概率分析：为什么阈值不可达、统计功效为何不足 | 同上 |
| [`2026-10-30-idle-loop-audit.md`](2026-10-30-idle-loop-audit.md) | 空转闭环审计：3 个永久循环、状态机机械提取、`loop_guard` 不变量 | 代码 10-16 快照 ⚠️ 已部分过期，见文首更正 |

## 补丁（`patches/`）

| 文件 | 内容 | 基线 |
|---|---|---|
| [`patches/2026-10-31-upload-retry-cap.md`](patches/2026-10-31-upload-retry-cap.md) | F3/F4/F5 上传侧重试上限：问题、改法、测试、上线、**自审 9 条** | `af3ae58` |
| [`patches/f3_f4_f5_upload_retry_cap.patch`](patches/f3_f4_f5_upload_retry_cap.patch) | 补丁本体（`git apply -p1`，仅改 `perpetua/auto_pipeline.py`） | 同上 |
| [`patches/test_upload_retry_cap.py`](patches/test_upload_retry_cap.py) | 收敛性测试：自动定位源文件 → 应用补丁 → 注入故障与可控时钟 → 断言有界收敛 | 同上 |

```bash
cd docs/analysis/patches && python test_upload_retry_cap.py
```

测试会自己把补丁打到临时副本上，**测的是补丁本身**，不需要预先改任何文件。
需要 `git` 在 PATH 里。

## 脚本（可重跑）

| 文件 | 作用 | 依赖 |
|---|---|---|
| [`scripts/mh_levers.py`](scripts/mh_levers.py) | 竞品特征效应：按账号分层的 Mantel-Haenszel OR + RBG 95%CI（消除粉丝量/风格混杂） | `openpyxl` + `competitor_viral_20261014.xlsx` |
| [`scripts/variance_decomp.py`](scripts/variance_decomp.py) | 播放量方差分解（ICC）：账号间 vs 账号内，判断"优化账号"还是"优化单条" | 同上 |

```bash
python scripts/mh_levers.py
python scripts/variance_decomp.py
```

> 输入表 `competitor_viral_20261014.xlsx` 未随仓库分发（含第三方平台原始数据）。要复跑需自备。

## 三条与直觉冲突、但可复算的结论

1. **账号层方差占一半**：ICC = 0.496（B站 0.459 / TikTok 0.560）。换一条视频最多改变一半结果。
2. **12 个结构特征账号分层后全部不显著**：标题含数字/问号/emoji/破折号/封面有字/陈述开场，95%CI 全部跨过 1。
3. **"TikTok 1–3 分钟 = 12 倍播放"不成立**：那是跨账号比较；账号内 13 个账号平均 Spearman rho = −0.057。

## 边界

- 分析基于 513 条历史视频与 288 条竞品，n<200 的调参禁令仍然有效。
- 结论的适用期到下一次产品形态变更（8–11s → 25–35s）为止，之后需重算。
