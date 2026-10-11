# AI Studio 哑火干预升级链 MUST/NEVER v1.0（2026-10-08 23:04 CST）
## 25 条可执行规格

### 核心设计决策
- Shorts vs 长视频分开定义：Shorts 24h<100 views；长视频 72h<50 views
- 旧"48h<50 自动换标题"明确废弃（实测无效）
- L1 自动执行（诊断+元数据补全，T+48h）；L2/L3 必须人工审批
- Shorts 不支持自定义缩略图 → "换封面"对 Shorts 无效，禁止作为干预手段
- NEVER 24h 内删重发（YouTube spam 政策）

### 状态机
NORMAL → WATCH → DUD_SHORTS → L1 →（T+72h 复检）→ RECOVERED | L2审批 →（A回炉重发/B放弃归档）→ L3审批 → 归档+题材禁发+复盘
DUD_SEVERE（24h 0播放0展示）跳过 L1 直进 L2

### 关键条文摘要
- 哑火定义：shorts 24h<100；severe：24h 0播放+0展示；WATCH：6h 0播放（只看板不干预）
- L1（T+48h）：拉 impressions/CTR/观看时长 → 可见性校验 → 元数据补全（标题/描述/hashtag/置顶评论）→ T+72h 复检
- L2：复检<100 → 人工审批单（A回炉重发：复用<50%且连续相同≤5s，占正常排期；B放弃归档：24h 内设 private）
- L3：回炉版 7 天<100 → 归档 + 题材 30 天禁发 + 复盘
- 幂等：(video_id, level) 键；API 失败 1h/4h/12h 退避 3 次；失败≠无效
- 人工：L2/L3 必须显式批准；审批单 72h 无决议 → 冻结升级链并升级告警
