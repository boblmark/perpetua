# 标题公式 2.0：从"爆点型"升级为"悬念型"

> 日期：2026-10-07 ｜ 来源：竞品拆解（HOA Karen 故事系）+ v2 研究 But/Therefore 张力结构
> 核心洞察：**竞品卖的是"故事的后半段"，我们卖的是"报应的一瞬间"。**
> 我们的标题是"大结局剧透"（观众 1 秒看完），竞品是"上集预告"（好奇心缺口阻止划走）。

## 公式对照

**旧公式（爆点型 / v1）**：`[emoji] [场景] [报应动词] Karen! [emoji] #Shorts`
**新公式（悬念型 / v2）**：`[emoji]Karen [具体作恶]—Then [反转事件] [emoji]`

保留：emoji 开头、Karen 主语（门禁 Gate 2/3/5a 不变）。
去掉：报应动词剧透、`INSTANT KARMA!`、`#Shorts` 后缀（标题已够长）。

---

## 5 组对照示例

### 1. 收银台
- **旧**：`🛒 Self-Checkout TRAPPED Karen! 🤖💸 #Shorts`
- **新**：`🛒 Karen Demanded a Refund—Then the AI Showed Her Receipt to Everyone 😂`
- **改了什么**：报应动词 TRAPPED → 具体反转事件（收据公示）。
- **为什么**："TRAPPED" 1 秒剧透结局；"Showed Her Receipt to Everyone" 让观众想知道收据上写了什么、围观者什么反应——好奇心缺口。

### 2. 加油站
- **旧**：`⛽ Smart Pump SOAKED Karen! 😱💦 #Shorts`
- **新**：`⛽ Karen Slammed an Expired Coupon on the Scanner—Then the Pump Displayed Her License Plate to the Whole Station 😱`
- **改了什么**：SOAKED → 车牌公示。
- **为什么**：旧标题的爽点是物理的（被喷湿），新标题的爽点是社会的（社死）。社死型反转的评论区讨论度更高（"what would YOU do" 天然接得上）。

### 3. 得来速
- **旧**：`🔊 Drive-Thru Speaker MUTED Karen! 😂🎙️ #Shorts`
- **新**：`🔊 Karen Yelled About Her Cold Fries—Then the Speaker Played Back Her Rant to the Line Behind Her 😂`
- **改了什么**：MUTED（抽象）→ 录音回放（具体事件）。
- **为什么**：MUTED 是结果，Played Back 是过程。过程型标题自带画面感，观众脑内已经开始播放那段录音了。

### 4. 停车场
- **旧**：`🅿️ Parking Kiosk BOOTED Karen! 😱🚙 #Shorts`
- **新**：`🅿️ Karen Tailgated the Gate—Then the Kiosk Towed Her Car While She Watched 😱`
- **改了什么**：BOOTED → 拖车进行时。
- **为什么**："While She Watched" 是点睛——把 Karen 的实时反应写进标题，观众想看她那一刻的表情。这是竞品"反应收割"模板的标题版。

### 5. 门铃
- **旧**：`🔔 Smart Doorbell EXPOSED Karen! 🤖📹 #Shorts`
- **新**：`🔔 Karen Pounded on the Door—Then the Doorbell Sent the Footage to the Neighborhood Group Chat 🤖`
- **改了什么**：EXPOSED（抽象）→ 发业主群（具体+社死）。
- **为什么**："Neighborhood Group Chat" 是具体可感的社死场景，每个观众都能代入。抽象动词 EXPOSED 没有这个代入感。

---

## A/B 测试计划

### 分组
- **A 组（对照）**：旧爆点型公式，5 条
- **B 组（实验）**：新悬念型公式，5 条
- 主题配对：同一场景（如 self-checkout）新老各 1 条，控制场景变量

### 发布控制
- 发布时间：都用最优窗口（12:30 / 00:00 CST），A/B 交错
- 间隔：≥6 小时，避免互相抢流量
- 周期：10 天发完 10 条（每天 1 条，A/B 交替）

### 观察指标（按重要性）
1. **CTR**（点击率）：悬念型核心假设——好奇心缺口提升点击
2. **平均观看时长**：标题是否带来"想看完"的观众
3. **播放量**（48h）：综合结果
4. **评论率**：社死型反转是否激发讨论

### 判定标准
- B 组 CTR 高于 A 组 **≥15%** 且播放量不低于 → 全面切换 v2
- CTR 持平但评论率高 → 保留 v2 用于社死类场景
- B 组全面落后 → 回滚 v1，复盘是公式问题还是执行问题

### 出结论时间
10 条发完后 + 48h 数据回流 = 约 12 天出结论。

---

## 落地状态
- [x] `viral_prompt.py`：`build_viral_prompt()` 默认生成 v2 标题（2026-10-07）
- [x] 新增 `build_suspense_title()` / `_misdeed_from_hook()` / `REVERSAL_EVENTS`
- [x] 门禁兼容性验证：Gate 2（主语）/ Gate 3（emoji）/ Gate 5a（纯度）/ Gate 5c（编号）/ Gate 6（动词）均无需改动
- [ ] A/B 测试：待排期
