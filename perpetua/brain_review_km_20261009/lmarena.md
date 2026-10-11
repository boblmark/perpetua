# LMArena 知识库架构判决（2026-10-09 08:29 CST verbatim存档）

## 判决：A 胜出（Central KB + auto-sync）

## 理由（3 条绑定 F1-F8）
1. **F1（今日漏写事故）**：A 是唯一在写入时触发的机制——"every important-doc write auto-triggers NotebookLM sync" 从结构上防止该类事故。B 的每日校验 cron 最多滞后 24h 发现，事故照样发生；C 的路由表是无强制力的标准，而当前故障模式正是"口头标准 + 0 自动化"。
2. **F4（36 文件零索引）**：A 自带 single INDEX.md 是具名交付物，唯一把 36 个无索引文件变成可导航记录的方案。B 明确不动散乱结构；C 根本不动存储。
3. **F2（"重要文档"无定义）+ 本地云端漂移**：A 的 typed subdirs（specs/reviews/prompts/decisions）把口头要求变成写入时可检查的规则——目录成员身份即定义；hash 漂移检查持续强制双备份。B 需要再维护一份人工"重要文档"清单——复制 NotebookLM 100% 人工维护的失败模式。

## 反转条件
- K1：14 天内 10 次写入试点，≥2 次未自动同步到 NotebookLM，或中位延迟 >60 分钟 → 转 B
- K2：7 天内"重要文档"书面定义未落地 → 转 C
- K3：迁移 kb/ 导致 ≥3 处线上引用断裂且 14 天未修复 → 转 B

## 前 3 个 Commit
1. 写 F2 定义：/home/hatch/data/kb/STANDARDS.md（"重要文档"定义、双备份规则、typed subdir 资格）
2. 建骨架：/home/hatch/data/kb/ + typed subdirs + single INDEX.md 覆盖 5 个 brain-review 目录 36 文件
3. 接自动化：write-trigger hook + hash 漂移检查 + 告警（kb/sync_notebooklm.py），K1 试点验证

## 今日事故
只有 A 能从结构上防止重演。B 是事后发现（且浏览器抓取脆弱）；C 写路径零变化。如果 K1 失败（NotebookLM 自动同步技术不可行），则三者都不能，只能转 B。

## 未覆盖
无方案解决 F1（日报归档）、F3（命名规范）、F6（废弃标记）、F8（空目标模板）；只有 C 解决 F7（统一检索）。A 是最佳平台，可后续扩展。
