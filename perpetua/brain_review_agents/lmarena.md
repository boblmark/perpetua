# Brain ① LMArena 回答原文（2026-10-08 11:56 CST）
# Side-by-Side: gemini-3.1-pro-preview (A) vs gemini-3.6-flash (B)
# https://arena.ai/c/01a119a5-fa59-7310-b8f7-74dd14f889e6

## 共识
- **总冠军：范式 C（结构消除）**，范式 B 为辅助，范式 A 降级为纯人类文档
- 范式A DROP：文本无法约束概率模型，灾难2已证明
- 范式B MODIFY：去掉"自觉申报"，改硬前置拦截（脚本自己执行检查，不问 agent）
- 范式C KEEP：让错误动作物理上不可能

## 分歧：灾难1（未知共享凭据）能否预防？
- 模型A：**不能**。unknown unknown 任何范式都防不住，只能靠回滚预案缓解。这是架构失败（缺 IAM 隔离），不是 agent 失败。
- 模型B：**能**。范式C 的凭据隔离架构（1 actor = 1 credential）从根上消除共享，Marvis revoke 只影响自己的 token。

## 核心机制
- 灾难2：同步状态强制——创建时就没有"先放 /tmp 稍后搬"的中间态可选
- 灾难1（B观点）：凭据按服务实例隔离，blast radius 结构性归零
