# AGENTS.md 灾难预防落地方案评审 — 综合结论

> 状态：待 LMArena + AI Studio 回答返回后填写

## 评审信息
- 日期：2026-10-08
- 主题：上一轮 verdict.md 的 4 组件落地方案是否完整、安全、优先级正确？
- 上一轮结论：范式 C（结构消除）为主，B 为辅，A 降级为文档

## 待评审的落地方案（原文）
1. /tmp 只读挂载 + TMPDIR 重定向到 /home/hatch/data/perpetua/tmp/
2. credential-proxy（/usr/local/bin/credential-proxy，1-agent:1-token，300s 金丝雀+自动回滚）
3. risk_register.json（/etc/agent-governance/，MAX_AGE 24h，systemd timer 超时停服+吊销 token）
4. AGENTS.md 更新（文档版 vs 执行版）

## LMArena 评审（陪审团）
### 完整性
（填入：有没有漏掉关键组件？谁写 risk_register？谁判定已消除？proxy 鉴权？）

### 风险评估（每组件一句话）
- C1 /tmp 只读：
- C2 credential-proxy：
- C3 24h 熔断：
- C4 文档降级：

### 优先级排序（投入产出比）
1.
2.
3.
4.

### 投票
（KEEP / MODIFY / DROP + 理由）

## AI Studio 实施步骤（总工程师）
（按 LMArena 优先级排序，每组件：COMMANDS / CONFIG / ROLLBACK / VERIFY）

## 最终落地方案（评审修订版）
（综合两脑，列出修订后的组件清单）

## 硬伤清单
（评审发现的致命缺陷，如有）

## 落地前置条件
- [ ] 用户逐项批准（infra Tier 3，不可代批）
- [ ] 每组件回滚方案已验证
- [ ] AGENTS.md 同步更新
