# 落地方案三脑评审结论（2026-10-08 12:28 CST）

## 投票：LMArena 双模型一致 MODIFY（非 KEEP）

## 硬伤清单（必须修）

1. **risk_register 自证漏洞**：agent 自己写=自己销账，灾难2换皮
   → 修：hatch 只读，ECDSA 签名，人类/CI 才能 ENFORCED

2. **credential-proxy 无鉴权**：绝对路径/direct 网络调用可绕过
   → 修：SO_PEERCRED + nftables egress 封锁

3. **无 break-glass**：token 被吊销后人类怎么恢复？
   → 修：root 紧急直连 revoke + 临时放行 + 紧急签名覆盖

4. **24h 熔断误伤**：周末/长任务被 kill
   → 修：critical 24h / non-critical 72h

5. **300s 金丝雀阻塞紧急**：真出安全事件时等不了
   → 修：删 canary，紧急 revoke 走 break-glass

6. **只读 /tmp 断工具链**：pip/编译器硬编码 /tmp
   → 修：改 bind-mount 到持久目录（不断工具链）

7. **"documentation"标签反效果**：训练 agent 无视文档
   → 修：叫"系统不变量"，物理定律式描述

## 优先级（投入产出比）

- **C2 credential-proxy**：高 ROI，防住的伤害最大（灾难1 级联 outage）
- **C1 /tmp bind-mount**：投入产出比最高（Model B），防本地数据丢失
- **C3 risk_register**：中/低 ROI，需持续治理成本
- **C4 AGENTS.md**：最低 ROI，纯文档零结构效力

**单做一个最值**：C2（绝对伤害）/ C1（性价比）

## 执行顺序（AI Studio）
C2 → C1 → C3 → C4（有依赖关系）

## 落地前置条件（Tier 3，需逐项批）
- [ ] C2：装 credential-proxy + nftables（改网络 egress）
- [ ] C1：bind-mount /tmp（改挂载）
- [ ] C3：建 /etc/risk-register + 签名密钥（改系统目录）
- [ ] C4：chattr +i AGENTS.md（改文件属性）

**评审不代替批准**。每项都是 Tier 3，需你明确批具体操作才动手。

## 文件
- lmarena.md：双模型 verbatim 摘要
- aistudio.md：详细实施步骤（命令/配置/回滚/验证）
- verdict.md：本文件
