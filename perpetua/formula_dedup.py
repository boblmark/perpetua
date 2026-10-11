#!/usr/bin/env python3
"""公式级去重：防"系列公式"滑向"套模板"。

标题去重（dedup_check.py）只比关键词，看不出两条视频用了
同一个 6 段式结构 + 同一个笑点机制。这个模块比"公式指纹"：

指纹 = {device（AI 设备类型）, karma_verb（高潮物理笑点动词）, hook_kw（钩子关键词）}

规则：
- 同一 device 在 90 天内出现过 → 硬拒绝（场景撞车）
- 同一 karma_verb 在 30 天内出现过 → 硬拒绝（笑点机制重复，模板感）
- hook 关键词与 90 天内某条重叠 >60% → 硬拒绝（钩子撞车）

A/B 测试豁免（2026-10-07）：同一 ab_group 内的条目互相比对时跳过。
即主动测试的 3 个钩子变体不会互相拦截，但仍会被组外历史拦截、
也会拦截组外的新选题。YouTube 侧已发布视频无 ab_group，不参与豁免。

比对源：pipeline_queue.json（90天内条目）+ YouTube 近 90 天已发布标题（device 推断）。
纯标准库。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

if "/home/hatch/data/perpetua" not in sys.path:
    sys.path.insert(0, "/home/hatch/data/perpetua")
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db

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


# 语义归一后仍判定为同一设备的显式别名（2026-10-09 arena 复审补）
# key/value 均为归一化后的 canonical device
DEVICE_ALIASES = {
    "car wash kiosk": "car wash",
    "drive thru window": "drive thru",
    "drive thru speaker": "drive thru",
    "fast food drive thru": "drive thru",
    "fast food drive thru window": "drive thru",
    "self checkout kiosk": "checkout",
    "checkout kiosk": "checkout",
    "self checkout": "checkout",
    "parking meter": "parking",
    "smart parking": "parking",
}

# 归一化时剔除的修饰词（位置不限）与无意义后缀
_DEVICE_MODIFIERS = {
    "ai", "smart", "automated", "autonomous", "robotic", "self-service",
    "selfservice", "intelligent",
}
_DEVICE_SUFFIXES = {
    "kiosk", "machine", "device", "system", "station", "pedestal",
    "unit", "terminal", "gadget", "appliance",
}


def _normalize_device(topic):
    """'Automated AI Car Wash Kiosk' -> 'car wash'
    'AI Fast-Food Drive-Thru Window' -> 'drive-thru'（经别名）
    """
    t = (topic or "").lower().strip()
    t = re.sub(r"[^a-z0-9\s\-&]", " ", t)
    toks = [w for w in re.split(r"[\s\-]+", t)
            if w and w not in _DEVICE_MODIFIERS and w != "&"]
    while toks and toks[-1] in _DEVICE_SUFFIXES:
        toks.pop()
    canon = " ".join(toks).strip()
    return DEVICE_ALIASES.get(canon, canon)


def _extract_karma_verb(prompt):
    """从 prompt 的 CLIMAX 段提取物理笑点动词。

    按动词在文本中出现的先后顺序取（最早出现的为准），
    避免误取模板示例词（如 "spray, lock, trap…" 列表）。
    """
    m = re.search(r"CLIMAX.{0,400}", prompt or "", re.S | re.I)
    seg = m.group(0) if m else (prompt or "")
    seg_low = seg.lower()
    best, best_pos = None, None
    for v in KARMA_VERBS:
        mm = re.search(r"\b" + re.escape(v) + r"\b", seg_low)
        if mm and (best_pos is None or mm.start() < best_pos):
            best, best_pos = v, mm.start()
    if best is None:
        return None
    # 归一到原形
    return re.sub(r"(s|ed)$", "", best) if best not in (
        "spray", "soak", "lock", "trap", "tow", "slam",
        "eject", "blast", "drench", "shock", "print") else best


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
        # D20261011-001 P1: pipeline_queue 已迁 SQLite
        q = queue_db.pipeline_load()
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
            "ab_group": it.get("ab_group"),
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
    atomic_write_json(REJECT_LOG, log)


def check_formula(topic, hook, prompt="", ab_group=None, skip_self_topic=None):
    """返回 (is_dup: bool, reason: str|None, detail: dict)。

    reason 取值：device_collision / karma_verb_reuse / hook_collision
    ab_group：A/B 测试组 id。非空时，跳过同组历史条目（组内互不拦截）。
    skip_self_topic：2026-10-11 新增——上传门禁场景下，被上传项自身已在
        pipeline queue 里（2026-10-09 新政后直接从队列发起上传），不跳过则
        必然自撞、所有上传被拦截。此处按确切 topic 跳过队列中的自身条目。
        选题阶段的去重调用不传此参数（新选题不应与在途条目同 topic）。
    """
    fp = fingerprint(topic, hook, prompt)
    device = fp["device"]
    verb = fp["karma_verb"]
    hook_kw = set(fp["hook_kw"])
    self_src = ("queue:" + str(skip_self_topic)) if skip_self_topic else None

    def _self(h):
        return self_src is not None and h.get("source") == self_src

    def _same_group(h):
        return (ab_group is not None and h.get("ab_group") is not None
                and h["ab_group"] == ab_group)

    history = _queue_fingerprints(DEVICE_WINDOW_DAYS) + \
        _yt_recent_devices(DEVICE_WINDOW_DAYS)
    verb_cutoff_days = VERB_WINDOW_DAYS

    for h in history:
        if _same_group(h) or _self(h):
            continue
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
            if _same_group(h) or _self(h):
                continue
            if h["fp"]["karma_verb"] == verb:
                detail = {"rule": "karma_verb_reuse", "verb": verb,
                          "matched": h["source"], "title": h["title"][:60]}
                _log_reject({"topic": topic, "hook": hook[:80], **detail})
                return True, "karma_verb_reuse", detail

    # 4. 钩子关键词 90 天内重叠 >60% → 钩子撞车
    if hook_kw:
        for h in history:
            if _same_group(h) or _self(h):
                continue
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
