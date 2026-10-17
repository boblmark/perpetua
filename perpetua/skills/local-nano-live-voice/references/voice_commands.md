# 语音指令清单

## 识别流程

1. Gemini Live 返回用户语音转写（`inputTranscription`）
2. 感知服务器显示转写 + 写入 `voice_commands.jsonl`
3. `voice_executor.py` 每 2 秒扫队列：
   - 先关键词匹配 `COMMAND_MAP`
   - 匹配不上 → LLM（agnes-2.5-flash）理解意图映射到任务
4. 执行任务（subprocess 跑 jobs.yaml 里的 command）
5. 结果生成自然语言回复

## 16 个可用指令（只读）

| 说什么 | 执行任务 | 说明 |
|--------|----------|------|
| 检查OA / OA状态 | shadow-oa-watchdog | OA 控制台是否正常 |
| 检查MCP | shadow-mcp-watchdog | MCP 服务状态 |
| 发布健康 | shadow-publish-health | 发布量三项指标 |
| 矩阵 | shadow-matrix-sync-show | 八平台矩阵同步状态 |
| 队列 | shadow-queue-lease-reaper | 任务队列 |
| 死状态 | dead-state-watchdog | 卡死的任务 |
| 备份 | sqlite-hourly-backup | 备份数据库 |
| 死数据 | shadow-dead-data-sweep | 死数据检查 |
| 决策 | shadow-decision-watchdog | 议会决策检查 |
| 议会 | shadow-council-auto-watch | 议会自动执行 |
| 每日指标 | shadow-daily-metrics | 每日指标 |
| 管线 | shadow-pipeline-orchestrator | 管线编排 |
| 零播放 | zero-view-watch | 零播放视频 |
| 趋势 | trend-spike-watch | 趋势热点 |
| 评论 | comment-reply-batch-am | 评论回复 |
| 竞品 | competitor-breakout-watch | 竞品动态 |

## 非指令 → 聊天模式

关键词和 LLM 都匹配不上时，走 `chat_reply()` 用 agnes-2.5-flash 直接对话（结合最近视觉上下文）。

## 扩展新指令

在 `voice_executor.py` 的 `COMMAND_MAP` 加一行：

```python
"关键词": "jobs.yaml中的任务id",
```

同时在 LLM prompt 的可用任务列表和 `names` 中文映射里加上。
