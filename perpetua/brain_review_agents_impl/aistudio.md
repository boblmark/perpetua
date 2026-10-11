# Brain ② AI Studio 回答（2026-10-08 12:28 CST）
# Gemini 3.8 Flash（免费档）

## 执行顺序
1. **C2 credential-proxy** 先：消除主要风险，建立 egress 边界
2. **C1 /tmp bind-mount** 次：防止数据丢失
3. **C3 risk_register** 第三：把规则落成签名状态
4. **C4 AGENTS.md** 最后：文档化已建立的边界

## C2：Credential Proxy + SO_PEERCRED + Egress 防火墙
- Unix socket `/run/credential-proxy/proxy.sock`，SO_PEERCRED 验证调用者 UID
- vault.json 存 token，shared_systems>1 时无 force 拒绝 revoke
- nftables 封锁 hatch 用户直连 OAuth 端点（142.250.0/15 等）
- 回滚：停服务、删文件、清 nft 规则

## C1：/tmp Bind-Mount（非只读）
- `/var/persist-tmp` bind 到 `/tmp`（不断工具链，采纳 Model B 方案）
- tmpfiles 阻止 systemd 清理
- 24h shadow audit timer 检查 mountpoint + prompt 文件
- 回滚：停 timer、umount、删配置

## C3：密码学签名 Risk Register
- ECDSA prime256v1 签名，hatch 只读（644，root:root）
- 私钥离线（CI/人类硬件），hatch 无法自证 ENFORCED
- SLA：critical 24h / non-critical 72h
- 回滚：删 /etc/risk-register

## C4：System Invariants（非"documentation"）
- 描述为系统不变量，非"文档版"
- chattr +i 防改
- 回滚：chattr -i 后删除

## Break-Glass（补 Gap 3）
- root 可直接 revoke（绕过 proxy）
- 紧急时临时放行 egress
- 紧急签名覆盖 risk_register

## 端到端测试（6 项）
1. AGENTS.md 不可变
2. /tmp 持久化
3. Risk register 签名+只读
4. Proxy SO_PEERCRED 认证
5. 共享凭据无 force 拒绝
6. 直接 egress 被阻断
