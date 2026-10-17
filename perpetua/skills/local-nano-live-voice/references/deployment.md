# 部署指南

## 前置条件

- VPS（有公网 IP，已配 nginx + Let's Encrypt）
- VM（本地开发机）
- Google AI Studio Gemini API key（已接受 Additional Terms）
- Secure Vault 已保存 `custom.google-gemini` connector

## 1. VPS 部署桥接器

```bash
# 复制文件
scp assets/gemini_live_bridge.py root@<VPS>:/root/

# VPS 上安装依赖
ssh root@<VPS> "pip3 install websockets"

# 写入 API key（权限 600）
ssh root@<VPS> "mkdir -p /etc/gemini-live && chmod 700 /etc/gemini-live"
# 通过安全方式写入 key（不要在聊天里贴）
ssh root@<VPS> "cat > /etc/gemini-live/key && chmod 600 /etc/gemini-live/key"

# 启动
ssh root@<VPS> "cd /root && nohup python3 gemini_live_bridge.py > /var/log/gemini-live-bridge.log 2>&1 &"
```

## 2. VM 部署感知服务器

```bash
# 创建独立 venv（避免污染全局）
python3 -m venv /path/to/perception/venv
/path/to/perception/venv/bin/pip install websockets faster-whisper

# 复制文件
cp assets/perception_server.py assets/live_bridge_client.py assets/voice_executor.py /path/to/perception/server/
cp assets/index.html /path/to/perception/web/

# 启动感知服务器（Live 模式）
NANO_LIVE_MODE=1 /path/to/perception/venv/bin/python /path/to/perception/server/perception_server.py &

# 启动 Web UI
cd /path/to/perception/web && python3 -m http.server 18737 --bind 127.0.0.1 &

# 启动语音执行器
/path/to/perception/venv/bin/python /path/to/perception/server/voice_executor.py &
```

## 3. SSH 隧道

```bash
# VM → VPS：桥接器通道（本地 18738 → VPS 18738）
ssh -L 127.0.0.1:18738:127.0.0.1:18738 root@<VPS> -N -f

# VPS → VM：Web 反向隧道
ssh -R 0.0.0.0:18737:127.0.0.1:18737 root@<VPS> -N -f
ssh -R 0.0.0.0:18736:127.0.0.1:18736 root@<VPS> -N -f
```

## 4. nginx 配置

```nginx
server {
    server_name nano.viralloopapp.com;
    location / {
        proxy_pass http://127.0.0.1:18737;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location /ws {
        proxy_pass http://127.0.0.1:18736;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    listen 443 ssl;
    # ... certbot 证书
}
```

## 端口清单

| 端口 | 位置 | 用途 |
|------|------|------|
| 18736 | VM | 感知 WebSocket |
| 18737 | VM | Web UI HTTP |
| 18738 | VPS 127.0.0.1 | Gemini Live 桥接 |
| 18739 | VM | nanoMuse Web 控制台（可选） |

## 保活

隧道断线是已知问题。建议用 cron 每 5 分钟检查并重建：

```bash
# 检查示例
ss -tln | grep 18738 || ssh -L ... # 重建
```
