# AI Studio 工程规格（2026-10-09 08:19 CST verbatim存档）
# 完整规格见浏览器任务原始输出，已按 §六格式整理

## 核心交付
- MUST-1~14 / NEVER-1~6（14 条必须 + 6 条禁止，全部可验证）
- 状态机：7 状态（MANAGED_SCHEDULED_DRAFT/GENERATING/READY_TO_UPLOAD/INTENTIONAL_PRIVATE/QUARANTINED/STABLE_LIVE/DELETED），完整跃迁表 + 每状态 owner/timeout/timeout动作
- 熔断器 CB-1~CB-4：gate bypass（>20%/24h）、管线不可用（>15min/天×3天）、动作失败风暴（≥10/60min 或 ≥25/24h）、quiet-window 违规；CB-RECOVERY 必须人工执行，禁止自动化重开
- 跃迁门 API：transition(video_key, from_state, to_state, actor, reason, run_id, idempotency_key, lease_ttl_seconds)，10 步执行顺序，8 种拒绝码闭集（QUIET_WINDOW/LEASE_HELD/STALE_FROM_STATE/ILLEGAL_TRANSITION/BREAKER_OPEN/EXEMPT/RECEIPT_UNVERIFIED/INTENT_CONFLICT）
- pipeline_state.json 规范 schema（13 字段）
- 判断层：J-1 incident ledger schema（13 字段）；6 条检测规则 R-OPPOSE-1（6h 内对立跃迁）/R-FLAP-2（24h 内 ≥3 次可见性变更）/R-VOID-3（GENERATE_NEEDED 30min 无人认领）/R-ALIAS-4（状态别名分歧动作）/R-SINK-5（生成成功 60min 无 receipt）/R-BYPASS-6（绕过 gate 的 API 变更，强制 severity 4）；severity 评分公式 + 4 档自动升级（LOG_ONLY/INBOX_ALERT/REVIEW_BRIEF/HALT_ACTOR）
- 冲突决议：dead-man's-switch KEEP（接入 CB-2）、approval TTL MODIFY（lease 持有时暂停）、reject-storm MODIFY（阈值换 CB-3）

## 关键数字常量
- 夜间静默窗口：00:00-08:00（Asia/Shanghai），max_unattended_flips=0
- lease TTL：300 秒
- 意图冲突窗口：6h；flap 阈值：24h 内 3 次；孤儿意图：30min；气隙汇：60min；bypass 检测：5min
- 反转条件：2 周内 >20% Tier-2+ 操作绕过 gate → 转 B
