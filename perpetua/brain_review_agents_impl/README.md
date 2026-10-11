# 四脑评审：AGENTS.md 灾难预防落地方案 — 执行说明

## 背景
上一轮三脑会诊（`../brain_review_agents/`）结论：AGENTS.md 是事后诸葛亮，
需转向范式 C（结构消除）为主。落地方案 4 组件：
1. /tmp 只读挂载 + TMPDIR 重定向
2. credential-proxy 凭据隔离代理
3. risk_register.json + systemd timer（24h 强制时限）
4. AGENTS.md 更新（文档版 vs 执行版）

本轮评审落地方案本身：完整吗？风险？优先级？

## 执行顺序（严格串行）
1. **LMArena**：按 `brief_1_lmarena.md` 调起 browser.spawn_task
   （initial_url=`https://arena.ai`，Side-by-Side 指定模型，禁匿名 Battle）
   → 双模型回答 verbatim 存入 `lmarena.md`
2. **AI Studio**：把 `lmarena.md` 全文填入 `brief_2_aistudio.md` 占位符，
   调起 browser.spawn_task
   （initial_url=`https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash`，
   免费档，禁付费/建 key）
   → 回答 verbatim 存入 `aistudio.md`
3. 填写 `verdict.md`：最终落地方案（评审修订版）

## 质量门
- 只要技术结论（完整性/风险/优先级/可执行步骤），不要空洞建议
- LMArena 必须给出 KEEP/MODIFY/DROP + 优先级排序，否则打回重问
- AI Studio 必须给出可直接执行的命令+配置+回滚+验证，否则打回重问
- 全程只读评审，不应用任何变更（infra Tier 3，需用户逐项批准）

## 文件
- `brief_1_lmarena.md` — 脑①调用简报（含可直接复制的 task 正文）
- `brief_2_aistudio.md` — 脑②调用简报（lmarena.md 占位符待填）
- `lmarena.md` — 待填（双模型原文）
- `aistudio.md` — 待填（实施步骤原文）
- `verdict.md` — 待填（最终方案）
