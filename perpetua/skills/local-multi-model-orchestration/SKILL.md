# Multi-Model Orchestration（多模型浏览器编排）

## Purpose
让任何 agent 都能调度外部 AI 模型做独立评审。核心洞察：**你不需要模型间直连**——你做中央调度，浏览器做传输层。

## 原理机制

```
你 (Muse)
  │  写 prompt
  ▼
browser.spawn_task ──→ Chromium ──→ 目标网站 ──→ 外部模型
  │                                              (arena.ai / aistudio.google.com / YouTube Studio)
  │  异步 handoff 返回文字
  ▼
你综合多个模型的回答 → 判决
```

- **大脑互不相识**：是你在大脑之间传话，不是它们自己协商
- **"一致结论"是你判定的**：你对比多个回答，找交集
- **传输层是浏览器 RPA**：填表单、点发送、等回答、抓文字

## Workflow

### 1. 准备 Prompt
写一个自包含的 prompt（浏览器任务看不到你的上下文）：
- 背景：发生了什么（具体事实，不是推测）
- 待评审对象：方案/代码/决策的原文或摘要
- 输出要求：明确要什么格式（KEEP/MODIFY/DROP、具体命令、拒绝空话）

### 2. 调度（串行，防状态污染）
```
browser.spawn_task(initial_url="<目标站>", task="<完整指令>")
```
- LMArena：`https://arena.ai`，指定 Side-by-Side + 具名模型，禁匿名 Battle（重大决策）
- AI Studio：`https://aistudio.google.com/prompts/new_chat?model=gemini-3.8-flash`（免费档，不建 API key）
- 串行：等 A 完成再调 B，把 A 的结论喂给 B（大脑互不相识，靠你传话）

### 3. 收结果
Handoff 返回 verbatim 文字。存档到文件（如 `lmarena.md`），不要只放上下文里。

### 4. 综合判决
- 找交集：多模型独立得出相同结论 → 可信度高
- 找分歧：记录分歧点，决定采谁的（说明理由）
- 输出：你的最终判决，不是模型的原话堆砌

## Output Contract
每次编排产出：
- `brief_*.md`：发给每个大脑的 prompt（可复现）
- `<brain>.md`：各大脑 verbatim 回答
- `verdict.md`：你的综合判决（含分歧处理）

## Operating Rules
1. **大脑只输出常量，不输出建议**：prompt 里明确要可执行、可验证的内容
2. **质量门**：缺判决（如无 KEEP/MODIFY/DROP）或缺具体命令 → 打回重问
3. **评审≠批准**：大脑的结论是输入，最终决策权在用户（Tier 3 尤其如此）
4. **诚实局限**：浏览器 RPA 脆弱（网站改版就挂）、慢、无 API 级集成；你是单点瓶颈
5. **不造神**："三脑一致" 是你对比判定的，不是它们达成的共识

## 局限（必须告诉用户）
- 全靠网页 UI，无 API，改版即挂
- 异步，慢（分钟级）
- 需要浏览器登录态（用户预先登好）
- 你是单点：你挂了协调就断

## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.