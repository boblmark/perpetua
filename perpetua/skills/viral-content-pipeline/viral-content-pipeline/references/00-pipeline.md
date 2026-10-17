# 00 · 流水线总览与执行顺序

## 四阶段架构

```
┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│ ① 采集      │   │ ② 规范化     │   │ ③ 分析        │   │ ④ 交付       │
│ collectors  │──▶│ rows.json    │──▶│ analysis.json │──▶│ xlsx + 文档  │
└─────────────┘   └──────────────┘   └───────────────┘   └──────────────┘
   按平台分别         统一契约          统一口径           从 JSON 生成
```

**设计核心：用 JSON 契约把"平台差异"和"分析/呈现"解耦。**
新增一个平台时，只需写一个产出 `rows.json` 的采集器，下游全部复用。

---

## 目录结构

```
viral-content-pipeline/
├── SKILL.md                      ← agent 主入口（先读这个）
├── README.md                     ← 人类快速上手
├── references/                   ← 方法论与平台手册
│   ├── 00-pipeline.md            ← 本文件
│   ├── 01-iron-rules.md          ← 铁律 + 字段契约
│   ├── 02-bilibili.md  …  08-dead-ends.md
│   ├── 09-analysis.md            ← 分析方法论
│   └── 10-deliverables.md        ← 交付物生成
├── scripts/
│   ├── setup_env.sh              ← 环境重建
│   ├── collect/                  ← 各平台采集器
│   ├── build/                    ← rows → xlsx
│   ├── analyze/                  ← rows → analysis.json
│   ├── docs/                     ← analysis.json → 文档/样片库/封面墙
│   └── verify/                   ← 数据复核
└── templates/
    └── field-spec.json           ← 字段定义（机器可读）
```

---

## 标准执行顺序

### 阶段 0：环境 + 立项

```bash
bash scripts/setup_env.sh          # 环境重建（每次新容器都要跑）
```
- 确认交付范围、平台清单、是否有登录态（见 `SKILL.md` §1）
- **先给可行性预判**（`SKILL.md` §2），不要承诺做不到的平台

### 阶段 1：采集（按优先级）

| 顺序 | 平台 | 理由 |
|---|---|---|
| 1 | **B站** | 字段最全，可作为数据质量基准 |
| 2 | **TikTok** | API 稳定，能拿到粉丝数 |
| 3 | **抖音** | 只能拿互动数（无播放量） |
| 4 | **快手** | 有播放量，但池子有限 |
| 5 | **X** | 只能按已知 ID 取数，样本少 |
| 6 | 小红书 | 笔记级可得，需签名或指纹浏览器 |
| 7 | Facebook / 视频号 | 预期不可得，备好证据话术 |

每个平台产出 `collector/<platform>_rows.json`，格式见契约。

### 阶段 2：构建与复核

```bash
python3 scripts/build/step7_build_final.py     # 合并所有平台 → xlsx
python3 scripts/verify/verify_*.py             # 定向复核
```

**复核是本流程的强制环节**，不是可选项。至少对 **1 个平台**做独立复核
（用**不同端点**交叉验证，如 B站用未签名的 `search/all/v2` 复核签名详情接口的数据）。

### 阶段 3：分析

```bash
python3 scripts/analyze/step8_analysis.py      # → analysis.json
python3 scripts/analyze/step9d_cover_visual.py # → cover_visual.json（像素级 + 检验）
```

### 阶段 4：交付

```bash
python3 scripts/build/step7_build_final.py     # 重跑：把分析 sheet 并入 xlsx
python3 scripts/docs/step9a_sample_lib.py      # 样片库
python3 scripts/docs/step9b_methodology.py     # 方法论 Word + PDF
python3 scripts/docs/step9c_onepager.py        # 一页纸
python3 scripts/docs/step9e_cover_wall.py      # 封面墙
```

> ⚠️ **顺序有依赖**：`analysis.json` 必须先于最终的 `step7` 生成，
> 否则 xlsx 里不会有分析 sheet。

---

## JSON 契约

### `<platform>_rows.json`

```jsonc
{
  "rows": [
    {
      "platform": "bilibili",
      "account_name": "...",
      "account_followers": 148727,
      "video_url": "https://www.bilibili.com/video/BV...",
      "title": "...",
      "cover_desc": "...",          // 封面文字摘要（OCR）
      "cover_ocr_full": "...",      // 可选：OCR 全文
      "views": 8327176,             // 平台不公开则 "N/A"
      "likes": 325194,
      "comments": 5789,
      "shares": 57489,
      "collects": 131145,
      "danmaku": 9967,              // B站专有
      "published_at": "2026-08-08 08:30",
      "duration_sec": 1867,
      "hashtags": "#AI,#剧情,...",
      "is_viral": 1,                // 1 爆款 / 0 对照
      "topic_category": "AI生成/制作",
      "hook_type": "陈述开场",
      "format_notes": "...",
      "sampling_frame": "...",      // 抽样口径标注
      "collected_at": "2026-10-14 17:49"
    }
  ],
  "accounts": [ { "name": "...", "fans": 148727, "style": "...", "n90": 32 } ]
}
```

**规则**：空值一律字符串 `"N/A"`，不要 `null`、不要空字符串、不要省略键。

### `analysis.json`

```jsonc
{
  "interaction": [ { "平台": "...", "组别": "爆款组", "样本数": 40,
                     "点赞/播放 (%)": 3.40, "口径说明": "..." } ],
  "topic":    [ { "平台": "...", "选题分类": "...", "条数": 58, "占比": "72%" } ],
  "hook":     [ { "平台": "...", "开场钩子": "...", "条数": 29, "其中爆款": 13, "爆款占比": "45%" } ],
  "duration": [ { "平台": "...", "时长档": "1-3分钟", "条数": 48, "爆款条数": 22,
                  "播放量中位数": 539865, "点赞中位数": 19673 } ],
  "title_len":[...], "cover":[...], "series":[...], "top_tags":[...], "notes":[...]
}
```

---

## 行数目标与现实的差距（要提前管理预期）

任务书常要求「每平台 ≥60 行，8 平台约 500 行」。实际能达到的：

| 平台 | 现实上限 | 原因 |
|---|---|---|
| B站 | ✅ 可打满 | 字段全，账号作品列表可取 |
| TikTok | ✅ 可打满 | 话题池够大 |
| 抖音 | ⚠️ 20–40 | 登出态池子有限 |
| 快手 | ⚠️ 20–30 | 登出态池子上限（本次 294 条筛选后剩 24） |
| X | ⚠️ 15–20 | 时间线不可枚举 |
| 小红书 | ⚠️ 笔记级 | 搜索需登录 → 发现受限 |
| Facebook / 视频号 | ❌ 0 | 无公开路径 |

**正确做法**：把差距和原因写进 `summary`，而不是凑数。
若用户要求"必须 60 行"，唯一诚实的选择是**上登录态**或**接受部分交付**。

---

## 复现提示

本技能内的构建脚本（`scripts/build/`、`scripts/docs/`）是**本次运行的实现**，
含平台特定逻辑与列顺序。迁移到新任务时：

- **采集器**：可直接复用（改关键词/账号参数）
- **构建器/文档生成器**：作为**模板**参考，按新的字段与平台调整
- **分析器**：口径与算法可直接复用，只需保证 `rows.json` 契约一致

把「契约」当接口、把「脚本」当参考实现，是这个技能能跨任务复用的关键。
