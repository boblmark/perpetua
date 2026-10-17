#!/bin/bash
# 用法：先改下面的 DOMAIN / IP / EMAIL / HOSTS，再传到 VPS /root/ 跑：
#   setsid nohup /root/setup_https.sh >/dev/null 2>&1 < /dev/null &
# 等公网 DNS 生效后自动用 certbot --nginx 申请证书并验证。
DOMAIN="example.com"
SERVER_IP="192.0.2.1"
EMAIL="user@example.com"
HOSTS=("example.com" "www.example.com" "oa.example.com")  # 与 nginx server_name 对应
BACKEND_CHECK_URLS=("https://example.com/" "https://oa.example.com/oa")

LOG=/root/setup_https.log
exec >>$LOG 2>&1
echo "[$(date)] 开始等待 DNS 生效: ${HOSTS[*]} -> $SERVER_IP"
for i in $(seq 1 72); do  # 最多约 2 小时
  ok=1
  for h in "${HOSTS[@]}"; do
    ip=$(dig +short "$h" A @8.8.8.8 2>/dev/null | head -1)
    echo "[$(date)] try $i: $h=$ip"
    [ "$ip" = "$SERVER_IP" ] || ok=0
  done
  if [ "$ok" = 1 ]; then
    echo "[$(date)] DNS 已生效，申请证书..."
    args=()
    for h in "${HOSTS[@]}"; do args+=(-d "$h"); done
    certbot --nginx "${args[@]}" \
      --non-interactive --agree-tos -m "$EMAIL" --redirect
    echo "[$(date)] certbot exit=$?"
    sleep 3
    echo "--- verify ---"
    for u in "${BACKEND_CHECK_URLS[@]}"; do
      curl -s -o /dev/null -w "$u -> %{http_code}\n" "$u" --max-time 15
    done
    echo "[$(date)] DONE"
    exit 0
  fi
  sleep 100
done
echo "[$(date)] 超时：DNS 2小时未生效，退出"
exit 1
