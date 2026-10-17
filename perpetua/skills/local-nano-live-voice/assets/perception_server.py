#!/usr/bin/env python3
"""
实时感知服务器 - nanoMuse 感知层
- WebSocket 接收浏览器端的音频流（麦克风）和视频帧（摄像头）
- 调用用户自定义模型：agnes-2.5-flash 做语音转文字，gemini-auto 做复杂理解
- 转写后的指令直接提交给 nanoMuse 调度器执行
"""
import asyncio
import json
import base64
import logging
import tempfile
import os
from datetime import datetime
from pathlib import Path
import websockets

# Gemini Live 模式（2026-10-12）：通过 VPS 桥接器接入 Gemini Live API
# 替代 Whisper+agnes 链路，实现真正的实时语音对话
USE_LIVE_MODE = os.environ.get("NANO_LIVE_MODE", "1") == "1"
_live_client = None

async def get_live_client():
    """获取或创建 Live 桥接客户端（单例）"""
    global _live_client
    if _live_client is None:
        from live_bridge_client import LiveBridgeClient
        _live_client = LiveBridgeClient()
        ok = await _live_client.connect()
        if not ok:
            log.error("[Live] 桥接器连接失败，回退到 Whisper 模式")
            _live_client = None
    return _live_client

async def webm_to_pcm16(webm_bytes):
    """WebM/Opus → 16kHz mono PCM16（供 Gemini Live）"""
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(webm_bytes)
        tmp_in = f.name
    tmp_out = tmp_in + ".pcm"
    try:
        loop = asyncio.get_event_loop()
        def _convert():
            import subprocess
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-i", tmp_in,
                "-ac", "1", "-ar", "16000", "-f", "s16le",
                tmp_out
            ], check=True, timeout=10)
            with open(tmp_out, "rb") as pf:
                return pf.read()
        pcm = await loop.run_in_executor(None, _convert)
        return pcm
    finally:
        for p in (tmp_in, tmp_out):
            try: os.unlink(p)
            except: pass

# Whisper 本地转写（不依赖谷歌，国内可用）
_whisper_model = None
def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import os
        # 修 NO_PROXY：去掉括号 IPv6，避免 httpx 解析失败（2026-10-12 踩坑）
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
        # 模型缓存在 /root/.cache（下载时 HOME=/root），显式指定
        os.environ["HF_HUB_CACHE"] = "/root/.cache/huggingface/hub"
        from faster_whisper import WhisperModel
        log.info("[STT] 加载 Whisper 模型 (tiny)...")
        _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        log.info("[STT] Whisper 模型就绪")
    return _whisper_model

BASE = Path("/home/hatch/data/nanomuse-migration")
LOG_DIR = BASE / "perception" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "perception.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("perception")

# 感知状态
perception_state = {
    "audio_active": False,
    "video_active": False,
    "last_transcript": "",
    "last_vision": "",
    "command_history": [],
}


async def transcribe_audio(audio_base64, model_slot="fast"):
    """
    音频转文字（本地 Whisper，不依赖谷歌）
    """
    log.info(f"[STT] 收到音频 {len(audio_base64)} 字符")
    try:
        audio_bytes = base64.b64decode(audio_base64)
        # 存临时文件
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            model = get_whisper()
            # 在线程池跑，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            segments, info = await loop.run_in_executor(
                None,
                lambda: model.transcribe(tmp_path, language="zh", beam_size=5)
            )
            text = "".join(s.text for s in segments).strip()
            log.info(f"[STT] 转写结果: {text} (语言: {info.language}, 置信度: {info.language_probability:.2f})")
            return {"status": "ok", "text": text}
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        log.error(f"[STT] 转写失败: {e}")
        return {"status": "error", "msg": str(e)}


async def understand_image(image_base64, model_slot="powerful"):
    """
    图像理解（调用 gemini-auto 多模态）
    """
    log.info(f"[Vision] 收到图像 {len(image_base64)} 字符")
    try:
        # 读 gemini-auto 配置
        env = {}
        with open('/home/hatch/data/llm_assets/gemini-auto.env') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    env[k] = v
        base_url = env.get('LLM_BASE_URL', '').rstrip('/')
        api_key = env.get('LLM_API_KEY', '')
        if not base_url or not api_key:
            return {"status": "error", "msg": "gemini-auto 未配置"}

        # OpenAI 兼容的 vision 调用
        payload = {
            "model": "gemini-auto",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "用中文简洁描述这张图片里看到了什么，50字以内。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }],
            "max_tokens": 200,
        }
        import urllib.request
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        loop = asyncio.get_event_loop()
        def _call():
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        result = await loop.run_in_executor(None, _call)
        text = result["choices"][0]["message"]["content"].strip()
        log.info(f"[Vision] 看到: {text[:80]}")
        # 存入状态，供对话时引用
        perception_state["last_vision"] = text
        perception_state["vision_history"] = perception_state.get("vision_history", [])[-9:] + [{
            "at": datetime.now().isoformat(), "desc": text
        }]
        # 落盘供 voice_executor 读取
        try:
            ctx_file = BASE / "perception" / "vision_context.json"
            ctx_file.write_text(json.dumps({
                "history": perception_state["vision_history"],
                "updated": datetime.now().isoformat(),
            }, ensure_ascii=False))
        except:
            pass
        return {"status": "ok", "desc": text}
    except Exception as e:
        log.error(f"[Vision] 失败: {e}")
        return {"status": "error", "msg": str(e)[:200]}


async def execute_voice_command(transcript):
    """
    执行语音指令：转写文本 → 提交给 nanoMuse 执行
    """
    log.info(f"[Command] 语音指令: {transcript}")
    perception_state["command_history"].append({
        "transcript": transcript,
        "at": datetime.now().isoformat(),
    })
    # 写入指令队列，供 nanoMuse 调度器认领
    queue_file = BASE / "perception" / "voice_commands.jsonl"
    with open(queue_file, "a") as f:
        f.write(json.dumps({
            "transcript": transcript,
            "at": datetime.now().isoformat(),
            "source": "voice",
        }, ensure_ascii=False) + "\n")
    return {"status": "queued", "transcript": transcript}


# Live 模式：每个浏览器客户端对应一个 bridge 会话
_live_sessions = {}  # websocket -> LiveBridgeClient

async def handle_live_audio(websocket, audio_base64):
    """Live 模式：浏览器音频 → 转 PCM16 → Gemini Live → 音频流回浏览器"""
    try:
        # 获取或创建该客户端的 Live 会话
        client = _live_sessions.get(websocket)
        if client is None:
            from live_bridge_client import LiveBridgeClient
            client = LiveBridgeClient()
            # 设置音频回调：收到 Gemini 音频 → 发给浏览器
            async def on_gemini_audio(pcm24k):
                try:
                    await websocket.send(json.dumps({
                        "type": "live_audio",
                        "data": base64.b64encode(pcm24k).decode(),
                        "sample_rate": 24000,
                    }))
                except Exception:
                    pass
            client.on_audio(on_gemini_audio)
            # 设置转写回调：用户说话的转写 → 显示 + 送入任务执行队列
            async def on_live_transcript(text, role):
                try:
                    if role == "user" and text.strip():
                        # 显示用户说了什么
                        await websocket.send(json.dumps({
                            "type": "transcript_result",
                            "text": text,
                        }, ensure_ascii=False))
                        # 送入 nanoMuse 任务执行队列（干活！）
                        perception_state["last_transcript"] = text
                        cmd_result = await execute_voice_command(text)
                        log.info(f"[Live] 指令已提交执行: {text[:50]}")
                    elif role == "gemini" and text.strip():
                        # 显示 Gemini 回复的文字版
                        await websocket.send(json.dumps({
                            "type": "live_text",
                            "text": text,
                        }, ensure_ascii=False))
                except Exception as e:
                    log.error(f"[Live] 转写回调失败: {e}")
            client.on_transcript(on_live_transcript)
            ok = await client.connect()
            if not ok:
                await websocket.send(json.dumps({
                    "type": "live_error",
                    "msg": "Gemini Live 连接失败",
                }))
                return
            _live_sessions[websocket] = client
            log.info(f"[Live] 新会话建立: {websocket.remote_address}")

        # WebM → PCM16 16kHz
        webm_bytes = base64.b64decode(audio_base64)
        pcm16 = await webm_to_pcm16(webm_bytes)
        if pcm16:
            await client.send_audio(pcm16)
            log.debug(f"[Live] 转发音频 {len(pcm16)} bytes → Gemini")
    except Exception as e:
        log.error(f"[Live] 处理失败: {e}")
        await websocket.send(json.dumps({"type": "live_error", "msg": str(e)[:200]}))


async def handle_client(websocket):
    log.info(f"客户端连接: {websocket.remote_address}")
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"error": "invalid json"}))
                continue

            msg_type = data.get("type")

            if msg_type == "audio":
                if USE_LIVE_MODE:
                    # Live 模式：音频直送 Gemini Live，实时返回语音
                    await handle_live_audio(websocket, data.get("data", ""))
                else:
                    # 传统模式：浏览器录音 → Whisper 转写 → 直接执行指令
                    result = await transcribe_audio(data.get("data", ""))
                    if result.get("status") == "ok" and result.get("text"):
                        transcript = result["text"]
                        perception_state["last_transcript"] = transcript
                        # 推送转写结果给前端显示
                        await websocket.send(json.dumps({
                            "type": "transcript_result",
                            "text": transcript,
                        }, ensure_ascii=False))
                        # 执行指令
                        cmd_result = await execute_voice_command(transcript)
                        await websocket.send(json.dumps({"type": "command_ack", **cmd_result}, ensure_ascii=False))
                    else:
                        await websocket.send(json.dumps({"type": "audio_ack", **result}, ensure_ascii=False))

            elif msg_type == "transcript":
                # 浏览器端已转写好的文字（Web Speech API）
                transcript = data.get("text", "")
                perception_state["last_transcript"] = transcript
                result = await execute_voice_command(transcript)
                await websocket.send(json.dumps({"type": "command_ack", **result}))

            elif msg_type == "video_frame":
                # 视频帧：Live 模式下直送 Gemini Live，否则走旧的图像理解
                if USE_LIVE_MODE:
                    client = _live_sessions.get(websocket)
                    if client:
                        # 限流：约1fps，避免刷屏
                        await client.send_video(data.get("data", ""))
                        log.debug("[Live] 视频帧已转发 → Gemini")
                else:
                    result = await understand_image(data.get("data", ""))
                    perception_state["last_vision"] = result.get("note", "")
                    await websocket.send(json.dumps({"type": "vision_ack", **result}))

            elif msg_type == "ping":
                await websocket.send(json.dumps({
                    "type": "pong",
                    "state": {
                        "audio": perception_state["audio_active"],
                        "video": perception_state["video_active"],
                        "last_transcript": perception_state["last_transcript"][:100],
                    }
                }))
            else:
                await websocket.send(json.dumps({"error": f"unknown type: {msg_type}"}))

    except websockets.exceptions.ConnectionClosed:
        log.info("客户端断开")
    except Exception as e:
        log.error(f"处理错误: {e}")
    finally:
        connected_clients.discard(websocket)
        # 清理 Live 会话
        live_client = _live_sessions.pop(websocket, None)
        if live_client:
            try:
                await live_client.close()
                log.info(f"[Live] 会话已关闭")
            except Exception:
                pass


# 已连接的客户端
connected_clients = set()

async def speak_broadcaster():
    """监听 speak_queue.jsonl，广播给所有客户端"""
    speak_file = BASE / "perception" / "speak_queue.jsonl"
    seen = set()
    while True:
        try:
            if speak_file.exists():
                for line in speak_file.read_text().splitlines():
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except:
                        continue
                    at = item.get("at", "")
                    if at in seen:
                        continue
                    seen.add(at)
                    text = item.get("text", "")
                    if text and connected_clients:
                        msg = json.dumps({"type": "speak", "text": text}, ensure_ascii=False)
                        for ws in list(connected_clients):
                            try:
                                await ws.send(msg)
                            except:
                                pass
                        log.info(f"[Speak] 已广播: {text[:50]}")
        except Exception as e:
            log.error(f"广播错误: {e}")
        await asyncio.sleep(1)

async def main():
    host = "127.0.0.1"
    port = 18736
    log.info(f"感知服务器启动: ws://{host}:{port}")
    log.info("模型: agnes-2.5-flash (STT) + gemini-auto (Vision/理解)")
    async with websockets.serve(handle_client, host, port):
        # 启动广播任务
        asyncio.create_task(speak_broadcaster())
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
