# Ask Studio 诊断回答（2026-10-09 08:14 CST verbatim存档）

## 1. 三种巡检/自愈架构模式及特征故障

**Pattern A: Heuristic State Inference（启发式状态推断/被动观察者）**
- 机制：分布式 cron 检查本地产物或外部状态指标（如视频隐私状态+播放量），推断意图，而非检查中央状态机
- 特征故障：**State Aliasing（状态别名/语义碰撞）**——不同的操作意图映射到相同的遥测足迹
- 对应事故 #1：定时待发 private 和隔离 quarantine private 在平台状态上完全相同（visibility: private），探针从原始遥测（views>0）推断意图而非查权威注册表，把"定时 staging"误判为"隔离待救"

**Pattern B: Log-Driven Polling without Distributed Task Queues（无分布式任务队列的日志/指标驱动轮询）**
- 机制：cron 读扫描输出、记日志（如 GENERATE_NEEDED），靠松散轮询而非带投递保证的持久消息队列
- 特征故障：**Orphaned Intent（孤儿意图/消费者饥饿）**——生产者把事件写进日志/文件，但没有绑定的消费者契约，工作声明过期或永久闲置
- 对应事故 #2：orchestrator 检测到批量失败并记了 GENERATE_NEEDED，但系统用被动状态日志而非带绑定工作池的主动队列，零任务被取出或重试

**Pattern C: Decoupled Multi-Environment Handoff（解耦多环境交接）**
- 机制：沙箱执行环境（无头浏览器、远程微服务）调生成端点，假设下游能解析输出位置
- 特征故障：**Air-Gapped Sinks（气隙汇/断裂的入站边界）**——上游远程生成成功，但 egress/传输原语（共享 blob 存储、产物上传协议）从任务规格中遗漏
- 对应事故 #3：Veo 在浏览器运行时内生成完成，但 runner 无本地文件系统集成、无 S3/blob 产物上传契约，成品 stranded 在沙箱

## 2. 自动修复何时从止血变闯祸 + 熔断机制

**反转条件**：当修复脚本基于不完整、单维度的启发式谓词执行破坏性/状态变更 API 调用（如 update_video(public)），且不验证目标所有权或 lease 锁时；当 read-repair 循环在没有权威全局排除 lease 的情况下运行时。
事故 #1 中规则（quarantine 中 views>0 → 翻 public）完全没检查视频是否处于 time lock 或归属另一个调度器（private_queue.json）——healer 变成了 unauthorized publisher。

**熔断机制**：
- **Source-of-Truth Mutex / State Lease**：执行修复翻转前必须对 private_queue.json 拿显式锁；video_id 在其中且 status=waiting 则立即中止
- **Rate-Limited Action Quotas（blast radius 上限）**：修复脚本每窗口状态变更次数上限；非预期的状态跃迁触发冷却（如 00:00-08:00 间 max_unattended_flips=0，无人工 bypass 不得执行）
- **Tri-State Visibility Assertions**：二进制（public/private）改为显式元数据标签：MANAGED_SCHEDULED_DRAFT、QUARANTINED_LOW_VIEW、STABLE_LIVE；watchdog 拒绝执行缺少精确标签 QUARANTINED_LOW_VIEW 的 payload

## 3. 最大结构性风险诊断

**结论：Fragmented State Authority with Asymmetric Coupling（ fragmented 状态权威 + 33 个独立 cron 任务间的非对称耦合）**

证据：
- 会写不读：zero_view_alert.py 完全绕过 private_queue.json，提前 9 小时做了影响观众的生产发布决策
- 会写无人读：pipeline_orchestrator.py 把 GENERATE_NEEDED 发射进架构虚空，无消费者
- 会产无传输：浏览器任务生成产物无 artifact 入站路径

管线现状是 33 个解耦、无协调的 agent 基于对共享基础设施的本地解读各自行动。重启看门狗（事故 #4）成功是因为进程管理是确定性的；内容管线依赖独立脚本间的隐式假设。没有中央事务状态机治理 generation→QC→staging→live 全生命周期，独立脚本会继续对 live 频道执行冲突变更。
