# AI Studio 知识激活规格（2026-10-09 08:42 CST verbatim存档）

## 7 大交付物
1. **KB_CONTEXT API**：get_context(task_type, device, video_key, limit=5, snippet_chars=400)，确定性相关性打分（无 ML），预算 2000 chars/调用，缓存 TTL 3600s；7 个调用点（file:line 级）
2. **调用点清单**：6 阶段 × 拉取内容 × 插入点；A1/A2 已有模式标注，4 个 NEW
3. **结构化抽取**：ask_studio_extractor.py 正则解析 → publish_cadence.json（posts_per_day/interval_hours/enforced）；解析失败保留旧版 + 记 failures.jsonl；3 连失败告警
4. **冲突检测**：4 条规则（R1 指令vs约束重叠<50%、R2 节奏矛盾、R3 criteria 漂移>30%、R4 重复跳过）；冲突阻断写入，staging 待人工
5. **使用度量**：kb_usage_ledger.jsonl（7 字段）；kb_prune_queue.py 90 天零用复核；kill criteria 查询（30 天 <95% 覆盖率 → 转 A）
6. **MCP 暴露**：4 个只读工具（kb.query/kb.get_entry/kb.list_sources/kb.usage_stats）；拒绝清单（MEMORY.md、原始 ledger、staging、凭据）
7. **模板版本化**：kb/templates/ + semver + CHANGELOG；viral_prompt.py:36-68 硬编码迁移路径（7 天账本验证后删）

## 共识判定
- 审计（5 链通/7 处断）→ LMArena（C 全票）→ AI Studio（按 C 落 7 规格）：三阶段收敛
- 诚实注记已编码：正则无法语义保证 markdown→规则转换，解析失败保留旧常量 + 告警（Deliverable 3 fallback）
- Kill criteria：30 天 <95% 覆盖率 → 转 A
