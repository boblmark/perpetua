#!/usr/bin/env python3
"""公式级去重：防"系列公式"滑向"套模板"。

标题去重（dedup_check.py）只比关键词，看不出两条视频用了
同一个 6 段式结构 + 同一个笑点机制。这个模块比"公式指纹"：

指纹 = {device（AI 设备类型）, karma_verb（高潮物理笑点动词）, hook_kw（钩子关键词）}

规则：
- 同一 device 在 90 天内出现过 → 硬拒绝（场景撞车）
- 同一 karma_verb 在 30 天内出现过 → 硬拒绝（笑点机制重复，模板感）
- hook 关键词与 90 天内某条重叠 >60% → 硬拒绝（钩子撞车）

比对源：pipeline_queue.json（90天内条目）+ YouTube 近 90 天已发布标题（device 推断）。
纯标准库。
"""
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

BASE = "/home/hatch/data"
QUEUE = os.path.join(BASE, "perpetua", "pipeline_queue.json")
YT_SCRIPT = os.path.join(BASE, "youtube", "yt.py")
REJECT_LOG = os.path.join(BASE, "perpetua", "formula_dedup_reject.log.json")

DEVICE_WINDOW_DAYS = 90
VERB_WINDOW_DAYS = 30
HOOK_OVERLAP_THRESHOLD = 0.60

KARMA_VERBS = [
    "spray", "sprays", "sprayed", "soak", "soaks", "soaked",
    "lock", "locks", "locked", "trap", "traps", "trapped",
    "tow", "tows", "towed", "slam", "slams", "slammed",
    "eject", "ejects", "ejected", "blast", "blasts", "blasted",
    "drench", "drenched", "shock", "shocks", "shocked",
    "print", "prints", "printed",
    # 2026-10-07 Ask Studio 审核去重后的干净名单 (7个)
    "balloon", "balloons", "ballooned",           # Ballooning: 充气垫弹飞
    "flap", "flaps", "flapped",                   # Flapping: 盖子掀飞帽子
    "reverse", "reverses", "reversed",             # Treadmill Reverse: 倒车转180°
    "stamp", "stamps", "stamped",                  # Barcode Stamping: 巨型贴纸拍胸口
    "vibrate", "vibrates", "vibrated",             # Vibration Jolt: 超声波震动
    "jolt", "jolts", "jolted",
    "mute", "mutes", "muted",                      # Pre-recorded Muting: 电梯音乐盖过
    "spotlight", "spotlights", "spotlighted",      # Pinpoint Spotlight: 强光定住
    # 2026-10-07 Ask Studio 改造后挽回的8个 (去重审核通过)
    "bop", "bops", "bopped",                       # Receipt Tower: 6英尺硬收据塔顶下巴
    "unroll", "unrolls", "unrolled",               # Party Horn: 派对喇叭伸进嘴里
    "yank", "yanks", "yanked",                     # Safe Yank: 智能微波炉/保险箱拽走道具
    "slurp", "slurps", "slurped",                  # Suction Vortex: 空气净化器吸住围巾
    "whistle", "whistles", "whistled",             # Slide-whistle: 滑音哨+LED翻白眼
    "dangle", "dangles", "dangled",                # Out-of-order Sign: 小牌子挂在鼻子上
    "snap", "snaps", "snapped",                    # Velvet Rope: 绒绳弹在小腿上
    "dive", "dives", "dived", "dove",              # Pet Dive-bomb: 宠物扑向她的包
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for",
    "with", "her", "his", "it", "its", "is", "are", "was", "then", "vs",
    "shorts", "short", "karen",
}


def _keywords(text):
    words = re.findall(r"[a-zA-Z]+", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _normalize_device(topic):
    """'AI self-checkout kiosk' -> 'self-checkout kiosk'"""
    t = (topic or "").lower().strip()
    t = re.sub(r"^(ai|smart)\s+", "", t)
    return t.strip()


def _extract_karma_verb(prompt):
    """从 prompt 的 CLIMAX 段提取物理笑点动词。"""
    m = re.search(r"CLIMAX.{0,400}", prompt or "", re.S | re.I)
    seg = m.group(0) if m else (prompt or "")
    seg_low = seg.lower()
    for v in KARMA_VERBS:
        if re.search(r"\b" + re.escape(v) + r"\b", seg_low):
            # 归一到原形
            return re.sub(r"(s|ed)$", "", v) if v not in (
                "spray", "soak", "lock", "trap", "tow", "slam",
                "eject", "blast", "drench", "shock", "print") else v
    return None


def fingerprint(topic, hook, prompt=""):
    return {
        "device": _normalize_device(topic),
        "karma_verb": _extract_karma_verb(prompt),
        "hook_kw": sorted(_keywords(hook)),
    }


def _queue_fingerprints(days=90):
    """pipeline_queue.json 里近 N 天的条目指纹。"""
    out = []
    try:
        q = json.load(open(QUEUE, encoding="utf-8"))
    except Exception:
        return out
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = q if isinstance(q, list) else q.get("items", [])
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("status") in ("rejected", "review_failed"):
            continue
        created = str(it.get("created_at", "") or it.get("submitted_at", ""))
        try:
            cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if cdt.tzinfo is None:
                cdt = cdt.replace(tzinfo=timezone.utc)
            if cdt < cutoff:
                continue
        except Exception:
            pass  # 日期缺失也纳入（宁严勿松）
        out.append({
            "source": "queue:" + str(it.get("topic", "")),
            "fp": fingerprint(it.get("topic", ""), it.get("hook", ""),
                              it.get("prompt", "")),
            "title": it.get("title", ""),
        })
    return out


def _yt_recent_devices(days=90):
    """YouTube 近 N 天已发布标题 → 推断 device 关键词。"""
    out = []
    try:
        r = subprocess.run(
            ["python3", YT_SCRIPT, "recent", "50"],
            capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout) if r.stdout.strip() else []
    except Exception:
        return out
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for it in items:
        if not isinstance(it, dict):
            continue
        pub = str(it.get("published", ""))
        try:
            pdt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            if pdt.tzinfo is None:
                pdt = pdt.replace(tzinfo=timezone.utc)
            if pdt < cutoff:
                continue
        except Exception:
            pass
        title = it.get("title", "")
        out.append({
            "source": "youtube:" + title[:40],
            "fp": {"device": "", "karma_verb": None,
                   "hook_kw": sorted(_keywords(title))},
            "title": title,
        })
    return out


def _log_reject(entry):
    log = []
    try:
        log = json.load(open(REJECT_LOG, encoding="utf-8"))
    except Exception:
        log = []
    entry["at"] = datetime.now(timezone.utc).isoformat()
    log.append(entry)
    json.dump(log, open(REJECT_LOG, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def check_formula(topic, hook, prompt=""):
    """返回 (is_dup: bool, reason: str|None, detail: dict)。

    reason 取值：device_collision / karma_verb_reuse / hook_collision
    """
    fp = fingerprint(topic, hook, prompt)
    device = fp["device"]
    verb = fp["karma_verb"]
    hook_kw = set(fp["hook_kw"])

    history = _queue_fingerprints(DEVICE_WINDOW_DAYS) + \
        _yt_recent_devices(DEVICE_WINDOW_DAYS)
    verb_cutoff_days = VERB_WINDOW_DAYS

    for h in history:
        hfp = h["fp"]
        # 1. 同一设备 90 天内出现过 → 场景撞车
        if device and hfp["device"] and device == hfp["device"]:
            detail = {"rule": "device_collision", "device": device,
                      "matched": h["source"], "title": h["title"][:60]}
            _log_reject({"topic": topic, "hook": hook[:80], **detail})
            return True, "device_collision", detail
        # 2. 同一标题关键词隐含同设备（YouTube 侧无 prompt，只有标题）
        if device and not hfp["device"] and h["title"]:
            tkw = _keywords(h["title"])
            dkw = _keywords(device)
            if dkw and len(dkw & tkw) / max(len(dkw), 1) >= 0.5:
                detail = {"rule": "device_collision", "device": device,
                          "matched": h["source"], "title": h["title"][:60],
                          "via": "title_keywords"}
                _log_reject({"topic": topic, "hook": hook[:80], **detail})
                return True, "device_collision", detail

    # 3. 同一 karma 动词 30 天内用过 → 笑点机制重复
    if verb:
        for h in _queue_fingerprints(verb_cutoff_days):
            if h["fp"]["karma_verb"] == verb:
                detail = {"rule": "karma_verb_reuse", "verb": verb,
                          "matched": h["source"], "title": h["title"][:60]}
                _log_reject({"topic": topic, "hook": hook[:80], **detail})
                return True, "karma_verb_reuse", detail

    # 4. 钩子关键词 90 天内重叠 >60% → 钩子撞车
    if hook_kw:
        for h in history:
            hkw = set(h["fp"]["hook_kw"])
            if not hkw:
                continue
            ov = len(hook_kw & hkw) / max(len(hook_kw), len(hkw))
            if ov >= HOOK_OVERLAP_THRESHOLD:
                detail = {"rule": "hook_collision",
                          "overlap": round(ov, 3),
                          "matched": h["source"], "title": h["title"][:60]}
                _log_reject({"topic": topic, "hook": hook[:80], **detail})
                return True, "hook_collision", detail

    return False, None, {"fingerprint": fp}


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else ""
    hook = sys.argv[2] if len(sys.argv) > 2 else ""
    prompt = sys.argv[3] if len(sys.argv) > 3 else ""
    dup, reason, detail = check_formula(topic, hook, prompt)
    print(json.dumps({"is_dup": dup, "reason": reason, "detail": detail},
                     ensure_ascii=False, indent=2))
