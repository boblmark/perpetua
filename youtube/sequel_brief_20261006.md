# 爆款续集选题包（Part 2）— 2026-10-06

依据：`youtube/all_videos.json`（490 视频，74.2万播放）Top12 + `jev/criteria.json` v3 公式
`[emoji] Karen + 冲突动作 + 即时报应 + [emoji]`，陈述句，前3秒强视觉冲击，时长 9–16 秒。

## 6 个候选（按原版热度排序）

| # | 续集标题 | 前3秒钩子 | 原版（播放） | 时长建议 |
|---|---------|-----------|-------------|---------|
| 1 | 🚗 HOA Karen Called the Tow Truck on ME — They Towed HER Ferrari Instead! 😱 #InstantKarma #hoa | 拖车开走红色法拉利，Karen 在后面狂追 | #1 HOA Karen 拖车（30.6K） | 11s |
| 2 | ⛽ Karen Tried to Siphon MY Gas — The Hose BACKFIRED All Over Her! 😱💦 #InstantKarma | 汽油管回喷，Karen 白裙瞬间湿透 | #2 加油站 Karen（30.6K） | 11s |
| 3 | 🛗 Karen Blocked the Elevator Doors — They SLAMMED Her Shopping Cart! 😂 #InstantKarma | 电梯门夹住购物车，东西洒一地 | #3 电梯行李箱爆炸（28.9K） | 9s |
| 4 | 🔊 Smart Speaker Heard "Order Pizza" — It Ordered 50 Pizzas to Karen's House! 🍕😱 #AIFail | 50 份披萨堆满门口，Karen 傻眼 | #4 智能音箱听错指令（27.9K） | 11s |
| 5 | 🍔 Elevator Opened — 10 DOGS Hijacked My Burger Delivery! 🐕💀 #viral | 电梯门开，狗群扑向汉堡袋 | #7 15 条狗抢披萨（15.9K） | 9s |
| 6 | 🚪 Karen Cut the Coffee Line — The Auto Door TRAPPED Her Shopping Bag! 😂 #InstantKarma #cctv | 自动门夹住购物袋，Karen 被拽停 | #8 插队门拒绝开（14.8K） | 9s |

## 模型校准实测（2026-10-06 11:35 左右）

| | jev_score | 规则版 virality_score |
|---|---|---|
| 原版爆款（30.6K 真实播放） | 28.4（confidence 0.0） | 33–43（C） |
| 本包 6 续集 | 28.4（confidence 0.0） | 36–46（C） |

**结论**：两个模型给"真实爆款"和"按爆款公式写的续集"打分基本一致——都远低于 60 分硬门槛。
模型无法区分真爆款与公式续集；按当前门槛，真爆款也会被拦。门槛是否下调（或换用数据公式直判），需用户定夺。

## 状态

待用户批准后推送给 Marvis（`collab/inbox.json` pending_pickup）。
