# Ask Studio 7×24 协作机制诊断（2026-10-08）

## 降权/停止推荐的核心监测指标（Studio 实际提供）

1. **Realtime 48h 曲线**（"Updating live"）：断崖式停滞 = 推荐停止
2. **"First 48 minutes" vs 典型范围**：低于典型范围 = 偏离正常推荐
3. **"How viewers find your Shorts"**：Shorts feed 占比骤降 = 降权信号
4. **"How viewers engaged"**：Stayed to watch / Swiped away 比率突变
5. **Reach 页面 Impressions**：展示次数断崖 = 系统停止分发

## 正常→停止推荐的信号顺序

1. Shorts feed 来源占比先跌至个位数
2. Realtime 48h 曲线由斜坡转 flatline（数小时零增长）
3. 平均观看时长百分比与 Swiped away 率同时恶化

**拐点基准线**：Studio 自身的"典型范围"（Typical range）
- 本频道 Shorts 28 天典型：260–9.4K 播放
- 首 48 分钟典型：0–1

## 监测频率

- Analytics API：每次查询约 1 quota unit，日配额 10,000
- 每 5 分钟检查 ≈ 288 次/天，仅 3% 配额，无压力
- **真正限制是数据刷新延迟**：Studio 实时数据约小时级刷新
- 结论：30 分钟轮询已足够，5 分钟不会获得更多信息

## 本频道特殊性（重要）

- 流量结构：Search 74.7%（348次/28天），Shorts feed 仅 10.7%（50次）
- **对该频道而言，Search 占比变化比 Shorts feed 更敏感**
- 看门狗的 DEMOTION_SIGNAL 检测应优先看 Search 流量变化

## 落地到 published_video_watchdog.py 的待办

- [ ] 接入 Analytics API 获取流量来源（Search vs Shorts feed 占比）
- [ ] 建立"典型范围"基线（28 天滚动）
- [ ] VIEW_CLIFF 检测加入 Realtime flatline 判断
