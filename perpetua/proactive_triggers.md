# 主动触发表（Dash 的自动调用知识库）

> 用户 2026-10-10 立规矩：把需要自动调用的工具维护成一张表，不断更新。
> 这是 Dash 自己的知识库——条件满足就自己干，不等用户开口；干完给结果。
> 状态分三档：`cron自动`（已在跑）/ `半自动`（条件满足时主动提议+执行）/ `手动`（需用户开口，目标是逐步升级）。

## Ask Studio（浏览器自动问）
| 触发场景 | 动作 | 频率/条件 | 状态 |
|---|---|---|---|
| 每日趋势/算法动态 | ask-studio-daily | 每天 08:49 | cron自动 |
| 问题队列有 pending | ask-studio-queue-processor | 每 30 分钟 | cron自动 |
| 热点爆发（相关度≥0.5） | auto_ask_studio 要选题角度 | trend_spike_detector 每小时 | cron自动 |
| 排期复核到期 | ask-studio-slot-review | 每天 09:30 检查，14 天到期才问 | cron自动 |
| 每周独有指标巡检 | ask-studio-weekly-patrol | 每周一 10:00 | cron自动 |

## 议会（brain_council）
| 触发场景 | 动作 | 条件 | 状态 |
|---|---|---|---|
| 模板版本进化（Ask Studio 连续 8 条<85） | 自动提议→10 分钟无反对即开 | council-auto-watch 每 30 分钟检测 | cron自动（2026-10-10） |
| 数据崩塌（连续 5 条 48h<50 播放） | 自动提议→10 分钟无反对即开 | council-auto-watch 每 30 分钟检测 | cron自动（2026-10-10） |
| 哨兵触发 | 自动提议→10 分钟无反对即开 | auto_council_request.json | cron自动（2026-10-10） |
| 重大策略调整（Plan 选型、发布政策） | 三脑议会 | 出现策略分叉 | 半自动（策略分叉难机器检测，仍由 Dash/用户发起） |
| AGENTS.md 规则变更 | 议会评审 | 规则变更动议 | 手动 |

## Arena agent 集群（外部多模型）
| 触发场景 | 动作 | 频率/条件 | 状态 |
|---|---|---|---|
| 月度调研派发 | arena-agent-monthly-dispatch | 每月 1 号 09:49 | cron自动 |
| 每周选题横评 | lmarena-weekly-jury | 每周一 10:49 | cron自动 |
| EP上线前陪审团预审 | jury评hook/标题/缩略图+改进点 | 新private长视频≥10min且7天内上传 | cron自动（arena-jury-auto 每6h，2026-10-10） |
| 标题缩略图三选一 | jury排序 | ai_unhinged/title_options_*.json 有≥2备选 | cron自动（arena-jury-auto 每6h，2026-10-10） |
| Kill线仲裁 | 独立verdict:kill/continue/pivot | 2026-12-08（一次性）或14天pace<30%所需（需≥10天数据窗口） | cron自动（arena-jury-auto 每6h，2026-10-10） |
| 数据崩塌诊断 | 紧急诊断jury | 最近2条≥48h且播放<50（比议会5条阈值更早的轻量预警，冷却7天） | cron自动（arena-jury-auto 每6h，2026-10-10） |
| 竞品季度拆解 | 对标dandingles等输出打法变化 | 季度变化自动 | cron自动（arena-jury-auto 每6h，2026-10-10） |
| 新视频模型评估 | 评估新模型出片质量vs现管线 | trend_spike检出新模型词时 | 待定 |

## AI Studio
| 触发场景 | 动作 | 频率/条件 | 状态 |
|---|---|---|---|
| 月度规格落地 | aistudio-monthly-spec | 每月 1 号 10:49 | cron自动 |

选型逻辑：Arena 的价值是"多模型独立判断"，适合用在**单模型易有盲区的高风险决策**（发片前、kill线、崩塌诊断），不适合高频低风险事项（日常选题已有周 jury）。每次 dispatch 约 4 分钟走 VM agent-browser，配额可控。

## 管线自驱
| 触发场景 | 动作 | 频率/条件 | 状态 |
|---|---|---|---|
| 每日两条发布铁律（自然日 2 条上传，含 private 预传） | publish_health 判 WARNING 即动手补：按管线顺序推（送审→追答案→生成→QC→private），卡住环节 2h 内必须有动作或升级；铁律不降任何硬门禁（≥85/QC/去重/120分钟门），宁缺勤不降质 | publish-health-watch 每 30 分钟检测 | 半自动（2026-10-17 用户亲立；诚实约束：后端容量不足如实报缺口） |
| 重写直到过 85（评审 <85 不静默归档） | rewrite 取消 2 轮硬上限：<78 回 review_failed 继续改；5 轮未过经 escalate 升级人工；对照组豁免（control_group_overridden） | review 捡答案后自动 | cron自动（2026-10-17 用户亲立；质量熔断：<60/无fix/FLAG 仍归档） |
| 48h 主题评估（两振出局+贝叶斯收缩） | evaluator_48h.py | 每小时 | cron自动（2026-10-12，B计划 R4；feed份额<50%或APV<70%为MISS，首振watchlist、连振blocklist，配额故障fail-open） |
| 生成任务积压 | perpetua-pipeline-collect | 每 20 分钟 | cron自动 |
| 死状态/超时 | dead-state-watchdog | 每 30 分钟 | cron自动 |
| 每日深度复盘 | perpetua-deep-dive-weekly | 每天 23:49 | cron自动 |
| 每日指标监控 | daily_metrics_monitor | 每天 08:30 | cron自动 |
| 30天执行表打勾 | sheet-daily-maintainer | 每天 23:49 | cron自动 |
| relay 18080 隧道断（YouTube API/jev 等鉴权请求全挂） | `bash /home/hatch/data/mcp_server/vm_ltunnel.sh` 或 `jev_keepalive.sh` 重建隧道 | 条件：`ss -tln` 不见 127.0.0.1:18080 | 半自动（2026-10-10 发现 keepalive 尚无 cron 覆盖，已手工重建；需补每 5 分钟 cron） |
| 管线代码改动后（模板/QC/拼接/发布任一环节） | 用合成素材跑真实代码路径回归（拼接+QC+状态机），确认无异常再宣布"落地" | 条件：相关 .py 文件 mtime 变化且当日未跑过回归 | 半自动（2026-10-10 teaser_validate._run_qc 因 run_qc 返回 dict 而非 tuple，全量 teaser 差点在 QC 环被误杀；教训：接口契约变更必须 grep 全部调用方） |

## 爆款加码 B 计划（内部新颖性引擎）
| 触发场景 | 动作 | 频率/条件 | 状态 |
|---|---|---|---|
| 每周限量格式扫描（B计划 R3） | 主 agent 手动：扫竞品/平台格式信号（时长、节奏、字幕样式），只采格式不抄选题标题 | 每周一次 | 手动（2026-10-12 用户拍板主 agent 手动执行；质量稳定后可转 cron自动） |

## 主 Muse 协作（dispatcher）
| 触发场景 | 动作 | 条件 | 状态 |
|---|---|---|---|
| 视频生成需求（spool 有 pending 即缺素材） | musemain-autodispatch 自动提交经 dispatcher | 每 30 分钟；熔断：探针拒收率<0.5、日<6、连续拒收<2 | cron自动（2026-10-10；探针完成前只积压不提交） |
| 三脑议会需外部模型 | brain_council 经 backend=dash | 议会召开时 | 半自动 |

## NotebookLM 知识库（ViralLoop Channel Knowledge Base）
| 触发场景 | 动作 | 条件 | 状态 |
|---|---|---|---|
| 用户让我查本子 | 浏览器打开 notebook 提问/找 source | 用户开口 | 手动 |
| 重大决策前（Plan 选型、kill 线、发布政策变更） | 问本子综合议会结论+历史教训 | 出现策略分叉或高风险决策 | 半自动 |
| 每周同步后 | 抽查云端 source 内容与本地一致 | notebook-weekly-sync 跑完 | 半自动 |
| 用户在外想查频道知识 | 代查后把答案带回聊天 | 用户开口 | 手动 |
| 运行中出现"没想到"事件 | 写 dated note 上传本子（标题"事件 YYYY-MM-DD：一句话"） | agents-md-lesson-sweep 每天 00:30 从 memory 日志挑 | cron自动（2026-10-10） |

实话：对我自己，本地文件 grep 更快更全，本子不是我的主力检索；它的价值是云端备份 + 跨 source 综合问答 + 你直接问它。没事不会去问，问一次就是有明确目的。

## 待升级（从手动→自动）
- [x] relay 18080 保活：已建 `relay-18080-keepalive`（每 5 分钟，2026-10-10 02:41 落地）。
  凌晨断过两次才补上——教训：保活脚本存在但无人调度等于不存在。
- [x] 议会召开：已落地 council_auto.py（watch 30m + executor 10m）+ 冷却 7 天 + 哨兵文件；2026-10-10
- [x] 主 Muse 视频生成：已落地 musemain_autodispatch.py（spool+熔断器）；拒收率探针后台测量中，探针完成前 HOLD；2026-10-10
- [ ] EP2+ 选题：lmarena 横评结论自动进选题加权（现为手动读入 dynamic_constraints.json）

## 更新纪律
- 每次新增自动调用或状态升级，更新本表并记 ~/memory/YYYY-MM-DD.md。
- 每月 1 号随 aistudio-monthly-spec 复核一次本表，淘汰失效触发器。

## Gemini 质检（2026-10-10 用户确认）
| 触发场景 | 动作 | 方式 | 状态 |
|---|---|---|---|
| EP长视频成片进private | 全片质检报告（钩子/字幕对位/穿帮/节奏） | gemini.google.com 经VM浏览器（免key） | 已确认，EP1 private完成后执行 |
| Shorts语义评审（2026-10-10 用户拍板走网页版，不等API key） | hook/字幕对位/穿帮/政策风险，verdict写入private_queue | gemini.google.com 经VM浏览器；cron gemini-semantic-review 每30分钟 | cron自动 |
| 语义评审门 | verdict=fail/缺失 → private_flip暂缓翻转并告警 | private_flip.py check_and_flip() 内 | 已落地 |
