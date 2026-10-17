#!/usr/bin/env python3
"""
Gemini Live 桥接客户端（运行在 VM 感知服务器上）

通过 SSH 隧道连接到 VPS 上的 gemini_live_bridge.py，
实现 VM <-> VPS <-> Gemini Live API 的音频双向流。

协议（VM <-> Bridge TCP）:
  - 发送: 4-byte BE length + PCM16 bytes (16kHz mono)
  - 接收: 4-byte BE length + PCM16 bytes (24kHz mono)
  - 控制: length=0 + 4-byte JSON len + JSON
"""
import asyncio
import json
import struct
import logging

log = logging.getLogger("live_bridge")

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 18738  # SSH 隧道转发到 VPS bridge


class LiveBridgeClient:
    """到 Gemini Live 桥接器的客户端连接"""

    def __init__(self):
        self.reader = None
        self.writer = None
        self._audio_callback = None
        self._transcript_callback = None
        self._ready_event = asyncio.Event()
        self._running = False

    async def connect(self):
        """连接到桥接器"""
        self.reader, self.writer = await asyncio.open_connection(
            BRIDGE_HOST, BRIDGE_PORT
        )
        self._running = True
        log.info(f"[Live] 已连接桥接器 {BRIDGE_HOST}:{BRIDGE_PORT}")
        # 启动接收循环
        asyncio.create_task(self._recv_loop())
        # 等待 ready（最多 30 秒）
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30)
            log.info("[Live] Gemini Live 会话就绪")
            return True
        except asyncio.TimeoutError:
            log.error("[Live] 等待 ready 超时")
            return False

    async def _recv_loop(self):
        """接收桥接器发来的音频/控制消息"""
        try:
            while self._running:
                hdr = await self.reader.readexactly(4)
                (length,) = struct.unpack(">I", hdr)
                if length == 0:
                    jlen_data = await self.reader.readexactly(4)
                    (jlen,) = struct.unpack(">I", jlen_data)
                    jdata = await self.reader.readexactly(jlen)
                    msg = json.loads(jdata.decode())
                    if msg.get("type") == "ready":
                        self._ready_event.set()
                    elif msg.get("type") == "turn_complete":
                        if self._audio_callback:
                            # 用 None 表示一轮结束
                            pass
                    elif msg.get("type") == "user_transcript":
                        if self._transcript_callback:
                            await self._transcript_callback(msg.get("text", ""), "user")
                    elif msg.get("type") == "gemini_transcript":
                        if self._transcript_callback:
                            await self._transcript_callback(msg.get("text", ""), "gemini")
                    log.debug(f"[Live] 控制消息: {msg.get('type')}")
                else:
                    pcm = await self.reader.readexactly(length)
                    if self._audio_callback:
                        await self._audio_callback(pcm)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            log.info("[Live] 桥接器连接断开")
        except Exception as e:
            log.error(f"[Live] 接收错误: {e}")
        finally:
            self._running = False

    async def send_audio(self, pcm16_bytes):
        """发送 16kHz PCM16 音频到 Gemini Live"""
        if not self.writer or not self._running:
            return False
        try:
            self.writer.write(struct.pack(">I", len(pcm16_bytes)) + pcm16_bytes)
            await self.writer.drain()
            return True
        except Exception as e:
            log.error(f"[Live] 发送音频失败: {e}")
            return False

    async def send_text(self, text):
        """发送文本消息到 Gemini Live"""
        if not self.writer or not self._running:
            return False
        try:
            ctrl = json.dumps({"type": "text", "text": text}).encode()
            self.writer.write(
                struct.pack(">I", 0) + struct.pack(">I", len(ctrl)) + ctrl
            )
            await self.writer.drain()
            return True
        except Exception as e:
            log.error(f"[Live] 发送文本失败: {e}")
            return False

    async def send_video(self, jpeg_base64):
        """发送视频帧（JPEG base64）到 Gemini Live"""
        if not self.writer or not self._running:
            return False
        try:
            ctrl = json.dumps({"type": "video", "data": jpeg_base64}).encode()
            self.writer.write(
                struct.pack(">I", 0) + struct.pack(">I", len(ctrl)) + ctrl
            )
            await self.writer.drain()
            return True
        except Exception as e:
            log.error(f"[Live] 发送视频失败: {e}")
            return False

    def on_audio(self, callback):
        """设置音频接收回调 callback(pcm24k_bytes)"""
        self._audio_callback = callback

    def on_transcript(self, callback):
        """设置转写接收回调 callback(text, role)，role=user/gemini"""
        self._transcript_callback = callback

    async def close(self):
        """关闭连接"""
        self._running = False
        if self.writer:
            try:
                # 发送 stop
                ctrl = json.dumps({"type": "stop"}).encode()
                self.writer.write(
                    struct.pack(">I", 0) + struct.pack(">I", len(ctrl)) + ctrl
                )
                await self.writer.drain()
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
