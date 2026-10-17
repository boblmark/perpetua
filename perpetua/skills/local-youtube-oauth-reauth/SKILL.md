# YouTube OAuth 重授权

无头 VM 上为 `Mark Bobl | Karen vs AI` 频道重新走 YouTube OAuth 授权。
触发词：YouTube 授权过期、oauth 失效、invalid_grant、重新授权、401。

## 适用场景

- `.oauth.json` 的 refresh_token 被撤销（`invalid_grant`）或丢失
- 所有 API（Data / Analytics / 上传）返回 401
- 用户确认需要重走授权

## 固定参数（勿改）

- OAuth client：`138339902705-...apps.googleusercontent.com`（Desktop 类型，存于现有 `.oauth.json` 的 `client_id`/`client_secret`）
- Scopes（三个缺一不可）：
  - `https://www.googleapis.com/auth/youtube.upload`
  - `https://www.googleapis.com/auth/youtube.force-ssl`
  - `https://www.googleapis.com/auth/yt-analytics.readonly`
- 凭据文件：`/home/hatch/data/youtube/.oauth.json`（600 权限）
- **新授权只存本机，不再与任何机器/MCP 共享**（2026-10-08 血泪教训：共用一份授权被 Marvis revoke 连根拔起）

## 流程（半自动：机器做全部，人工只给 code）

1. 跑 `bin/gen_auth_url.py` → 生成授权 URL（含 `access_type=offline` + `prompt=consent`，确保拿 refresh_token）
2. 把 URL 发给用户（手机浏览器打开）
3. 用户用 `bat08738@gmail.com` 登录并点"允许"
4. 浏览器会跳转到 `http://localhost:8080/?code=...` 打不开——**让用户把地址栏整串 URL 复制发回聊天**（code 藏在里面）
5. 跑 `bin/exchange_code.py "<用户贴回的URL或code>"` → 自动换 token、写 `.oauth.json`（600）、验证三个 API
6. 验证通过后逐项恢复：上传链路、评论回复、post-publish、审计、数据拉取定时任务

## 验证清单（exchange 后自动跑）

- [ ] `channels.list(mine=true)` → `Mark Bobl | Karen vs AI`
- [ ] Analytics API：`views,averageViewDuration,averageViewPercentage,shares` 可拉取
- [ ] `commentThreads.list` 可读
- [ ] MCP `youtube_upload` 工具链可用（**不**用公开视频测试）

## 禁忌

- 不要把 token/secret 贴进聊天
- 不要把 `.oauth.json` 发给 Marvis 或其他 agent（它走 MCP `youtube_upload` 即可）
- 不要跳过 `prompt=consent`，否则可能拿不到 refresh_token
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
