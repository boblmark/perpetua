# 分发器 vendor 说明

## 底座
- 项目：dreammis/social-auto-upload（MIT）
- pin：commit 0012d2c355f88f683cc38dde2a2db209e14091bc（2026-10-10）
- 取用：uploader/ + myUtils/ + utils/ + requirements.txt（不要前端/后端/整套CLI）
- 上游更新：重新 shallow clone 后重跑 patches/apply_draft_patch.py（锚点变了会报错，人工跟进）

## Perpetua 补丁
- patches/apply_draft_patch.py：抖音新增 draft 策略（只点"存草稿"，找不到按钮直接抛异常，绝不回退到发布）
- 已应用（3处标记 Perpetua-P1-draft-patch）

## 平台状态（v1）
| 平台 | 簇 | v1行为 | 说明 |
|---|---|---|---|
| douyin | 国内 | 浏览器→存草稿 | P1人工发布（jury Y）；AI声明默认"内容由AI生成" |
| xiaohongshu | 国内 | 备料→人工发 | 无草稿策略，定时=自动公开，P1不碰浏览器 |
| bilibili | 国内 | phase2 | biliup二进制供应链待评估 |
| youtube | 海外 | 沿用官方API | 走现有 youtube_upload private 通道，本分发器跳过 |
| tiktok | 海外 | phase2 | vendor有tk_uploader，待验证 |
| facebook/x | 海外 | stub | 待官方API模块 |

## 密钥纪律
- cookies/<平台>/account.json，一账号一文件，600权限，不跨机
- 用户扫码登录后放入；每日探针检查有效性（待接cron）
- AiToEarn（yikart）因走官方Relay云端授权，禁用为底座（见调研报告）

## 调研报告
/home/hatch/data/douyin/distributor_research_20261010.md
