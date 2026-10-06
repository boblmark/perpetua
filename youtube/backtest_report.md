# 频道历史回溯分析报告

- 样本量：**488** 条
- 播放量：min=0 / p25=569 / median=1051 / p75=1324 / p90=2138 / max=30676
- 总播放：742,357 / 均值：1,521
- **0 播放视频数：7** (1.4%)
- **<10 播放：25** (5.1%)

## 一、现有 virality_score 对历史数据的预测力

| 分数区间 | 条数 | 平均播放 | 中位播放 | 最高播放 |
|---|---|---|---|---|
| 30-39 | 312 | 1,676 | 1,051 | 30,676 |
| 40-49 | 153 | 1,313 | 1,044 | 20,959 |
| 50-59 | 21 | 880 | 1,008 | 2,204 |
| 60-69 | 2 | 18 | 18 | 19 |

- **Pearson r = -0.0336**
- **Spearman ρ = -0.0003**

> 判读：ρ > 0.3 才算有弱相关；接近 0 说明**打分器与实际播放无关**。

## 二、Top 10% vs Bottom 10% 标题词频差异

（Top = 播放前 48 条，Bottom = 后 48 条）

| 词 | Top 出现 | Bottom 出现 | 差值 |
|---|---|---|---|
| `her` | 14 | 1 | +13 |
| `karen` | 21 | 8 | +13 |
| `instant` | 11 | 0 | +11 |
| `viral` | 12 | 2 | +10 |
| `karma` | 11 | 2 | +9 |
| `hoa` | 7 | 0 | +7 |
| `caught` | 6 | 0 | +6 |
| `instantkarma` | 9 | 3 | +6 |
| `car` | 6 | 0 | +6 |
| `cam` | 6 | 0 | +6 |
| `funny` | 6 | 0 | +6 |
| `gets` | 6 | 0 | +6 |
| `then` | 6 | 0 | +6 |
| `own` | 5 | 0 | +5 |
| `uncanny` | 6 | 1 | +5 |
| `glitch` | 4 | 0 | +4 |
| `case` | 4 | 0 | +4 |
| `horror` | 5 | 1 | +4 |
| `tried` | 4 | 0 | +4 |
| `doorbell` | 4 | 0 | +4 |

**Top 独有词**：`karen`(21), `her`(14), `viral`(12), `instant`(11), `karma`(11), `instantkarma`(9), `hoa`(7), `gets`(6), `car`(6), `caught`(6), `then`(6), `funny`(6), `cam`(6), `uncanny`(6), `own`(5)

**Bottom 独有词**：`karen`(8), `cinematic`(6), `epic`(6), `automobile`(5), `dog`(5), `film`(5), `mind`(4), `cyberpunk`(4), `animation`(3), `cctv`(3), `generated`(3), `wait`(3), `did`(3), `just`(3), `scenes`(3)

## 三、播放 Top 20

| 播放 | 标题 | 旧分 | 发布 |
|---|---|---|---|
| 30,676 | 【AI Satire】 🤯 HOA Karen Gets HER OWN CAR TOWED While Yelling | 39 | 2025-10-27 |
| 30,607 | ⛽ Karen Cut The Gas Line—Pump SOAKED Her Designer Outfit! 😱💦 | 36 | 2025-12-05 |
| 28,902 | 🤯 Karen Rushed The Elevator—Her Suitcase EXPLODED! 🧳👙 #trave | 39 | 2025-12-03 |
| 27,928 | 😳 Smart Speaker Heard the WRONG Command... Instant Fail 😂 | 33 | 2026-01-10 |
| 20,959 | Hero Dog Saves Child Protocol Guardian Case #087 😱 #HeroDog  | 43 | 2025-10-25 |
| 16,416 | My camera caught a wild deer comforting my crying child thro | 30 | 2025-10-20 |
| 15,930 | 🍕 Elevator Opened—15 DOGS Ambushed My Pizza! 🐕💀 | 43 | 2025-12-11 |
| 14,853 | 🚪 Karen Cuts The Line—Door REFUSED To Open! FACE PLANT! 😂 #c | 39 | 2025-12-03 |
| 11,380 | 🛒 Self-Checkout Smoothie TSUNAMI—It Hit 3 Lanes! 😱💚 #grocery | 46 | 2025-12-05 |
| 11,158 | 💪 Gym Bro Lost Grip—Started a DUMBBELL AVALANCHE! 🏋️💀 #gymfa | 39 | 2025-12-05 |
| 10,383 | 【AI Satire】 💦 INSTANT KARMA! HOA Karen Screams About Water W | 39 | 2025-10-28 |
| 9,191 | HOA Karen Fined ME... Then Her OWN Car Got TOWED! 🤯 #Instant | 39 | 2025-11-10 |
| 7,298 | 【AI Satire】🚨 CAUGHT! My HOA Karen Tried To FINE Me For a Wee | 39 | 2025-10-26 |
| 6,839 | 🤯 Karen Fought The Car Wash—The Brushes FLOODED Her Car INST | 36 | 2025-11-28 |
| 6,640 | My doorbell cam caught... a Skinwalker pretending to be my h | 43 | 2025-10-21 |
| 6,584 | 🤣 Headshot! Wait for His Reaction... The Stare of Betrayal 🐶 | 39 | 2026-01-19 |
| 6,313 | 🚨 INSTANT KARMA HITS HARD - The Moment This Guy Stepped In!  | 39 | 2025-11-18 |
| 5,113 | 🤯 Karen Left The Cart—The Wind Gave Her INSTANT KARMA! 🛒💨 #c | 39 | 2025-12-02 |
| 4,174 | 🤯 Karen Kicked The Cat's Box—She Fell Face-First Into The LI | 49 | 2025-11-30 |
| 4,159 | 【AI Visual Experiment】 🤯 UNSEEN HAND Saves Child | 33 | 2025-10-27 |

## 四、播放 Bottom 20

| 播放 | 标题 | 旧分 | 发布 |
|---|---|---|---|
| 0 | Rare Treasure: Nature's Gift from the Snowy Peaks | 30 | 2025-06-03 |
| 0 | This 80-Second Film Has a Better TWIST Than Most Hollywood M | 37 | 2025-09-02 |
| 0 | From Hero to Zero: 8 Shots of a Battlefield Charge | 37 | 2025-09-20 |
| 0 | Surreal Cuts! How I Used 8 Mind-Bending Scenes to Play with  | 43 | 2025-09-21 |
| 0 | The 8 Moments of "The Comeback": The Story of a Man Who Refu | 37 | 2025-09-28 |
| 0 | WB Verify Probe 001 | 37 | 2026-10-05 |
| 0 | AI Awakens: The Face of Tomorrow (You're Not Ready) | 36 | 2026-10-05 |
| 1 | THE AWAKENING: An AI-Generated Sci-Fi Short Film (4K Cinemat | 40 | 2025-09-23 |
| 1 | stodownload | 30 | 2026-02-18 |
| 1 | AI in 60 Seconds — Karen vs AI #shorts | 50 | 2026-10-05 |
| 2 | When the World Hits Mute: An Emotional Short Film About Lone | 30 | 2025-09-22 |
| 2 | Wait! This Horse Did Something IMPOSSIBLE 🐴 #shorts | 39 | 2026-02-25 |
| 2 | CAN YOU SPOT IT? 5 AI Glitches Hidden in This Video 🕵️‍♂️ (W | 47 | 2026-06-07 |
| 3 | I Used AI to Create a Cinematic Chinese Epic (VEO 3 Showcase | 40 | 2025-09-30 |
| 3 | 💰 FOLLOW THE MONEY: You Won’t Believe What’s at the End! (Mi | 46 | 2026-02-03 |
| 3 | EPIC STORE BATTLE: Karen vs Manager | Wuxia Style AI Demo ⚔️ | 43 | 2026-06-07 |
| 3 | ZhongceTong — Policy Intelligence Hub for S&T Funding Consul | 30 | 2026-09-28 |
| 4 | 🚨 THIS IS WHY YOUR PASSWORDS GET HACKED! (The Pizza Duck Con | 46 | 2026-01-20 |
| 5 | An Epic Solo Journey Across the Wilderness (4K Cinematic) | 37 | 2025-09-22 |
| 5 | geminigen PLAN 1779963661850 3f7c7f | 37 | 2026-05-28 |
