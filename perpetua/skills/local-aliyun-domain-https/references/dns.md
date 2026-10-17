# Phase 3: DNS 解析（browser 任务）

## 添加 A 记录
- 打开 `https://dns.console.aliyun.com/`（与下单同一阿里云账号，已登录）。
- 进入目标域名的解析设置，逐条添加：
  - 主机记录：`@` / `oa` / `www`（按用户要的 hosts 列表）
  - 记录类型：A，线路：默认，记录值：服务器 IP，TTL：10 分钟
- 加完在记录列表页确认条数（如"共 3 条"）。

## 验证
```bash
for h in @ oa www; do
  d="viralloopapp.com"; [ "$h" != "@" ] && d="$h.viralloopapp.com"
  echo -n "$d: "; dig +short $d A @8.8.8.8
done
```

## 已知延迟
- 新注册域名可能出现 NS 同步延迟：控制台显示已添加，但 `dns9.hichina.com` / `dns10.hichina.com` 查不到，公网 DNS 也查不到。
- 属正常，等即可（通常 10 分钟–数小时）。Phase 4 的 certbot 必须等公网 DNS 生效后再跑。
