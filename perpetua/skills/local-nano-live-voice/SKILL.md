

# nano-live-voice

## Purpose

通过 Gemini Live API 实现 nanoMuse 的实时语音视频对话：用户说话→Gemini 实时语音回复+文字显示，同时语音指令自动进入 nano 任务队列执行。摄像头视频帧实时送 Gemini 实现视觉理解。

## 架构

```
手机浏览器 → HTTPS/WSS → VPS nginx → SSH 隧道 → VM
  ├── 18737: Web UI (index.html)
  ├── 18736: perception_server.py (WebSocket)
  │     ├── live_bridge_client.py → SSH 隧道 → VPS 18738
  │     └── voice_executor.py (指令执行)
  └── VPS 18738: gemini_live_bridge.py → Gemini Live API
```

## 文件清单

`assets/` 下完整代码（2026-10-12 调试通过版）：

| 文件 | 部署位置 | 说明 |
|------|----------|------|
| `gemini_live_bridge.py` | VPS `/root/` | Gemini Live WebSocket 桥接，音频+视频+转写转发 |
| `perception_server.py` | VM 感知目录 | WebSocket 服务器，Live 模式/传统模式切换 |
| `live_bridge_client.py` | VM 感知目录 | TCP 客户端，连接 VPS 桥接器 |
| `voice_executor.py` | VM 感知目录 | 语音指令→任务映射→执行 |
| `index.html` | VM Web 目录 | 前端：录音+摄像头+前后镜头切换+连续对话 |

## 快速部署

详见 `references/deployment.md`。

## 语音指令

16 个只读任务，关键词触发，详见 `references/voice_commands.md`。

## Operating Rules

1. API key 通过 Secure Vault 管理，绝不写进代码或聊天
2. VPS 桥接器 key 文件权限 600
3. 生产重启禁用宽泛 `pkill -f`（Rule 9）
4. 语音指令仅限只读任务，写操作需用户明确批准
5. 重要文件禁写 /tmp（Rule 3）
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
