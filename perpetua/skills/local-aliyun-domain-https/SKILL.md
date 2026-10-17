

# Aliyun 域名一键申请 + DNS + HTTPS

## Purpose
输入一个域名和一台服务器 IP，输出一个 HTTPS 可访问的站点。覆盖阿里云万网购买全流程、DNS 解析、VPS 上 nginx 反代 + Let's Encrypt 证书。

## Inputs（开始前向用户要齐）
- `domain`：要买的域名（如 viralloopapp.com）
- `server_ip`：解析指向的服务器 IP
- `hosts`：需要的解析记录，默认 `["@", "oa", "www"]`（可增减）
- 实名信息（个人）：姓名、身份证号、手机号、邮箱、省/市/详细地址、身份证正面照片
- 付款：用户自己付（见 Operating Rules 第 4 条）

## Workflow
分 4 个阶段，按顺序执行。详细步骤见 `references/`。

### Phase 1 — 查域名、下单（browser 任务）
见 `references/order-flow.md`。要点：万网搜域名→加入清单→结算→创建实名信息模板→提交订单→停在付款页。

### Phase 2 — 用户付款
把付款方式交给用户（阿里云 App → 费用 → 待支付订单，或用户自己浏览器打开收银台）。**不要**在自动化浏览器里点付款。付款完成后继续。

### Phase 3 — DNS 解析（browser 任务）
见 `references/dns.md`。要点：在 `dns.console.aliyun.com` 给 domain 加 A 记录，每条 host → server_ip，TTL 10 分钟。加完用 `dig +short <host>.<domain> A @8.8.8.8` 验证（新域名可能有 NS 同步延迟，属正常）。

### Phase 4 — VPS 上 HTTPS（shell）
见 `references/https-setup.md`，脚本模板在 `bin/setup_https.sh`。要点：装 nginx + certbot → 写反代配置（参考 `references/nginx-site.conf.example`）→ 等 DNS 生效 → `certbot --nginx` 申请证书 → 验证 `curl -sI https://<domain>`。

## Output Contract
完成时向用户报告：
- 域名注册状态、到期日
- 已添加的 DNS 记录列表
- 每个 https://host.domain 的访问验证结果（HTTP 状态码）

## Operating Rules
1. 付款、实名认证、扫码登录必须用户亲自做；agent 只走到"待用户操作"页面就停下。
2. 实名信息（姓名/身份证号/手机/邮箱/地址/证件照）只能用用户亲口给的值，绝不编造。
3. 浏览器任务之间共享 Chromium profile；买域名和配 DNS 可以是两个任务，但别和同一站点的其他写入任务并行。
4. 支付宝付款码在自动化浏览器里会被反爬拦截，且在自动化会话生成的付款链接换设备打开会触发"钓鱼风险"警告——一律让用户在自己的阿里云 App/浏览器里付。
5. 新注册域名 DNS 可能有数小时 NS 同步延迟：Phase 4 的 certbot 必须等 `dig @8.8.8.8` 返回正确 IP 后再跑，用 `bin/setup_https.sh` 的等待循环，不要硬等。
6. SSH 连 VPS 的方式因运行环境而异（如本机需经 egress 代理 `ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p"`），先确认连通再操作。
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
