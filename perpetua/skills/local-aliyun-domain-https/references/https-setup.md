# Phase 4: VPS 上 nginx + Let's Encrypt

## 1. 装软件
```bash
apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  nginx certbot python3-certbot-nginx
```

## 2. 写 nginx 站点配置
模板见 `references/nginx-site.conf.example`。把 `example.com` / `192.0.2.1` 换成实际值。
关键点：
- 80 端口先只做反代（certbot 稍后会加上 443 和跳转）。
- 每个 server 块里必须给 `/.well-known/acme-challenge/` 开例外（否则挑战请求会被 proxy_pass 吃掉）：
  ```nginx
  location ^~ /.well-known/acme-challenge/ {
      default_type "text/plain";
      root /var/www/html;
  }
  ```
- `nginx -t` 通过后 reload；删掉 default 站点避免冲突。

## 3. 等 DNS 生效后申请证书
不要轮询等，丢给后台脚本（模板 `bin/setup_https.sh`，改里面的域名/IP/邮箱）：
```bash
setsid nohup /root/setup_https.sh >/dev/null 2>&1 < /dev/null &
```
脚本每 ~100 秒查一次公网 DNS，三域名都解析到服务器 IP 后自动跑：
```bash
certbot --nginx -d example.com -d www.example.com -d oa.example.com \
  --non-interactive --agree-tos -m user@example.com --redirect
```

## 4. 验证
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://oa.example.com/oa
curl -s -o /dev/null -w "%{http_code}\n" https://example.com/
```
证书自动续期：certbot 装好后自带 systemd timer，无需手动处理。

## SSH 连通性
先确认能 SSH 到 VPS 再操作。运行环境不同走法不同（有的需经 egress 代理，
如 `ssh -o ProxyCommand="nc -X connect -x 198.19.0.1:3128 %h %p" root@<ip>`），
连不上先解决网络再继续。
