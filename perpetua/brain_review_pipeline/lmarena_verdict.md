# LMArena 陪审团 verdict（2026-10-08 22:50 CST）
## 管线架构健壮性审查

### 共识 Top 3（双模型都提到）

1. **发布路径 fail-open 最危险** — QC/AI评审失败默认通过，未审视频可直接发布。必须 fail-closed + deny-by-default + 人工兜底。
2. **Cron 竞态** — ~40 个轮询 cron 无原子认领、无幂等键、无 run fencing，check-then-act 必导致重复生成/重复上传/文件撕裂。需原子状态转移 + 上传幂等键 + 分布式锁。
3. **永久卡死状态无收割者** — generating（无心跳租约）、awaiting_approval（无升级超时）、review_failed/qc_failed（无死信队列/重试/告警）；uploaded 之后阶段根本不在状态机里。需每个非终态加超时转移 + 存活租约，终态失败进死信队列并告警。

### 非共识但建议跟进
- 墙钟调度的隐式生产者→消费者顺序依赖
- 缺少 checksum/manifest 做 artifact 完整性校验

### 诚实注
单模型分饰两角（可靠性视角 vs 对抗视角），非真正的双独立模型陪审。
