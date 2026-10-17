#!/usr/bin/env python3
"""
语音指令执行器 - nanoMuse 感知层
监听 voice_commands.jsonl，用 LLM 理解意图，映射到任务并执行
"""
import json
import time
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime

BASE = Path("/home/hatch/data/nanomuse-migration")
QUEUE_FILE = BASE / "perception" / "voice_commands.jsonl"
PROCESSED_FILE = BASE / "perception" / "voice_commands.processed.jsonl"
LOG_FILE = BASE / "perception" / "logs" / "executor.log"

import sys
sys.path.insert(0, str(BASE / "scheduler"))
from model_router import get_model_config


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def call_llm(prompt, slot="fast"):
    """调用用户自定义模型理解指令"""
    cfg = get_model_config(slot)
    if not cfg["api_key"] or not cfg["base_url"]:
        return {"error": "模型未配置"}
    try:
        req_data = json.dumps({
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }).encode()
        req = urllib.request.Request(
            f"{cfg['base_url']}/chat/completions",
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg['api_key']}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return {"text": result["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"error": str(e)}


# 语音指令 → 任务映射（关键词）
COMMAND_MAP = {
    "检查OA": "shadow-oa-watchdog",
    "OA状态": "shadow-oa-watchdog",
    "检查MCP": "shadow-mcp-watchdog",
    "发布健康": "shadow-publish-health",
    "矩阵": "shadow-matrix-sync-show",
    "队列": "shadow-queue-lease-reaper",
    "备份": "sqlite-hourly-backup",
    "死状态": "dead-state-watchdog",
    "死数据": "shadow-dead-data-sweep",
    "决策": "shadow-decision-watchdog",
    "议会": "shadow-council-auto-watch",
    "每日指标": "shadow-daily-metrics",
    "管线": "shadow-pipeline-orchestrator",
    "零播放": "zero-view-watch",
    "趋势": "trend-spike-watch",
    "评论": "comment-reply-batch-am",
    "竞品": "competitor-breakout-watch",
    # 购物类（特殊处理，非 jobs.yaml 任务）
    "买": "__shopping__",
    "购买": "__shopping__",
    "下单": "__shopping__",
    "搜一下": "__shopping__",
    "多少钱": "__shopping__",
    "链接": "__shopping__",
}


def understand_command(transcript):
    """用 LLM 理解语音指令，映射到任务"""
    # 先试关键词快速匹配
    for keyword, task_id in COMMAND_MAP.items():
        if keyword in transcript:
            return {"task_id": task_id, "method": "keyword", "confidence": "high"}

    # 关键词没命中，用 LLM 理解
    prompt = f"""用户说了一句中文语音指令，请判断它对应哪个系统任务。
可用任务：
- shadow-oa-watchdog：检查 OA 控制台状态
- shadow-mcp-watchdog：检查 MCP 服务状态
- shadow-publish-health：检查发布健康
- shadow-matrix-sync-show：查看平台矩阵
- shadow-queue-lease-reaper：检查任务队列
- sqlite-hourly-backup：备份数据库
- dead-state-watchdog：检查死状态
- shadow-dead-data-sweep：检查死数据
- shadow-decision-watchdog：检查议会决策
- shadow-council-auto-watch：检查议会自动执行
- shadow-daily-metrics：查看每日指标
- shadow-pipeline-orchestrator：检查管线编排
- zero-view-watch：检查零播放视频
- trend-spike-watch：检查趋势热点
- comment-reply-batch-am：检查评论回复
- competitor-breakout-watch：检查竞品动态
- __shopping__：购物/买东西/搜商品（看到商品想买）

用户指令：{transcript}

只返回任务 ID，不要解释。如果无法判断，返回 unknown。
注意：如果用户说"买"、"购买"、"下单"、"多少钱"、"搜一下这件"，返回 __shopping__。"""
    result = call_llm(prompt, slot="fast")
    if "error" in result:
        return {"task_id": "unknown", "method": "llm_failed"}
    task_id = result["text"].strip().split()[0]
    return {"task_id": task_id, "method": "llm"}


def execute_task(task_id):
    """执行任务（通过 nanoMuse 调度器的命令）"""
    import yaml
    jobs = yaml.safe_load(open(BASE / "scheduler" / "jobs.yaml"))
    job = next((j for j in jobs if j["id"] == task_id), None)
    if not job:
        return {"status": "error", "msg": f"任务不存在: {task_id}"}
    cmd = job.get("command", "")
    if not cmd or job.get("mode") == "manual":
        return {"status": "error", "msg": f"任务不可自动执行: {task_id}"}
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=120, cwd="/home/hatch/data/perpetua",
        )
        output = result.stdout[:2000]  # 截断
        return {"status": "ok", "output": output, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"status": "error", "msg": "执行超时"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_shopping(transcript):
    """
    语音购物流程：
    1. 读取最近视频帧
    2. 用 LLM 描述商品
    3. 返回搜索建议（实际下单需用户手动确认，Tier 3）
    """
    # 读最近视觉帧描述
    vision_desc = ""
    try:
        state_file = BASE / "perception" / "vision_context.json"
        if state_file.exists():
            vh = json.loads(state_file.read_text()).get("history", [])[-1:]
            if vh:
                vision_desc = vh[0].get("desc", "")
    except:
        pass

    # 用 LLM 理解用户想买什么
    prompt = f"""用户正在用摄像头对着一件商品，通过语音说要购买。
用户说：{transcript}
摄像头看到：{vision_desc if vision_desc else "（暂无画面描述）"}

请用一句话描述用户想买的商品（颜色、款式、品类），50字以内。
如果无法判断，直接说"无法识别商品"。"""
    
    result = call_llm(prompt, slot="fast")
    if "error" in result:
        return {"status": "error", "reply": "抱歉，购物功能暂时不可用。"}
    
    desc = result["text"].strip()[:100]
    if "无法识别" in desc:
        return {
            "status": "unknown_product",
            "reply": "我没看清你想买什么，能把摄像头对准商品再说一遍吗？"
        }
    
    # 记录购物意图，等待用户确认（Tier 3：下单必须手动批准）
    shopping_file = BASE / "perception" / "shopping_intents.jsonl"
    with open(shopping_file, "a") as f:
        f.write(json.dumps({
            "transcript": transcript,
            "product_desc": desc,
            "vision_desc": vision_desc,
            "at": datetime.now().isoformat(),
            "status": "pending_confirm",
        }, ensure_ascii=False) + "\n")
    
    return {
        "status": "pending",
        "reply": f"我看到你想买：{desc}。正在帮你找同款，稍后把链接发你确认，下单前需要你点头。"
    }


def process_queue():
    """主循环：监听队列并执行"""
    log("语音指令执行器启动")
    seen = set()
    # 加载已处理的
    if PROCESSED_FILE.exists():
        for line in PROCESSED_FILE.read_text().splitlines():
            if line.strip():
                try:
                    seen.add(json.loads(line)["at"])
                except:
                    pass
    while True:
        try:
            if QUEUE_FILE.exists():
                lines = QUEUE_FILE.read_text().splitlines()
                for line in lines:
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
                    transcript = item.get("transcript", "")
                    log(f"收到指令: {transcript}")

                    # 理解意图
                    intent = understand_command(transcript)
                    log(f"意图识别: {intent}")

                    # 执行
                    if intent["task_id"] == "__shopping__":
                        # 购物流程：截图 → 搜货 → 展示 → 等确认
                        result = handle_shopping(transcript)
                        log(f"购物结果: {result['status']}")
                        reply = result.get("reply", "购物搜索完成。")
                        broadcast_speak(reply)
                    elif intent["task_id"] != "unknown":
                        result = execute_task(intent["task_id"])
                        log(f"执行结果: {result['status']}")
                        # 生成语音回复
                        reply = make_voice_reply(transcript, intent, result)
                        log(f"回复: {reply}")
                        # 通过 WebSocket 推给浏览器（由 perception_server 转发）
                        broadcast_speak(reply)
                    else:
                        # 不是命令 → 对话模式：结合视觉上下文聊天
                        reply = chat_reply(transcript)
                        log(f"对话回复: {reply[:80]}")
                        broadcast_speak(reply)
                        # 回写结果
                        with open(PROCESSED_FILE, "a") as f:
                            f.write(json.dumps({
                                "at": at,
                                "transcript": transcript,
                                "intent": intent,
                                "reply": reply,
                            }, ensure_ascii=False) + "\n")
            time.sleep(2)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"错误: {e}")
            time.sleep(5)


def make_voice_reply(transcript, intent, result):
    """生成自然语言回复"""
    task_id = intent["task_id"]
    if result["status"] == "ok":
        # 任务名映射为中文
        names = {
            "shadow-oa-watchdog": "OA 状态",
            "shadow-mcp-watchdog": "MCP 服务",
            "shadow-publish-health": "发布健康",
            "shadow-matrix-sync-show": "平台矩阵",
            "shadow-queue-lease-reaper": "任务队列",
            "sqlite-hourly-backup": "数据库备份",
            "dead-state-watchdog": "死状态检查",
            "shadow-dead-data-sweep": "死数据检查",
            "shadow-decision-watchdog": "议会决策检查",
            "shadow-council-auto-watch": "议会自动执行",
            "shadow-daily-metrics": "每日指标",
            "shadow-pipeline-orchestrator": "管线编排",
            "zero-view-watch": "零播放检查",
            "trend-spike-watch": "趋势热点",
            "comment-reply-batch-am": "评论回复",
            "competitor-breakout-watch": "竞品动态",
        }
        name = names.get(task_id, task_id)
        # 从输出中提取关键信息
        output = result.get("output", "")[:200]
        if "200" in output or not output.strip():
            return f"{name}检查完成，一切正常。"
        return f"{name}检查完成。"
    else:
        return f"执行失败：{result.get('msg', '未知错误')}。"


def broadcast_speak(text):
    """通过文件让 perception_server 转发语音（简单 IPC）"""
    import json
    speak_file = BASE / "perception" / "speak_queue.jsonl"
    with open(speak_file, "a") as f:
        f.write(json.dumps({"text": text, "at": datetime.now().isoformat()}, ensure_ascii=False) + "\n")

def chat_reply(transcript):
    """对话模式：用 agnes-2.5-flash 聊天，结合最近看到的画面"""
    # 读最近视觉
    vision_ctx = ""
    try:
        import json as _json
        state_file = BASE / "perception" / "vision_context.json"
        if state_file.exists():
            vh = _json.loads(state_file.read_text()).get("history", [])[-3:]
            if vh:
                vision_ctx = "\n最近看到的画面：" + "; ".join(h["desc"] for h in vh)
    except:
        pass
    prompt = f"""你是 nanoMuse，一个友善的 AI 助手。用户正在跟你语音对话。
{vision_ctx}
用户说：{transcript}
用中文简洁回复（50字以内），像朋友聊天一样自然。"""
    result = call_llm(prompt, slot="fast")
    if "error" in result:
        return "抱歉，我刚才没听清，能再说一遍吗？"
    return result["text"].strip()[:200]

if __name__ == "__main__":
    process_queue()




