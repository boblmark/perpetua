# Dash 全量服务清单与保活机制

生成：2026-10-21 11:40 CST（Dash 实测，端口/进程/单元状态均以当日 11:16–11:40 现场为准）
背景：本机（Muse 运行时 VM）会被平台整机替换（10-21 当日已 4 次：09:26 / 09:43 / 11:04 / 11:20 CST），
每次替换清空 /etc、/run、/root —— 所有恢复机制都围绕这个事实设计。

---

## 一、本机常驻服务（11 个监听端口）

| 端口 | 服务 | 用途 |
|---|---|---|
| 18739 | nanoMuse 主控制台（serve） | nano 主控台 API |
| 18736 | perception server | WebSocket 感知服务 |
| 18737 | nano 语音 Web UI | 公网 nano.viralloopapp.com 的源站 |
| 8080 | Perpetua 控制台 / OA 后端 | console_server.py，本机副本（生产副本在 VPS，见三） |
| 8734 | 对外 MCP server | Marvis 协作通道（含 ws_poller 中继到 Cloudflare relay） |
| 8735 | nanoMuse MCP server | nanoMuse 对外 MCP |
| 3129 | 浏览器代理转发器 | Chromium 出网必须经它中转到 egress 代理 |
| 9335 | Chrome CDP | 本机自动化浏览器（geminigen local 故障转移后端）；另有 9344 专用自动化浏览器 |
| 18901 | 天枢控制台后端 | tianshu console |
| 18091 | Semantica explorer | 知识图谱浏览器（kb.viralloopapp.com 源站） |
| 18092 | kb-search sidecar | 混合检索 API（/api/search、/healthz） |

凭据层（无端口，Unix socket）：
- **credential-proxy**：/run/credential-proxy/proxy.sock，SO_PEERCRED 校验调用者；
  vault 在 /etc/credential-proxy/vault.json（600 root），托管 YouTube OAuth；
  客户端 /home/hatch/data/perpetua/credential_proxy_client.py（GET_TOKEN / REVOKE，
  共享凭据 >1 个系统时无 force 拒绝 revoke）。

## 二、SSH 隧道群（到 VPS 192.166.82.123，全部经 egress 代理 3128）

- nano 反向隧道：-R 18736 / 18737 / 18739（tunnel_nano.sh，脚本内 while true 自重连）
- 8738：-R 8734 的公网暴露（MCP server 对外）
- 8737：-R 8735（nanoMuse MCP 公网暴露，tunnel.sh）
- 18738：-L Gemini Live 桥接（VM → VPS 18738）
- 18901：-R 天枢控制台
- 18091/18092：-R Semantica（tunnel_18091.sh）
- 18080：relay 隧道
- 8080：OA/控制台反代链路一环

## 三、VPS 侧服务（192.166.82.123，不受本机换机影响）

- nginx：viralloopapp.com / oa. / www / kb. / nano. 各站点 HTTPS 反代
- dispatcher 8740：主 Muse 派活通道（backend=b）
- Perpetua 控制台生产副本：/opt/mcp-b/data/perpetua/vps_console（公网实际 serving 的是这份）
- mcp-b 队列：/opt/mcp-b/data/mcp_jobs/{pending,done}，主 Muse 消费
- 热备看门狗：hotstandby-watchdog（systemd timer，15 分钟）+ 接管状态层 /opt/mcp-b/data/takeover/

## 四、保活机制（三层）

### 第 1 层：Muse 平台 cron 保活（当前主力，恢复延迟 ≤5 分钟）
调度不在系统 crontab 里，全部在 Muse 平台 cron。核心保活任务（均 5 分钟间隔）：
- 服务类：nanomuse-serve-keepalive(18739)、perception-server-keepalive(18736)、
  nano-webui-18737-keepalive、browser-proxy-fwd-keepalive(3129)、local-chrome-keepalive(9335)、
  agent-browser-keepalive(9344)、oa-watchdog(8080)、tianshu-console-keepalive(18901)、
  mcp-watchdog(8734，一次拉 server+ws_poller+console+隧道四路)、semantica-keepalive(18091/18092+隧道)
- 隧道类：tunnel-nano-keepalive、tunnel-18738-keepalive、tunnel-18901-keepalive、
  tunnel-8734-keepalive(8738)、relay-18080-keepalive、nanomuse-mcp-tunnel-keepalive(8735+8737)
机制统一：探活（pgrep + curl /health 或 ss 监听）→ 死了才 setsid/nohup 拉起；
隧道脚本自身还有 while true 重连（脚本进程活着就自愈）。

### 第 2 层：systemd（备份层，Restart=always + enabled）
- 8 个 unit 源文件：/home/hatch/data/perpetua/systemd_units/dash-*.service
  （perception / nano-webui / nanomuse-serve / console / mcp-8734 / nanomuse-mcp-8735 /
  browser-proxy-fwd / credential-proxy）
- 纪律：只 enable 不 start（防与 cron 层拉起的进程端口冲突）；进程下次死亡或开机时 systemd 秒级接管。
- 换机后 /etc 被清空 → 跑 systemd_units/install.sh 一键重装（含 credential-proxy 的代理 env drop-in 重建）。
- 注意现状：任一时刻实际运行的进程多由第 1 层拉起，unit 显示 inactive 属正常，不代表没保活。

### 第 3 层：脚本内自愈与看门狗
- 隧道脚本 while true 重连；fallback_daemon（muse-main 不健康 → 任务转 nano）；
  dead_state_watchdog / anomaly-watchdog 管状态层面的死状态与分级告警。

### 换机恢复清单（Rule 11，每次整机替换后）
1. 跑 systemd_units/install.sh（重装 8 unit + credential-proxy env drop-in）
2. 恢复 VPS 主机密钥：/root/.ssh/known_hosts 被清 → 从 /home/hatch/.ssh/known_hosts_vps 恢复
3. 重建 SSH mux master（可选优化，直连可替代）
4. 等第 1 层 cron（≤5 分钟）逐项拉起，ss/curl 逐项验 LISTEN/200 才算恢复
5. 数据新鲜度清单补跑：矩阵同步、发布巡检（冻结/换机期间被跳过的 cron 不会自动补）

## 五、2026-10-21 补齐的两个缺口

1. **kb 站（kb.viralloopapp.com）502 → 已恢复 200**
   根因：semantica-keepalive 这条 5 分钟保活 cron 在平台侧丢失（cron 列表里不存在），
   01:29 后 explorer/kb-search/隧道死了无人拉。已处置：手动跑保活脚本三部分全拉起
   （systemd 单元 kb-search / semantica-tunnel 均 active，18091/18092 LISTEN，公网 200），
   并重建 semantica-keepalive cron（5 分钟，owner=goal:semantica-knowledge-graph-system）。

2. **credential-proxy 缺失 → 已重建并端到端验证**
   根因：原 server 程序与 vault 只存在于 /etc、/usr/local/bin，整机替换时随 /etc 清空丢失；
   持久目录里只剩客户端。已处置：
   - server 重写为 /home/hatch/data/perpetua/credential_proxy_server.py（持久目录，不再放 /etc）
   - unit 改名 dash-credential-proxy.service 纳入 systemd_units/，install.sh 自动覆盖
   - vault 启动时自种子：缺失则从权威 OAuth 存储 /home/hatch/data/youtube/.oauth.json 生成（不新增凭据副本）
   - 出网刷新走代理 env drop-in（install.sh 从执行 shell 环境自动重建）
   - 验证：STATUS 正常、GET_TOKEN 成功返回有效 token、服务 active
   说明：当前生产管线无人 import 该客户端（管线直读 .oauth.json），proxy 是凭据保险层；
   本次重建恢复的是保险层本身，未改动任何生产凭据路径。
