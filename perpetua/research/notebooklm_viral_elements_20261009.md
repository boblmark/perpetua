# NotebookLM「ViralLoop Channel Knowledge Base」问答存档（2026-10-09）

Notebook：https://notebook.google.com/notebook/71e2e25e-ace4-48c4-8133-d82fbc06e18b
8 个来源中与病毒视频相关的：veo_prompt_v51.txt、veo_v51_test_report.md
（两个回答的引用全部来自这两个 v5.1 时代文档）

---

## 回答 1：病毒视频（viral short video）的完整要素（5 大类）

根据短视频留存数据与制作规范，一个高留存、无缝循环的病毒式短视频包含以下 5 大核心类别要素：

### 1. 结构与时间轴安排（Pacing & Timeline Engine）

**0–2s 黄金 Hook 引擎：**
- 0.00s 极特写开场：首帧直接开启极特写，主体处于峰值情绪（震惊、愤怒、困惑），严禁远景、开场场景、Logo 或渐入动画。
- 即时 Premise Hook 文字：0.00s 即在屏幕呈现前提 Hook 文本（最多 6 个词），并在 0–2s 全程保持可见。

**2–6s 冲突快速升级（Rapid Escalation）：**矛盾对抗迅速升级，冷酷规则与荒谬诉求碰撞；中间穿插 0.5s 极度死板的停顿作为笑点预备。

**6–7s 高潮突发业报（Instant Karma）：**高潮必须在 2 秒内落地为实体物理喜剧（如喷水、锁死、浸湿、拖走等），禁止纯语言吐槽。

**7–8s 硬切与无缝循环（Loop-Out）：**高潮落地后约 1 秒迅速硬切，无废镜头；结尾播放重置音效或台词，形成闭环周期。

### 2. 视觉美学与镜头语言（Visuals & Camera Language）

- 开场极特写取景（Extreme Close-Up）：首帧主体人脸须占竖屏画面的 50% 以上（Mugshot 紧凑取景），极大化画面张力。
- 高强度运动量化（Motion Quantification）：主体头部或上身每秒位移必须达 ≥20% 画面宽度，画面静止绝对不可超过 0.3 秒。允许并鼓励快速运动产生的运动模糊（Motion Blur），禁止僵硬的静止画帧。
- 纪实手持微抖（Handheld Shake）：画面保留 ±10px 的微幅手持抖动，营造 CCTV / 监控 / 行车记录仪的真实现场感。
- UI 安全区布局（UI Safe Zone）：9:16 竖屏，核心文字与视觉笑点必须锁定在顶部至中部三分之一区域。严禁将关键信息置于右侧（互动按钮覆盖区）或底部 25%（频道与标题覆盖区）；CCTV 时间戳 HUD 仅限置于左上角。

### 3. 音频与声学设计（Audio & Sound Design）

- 即时人声起音与音量渐变（Vocal Onset & Volume Ramp）：音频必须在 0.00s 即时开启（起始音量 70%），以具辨识度的人声音节开场（如 "Excuse me—"），并在 2.00s 内渐增至峰值。严禁开场静音、大音效爆音或背景音乐遮挡，避免触发用户的刷走本能。
- 自然环境音与音效：2 秒之后接入自然 Foley 音效与环境电流声，避免使用俗套欢快音乐或长于 1 秒的静音。
- 首尾音效呼应：结尾 AI 或系统重置音效与开场形成呼应，强化循环感受。

### 4. 角色与叙事对立（Cast & Narrative Dynamics）

- 强烈角色反差：情绪极度激进的角色 vs 绝对冷酷死板的自动化设备/AI（日常摩擦点），搭配背景僵住的围观群众增强真实感。
- 实体物理反转：以日常生活中的摩擦为切入点，冷酷逻辑执法，最终以突发的实体物理业报收尾，AI/设备永远拿到最后的笑柄。

### 5. 无缝循环与元数据优化（Loop & Metadata Telemetry）

- 首尾像素级呼应（Loop Pre-Burial）：最后 0.5 秒主体的姿态、头角与口型必须精确回归首帧姿态。视频整体呈 8 秒振荡周期（前冲 0–3s → 回缩 3–6s → 再前冲 6–8s），后处理验证首尾图像相似度 ≥0.75。
- 口播纯台词字幕：字幕仅显示实际口播台词，严禁出现场景标签、角色名、'POV' 或 'Wait for it' 等元标签。
- 数据驱动的元数据：标题宜短（胜利视频标题平均约 57 字符），Hashtag 精简（约 1.4 个），提高留存与算法推荐效率。

---

## 回答 2：AI 短视频生成提示词模板（可直接用的完整版本）

### 一、通用 AI 短视频提示词模板（可直接替换方括号 [ ] 内变量）

**[GLOBAL SYSTEM SPECS]**
Vertical 9:16 short video, exactly 8 seconds, 30fps.
Aesthetic: Raw CCTV / dashcam / smart-camera aesthetic, high contrast, slightly desaturated daylight.
HUD: Timestamp overlay in the top-LEFT corner ('CAM 03 - 14:22:07'). No watermarks, no black bars, no cinematic letterbox.
Camera Mechanics: HANDHELD camera with constant subtle micro-shake (±10px), motion blur desired, zero static lockoff.

**[CAST & SCENE]**
- Protagonist: [主角人设，例如：Middle-aged woman in pink tracksuit], perpetually outraged, wide eyes, mouth open mid-rant.
- Automated Friction Device: [智能设备/摩擦节点，例如：Smart parking meter / AI vending machine], anthropomorphized with a glowing status light and deadpan screen text. Stays perfectly calm while protagonist escalates.
- Bystander: One bystander in background frozen mid-stare, phone out, selling "caught on camera" realism.

**[0-2s HOOK ENGINE]**
- Frame 0.00s: OPENS IMMEDIATELY on EXTREME CLOSE-UP. Protagonist's face fills at least 50% of the vertical frame (mugshot framing, nose near lens). Peak facial tension (outrage/disbelief).
- On-Screen Text: Premise hook text at 0.00s: "[开场 Hook 文案，例如：PARKING METER DENIES COIN]" (MAX 6 words, high-contrast yellow with black stroke, placed in TOP-MIDDLE THIRD). Visible for full 0-2s window.
- Audio Onset: Begins at 0.00s at 70% volume with a distinct vocal onset (e.g., "[第一句台词，例如：Excuse me—]"). Ramps continuously to 100% peak volume at 2.00s. Zero silent frames, no music.

**[2-6s RAPID ESCALATION & MOTION QUANTIFICATION]**
- Motion Requirement: Protagonist's head/upper body MUST move at least 20% of frame width every single second. No static holding over 0.3 seconds.
- Action: Protagonist escalates conflict by [冲突升级动作，例如：violently shaking the machine and finger-jabbing].
- Device Response: Cold literal enforcement following a deadpan 0.5s pause.

**[6-7s CLIMAX - SUDDEN PHYSICAL KARMA]**
- Physical Karma: Tangible slapstick mishap erupts in under 2 seconds: [物理惩罚落地，例如：sudden water spray / instant wheel lock / foam trap].
- Aftermath: Protagonist freezes mid-gesture in comic disbelief.

**[7-8s LOOP-OUT & LOOP PRE-BURIAL]**
- Loop Burial: Final 0.5 seconds MUST show protagonist returning to the EXACT opening pose, head angle, and mouth shape as Frame 0.00s (completing an 8s oscillation cycle).
- Audio Reset: AI device chimes a reset phrase: "[结尾复位音效/台词，例如：NEXT CUSTOMER, PLEASE.]" matching frame 0.
- Hard cut at 8.00s. No fade-out, no slow motion.

**[UI SAFE ZONE & TEXT CONSTRAINTS]**
- All text overlays strictly locked within TOP-MIDDLE THIRD of frame (never right edge or bottom 25%).
- Subtitles: SPOKEN DIALOGUE ONLY. No character names, no 'POV', no 'Wait for it'.

### 二、可直接复制使用的实战 Prompt 范例（人机停车位冲突）

Vertical 9:16 short video, exactly 8 seconds, 30fps. Raw CCTV dashcam aesthetic, timestamp HUD in top-LEFT corner 'CAM 03 - 14:22:07'. Handheld camera with constant ±10px micro-shake and slight motion blur.
Frame 0.00s - 2.00s: Opens immediately on an EXTREME CLOSE-UP of a middle-aged woman in a pink tracksuit, face filling 50% of the vertical frame (mugshot framing). She is mid-rant with wide outraged eyes and finger jabbing at camera. Text overlay at 0.00s in top-middle third: "PARKING METER DENIES COIN" (yellow with black stroke). Audio begins at 0.00s at 70% volume with her voice shouting "Excuse me—" ramping to peak volume at 2.00s.
2.00s - 6.00s: Woman vigorously shakes the smart parking meter, moving her head and body over 20% of screen width every second. The smart parking meter stays deadpan with a glowing status light, pauses for 0.5s, then responds with cold literal logic.
6.00s - 7.00s: A sudden physical karma erupts: the parking meter sprays a burst of water straight into her face. She freezes mid-gesture in comic shock and disbelief.
7.00s - 8.00s: The AI meter chimes "NEXT CUSTOMER, PLEASE.". In the final 0.5 seconds, the woman's pose and face angle swiftly return to the exact opening pose of frame 0.00s for a seamless 8-second loop cycle. Hard cut at 8.00s.
Constraints: UI safe zone enforced (top-middle third only for text). Spoken dialogue subtitles only, no 'POV' tags. No static poses, no slow motion.

---

## 与当前管线（v5.2 + RESEARCH CONSTANTS）的差异审计（2026-10-09）

Notebook 的两个回答全部引自 v5.1 时代文档，与 v5.2 有两处实质差异：

1. **Loop Pre-Burial 振荡周期（前冲→回缩→再前冲）**：v5.2 三脑会诊已明确删除（V51_LOOP_SEED），认定回缩抹平高潮。v5.2 保留的是"终帧与首帧视觉呼应 + loop_check ≥0.75 验证"，不要复活振荡周期。
2. **面瘫停顿 0.5s vs 1.2s**：v5.1 写 0.5s；2026-10-09 LMArena 趋势研究给的是 ~1.2s（4.5–5.8s）。新研究更新，模板里"Deadpan 0.5s pause"措辞可考虑跟进到 1.2s。

可采纳的增量细节（不冲突）：
- Hook 文字样式：高对比黄字黑描边（yellow with black stroke）——当前模板只写了 MAX 6 词 + upper-third，可补样式。
- 字幕约束：仅口播台词，禁角色名/'POV'/'Wait for it' —— 检查 burn_subtitles.py 是否执行。
- 元数据：标题 ~57 字符、hashtag ~1.4 个 —— 与当前标题公式一致（3-5 标签含 #Shorts 需复核数量）。
