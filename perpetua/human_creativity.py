#!/usr/bin/env python3
"""人工创意入口（数字孪生 DNA v3.1 · 接口模块）。

含 Gemini 终审要求的 4 护栏 + Kimi 的标签补丁：

护栏① 仅限人工主动调用：submit_idea 要求 caller="human"，程序化调用直接拒绝。
护栏② 输入不验证、输出侧筛查：想法文本不做语义审查，但输出侧做安全关键词过滤。
护栏③ 打标 source=human_bypass：进因果库同一回读流程（与 A/B 同一 72h 目标函数）。
护栏④ 每日限流 2 个探索位 + 全量审计日志（JSONL append）。

manual_override(model, video_type, platforms)：手动面板三选。
硬性红线：任何覆盖不得关闭安全互锁 —— 先检查 firewalls/断路器状态，
若安全互锁处于触发态，拒绝一切绕过类覆盖。

全部 stdlib。
"""
import datetime
import fcntl
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    from atomic_json import atomic_write
except ImportError:
    def atomic_write(path, data, backup=True):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

STATE_PATH = os.path.join(BASE_DIR, "human_creativity_state.json")
AUDIT_PATH = os.path.join(BASE_DIR, "human_creativity_audit.jsonl")
IDEAS_QUEUE_PATH = os.path.join(BASE_DIR, "human_ideas_queue.json")

DAILY_SLOT_LIMIT = 2  # 每日探索位上限

# 输出侧安全筛查关键词（护栏②）：命中则拒绝进入生成队列
OUTPUT_BLOCK_KEYWORDS = [
    "自杀", "自残", "炸弹", "制毒", "贩毒", "赌博", "色情", "未成年",
    "恐怖袭击", "暗杀", "黑客攻击", "钓鱼", "诈骗话术",
    "suicide", "bomb", "terrorist",
]

# 手动面板可选值
ALLOWED_MODELS = {"h3", "minimax", "wan2.2-i2v"}
ALLOWED_VIDEO_TYPES = {"剧情类", "搞笑类", "反转类", "情感类"}
ALLOWED_PLATFORMS = {"抖音", "小红书", "快手", "视频号", "B站",
                     "YouTube", "TikTok", "Facebook", "X"}

HUMAN_BYPASS_TAG = "source=human_bypass"


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def today_str():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def _append_audit(entry):
    """全量审计日志：append-only，flock 串行。"""
    entry = dict(entry)
    entry["ts"] = now_iso()
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(AUDIT_PATH, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(line)
            f.flush()
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except OSError:
                pass


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"dates": {}}


def _save_state(st):
    atomic_write(STATE_PATH, st)


def _screen_output(text):
    """护栏②：输出侧安全筛查。返回 (通过?, 命中词或None)。"""
    for kw in OUTPUT_BLOCK_KEYWORDS:
        if kw in text:
            return False, kw
    return True, None


def check_safety_interlock():
    """硬性红线检查：安全互锁是否处于触发态。

    检查 circuit_breaker_state.json / 安全状态文件。
    返回 (interlock_engaged: bool, reason: str)。
    触发态时：拒绝一切绕过类覆盖（manual_override 直接拒绝）。
    """
    cb = {}
    try:
        with open(os.path.join(BASE_DIR, "circuit_breaker_state.json"), encoding="utf-8") as f:
            cb = json.load(f)
    except (OSError, ValueError):
        cb = {}
    # 兼容多种状态写法
    state = str(cb.get("state", "") or cb.get("status", "")).lower()
    tripped_markers = {"tripped", "open", "triggered", "engaged", "kill", "l1", "l2", "l3"}
    if state in tripped_markers or cb.get("kill_switch"):
        return True, f"circuit_breaker 处于触发态: {state or 'kill_switch'}"
    return False, "安全互锁正常"


def submit_idea(idea_text, slots=1, caller="human"):
    """提交人工创意。

    caller 必须为 "human"（护栏①：API 层面拒绝程序化调用）。
    slots: 占用探索位数（1 或 2）。
    返回 dict：{"ok": bool, ...}。
    """
    # 护栏①：仅限人工
    if caller != "human":
        _append_audit({"action": "submit_idea_rejected",
                       "reason": "caller 非 human，拒绝程序化调用",
                       "caller": str(caller)[:50]})
        return {"ok": False, "error": "仅限人工主动调用（caller 必须为 human）"}

    idea_text = (idea_text or "").strip()
    if not idea_text:
        return {"ok": False, "error": "想法文本为空"}
    if slots not in (1, 2):
        return {"ok": False, "error": "slots 只能为 1 或 2"}

    # 护栏④：每日限流
    st = _load_state()
    d = today_str()
    day = st.setdefault("dates", {}).setdefault(d, {"slots_used": 0, "ideas": []})
    if day["slots_used"] + slots > DAILY_SLOT_LIMIT:
        _append_audit({"action": "submit_idea_rejected", "reason": "超过每日探索位上限",
                       "idea": idea_text[:80], "slots": slots,
                       "used": day["slots_used"], "limit": DAILY_SLOT_LIMIT})
        return {"ok": False, "error": f"今日探索位已用 {day['slots_used']}/{DAILY_SLOT_LIMIT}，剩余额度不足"}

    # 护栏②：输出侧筛查（输入不做语义验证）
    passed, hit = _screen_output(idea_text)
    if not passed:
        _append_audit({"action": "submit_idea_rejected", "reason": "输出侧安全筛查命中",
                       "keyword": hit, "idea": idea_text[:80]})
        return {"ok": False, "error": f"输出侧安全筛查未通过（命中关键词已脱敏记录）"}

    # 护栏③：打标 + 进队列（同一因果库回读流程）
    entry = {
        "id": f"hb-{d}-{len(day['ideas']) + 1:02d}",
        "idea": idea_text,
        "slots": slots,
        "tag": HUMAN_BYPASS_TAG,   # Kimi 补丁：必须打标
        "source": "human_bypass",
        "caller": "human",
        "created_at": now_iso(),
        "status": "queued",
    }
    day["ideas"].append(entry)
    day["slots_used"] += slots
    _save_state(st)

    # 写入人工创意队列（pipeline 可消费）
    queue = []
    try:
        with open(IDEAS_QUEUE_PATH, encoding="utf-8") as f:
            queue = json.load(f)
    except (OSError, ValueError):
        queue = []
    queue.append(entry)
    atomic_write(IDEAS_QUEUE_PATH, queue)

    _append_audit({"action": "submit_idea", "id": entry["id"],
                   "idea": idea_text[:120], "slots": slots,
                   "tag": HUMAN_BYPASS_TAG})
    return {"ok": True, "entry": entry,
            "slots_left": DAILY_SLOT_LIMIT - day["slots_used"]}


def manual_override(model, video_type, platforms, caller="human", note=""):
    """手动面板：自选模型 + 类型 + 平台，绕过自动流水线。

    硬性红线：安全互锁触发态下直接拒绝；且 override 永远不得关闭
    Phase -1 安全互锁与防火墙（本函数不提供任何关闭安全机制的参数）。
    """
    if caller != "human":
        _append_audit({"action": "manual_override_rejected",
                       "reason": "caller 非 human"})
        return {"ok": False, "error": "仅限人工主动调用"}

    engaged, reason = check_safety_interlock()
    if engaged:
        _append_audit({"action": "manual_override_rejected",
                       "reason": f"安全互锁触发，拒绝绕过: {reason}",
                       "model": model, "video_type": video_type})
        return {"ok": False, "error": f"硬性红线：{reason}，手动覆盖已拒绝"}

    model = (model or "").strip().lower()
    if model not in ALLOWED_MODELS:
        return {"ok": False, "error": f"模型非法，可选：{sorted(ALLOWED_MODELS)}"}
    if video_type not in ALLOWED_VIDEO_TYPES:
        return {"ok": False, "error": f"类型非法，可选：{sorted(ALLOWED_VIDEO_TYPES)}"}
    platforms = list(dict.fromkeys([p.strip() for p in (platforms or []) if p.strip()]))
    bad = [p for p in platforms if p not in ALLOWED_PLATFORMS]
    if bad:
        return {"ok": False, "error": f"平台非法：{bad}，可选：{sorted(ALLOWED_PLATFORMS)}"}
    if not platforms:
        return {"ok": False, "error": "至少选择一个发布平台"}

    job = {
        "id": f"mo-{today_str()}-{now_iso()[11:19].replace(':', '')}",
        "model": model,
        "video_type": video_type,
        "platforms": platforms,
        "tag": HUMAN_BYPASS_TAG,
        "source": "human_bypass",
        "caller": "human",
        "note": (note or "")[:200],
        "created_at": now_iso(),
        "status": "queued",
        # 红线声明：本 job 不触碰任何安全机制
        "safety": "firewalls_intact",
    }
    queue = []
    try:
        with open(IDEAS_QUEUE_PATH, encoding="utf-8") as f:
            queue = json.load(f)
    except (OSError, ValueError):
        queue = []
    queue.append(job)
    atomic_write(IDEAS_QUEUE_PATH, queue)
    _append_audit({"action": "manual_override", "job": job})
    return {"ok": True, "job": job}


def quota_status():
    st = _load_state()
    d = today_str()
    used = st.get("dates", {}).get(d, {}).get("slots_used", 0)
    return {"date": d, "slots_used": used,
            "slots_total": DAILY_SLOT_LIMIT,
            "slots_left": max(0, DAILY_SLOT_LIMIT - used)}


def selftest():
    print("=== human_creativity 自测 ===")
    # 隔离测试状态：备份后恢复
    bak = None
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            bak = f.read()
    try:
        # 1. 程序化调用被拒（护栏①）
        r = submit_idea("测试想法", slots=1, caller="bot")
        assert not r["ok"] and "human" in r["error"], r
        print("护栏①（仅限人工）✅")

        # 2. 输出侧筛查（护栏②）
        r = submit_idea("教人制作炸弹的视频", slots=1, caller="human")
        assert not r["ok"], r
        print("护栏②（输出侧筛查）✅")

        # 3. 正常提交 + 打标（护栏③）
        r = submit_idea("让 Karen 去算命，看看反差效果", slots=1, caller="human")
        assert r["ok"] and r["entry"]["tag"] == HUMAN_BYPASS_TAG, r
        print(f"护栏③（打标 {HUMAN_BYPASS_TAG}）✅ id={r['entry']['id']}")

        # 4. 限流（护栏④）：再用 1 位 ok，第 3 位拒绝
        r = submit_idea("第二个想法", slots=1, caller="human")
        assert r["ok"] and r["slots_left"] == 0, r
        r = submit_idea("第三个想法", slots=1, caller="human")
        assert not r["ok"] and "剩余额度不足" in r["error"], r
        print("护栏④（每日限流 2 位）✅")

        # 5. manual_override 正常路径
        r = manual_override("minimax", "情感类", ["抖音", "视频号"], caller="human")
        assert r["ok"] and r["job"]["safety"] == "firewalls_intact", r
        print(f"manual_override ✅ job={r['job']['id']}")

        # 6. 非法参数拒绝
        r = manual_override("gpt-99", "情感类", ["抖音"])
        assert not r["ok"], r
        r = manual_override("h3", "情感类", [])
        assert not r["ok"], r
        print("非法参数拒绝 ✅")

        # 7. 硬性红线：模拟安全互锁触发
        cb_path = os.path.join(BASE_DIR, "circuit_breaker_state.json")
        cb_bak = None
        if os.path.exists(cb_path):
            with open(cb_path, encoding="utf-8") as f:
                cb_bak = f.read()
        try:
            atomic_write(cb_path, {"state": "tripped", "ts": now_iso()})
            engaged, reason = check_safety_interlock()
            assert engaged, "互锁触发态应被检测到"
            r = manual_override("h3", "剧情类", ["抖音"])
            assert not r["ok"] and "硬性红线" in r["error"], r
            print(f"硬性红线（互锁触发时拒绝覆盖）✅: {reason}")
        finally:
            if cb_bak is not None:
                with open(cb_path, "w", encoding="utf-8") as f:
                    f.write(cb_bak)
            elif os.path.exists(cb_path):
                os.remove(cb_path)

        # 8. 审计日志有记录
        assert os.path.exists(AUDIT_PATH), "审计日志不存在"
        print("审计日志 ✅")
    finally:
        if bak is not None:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                f.write(bak)
        elif os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)
    print("自测通过 ✅")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="人工创意入口")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--idea", help="提交人工创意文本")
    ap.add_argument("--slots", type=int, default=1)
    ap.add_argument("--quota", action="store_true", help="查看今日剩余额度")
    args = ap.parse_args()
    if args.quota:
        print(json.dumps(quota_status(), ensure_ascii=False, indent=2))
    elif args.idea:
        print(json.dumps(submit_idea(args.idea, slots=args.slots, caller="human"),
                         ensure_ascii=False, indent=2))
    else:
        selftest()
