# 动词池回血包（待拍板）— 2026-10-12 11:31 起草

## 现状（已核验）

- 可用 karma 动词池 = 17 个（tier_s 9 + tier_b 8），全部在近 30 天用过 → 去重硬门下**结构性耗尽**
- 今晨 11:00 档选题轮：**0 新选题**（pipeline event_bus 31 PENDING 库存，generating=0）
- 今晚 22:00（perpetua-pipeline-pm）选题轮：大概率同样 0 选题
- 唯一回血通道 = Ask Studio 扩充回答，但浏览器通道今日故障（08:49 日检登录页拦截；队列处理器 3 轮失败；已按规则升级主 agent 绕行，结果未定）
- 三文件同源：`karma_verbs.json`（tiers）→ `mcp_server/server.py:1352` 上传硬门只认 tier_s/tier_b；
  `formula_dedup.py KARMA_VERBS`（去重提取）；`viral_prompt.py KARMA_VERBS_TIER_S/B`（生成轮换）。
  三处必须同步加，否则"能生成但发不出去"或"去重追踪不到"。

## 候选 10 词（全部满足 Ask Studio 2026-10-06 常量：具象 slapstick > 抽象夸张；动词强度=画面强度；family-friendly；与现有 17 词 + dedup 16 词视觉上不重叠）

### S 档（强物理笑点）
| 动词 | 例标题 | 笑点画面 | 与现存词区别 |
|---|---|---|---|
| LAUNCHED | 🚽 Karen Sat On The Smart Toilet… It LAUNCHED Her 😱 | 智能马桶盖把她向上弹飞 | EJECT=被甩出原地；LAUNCH=垂直升空 |
| SWALLOWED | 🗑️ Karen Dropped Her Phone… The Smart Trash Can SWALLOWED It 😭 | 垃圾桶盖"咔"吞掉手机 | TRAPPED=她被困；SWALLOWED=设备吃掉物件 |
| WRAPPED | 🪟 Karen Opened The Smart Blinds… They WRAPPED Her Like A Burrito 🌯 | 电动百叶把她卷成卷饼 | 无近似词 |
| DUNKED | 🎯 Karen Mocked The Dunk Tank… Got DUNKED Instantly 💦 | 整人座椅掉落全身入水 | SOAKED=表面淋湿；DUNKED=整人下坠 |
| FROZEN | ❄️ Karen Opened The Smart Freezer… It FROZE Her Mid-Rant 🥶 | 速冻雾让她僵在原地 | SHOCKED=电击；FROZEN=冰冻定格 |
| GLUED | 👟 Karen Stepped On Smart Adhesive… Got GLUED To The Floor 😂 | 鞋粘住单脚跳 | 无近似词 |
| PAINTED | 🎨 Karen Yelled At The Paint Robot… It PAINTED Her Face 🖌️ | 机械臂转向喷她一脸漆 | SPRAYED=水雾；PAINTED=可见颜料糊脸 |
| FOAMED | 🫧 Karen Pressed 'Extra Clean'… The Car Wash FOAMED Her 🚗 | 泡沫炮爆发淹没 | SOAKED=水；FOAMED=厚泡沫毯 |

### B 档（caught-in-the-act 系，弱视觉承诺）
| 动词 | 例标题 | 笑点画面 | 与现存词区别 |
|---|---|---|---|
| FRAMED | 📸 The Doorbell Cam FRAMED Karen Stealing Packages 🚨 | 摄像头红框锁定她的脸 | CAUGHT=行为被看见；FRAMED=镜头字面"框住"她 |
| CALLED OUT | 🔊 Karen Lied To The Smart Speaker… It CALLED HER OUT 😳 | 音箱当众拆穿她的谎 | SNITCHED=告密给第三方；CALLED OUT=当场拆穿 |

## 落地三步（批了即执行，全部可逆，先备份）

1. `karma_verbs.json`：tier_s += 8 个，tier_b += 2 个
2. `formula_dedup.py` KARMA_VERBS += 词形变化：
   launch/launches/launched, swallow/swallows/swallowed, wrap/wraps/wrapped,
   dunk/dunks/dunked, freeze/freezes/frozen, glue/glues/glued,
   paint/paints/painted, foam/foams/foamed, frame/frames/framed,
   "call out"/"calls out"/"called out"
3. `viral_prompt.py` KARMA_VERBS_TIER_S/B += 同 10 个

护栏：banned 4 词不动；强度=画面规则不动；每个新词首用走正常 Ask Studio ≥85 评审。

## 与 Ask Studio 的关系

- 若主 agent 绕行的 Ask Studio 扩充回答在 22:00 前回来 → 以它的答案为准，本包自动作废
- 若没回来 → 你批一个字（"上"），22:00 档即有 10 个新动词可用

有效期：今晚 22:00 选题轮前最有价值；之后仍可作明早 11:00 档的回血。
