# LMArena 知识激活架构判决（2026-10-09 08:41 CST verbatim存档）
# Side-by-Side: GPT-5.2-high vs claude-sonnet-5-high，两模型独立一致选 C

## 判决：C 胜出（Hybrid + usage metrics）

## 理由（3 条绑定 B1-B7）
1. 死知识自报：B1/B2/B3/B6 的存在是因为零消费不可见。C 的使用账本（每次 KB 读取记 entry_id/caller_stage/decision，90 天零用进复核队列）让不消费在运行时可见。A 和 B 保留盲区：调用点存在但可能从未有效触发——A4 前车之鉴（代码碰了诊断容器但忽略 payload）。
2. 异常推送复用唯一已验证的事件模式：A2 已跑通（3 连 dud → hook-boost）。C 泛化 A2：QC 异常时自动查 NotebookLM（B2）和 brain_review 结论（B3），而不是 B 的大而无当（从零建通用事件总线+冲突检查器）。
3. 确定性拉取给 B7 单向街第二个方向、给 B4 版本钩子：5 个确定性阶段的固定调用点，deep_dive/brain_review 发现注入 prompt/QC 决策输入，并可写回 dynamic_constraints.json/criteria.json（闭合 B7）；同一调用点用模板版本元数据替代硬编码 v5.2 常量（B4）。

## 反转条件
上线 30 天后，若使用账本显示 <95% 的管线运行在 5 个确定性阶段都有 KB 读取记录 → C 的自审计没落地，转 A（诚实运营的简单架构胜过自审计缺失的混合架构）。

## 前 3 个 Commit
1. kb_context.py + kb_sources.yaml，实现 get_context(task_type, device, ...)，适配器覆盖 deep_dive_*.md、brain_review_*/**、NotebookLM 导出、dynamic_constraints.json、criteria.json；第一个调用点接 prompt_review.py，把 Ask Studio 诊断 markdown（"strictly 1-2/day"）转成结构化 publish_cadence.json
2. kb_usage_ledger.jsonl + get_context 装饰器（记 entry_id/caller_stage/timestamp/used_in_decision）+ kb_prune_queue.py（90 天零用复核队列）
3. deep_dive_extractor.py（每日 cron）：解析 deep_dive_*.md → deep_dive_findings.json（device/issue/recommendation），注册进账本，加 QC 阶段调用点——给 B1 第一个代码读者

## B1+B5
- B1：C 结构性最优——deep_dive 变成确定性阶段的拉取依赖，且账本证明是否真被读了
- B5：C 在方案集内最优，但诚实注记（GPT-5.2）：A/B/C 都不保证把 markdown 转成可执行结构化规则——只保证激活钩子，不保证表示格式。Claude 的 commit #1（publish_cadence.json 转换）必须作为 C 的显式部分，否则 B5 还是半残
