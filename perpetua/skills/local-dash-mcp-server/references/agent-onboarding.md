# 给外部 Agent 的接入指令（复制粘贴模板）

把下面整段发给外部 agent（如 Marvis），它按此配置即可接入：

---
## Dash MCP 接入配置

- **Server URL**：`http://192.166.82.123:8734/mcp`
- **Transport**：Streamable HTTP
- **Auth Header**：`Authorization: Bearer <把.token内容填这里>`

### 可用工具（以 `tools/list` 实时返回为准）

**文件**
- `read_file(path)` — 读 `/home/hatch/data` 下文本文件（path 为相对路径；大文件分片读，单次上限约 1MB）
- `read_chunk(path, offset, size)` — 以 hex 读任意文件（含二进制）分片，单次上限 48000 字节；大文件搬运前先调 `file_info` 拿大小与 md5
- `file_info(path)` — 查文件元信息：大小、md5、是否存在
- `write_file(path, content)` — 写文本文件
- `list_dir(path)` — 列目录

**任务（异步，约 5-15 分钟完成）**
- `submit_job(job_type, payload)` — 派任务给 Dash；`job_type`: `generate_video` | `generate_image` | `ask_dash` | `brain_council` | `note` | `collab_poll`；`payload` 为 JSON 字符串；返回 `job_id`
  - `generate_video` / `generate_image`：`payload` 需含 `prompt`（英文描述效果更好）；视频为 10 秒竖屏 Shorts 规格
  - `ask_dash`：把难题发给 Dash，Dash 会直接动手解决（查资料、跑命令、生成文件等），结果写回 `job_status`
  - `brain_council`：开三脑议会做架构/方向评审（见下）
  - `note`：人工查看通道，Muse 不会自动消费，需人工/agent 处置
- `job_status(job_id)` — 查任务状态与结果（`pending` | `done` | `failed`）
- `jobs_list(status)` — 列任务（`pending` | `done` | `failed` | `all`），排查积压
- `requeue_job(job_id)` — 把卡住的任务重新投回 pending（幂等）
- `notes_list()` / `note_handle(note_id)` — 列出并处置 note 留言（处置后归档到 `pending/.handled/`）
- `get_protocol()` — 读协作协议（`collab/PROTOCOL.md`）

**执行与网络**（⚠️ 高权限：工作目录固定 `/home/hatch/data`）
- `exec_shell(command, timeout)` — 在 Dash 的 VM 上执行 shell（默认超时 30 秒，上限 120 秒）
- `web_search(query, max_results)` — 网页搜索（DuckDuckGo）
- `fetch_url(url)` — 抓取网页文本（自动去 HTML 标签）

**爆款流水线（YouTube @karenvsai 英文 AI 频道）**
- `virality_score(title, hook, topic_heat, duration)` — 规则版爆款分（0-100），数据驱动 v2（481 条历史视频回归）；<58 建议回炉
- `jev_score(title, hook, topic_heat, duration)` — jev 模型（TypeSafe System One）AI 爆款判决：0-100 分、置信度、钩子强度概率、发布/优化/放弃建议。**注意校准偏差**：confidence 经常接近 0，且曾给完全符合爆款公式的标题只打 36 分；请结合 `action_probs` 与 `virality_score` 交叉判断，频道真实数据规律优先
- `youtube_stats()` — 频道数据（订阅/视频数/总播放）
- `youtube_recent(n)` — 近期视频播放数据（标题/播放/点赞/评论），用于复盘爆款规律
- `youtube_audit(days)` — 复盘最近 N 天视频真实表现，对比当时预测分（闭环回流）
- `youtube_upload(filepath, title, description, skip_gate=false)` — 上传视频到 YouTube（**公开**）。**内置爆款硬门槛**：jev 爆款分 ≥60（`jev/criteria.json` 的 `gate_threshold`，可进化）才允许上传；低于门槛自动拒绝并说明原因。`skip_gate=true` 可强制上传（谨慎使用）
- `jev_relay_status(fix)` — 检查 jev 调用依赖的旁路通路；`fix=true` 可自愈重建。**建议每 5 分钟调一次 `fix=true` 保活**（VM 的 egress 代理会挂起带鉴权头的直连请求，jev/youtube 调用走 VPS 旁路）

**知识库（KB：查经验 + 提案写回，全 agent 共享）**
- `kb_query(question, task_type="general", device="", limit=5)` — 查知识库。**遇到疑难先调这个**：90% 的坑前人踩过。`task_type` 不传则按问题关键词自动映射（topic_gen/prompt_gen/qc/review/publish/post_publish）。返回条目 id/来源/片段/相关度
- `kb_get_entry(entry_id)` — 按 id 取单条完整内容
- `kb_list_sources()` — 列知识库全部 7 个源 + 新鲜度 + 条目数
- `kb_usage_stats(days=30)` — 各源被查次数 / 各阶段分布
- `kb_propose_finding(problem, solution, evidence="", device="")` — **提案写回**：你解决了一个知识库里没有的新问题，把"问题+解法+证据"提案上来。先自动去重（已有相似条目则直接返回已有解法，不重复提交）；否则进人工审核队列，通过后全网可见（通常 24 小时内）。**只写 staging，不直写知识库**

工作流示例：选题前 `kb_query("停车咪表")` 查历史教训 → 动手干 → 踩了新坑 → `kb_propose_finding` 写回 → 其他 agent 下次直接查到，不用再踩一遍。

### 图片/视频生成（全自动，无需人工）
**1. 提交任务** — 调 `submit_job`：
```json
{
  "job_type": "generate_video",
  "payload": "{\"prompt\": \"视频描述词（英文效果更好）\", \"title\": \"标题\", \"duration\": 10}"
}
```
图片把 `job_type` 换成 `generate_image`。`prompt` 必填，`title` 可选。返回 `job_id`。

**2. 轮询状态** — 每隔几分钟调 `job_status(job_id)`，直到 `status` 为 `done`（约 5-15 分钟，含排队+生成）。

**3. 取货** — 结果中的 `file` 字段即 `/home/hatch/data/` 下的文件名，调 `read_file` 读取即得成品。

**注意**：
- prompt 用英文描述，生成质量更高
- 视频约 10 秒竖屏，适合 Shorts/Reels
- 不要重复提交相同 prompt，先查 `job_status` 确认上一个完成了
- 后台每 10 分钟自动处理队列（`mcp-media-job-processor`），无需催促
- 发布前先用 `virality_score` / `jev_score` 测分；`youtube_upload` 有 60 分硬门槛，低分会被拒

### 代办求助（ask_dash）
搞不定的难题直接甩给 Dash：
```json
{"job_type": "ask_dash", "payload": "{\"question\": \"具体问题描述，越具体越好\"}"}
```
Dash 的定时任务每 10 分钟处理，会直接动手解决（查资料、跑命令、生成文件等），结果写回 `job_status(job_id)`。完成后用 `read_file` 取走产物。

### 三脑议会评审（brain_council）
**什么时候用**：`ask_dash` = "有个具体问题，帮我动手解决"；`brain_council` = "有个架构/方向/策略要拍板，帮我开三脑会议评审"。前者要的是**执行结果**，后者要的是**带评审链的工程判决**（判决 + 可执行规格 + 反转条件）。

默认**双脑**：LMArena（陪审团：多模型横评，抹平单模型方差）+ AI Studio（总工程师：把结论落成 MUST/NEVER 可执行规格）。Ask Studio（YouTube 传感器）默认不参与——它只服务 YouTube/Perpetua 相关问题，别的项目用不上；确需时在 `brains` 里显式加 `"ask_studio"`（问题须与 YouTube/视频相关，否则会被拒绝）。

```json
{
  "job_type": "brain_council",
  "payload": "{\"question\": \"10人团队做内部工具，选单体还是微服务？\", \"context\": \"无专职运维，单台云服务器，迭代速度优先\", \"brains\": [\"lmarena\", \"aistudio\"], \"depth\": \"standard\"}"
}
```
- `question` 必填；`brains` 可选（缺省 `["lmarena","aistudio"]`，可用值 `lmarena`/`aistudio`/`ask_studio`）；`context` 可选（背景、约束、已试过的方案——给得越全判决越准）；`depth` 可选 `standard`|`deep`（deep 时陪审团用双模型 side-by-side，耗时更长）。
- 处理约 10-40 分钟（浏览器跑三脑）；轮询 `job_status(job_id)` 取结果。`result` 含 `verdict`（判决）、`specs`（可执行规格）、`reversal_conditions`（反转条件）、`honest_limits`（诚实边界）、`raw_outputs`（各脑原文）。
- 建议传 `idempotency_key`，防重复开会。

### 自动取货（定时任务，每 30 分钟）
1. `read_file` 读 `/home/hatch/data/collab/inbox.json`
2. `pending_pickup` 为空则结束；有 `status=ready` 的条目则：
   - `read_file` 取走 `/home/hatch/data/` 下对应文件
   - 按既定流程处理
   - `write_file` 更新 `inbox.json`，把该条目 `status` 改为 `done`
---

## inbox.json schema
```json
{
  "pending_pickup": [
    {"file": "xxx.mp4", "title": "标题", "created": "2026-10-05T06:52:00Z", "status": "ready"}
  ]
}
```
`status`: `ready`（待取）| `done`（已取）。Dash 上架新产物时追加条目。
