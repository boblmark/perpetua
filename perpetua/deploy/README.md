# Perpetua / ViralLoop 一键部署包

## 快速开始（新机器）

```bash
tar -xzf perpetua-deploy-*.tar.gz
cd perpetua-deploy-*
./install.sh
```

install.sh 会自动完成：Python 依赖安装、Playwright 浏览器、文件部署、MCP token 生成、数据文件初始化。

之后按 install.sh 最后输出的 5 个手动步骤补齐凭据即可。

## 包内容

| 目录/文件 | 说明 |
|---|---|
| mcp_server/ | 对外 MCP server（FastMCP，30 工具） |
| jev/ | 爆款打分（jev_score / noleak_baseline / criteria.json） |
| youtube/ | YouTube 上传/分析/评论/发布后优化 |
| ask_studio/ | Ask Studio 队列 |
| collab/ | Marvis 协作协议 + inbox |
| perpetua/ | 商业化模块（多租户/计费/安全/健康/合规/浏览器上传） |
| trend_spike_detector.py | 热点爆发检测 |
| pipeline_latency.py | 趋势→发布延迟追踪 |
| virality_score.py | 规则版爆款打分 fallback |

**已脱敏**：打包时自动删除了 `.token`、`.oauth.json`、`.api_key`、日志、venv、大体积媒体文件。新机器需重新授权。

## Cron 定时任务清单（新机器需手动配置）

| 任务 | 频率 | 命令 |
|---|---|---|
| mcp-watchdog | 每 5 分钟 | 看门狗：保活 mcp-server / ws_poller / ssh tunnel |
| mcp-media-job-processor | 每 10 分钟 | 处理 submit_job 媒体任务（含 ask_dash 代办） |
| trend-spike-watch | 每小时 | `python3 /home/hatch/data/trend_spike_detector.py` |
| ai-trend-radar | 每天 07:49 | 抓 AI 热点写 trends/daily.json |
| ask-studio-daily | 每天 08:49 | Ask Studio 每日对齐 |
| ask-studio-queue-processor | 每 30 分钟 | 处理 Ask Studio 问题队列 |
| post-publish-optimizer | 每 6 小时 | 发布后运营（换标题/回评论） |
| ypp-daily-tracker | 每天 20:49 | YPP 资格进度追踪 |
| youtube-align-weekly | 每周一 | 爆款标准校准 |
| zbj-quota-monitor | 每天 09:49 | 猪八戒配额监控 |

## 架构

```
新机器 (MCP server :8734, systemd 独立调度)
   │  Streamable HTTP + Bearer token
   ▼
VPS 反向隧道 (0.0.0.0:8734)
   │
   ▼
外部智能体 (Marvis 等) 远程接入，无需装在新机器上
```

**Marvis 需要装在新机器上吗？不需要。** Marvis 是腾讯的外部 AI，通过公网 HTTP 调用 MCP 接口，是纯远程接入方。新机器只需暴露 8734 端口（经 VPS 隧道）。

**Muse 需要装在新机器上吗？分两部分看：**

| 任务类型 | 能否独立运行 | 说明 |
|---|---|---|
| MCP server 常驻服务 | ✅ systemd | perpetua-mcp.service |
| 看门狗（5分钟） | ✅ systemd timer | 保活 server+隧道 |
| 热点检测（每小时） | ✅ systemd timer | trend_spike_detector.py |
| 发布后优化（每6小时） | ✅ systemd timer | post_publish_optimizer.py |
| 周对齐检查 | ✅ systemd timer | align_check.py |
| 媒体任务处理（含 ask_dash） | ❌ 需 AI agent | 要调用视频生成+AI 决策 |
| Ask Studio 问答 | ❌ 需 AI agent | 要浏览器+AI 对话 |
| AI 趋势雷达分析 | ❌ 需 AI agent | 要 AI 做选题判断 |
| 猪八戒配额监控 | ❌ 需 AI agent | 要浏览器登录 |

纯脚本任务已做成 systemd timer，随包自动安装；需要 AI 决策的 4 个任务在新机器上需另行部署 agent 运行时（如 Muse），或保持由原机器的 Muse 调度。

## 注意事项

- 一 VM 一 MCP 实例，不在同一 VM 跑多实例
- YouTube OAuth 和 TypeSafe key 必须在新机器重新配置（安全考虑不随包分发）
- Dashboard 是独立的 web artifact，不在部署包内
