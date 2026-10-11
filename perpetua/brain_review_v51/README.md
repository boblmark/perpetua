# 三脑会诊 v5.1 → v5.2

## 执行顺序（严格串行）
1. `brief_1_ask_studio.md` → browser.spawn_task → 答案存 `ask_studio.md`
2. `brief_2_lmarena.md`（填入 ask_studio.md 全文）→ browser.spawn_task → 答案存 `lmarena.md`
3. `brief_3_aistudio.md`（填入 ask_studio.md + lmarena.md 全文）→ browser.spawn_task → 答案存 `aistudio.md`
4. 填写 `verdict.md`：共识点 / 分歧点 / v5.2 改动清单

## 质量门
- 只要常量不要建议；出现"建议…"类措辞 → 打回重问
- LMArena 必须 Side-by-Side 指定模型，禁匿名 Battle
- AI Studio 必须免费档（gemini-3.8-flash），禁付费/建 key
- 只读评审，不修改任何生产文件（viral_prompt.py 等）

## 文件
- `brief_1_ask_studio.md` — 脑①调用简报（含完整 task 正文）
- `brief_2_lmarena.md` — 脑②调用简报
- `brief_3_aistudio.md` — 脑③调用简报
- `ask_studio.md` — 脑①完整原文回答（待填）
- `lmarena.md` — 脑②完整原文回答（待填）
- `aistudio.md` — 脑③完整原文回答（待填）
- `verdict.md` — 综合结论（待填）
