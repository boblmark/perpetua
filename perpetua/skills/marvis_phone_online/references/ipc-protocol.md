# Daemon IPC 协议

Marvis 主进程里的 daemon-bridge 通过 Unix socket 与 MarvisService（daemon）说话。这条通道管手机远程控制，不管道 presence。presence 走网关 relay，见 SKILL.md。

## Socket 与信封

- Socket 路径是家目录下 .config/Marvis/services/daemon.sock。
- 消息是 NDJSON，每行一个 JSON 信封。
- 信封字段：type、protocalVersion、callbackId、namespace、method、params。
- type 必须是 send。type 为 request 的消息会被静默丢弃。
- protocalVersion 是字符串 1.0，不是数字。

## 握手

- 客户端先发 base.init，params 里带 guid。
- daemon 回 ack，然后拉 base.fetchDeviceId 和 base.fetchGuid。
- 握手完成后 daemon 从 WaitingGuid 进入 Connecting，再进入 Connected。
- bridge 只在应用启动时连接一次。启动后断开不会自重连，必须重启应用。

## 方法

- base.init：握手，带 guid。
- updateGuid：推 guid，字段名是 guid。
- updateDeviceId：推 device id，字段名是 device_id。
- fetchGuid、fetchDeviceId：daemon 向客户端拉取值。
- version、upgradeExit：版本与退出。
- connection.sendText、connection.forcePing：连接层消息。

## device_id 的缓存行为

- device_id 缓存在 daemon 内存里。全部 IPC 客户端断开后，缓存清空。
- 想让 device_id 一直有效，必须保持一个持久 IPC 会话。
- bridge 回答 fetchDeviceId 为 null 是正常现象，不是故障。不要拿它当在线判断。

## daemon 状态

- Idle、Start、WaitingGuid、Connecting、Connected、ReconnectWait。
- WaitingGuid 的意思是 guid 还没送达。主进程的 bridge 在启动时判 socket 未就绪后会永久断开，之后 guid 永远送不到。
- guid 持久化在 data dir 的 device-info.cache 里，是 TOML 单行 guid 等于某个值。daemon 启动时从磁盘缓存读 guid，直接进 Connecting。

## 环境变量覆盖

- MARVIS_DEVICE_GUID：直接指定 guid。
- MARVIS_DAEMON_DATA_DIR：data dir。
- MARVIS_DAEMON_SOCKET_PATH：socket 路径。
- MARVIS_DAEMON_CONFIG：配置文件。
- MARVIS_LOG_DIR、MARVIS_DAEMON_LOG：日志位置。
- MARVIS_CLIENT_VERSION、MARVIS_CLIENT_PLATFORM：客户端标识。

## VPS 托管

- daemon 是静态链接的二进制，LD_PRELOAD 治不了它。沙箱里它的 wss 订阅死于两层：UDP DNS 被禁，hickory 解析器没有 TCP 回退；直连 TLS 撞透明拦截。
- 解法是把 daemon 放在 VPS 上跑，沙箱侧用 ssh 原生 Unix socket 转发把本地 daemon.sock 连到 VPS 的 daemon.sock。
- VPS daemon 的 beacon 从 data dir 的 marvis-build.json 读 channelId。
- wss 订阅每 60 到 70 秒被对端关闭一次是空闲关闭常态，5 秒内自动重连，不是 daemon 缺陷。
- 转发脚本在本地 MarvisService 活着时 stand down。本地 daemon 占着 socket 时，转发不会接管。手动接管顺序是先精确 PID 杀本地 daemon，再跑转发脚本，再重启应用。
- 恢复脚本清理残留 socket 时要保留活着的转发 socket。转发 socket 的特征是 root 属主且探通。
