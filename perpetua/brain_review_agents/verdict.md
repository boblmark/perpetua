# AGENTS.md 灾难预防评审 — 综合结论（2026-10-08 12:00 完成）

## 评审信息
- 日期：2026-10-08
- 主题：AGENTS.md 为什么没能预防两次灾难？如何改造？
- 灾难1：YouTube OAuth revoke → 三方失效 30 分钟（未知风险）
- 灾难2：veo_prompt_v51 只写 /tmp → 丢失（已知风险拖延不治）
- Ask Studio 不参与（YouTube 专用）

## 根本缺陷（三脑共识）
AGENTS.md 是**事后诸葛亮**：文档本身不执行，靠 agent 自觉。灾难2证明——风险白纸黑字写着、排第2，还是没动手。文本无法对抗拖延。

## 解决方案：范式 C（结构消除）为主，B 为辅，A 降级
- **C 结构消除**：/tmp 对 agent 只读（TMPDIR 重定向到持久目录）；revoke/rm 不走裸命令，走 credential-proxy（1-agent:1-token 隔离）
- **B 硬前置**：Tier 3 操作由脚本自己执行检查，不问 agent"做了吗"
- **A 文档**：降级为人类阅读文档，不再作为控制手段

## 已知风险强制时限
- MAX_AGE: 24 小时（识别→消除）
- TRACKER: /etc/agent-governance/risk_register.json
- ESCALATION: 超时未消除 → 停 agent 服务 + 吊销 runtime token，等人工介入

## 灾难1（未知风险）覆盖
- AI Studio 诚实回答：No，结构消除防不住 unknown unknown
- 替代方案：credential-proxy 做 300 秒软禁用 + 金丝雀健康检查，401/403/5xx 自动回滚

## 落地清单
- [ ] /tmp 只读挂载 + TMPDIR 重定向（需 infra 变更，用户批准）
- [ ] credential-proxy 凭据隔离代理（需开发）
- [ ] risk_register.json + systemd timer（需 infra 变更，用户批准）
- [ ] AGENTS.md 更新：Rule 1/2/3 标注为"文档版"，新增"执行版"指向上述机制
