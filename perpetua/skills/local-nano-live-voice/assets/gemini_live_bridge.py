#!/usr/bin/env python3
"""
Gemini Live API WebSocket Bridge (runs on VPS with direct internet).

Architecture:
  VM perception server <--TCP tunnel--> VPS bridge <--wss--> Gemini Live API

The bridge accepts raw PCM audio (16kHz, mono, 16-bit) from the VM via a
local TCP socket, forwards it to Gemini Live, and streams back the
24kHz PCM audio responses.

Protocol (VM <-> Bridge, over TCP):
  - Client sends: 4-byte big-endian length + PCM16 audio bytes (16kHz mono)
  - Bridge sends: 4-byte big-endian length + PCM16 audio bytes (24kHz mono)
  - Control messages: length=0 + JSON payload (e.g. {"type":"start"}, {"type":"stop"})

API key is read from /etc/gemini-live/key (600, root only).
"""
import asyncio
import json
import struct
import sys
import os

KEY_FILE = "/etc/gemini-live/key"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 18738

LIVE_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-09-2025"

def load_key():
    with open(KEY_FILE, "r") as f:
        return f.read().strip()

async def gemini_session(key, to_phone, from_phone):
    """Maintain one Gemini Live session, bridging audio both ways."""
    import websockets
    url = f"{LIVE_WS_URL}?key={key}"
    async with websockets.connect(url, max_size=16*1024*1024) as ws:
        setup = {
            "setup": {
                "model": LIVE_MODEL,
                "generation_config": {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {"prebuilt_voice_config": {"voice_name": "Zephyr"}}
                    }
                },
                "system_instruction": {
                    "parts": [{"text": "你是 nanoMuse 语音助手。用简洁自然的中文回答，控制在 2-3 句话内。如果用户说的是指令（如检查状态、执行任务），先简短确认再回答。"}]
                },
                "realtime_input_config": {
                    "automatic_activity_detection": {"disabled": False}
                },
                "input_audio_transcription": {},
                "output_audio_transcription": {}
            }
        }
        await ws.send(json.dumps(setup))

        async def ws_to_phone():
            async for raw in ws:
                msg = json.loads(raw)
                if "setupComplete" in msg:
                    await to_phone.put({"type": "ready"})
                    continue
                sc = msg.get("serverContent", {})
                # 用户语音转写（用于指令执行）
                input_tc = sc.get("inputTranscription", {})
                if input_tc.get("text"):
                    await to_phone.put({"type": "user_transcript", "text": input_tc["text"]})
                # Gemini 回复转写
                output_tc = sc.get("outputTranscription", {})
                if output_tc.get("text"):
                    await to_phone.put({"type": "gemini_transcript", "text": output_tc["text"]})
                # Audio output chunks
                model_turn = sc.get("modelTurn", {})
                for part in model_turn.get("parts", []):
                    blob = part.get("inlineData", {})
                    if blob.get("mimeType", "").startswith("audio/"):
                        import base64
                        pcm = base64.b64decode(blob["data"])
                        await to_phone.put({"type": "audio", "data": pcm})
                # Turn complete
                if sc.get("turnComplete"):
                    await to_phone.put({"type": "turn_complete"})

        async def phone_to_ws():
            while True:
                item = await from_phone.get()
                if item is None:
                    break
                if item.get("type") == "audio":
                    import base64
                    pcm_b64 = base64.b64encode(item["data"]).decode()
                    await ws.send(json.dumps({
                        "realtime_input": {
                            "audio": {
                                "mime_type": "audio/pcm;rate=16000",
                                "data": pcm_b64
                            }
                        }
                    }))
                elif item.get("type") == "text":
                    await ws.send(json.dumps({
                        "client_content": {
                            "turns": [{"role": "user", "parts": [{"text": item["text"]}]}],
                            "turn_complete": True
                        }
                    }))
                elif item.get("type") == "video":
                    # 视频帧：JPEG base64 → Gemini Live
                    await ws.send(json.dumps({
                        "realtime_input": {
                            "video": {
                                "mime_type": "image/jpeg",
                                "data": item["data"]
                            }
                        }
                    }))

        await asyncio.gather(ws_to_phone(), phone_to_ws())

async def handle_client(reader, writer, key):
    """Handle one VM client connection."""
    to_phone = asyncio.Queue()
    from_phone = asyncio.Queue()

    async def read_frames():
        try:
            while True:
                hdr = await reader.readexactly(4)
                (length,) = struct.unpack(">I", hdr)
                if length == 0:
                    payload = await reader.readexactly(4)
                    (jlen,) = struct.unpack(">I", payload)
                    data = await reader.readexactly(jlen)
                    ctrl = json.loads(data.decode())
                    if ctrl.get("type") == "stop":
                        await from_phone.put(None)
                        break
                    elif ctrl.get("type") == "text":
                        await from_phone.put({"type": "text", "text": ctrl["text"]})
                    elif ctrl.get("type") == "video":
                        await from_phone.put({"type": "video", "data": ctrl["data"]})
                else:
                    pcm = await reader.readexactly(length)
                    await from_phone.put({"type": "audio", "data": pcm})
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            await from_phone.put(None)

    async def write_frames():
        try:
            while True:
                item = await to_phone.get()
                if item is None:
                    break
                if item["type"] == "audio":
                    data = item["data"]
                    writer.write(struct.pack(">I", len(data)) + data)
                    await writer.drain()
                else:
                    j = json.dumps(item).encode()
                    writer.write(struct.pack(">I", 0) + struct.pack(">I", len(j)) + j)
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass

    # Run Gemini session + frame pumps concurrently
    try:
        await asyncio.gather(
            gemini_session(key, to_phone, from_phone),
            read_frames(),
            write_frames(),
        )
    except Exception as e:
        print(f"session error: {e}", file=sys.stderr, flush=True)
    finally:
        try:
            writer.close()
        except Exception:
            pass

async def main():
    key = load_key()
    if not key:
        print("no API key", file=sys.stderr)
        sys.exit(1)
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, key), LISTEN_HOST, LISTEN_PORT
    )
    print(f"bridge listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
