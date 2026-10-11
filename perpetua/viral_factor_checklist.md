# 爆款全要素清单（2026-10-09）

> 战略：prompt = 爆款要素的完整规格书（spec）；后期 = 机械门修复；
> QC = 对可测量要素的验证；修不好/内容门 = 自动重生成；供应商拒单 = 换供应商。
> 只要最终交付的视频通过全部可测量要素验证，爆款概率即被工程化拉满；
> 剩余方差在分发端（时机、竞争），由动态排期/48h换标题/爆款续集对冲。

来源：LMArena Agent 趋势调研（2026-10-09，`research/lmarena_ai_comedy_trends_20261009.md`）
+ 频道自有数据规律 + v5.2 三脑会诊常量。

## 要素 → Prompt 规格 → QC 验证 → 后期修复

| # | 爆款要素 | Prompt 规格位置 | QC 验证 | 后期修复 |
|---|----------|----------------|---------|----------|
| 1 | 4节拍：0–3.5s 刁蛮升级 | RESEARCH CONSTANTS + 2-6s escalation | hookmotion（0-1.5s，Tier2计分） | — |
| 2 | 3.5–4.5s 单一物理触发点 | RESEARCH CONSTANTS | —（prompt级，暂不可测） | — |
| 3 | 4.5–5.8s 机器面瘫停顿 ~1.2s | RESEARCH CONSTANTS | deadpan_pause（Tier2 warn-only诊断，2026-10-09新增） | — |
| 4 | 5.8–8s 不成比例物理报应 + 冷漠路人 | RESEARCH CONSTANTS + 6-7s CLIMAX | climax（音频峰值6.5-7.5s）+ actionclarity（高潮/升级能量比） | — |
| 5 | 首帧 mid-argument 特写（嘴张开、手指戳镜头） | V51_CLOSEUP_OPENING + 0-2s HOOK ENGINE | frame0_face（Tier1硬门，≥30%）+ firstframe_hook | R2 起始帧重定 |
| 6 | 零BGM + 纯环境音（荧光嗡鸣/风声/伺服/哔声/TTS） | RESEARCH CONSTANTS | audio_first_100ms（Tier1硬门）+ audiodyn | audio_envelope（响度标准化+包络） |
| 7 | 尖锐人声 vs 扁平面瘫机器重复 | RESEARCH CONSTANTS | —（prompt级，暂不可测） | — |
| 8 | candid iPhone/CCTV质感，无电影调色 | RESEARCH CONSTANTS + FORMAT_LOCK | —（prompt级，暂不可测） | — |
| 9 | Motion ramp ≥20%（0-6s），高潮 ≥40%，能量比 ≥1.60 | V52_MOTION_RAMP + V52_CLIMAX_RULES | motion_1s（Tier2，<2.50扣40分） | — |
| 10 | Loop 首尾呼应 ≥0.75 | 7-8s LOOP-OUT | loop_check（Tier2计分20） | R3 尾部切点搜索 |
| 11 | 8s / 9:16 / 手持抖动 / 无黑边 | FORMAT_LOCK | duration（7.5-11s）+ resolution + fps（Tier1） | R1 黑帧修剪 |
| 12 | 背景冷漠路人（手机拍摄感） | Cast 描述 | —（prompt级，暂不可测） | — |
| 13 | 无黑帧/冻结/首帧静音 | —（生成质量基线） | blackframe + frozen + firstframe_silent（Tier1） | R1 |

## 分工铁律

- **Prompt 缺要素** → 补模板（走三脑议会才升版本；研究常量走 research_brief 注入，不升版本）。
- **QC 可测要素不达标**：
  - 机械门（#5部分、#6、#10、#11、#13）→ 后期自动修（qc_repair），修不好才重生成。
  - 内容门（#1、#4、#9）→ 自动重生成（最多2次），耗尽则归档+告警。
- **供应商拒单**（integrity_check_failed / 内容审核误判）→ 判 failed，不换措辞重试，直接换供应商。
- **QC 终裁永远跑在最终交付文件上**（postprocess 之后），fail-closed 不变。

## 诊断项升级路径

deadpan_pause 目前 warn-only。积累 ≥20 条样本后看分布：若"有停顿凹陷"的视频
完播/循环率显著更高，则升级为 Tier2 计分项；反之维持诊断。
