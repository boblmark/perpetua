# 爆款雷达（只读）— Perpetua 跨平台数据仓库

决策：[D20261017-002]（2026-10-17 用户拍板）+ 竞品池规格 v1 [D20261017-003]（四脑议会 2026-10-17，技术决策直行权）。
**只读雷达**：采集各平台公开数据、算日增速 / outlier 分数 / 标题·缩略图变更，供人工与评审管线参考。
**永不触发选题快车道、自动发布或任何 Tier 3 动作**（D20261016-007 冻结期至 2026-12-10）。

## 竞品池规格 v1（D20261017-003）

- **池子 ≤25**，三档为筛选起点不是硬配额，**宁可空位不降标准**：
  - tier1 直接对标：8–10 个，500–5K 粉，AI 喜剧
  - tier2 增长标杆：5–8 个，10K–100K 粉
  - tier3 趋势风向标：3–5 个，100K+ 粉
- **挑战者**：0–2 个可选（非常备），30 天轮换；留用需 ≥2 个增速信号 或 1 个确认 outlier。
- **人工一句话门**：受众匹配 + 可拍性，入库前必须过（种子文件由人工填写）。
- **三档分 lane 看**：禁全局榜（待控制台雷达页实现）。

### outlier 定义（红队 KILL 规则 4 修订后）

`outlier = 视频第 N 天累计播放 ÷ 基线视频同为第 N 天时的累计播放中位数`
- 同格式（short/long）才比，绝不混算
- N = 视频当前年龄（天），N≥3；**<48h 新视频不进基线、不算 outlier**
- 基线中位数为 0 → 记 **UNDEFINED**（不是 0 也不是无穷大）
- 基线 <10 条 → **PROVISIONAL** 并显示样本数；<6 条 → INSUFFICIENT_BASELINE
- 基线 = 同频道、同格式、90 天内上传（目标 15–30 条；低频博主按实际发片量标注）
- 365 天 cutoff 只约束增速/outlier 计算，老视频保留作历史上下文
- 无 published_at/格式数据的视频走降级口径（LEGACY_NO_FORMAT，恒标）

### 清退（红队 KILL 规则 9 修订后）

- 每月检查只做**候选标记**（`radar_prune.py` → prune_candidates 表 + reports/prune-YYYY-MM.json），
  移除必须人工确认：`python3 radar_prune.py --apply-confirm <channel_id>`
- **唯一自动移除**：频道被删/停用/转私密（采集时检测到自动归档）
- 被清退频道历史数据归档但保持可查；**恢复 = 重新加回种子文件**（archived 自动清零）

### 变更检测（红队 WEAKEN 修订后）

- 缩略图：以 dHash 感知哈希汉明距离 > 8 为准（64 位）；**URL 变化/CDN 变体不算**
- 标题：文本 diff（去首尾空白）
- 配额：YouTube 配额硬停 9500（雷达自有项目用量口径），估算超限直接中止本轮

## 文件

| 文件 | 说明 |
|---|---|
| `radar_lib.py` | 共享库：SQLite schema、Asia/Shanghai 时间、快照写入、缩略图 hash |
| `radar.db` | 仓库（SQLite）：`tracked_videos` / `video_snapshots` / `metrics` |
| `youtube_snapshot.py` | Phase 1 轮询器：自有频道 uploads 列表 + 竞品种子（`competitors_youtube.json`） |
| `radar_metrics.py` | 指标计算：日增速（快照差分）、outlier（同龄第 N 天÷基线同龄中位数，PROVISIONAL/UNDEFINED 标记）、标题文本 diff / 缩略图 dHash 变更 → `reports/metrics-YYYY-MM-DD.json` |
| `radar_prune.py` | 每月清退检查：只标记候选（dormant_60d/flatline_90d/challenger_expired），人工 `--apply-confirm` 才归档；永不自动删 |
| `bilibili_snapshot.py` | Phase 2 轮询器：公开 API（wbi 签名）+ 页面兜底；被风控时降级写日志不造假 |
| `competitors_youtube.json` | YouTube 竞品种子（channels/videos），默认空 |
| `competitors_bilibili.json` | B站竞品种子（mids/bvids），默认空 |
| `platform_health.json` | 各平台采集健康状态（ok/degraded） |
| `phase3/` | 设计文档 + 抖音/视频号/快手/小红书 stub（等用户 OAuth 授权） |

## 加竞品（只读跟踪）

```bash
# YouTube：编辑 competitors_youtube.json
#   channels 可填字符串或对象：{"channel_id": "UC...", "tier": "tier1", "added_at": "2026-10-17"}
#   tier 可选 tier1/tier2/tier3/challenger；挑战者 30 天轮换、留用需 ≥2 增速信号或 1 确认 outlier
# B站：编辑 competitors_bilibili.json
#   mids 可填 UID 数字或对象：{"channel_id": 12345, "tier": "tier1", "added_at": "2026-10-17"}
```
下一轮 daily cron 自动开始跟踪其每日快照。**只产生数据，不产生任何选题/发布动作。**

## Cron

- `radar-youtube-snapshot`：每天 06:10（Asia/Shanghai）→ youtube_snapshot.py + radar_metrics.py
- `radar-bilibili-snapshot`：每天 06:25（Asia/Shanghai）→ bilibili_snapshot.py + radar_metrics.py
- 日志：`~/workspace/goals/karenvsai/hidden_files/radar/*.log`

## 已知限制

- YouTube Data API 默认配额 10000 单位/天；本轮询约 20 单位/天，硬停线 9500。永不用 search.list 做批量发现。
- outlier 同龄计算依赖 published_at + duration（contentDetails）：规格 v1 落地后新快照才带，老视频走 LEGACY_NO_FORMAT 降级口径。
- 红队来源偏差标注：KILL/WEAKEN/WATCH 评审时 chat.deepseek.com 不可用，降级到 duck.ai（GPT-6 Luna）执行，18 条规格全覆盖（见议会 synthesis）。
- B站 2026-10-17 实测：本机出口 IP 被风控（-799/412/404），脚本降级运行；
  解封路径：换住宅出口 / VPS 出口实测 / 用户创作中心 cookie（走保险库）。
- 留存率、流量来源：公开 API 对竞品永远拿不到（需博主本人 OAuth），本雷达不提供。
- 收益估算：不做（ViewStats 式 CPM 建模误差 200–400%，无价值）。
