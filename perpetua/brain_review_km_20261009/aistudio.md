# AI Studio 知识库规格 v1.0（2026-10-09 08:31 CST verbatim存档）

## 核心交付
- 常量：KB_ROOT=/home/hatch/data/kb；SYNC_SLA 15 分钟；漂移检查 6 小时；单存储上限 24 小时；重试退避 5/15/45/120 分钟
- MUST/NEVER：is_important() 可验证谓词（目录成员或 front-matter dual_backup:true）；命名正则 ^[a-z0-9]+(-[a-z0-9]+)*_[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$；废弃标记 > [!DEPRECATED] 4 行头 + 7 天内移 archive/deprecated/；路由表 R1-R6（MEMORY.md≤200 行禁事件 section；日报走归档；specs/decisions/reviews 双备份；prompts 默认本地）
- SYNC SPEC：inotify→debounce 60s→outbox→uploader（借已登录 NotebookLM 会话，$0）→ack；sha256 校验；INDEX.md notebooklm_status 状态机
- INDEX SPEC：单文件 /home/hatch/data/kb/INDEX.md，YAML 机器可读块，13 字段 schema，kb-index validate 卡点
- RETENTION SPEC：日报 >100KB 24h 内摘要归档；>30 天 raw 归档；live 目录 ≤30 天/30 文件；单文件禁超 1MB；raw 保留 365 天
- BRAIN-REVIEW ARCHIVE SPEC：reviews/{YYYY-MM-DD}-{slug}/ 下 00-brief.md~06-notebooklm-sync.json 8 文件固定布局；review 完成当且仅当 06 complete=true
- 冲突决议：双备份铁律 KEEP（量化）；prompts 默认本地 MODIFY；archive 本地 KEEP
- Kill criteria 接线：K1→§2b 试点指标；K2→STANDARDS.md §F2 截止 2026-10-16；K3→linkcheck

## 共识判定
- 审计（实测）→ LMArena（A 胜出）→ AI Studio（按 A 落规格）：三阶段收敛，无分歧
- 唯一诚实注记：若 K1 试点证明 NotebookLM 自动同步技术不可行，则三者皆不能防漏写，按 K1 诚实转 B
