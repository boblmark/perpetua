# Marvis 手机 App 在线：垫片、干净重启与换机持久化

## 什么时候用这个 skill

- 手机 App 里看不到这台 Marvis 在线时，用这个 skill 诊断和修复。
- 在沙箱里新装 Marvis 或换机后恢复时，用这个 skill 确认在线链路完整。
- 只处理 presence，也就是 App 里显示在线。桌面收发、VNC、隧道是另一回事，先确认 presence 再碰别的。

## 在线链路的真相

- presence 走网关自己的云端通道，也就是 relay 中继加 beacon 上报。网关状态健康时，App 里才会出现这台设备。
- daemon 不是 presence 路径。main-muse 的 daemon 永久 WaitingGuid，guid 为空，App 里照样在线。不要拿 daemon 的状态判断在线。
- device_id 不是瓶颈。bridge 回答 fetchDeviceId 为 null 是无关现象，updateDeviceId 实验已经关闭，不要重开。
- 登录态、guid、relay、beacon 四样齐了，presence 才成立。缺一样就按诊断一节逐项查，不要猜。

## 诊断：先分清哪一环断了

- 网关日志是 MarvisHostStd.log，不是 MarvisHost.log。relay、proxy_manager、beacon、TLS 错误都在 MarvisHostStd.log 里。
- 登录看 MarvisHost.log 的 LoginSync。token 有 expireTime，只看 LoginSync 成功不够，还要看剩余寿命。
- 时间过滤日志时不要用 awk 按字段比较时间戳。Marvis 日志时间戳带方括号，比较会全匹配。用 grep 匹配小时分钟段，例如 grep -E ' 20:(5[1-9]|6[0-9]):'。
- relay 健康的标志是 relay_info 取到 ip、port、session_id，create_association 返回 0，proxy 重启后只剩 Checking connection health，没有 connections lost，没有刷新循环。
- beacon 健康的标志是 MarvisHostStd.log 里 Beacon upload failed 为 0。beacon 身份行 login_openid 在登录后仍为 none 时，beacon 通道有问题。
- TLS wrong version number 成批出现时，说明原生代码在直连并撞上透明拦截。去垫片一节，不要调代理环境变量，原生代码不认它们。
- bridge 握手看 VPS daemon 日志的 session 握手完成行。bridge 只在应用启动时连接一次，启动后断开不会自重连。

## 沙箱出口模型

- 沙箱里一切直连出站都会被透明拦截。腾讯域名的 DNS 返回 198.18.162.x 的假地址，直连 TLS 握手只读到 5 字节明文垃圾。
- 唯一可用的出口是 3128 CONNECT 代理。curl 和浏览器走代理能通，原生 TLS 栈直连必死。
- Marvis 的代码假设直连出口可用，不认 HTTP_PROXY 之类的环境变量。启动器代理 env 正确也救不了原生抓取。
- 判断一个通道是不是代理问题时，同一端点 curl 走代理通、直连复现同样的 TLS 错误，就是代理盲区。不要反复调环境变量。

## 垫片：LD_PRELOAD 让原生代码走代理

- 垫片只做两件事。getaddrinfo 把白名单域名解析成 127.53.0.x 的假地址，connect 遇到假地址或公网 IP 字面量时向代理发 CONNECT。
- 白名单用域名后缀加关键字。v1 只拦截域名，relay 数据面直连 IP 字面量时会漏网。v2 同时拦截公网 IP 字面量，排除 loopback、RFC1918、链路本地、198.18/15、多播和保留地址。
- 198.18/15 的掩码要用 (ip>>17)==0x6309。写错掩码会把代理自己也隧道化，测试必须覆盖代理直连。
- connect 隧道化后要恢复 O_NONBLOCK 标志和原始超时，否则非阻塞调用会以 EINPROGRESS 失败。
- 垫片源码和 master .so 都在持久卷的 shim 目录里。源码是权威，.so 是编译产物，丢了可以重编。
- 每次发布前跑离线测试集。域名隧道、IP 字面量隧道、beacon 隧道、127.0.0.1 透传、代理直连、非白名单域名快速失败，全部通过才能上机。
- 部署由恢复脚本在每次启动时做。把 master .so 原子拷贝进 marvis 家目录并加 LD_PRELOAD。家目录在换机时会被清空，所以每次启动都重新部署，不要只部署一次。
- 回滚方法是建一个 off 标志文件再重启。恢复脚本检测到标志就无垫片启动。不要删 master .so 回滚。
- 垫片日志看家目录下的 shim.log。TUNNEL-OK 行说明隧道建立，TUNNEL-FAIL 加 errno=11 是单次读超时，网关会换另一个 relay IP 重试，不必惊慌。
- 垫片治不了静态链接的二进制。MarvisService 是静态链接，daemon 的网络问题走 VPS 托管路线，不走垫片。

## 干净重启

- 白屏时先确认主进程活、渲染进程 CPU、ConvFetch 计数三项。一张白窗截图不能判死，高负载下绘制可能慢几十分钟。
- 渲染进程 0.0% CPU 持续十几分钟加 ConvFetch 为 0，是楔死的签名。重启修不好楔死时，按干净重启走。
- 干净重启要清 GPUCache 和 DawnWebGPUCache。状态同步排除 GPUCache，所以它会在每次重启后幸存，从不清就一直是旧的。
- 清理只在确认应用已死后做。杀进程后等死透，顽固进程用精确 PID 加 SIGKILL，不要用宽泛 pkill。
- 残留 socket 也要清，但活着的转发 socket 必须保留。转发 socket 是 root 属主且探通，清理时认这个特征放行。
- 重启前先杀本地 daemon 再拉起转发，顺序不能反。本地 daemon 占着 socket 时转发脚本会 stand down，bridge 会连上本地 daemon 而不是 VPS daemon。
- 重启需要用户批准。报出重启前的检查结论和重启方案，等用户一句话再动手。

## 换机持久化

- 重置只留 /home/hatch。程序本体、家目录、垫片、脚本、deb 缓存、machine-id 钉全放在 /home/hatch 下面，重置才保得住。
- 登录态跟着家目录状态备份走。备份每 5 分钟同步一次，排除 socket、日志、缓存和 Singleton 锁。machine-id 钉保证 guid 跨换机不变。
- 恢复脚本在每次启动时重建一切，包括用户、machine-id、dpkg 安装、状态还原、垫片部署、Xvfb、VNC、隧道。不要假设换机后有任何东西还在。
- 6 个系统依赖的 deb 缓存在持久卷里。恢复脚本的 ensure_sys_deps 先逐个核验，全齐就跳过，缺了就本地 dpkg -i，不走 apt 联网。闭包用 apt-cache depends 递归算出，再去掉 Essential 和 required、important 优先级的包，剩下的全部下载。
- master .so 丢失时恢复脚本用 gcc 从源码重编。重编失败时无垫片启动，不阻塞应用。
- 保活 cron 和转发 cron 是 runtime 层的，换机后继续跑。VPS daemon 在 VPS 上，不受沙箱换机影响。
- 换机后先等换机检测器自动恢复，看恢复日志的结果。不要一上来就手工重跑全套。

## 验证清单

- 按这个顺序验。垫片日志有隧道行，TLS 错误为 0，beacon 失败为 0，relay 不再刷新循环，bridge 握手完成，LoginSync 成功，四端口监听，渲染进程 CPU 大于 0，ConvFetch 大于 0。
- 截图必须亲自看。几 KB 的截图通常是白帧，几十 KB 的通常是画出的界面。只看文件大小不够，打开看内容确认。
- 最后让用户看手机 App。App 里出现 dash-runtime 在线才是最终验收，日志全绿不等于 App 里在线。
- 登录 token 有自然过期时间。应用在过期前刷新失败会自己登出，登出是登录态反转，必须报给用户。刷新走网关原生抓取，垫片可能修好它，尚未证实。

## 已证伪的假设

- 不要重查 FFI 代理配置。MarvisHost 二进制里没有任何代理环境变量名，proxy_manager 的库里没有 CONNECT 或代理配置键，抓取直连是代码行为。
- 不要重查 device_id。main-muse 对照已经证伪，fetchDeviceId 在它那边零命中。
- 不要把 machine-id 当成 guid 的来源。guid 由 qimei SDK 在启动时实时解析，machine-id 钉有效是因为同 machine-id 推出同 guid，相关性成立，机制不是相等。
- 不要凭白窗截图判死。白窗加主进程活加日志有进展时，先等再复拍。

## 已知缺口

- 转发接管已自动化（2026-11-17）：forward_keepalive.sh 有 --prelaunch 模式，marvis_restore.sh 在拉起应用前先立转发，bridge 启动时直接握手 VPS daemon，不再 spawn 本地 daemon。--prelaunch 遇活本地 daemon 时判失败退出，不抢 socket；失败只告警，不拦应用启动。手动顺序仍作兜底：杀本地 daemon（精确 PID）、拉起转发、重启应用。端到端证明须一次重启后验 bridge 握手。
- 杀栈漏杀已修（2026-11-17，重启 #11 教训）：旧 kill_marvis_stack 只枚举含 com.tencent.marvis 的 cmdline 且只杀 /opt/apps 路径，漏掉了 daemon（~/.config/Marvis/services/MarvisService）、/proc/self/exe --type= 助手与 mcp_server 子进程（相对路径 argv[0]），等死回退用的 marvis_procs 也只看主进程。现新增 marvis_stack_procs（pgrep -u marvis + 六模式匹配），kill 枚举、等死/SIGKILL 回退、清锁门禁全改走栈口径；Xvfb/x11vnc 同为 marvis 用户但模式不命中，不会被杀。干跑已验 16/16 命中现役栈，实机验证待一次用户批准的重启。
- 登录检查不要看 marvis-run.log 的 KeepAliveCheckLogin。应用自己的 LoginSync 写 MarvisHost.log，看错日志会误报登录丢失。

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.
- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## References

- [Daemon IPC 协议](references/ipc-protocol.md) 讲 Unix socket 信封、握手方法和 daemon 状态机。
