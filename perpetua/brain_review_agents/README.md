# AGENTS.md 灾难预防能力评审（2026-10-08）

## 主题
AGENTS.md 为什么没能预防两次灾难？如何改造才能真正预防第三次？

## 参与大脑
- ① LMArena（陪审团）：三范式横评，判哪个最能解决"已知风险拖延不治"
- ② AI Studio（总工程师）：基于判决，写可执行的预防机制规格
- Ask Studio 不参与（YouTube 专用，与流程设计无关）
- NotebookLM 归档由主 agent 手动做

## 执行顺序（严格串行）
1. 父级按 `brief_1_lmarena.md` 调起 browser.spawn_task（arena.ai, Side-by-Side）
   → 双模型回答 verbatim 存入 `lmarena.md`
2. 父级把 lmarena.md 全文填入 `brief_2_aistudio.md` 占位符，调起 browser.spawn_task
   （aistudio.google.com, 免费档 gemini-3.8-flash）
   → 回答 verbatim 存入 `aistudio.md`
3. 填写 `verdict.md`：根本缺陷 + 解决方案 + 落地清单

## 质量门
- 只要可执行机制，不要空洞建议（出现"建议…"打回重问）
- LMArena 禁匿名 Battle，必须 Side-by-Side 指定模型
- AI Studio 禁付费档、禁建 API key
- 全程只读评审，不碰 AGENTS.md 等生产文件（改造由主 agent 另行决定）
