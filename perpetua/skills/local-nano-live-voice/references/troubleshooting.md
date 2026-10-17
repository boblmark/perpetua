# 故障排查

## 音频队列卡住（N 块待播）

**现象**：日志刷 "Live 音频块已加入队列 (N 待播)"，N 越来越大，没声音。

**原因**：移动端 AudioContext 被浏览器挂起，`source.start()` 静默失败，`onended` 不触发，`liveIsPlaying` 卡死。

**修复**：`playNextLiveChunk()` 开头加：
```js
if (liveAudioCtx.state === 'suspended') {
  liveAudioCtx.resume().catch(() => {});
}
```
并给 `source.start()` 加 try/catch，出错时重置 `liveIsPlaying=false` 继续下一块。

## 听到了立马挂断 / 一句话没说完就断

**原因**：每个 Gemini 音频块独立播放，多块同时播或每块结束都重启录音。

**修复**：音频块进队列 `liveAudioQueue` 顺序播放，一块播完再播下一块，队列空了才重启录音。

## 摄像头 Permission denied

手机浏览器站点权限没给。地址栏锁图标 → 网站设置 → 麦克风/摄像头 → 允许，刷新。

## Gemini 说无法识别视觉

桥接器没转发视频帧。检查：
1. `gemini_live_bridge.py` 有 `video` 类型处理
2. `perception_server.py` 的 `video_frame` handler 在 Live 模式下调用 `client.send_video()`
3. 前端每 5 秒发 `video_frame`

## 指令没执行

`voice_executor.py` 没在跑。检查进程：
```bash
ps aux | grep voice_executor
```

## 隧道断了

VPS 反向隧道（18736/18737）会断。重建：
```bash
ssh -R 0.0.0.0:18737:127.0.0.1:18737 root@<VPS> -N -f
ssh -R 0.0.0.0:18736:127.0.0.1:18736 root@<VPS> -N -f
```

## NO_PROXY 括号 IPv6 坑

`NO_PROXY` 里 `[::1]` 会被 httpx 报 InvalidURL。改成：
```bash
export NO_PROXY="localhost,127.0.0.1,::1"
```

## 生产重启禁 pkill -f

Rule 9：别在含目标字样的命令行里用宽泛 `pkill -f`，会自杀。先 `ps` 列 PID 再 kill。
