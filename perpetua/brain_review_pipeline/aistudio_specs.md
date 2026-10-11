# AI Studio 总工程师规格（2026-10-08 22:51 CST）
## 管线深度代码审查 → 14 条 MUST/NEVER

### 死状态
1. MUST: 非终态 + 超 TTL → 自动转恢复态（有限重试，否则 review_failed/rejected）；24h transient 释放必须覆盖 awaiting_approval 和 approved
2. MUST: review_timeout 必须有明确出边（重排评审或拒绝释放）；不得永久留在 used
3. MUST: awaiting_approval 超 TTL → 自动按策略批准/拒绝并释放 topic；人工不作为不得永久阻塞
4. MUST: qc 连续 regen 失败 ≥3 → 停止重试标 review_failed；无界重试不得占用 topic
5. MUST: 上传成功→写 uploaded 之间崩溃 → API 返回 videoId 立即持久化；重启先查 YouTube 是否已存在（幂等）再决定重传

### 数据竞争
6. NEVER: 写 JSON 不得原地写；MUST 写临时文件 + fsync + 原子 rename
7. MUST: 读状态必须容忍损坏 JSON（try/except + 校验），回退到最后好的备份
8. MUST: 共享状态读写序列化（文件锁或单写者）+ cron 单飞（stale-safe 锁）；重叠运行不得双处理

### 失败恢复
9. MUST: 上传后步骤（privacyStatus 验证、引导评论）必须基于已持久化的 videoId 幂等可恢复；评论/验证失败不得触发重传
10. NEVER: 原创度/合规检查无法完成时不得 fail-open；MUST fail-closed 拦截上传
11. MUST: 终态 + 失败 artifact 必须删除或归档，加孤儿 artifact 收割者；不得堆满磁盘

### 监控盲区
12. MUST: 2 倍发布周期内零 uploaded → dead-man's-switch 告警（唯一能抓到静默卡死的方式）
13. MUST: privacyStatus 验证重试失败 → 立即告警
14. MUST: Tier3 warn + D1 拒绝聚合计数告警；warn-only 不得等于 watch-never
