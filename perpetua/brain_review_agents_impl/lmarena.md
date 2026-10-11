# Brain ① LMArena 回答（2026-10-08 12:05 CST）
# Side-by-Side: gemini-3.1-pro-preview (A) vs gemini-3.6-flash (B)

## 投票：双模型一致 MODIFY

## 完整性硬伤（双模型一致）
1. **谁写 risk_register？** agent 自己写 = 自证关闭工单，灾难2换皮重演
2. **credential-proxy 鉴权缺失**：无 SO_PEERCRED，绝对路径/direct 网络调用可绕过
3. **无恢复流程**：没定义 break-glass，token 被吊销后人类怎么签发恢复？

## 风险评估
- C1：只读 /tmp 会搞坏硬编码 /tmp 的工具链（pip、编译器）
- C2：单点故障 + 300s 金丝雀阻塞紧急 revoke
- C3：24h 熔断周末误伤正常任务
- C4："documentation"标签训练 agent 无视文档

## 优先级
- A：C2 > C1 > C3 > C4（C2 防住的伤害最大）
- B：C1 > C2 > C3 > C4（C1 投入产出比最高，C2 防住的绝对伤害最大）

## 关键修改
- C1：A 说保留只读+24h 影子预检；B 说改 bind-mount 到持久目录（不断工具链）
- C2：删 300s canary（阻塞紧急），加 SO_PEERCRED + 网络 egress 封锁
- C3：agent 对 risk_register 只读，需人类签名才能 ENFORCED；非关键 72h
- C4：别叫"documentation"，叫"系统不变量"（物理定律式描述）
