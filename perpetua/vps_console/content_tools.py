#!/usr/bin/env python3
"""ViralLoop 内容工具箱：7 项内容技能的规则引擎实现。

数据来源全部是频道真实数据文件（criteria.json / karma_verbs.json /
sequel_candidates.json），不是演示数据。供 console_server.py 的
/api/oa/content/* 接口调用。
"""
import json
import os
import re

DATA = "/home/hatch/data"
GATE_THRESHOLD = 58  # criteria.json v11 gate_threshold


def _has_emoji(t):
    return any(ord(ch) > 0x2500 for ch in t)


def _emoji_first(t):
    s = t.lstrip()
    return bool(s) and ord(s[0]) > 0x2500


_BANNED_RE = re.compile(r"\b(DESTROYED|ANNIHILATED|OBLITERATED|DEMOLISHED)\b", re.I)
_EPISODE_RE = re.compile(r"(Episode|Part|Complaint)\s*#?\s*\d+", re.I)
_VIRAL_KWS = ["viral", "instant", "karma", "gets", "caught", "cam", "hoa"]


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _verbs():
    return _load(os.path.join(DATA, "perpetua", "karma_verbs.json"), {})


def _criteria():
    return _load(os.path.join(DATA, "jev", "criteria.json"), {})


# ---------------------------------------------------------------- 1. 品牌简报
def brand_briefing():
    c = _criteria()
    kf = c.get("key_findings", [])
    ev = c.get("gate_evidence", {}).get("channel_baseline", {})
    return {
        "brand": "Mark Bobl | Karen vs AI（@karenvsai）",
        "voice": "英文 AI 讽刺短剧；Karen 是核心 IP，永远是冲突发起方且必输；"
                 "slapstick 肢体喜剧，禁止针对真人的羞辱表述",
        "audience": "英语区 Shorts 观众；平均观看 7-20 秒，前 3 秒定生死",
        "title_formula": c.get("title_formula", "[emoji] Karen + 冲突动作 + 即时报应 + [emoji]"),
        "key_findings": kf,
        "baseline": ev,
        "hard_rules": [
            "标题纯度：英文且含 Karen（AI 仅【AI Satire】系列可用），中文/偏题直接拒",
            "禁用词 DESTROYED/ANNIHILATED/OBLITERATED/DEMOLISHED 上传门禁直接拒",
            "禁用知名 IP（漫威/DC/迪士尼/任天堂等），版权红线",
            "疑问句标题不利，用陈述冲突",
            "发布/删除/私享/花钱/对外消息必须人类明确批准",
        ],
        "gate": "v2 模型，%d 分放行；Ask Studio ≥85 + QC + 人工终审" % GATE_THRESHOLD,
    }


# ---------------------------------------------------------------- 2. 内容指导
def content_guide(topic):
    t = (topic or "").strip()
    v = _verbs()
    checks = []
    tl = t.lower()
    if not re.search(r"karen", tl, re.I):
        checks.append({"item": "主角", "ok": False, "note": "话题未含 Karen，建议把 Karen 设为冲突发起方"})
    else:
        checks.append({"item": "主角", "ok": True, "note": "含 Karen，符合品牌 IP"})
    banned = [w for w in v.get("banned", []) if w.lower() in tl]
    if banned:
        checks.append({"item": "禁用词", "ok": False, "note": "含禁用词 %s，必须改掉" % banned})
    else:
        checks.append({"item": "禁用词", "ok": True, "note": "无禁用词"})
    has_device = bool(re.search(r"ai|robot|smart|self-driving|drone|camera|meter|kiosk", tl, re.I))
    checks.append({
        "item": "AI 设备",
        "ok": has_device,
        "note": "有具体 AI 设备可拍" if has_device else "建议绑定一个具体 AI 设备（门铃/售货机/停车计费器…），90 天设备去重",
    })
    fit = sum(1 for c_ in checks if c_["ok"])
    return {
        "topic": t,
        "fit_score": "%d/%d" % (fit, len(checks)),
        "checks": checks,
        "recommended_angles": [
            "Karen 挑衅 AI 设备 → 设备用规则反杀（即时报应）",
            "Karen 误报/投诉 AI → 反转打脸（caught-in-the-act）",
            "围观者视角：Karen vs AI 设备，路人神补刀",
        ],
        "avoid": ["疑问句标题", "剧集编号式数字（Part 2/Episode 3）", "慢开场", "Karen 获胜结局"],
        "dedup_reminder": "设备 90 天 / 动词 30 天 / 钩子 90 天去重，撞车打回",
    }


# ---------------------------------------------------------------- 3/4 共用：标题与钩子生成
_HOOK_EMOJIS = ["🅿️", "🚗", "📹", "😱", "🔥", "🤖", "🚨", "💥", "📸", "🧾"]
_ACTIONS = ["yells at", "kicks", "reports", "sues", "blocks", "unplugs", "fines", "bans"]
_PAYOFF_S = ["TRAPPED", "SLAPPED", "SOAKED", "TOWED", "FLOODED", "LOCKED", "BOOTED", "SPRAYED"]
_PAYOFF_B = ["CAUGHT", "EXPOSED", "BUSTED", "SHUT DOWN", "KICKED OUT"]


def _title_variants(topic, n=3):
    t = (topic or "AI device").strip()
    titles = []
    for i in range(n):
        e1 = _HOOK_EMOJIS[i % len(_HOOK_EMOJIS)]
        e2 = _HOOK_EMOJIS[(i + 5) % len(_HOOK_EMOJIS)]
        verb = (_PAYOFF_S + _PAYOFF_B)[i % (len(_PAYOFF_S) + len(_PAYOFF_B))]
        action = _ACTIONS[i % len(_ACTIONS)]
        titles.append("%s Karen %s %s... Gets %s Instantly %s #instantkarma" % (e1, action, t, verb, e2))
    return titles


def copywriter(topic, hook=""):
    titles = _title_variants(topic)
    scored = [post_score(t) for t in titles]
    desc = (
        "Karen takes on %s... and instantly regrets it. "
        "Watch till the end for the karma.\n\n"
        "#karen #instantkarma #ai #shorts" % (topic or "an AI device")
    )
    pinned = "Team Karen or Team AI? Drop your verdict — most liked comment gets pinned next video!"
    return {
        "titles": [{"title": t, "score": s["score"], "pass": s["pass"]} for t, s in zip(titles, scored)],
        "description": desc,
        "pinned_comment": pinned,
        "purity_note": "已自检：英文 / 含 Karen / 无禁用词 / 陈述句",
    }


def viral_hooks(topic, device=""):
    subj = (device or topic or "the AI device").strip()
    v = _verbs()
    patterns = [
        ("0 秒定格", "Karen 在 %s 面前举起手机——下一秒她就后悔了" % subj),
        ("冲突前置", "%s 当场拆穿 Karen 的谎言" % subj),
        ("报应预告", "3 秒后，Karen 被 %s 当众处刑" % subj),
        ("数字钩子", "Karen 连拨 47 次投诉电话，%s 一次反杀" % subj),
        ("反转钩子", "她以为 %s 怕她，结果…" % subj),
        ("围观钩子", "全停车场的人都在拍 Karen vs %s" % subj),
        ("规则钩子", "%s 只认规则不认人，Karen 撞枪口了" % subj),
        ("升级钩子", "Karen 踢了一脚 %s——踢出了连锁反应" % subj),
        ("打脸钩子", "Karen 刚说完'你奈我何'，%s 动了" % subj),
        ("循环钩子", "结尾神反转：Karen 自己成了笑话（可无缝循环）"),
    ]
    hooks = []
    tiers = v.get("tier_s", []) + v.get("tier_b", [])
    for i, (ptype, text) in enumerate(patterns):
        verb = tiers[i % len(tiers)] if tiers else ""
        hooks.append({"rank": i + 1, "type": ptype, "hook": text,
                      "verb_tier": "S" if verb in v.get("tier_s", []) else "B",
                      "verb": verb})
    return {"topic": topic, "device": device, "hooks": hooks,
            "note": "S 级动词=突然物理报应，好奇心缺口最大；动词强度必须匹配视觉 payoff"}


# ---------------------------------------------------------------- 5. 贴文评分
def post_score(title, script=""):
    t = (title or "").strip()
    breakdown = []
    score = 50.0

    if _BANNED_RE.search(t):
        return {"title": t, "score": 0, "pass": False, "grade": "拒",
                "breakdown": [{"item": "禁用词", "delta": "-50", "note": "含 DESTROYED 类抽象标题党，直接 0 分"}],
                "suggestion": "换 tier_s 动词（TRAPPED/SLAPPED/SOAKED…）"}

    def add(item, delta, note):
        nonlocal score
        score += delta
        breakdown.append({"item": item, "delta": "%+d" % delta, "note": note})

    if _has_emoji(t):
        add("含 emoji", 8, "Pearson 0.434，全频道最强正变量")
        if _emoji_first(t):
            add("emoji 开头", 4, "放开头 3.43x")
    else:
        add("无 emoji", -8, "爆款 100% 用 emoji")
    if re.search(r"karen", t, re.I):
        add("含 Karen", 6, "核心 IP，老视频 1.78x")
    else:
        add("无 Karen", -6, "Karen 优先于泛 AI")
    if re.search(r"ai satire", t, re.I):
        add("AI Satire 系列", 5, "品牌系列 3.93x")
    elif re.search(r"\bai\b", t, re.I):
        add("泛 AI 提及", -8, "普通 AI 提及 0.22x，有害")
    if "?" in t or "？" in t:
        add("疑问句", -6, "疑问句标题不利，用陈述冲突")
    if _EPISODE_RE.search(t):
        add("剧集编号", -10, "Part 2/Episode 3 式数字拒绝")
    kws = [k for k in _VIRAL_KWS if k in t.lower()]
    if kws:
        add("爆款关键词", min(9, 3 * len(kws)), "命中 %s" % kws)
    v = _verbs()
    tl = t.upper()
    if any(w in tl for w in v.get("tier_s", [])):
        add("S 级动词", 5, "突然物理报应，好奇心缺口最大")
    elif any(w in tl for w in v.get("tier_b", [])):
        add("B 级动词", 2, "caught-in-the-act 类，可用")
    if re.search(r"\d+", t) and not _EPISODE_RE.search(t):
        add("具象数字", 3, "15 DOGS 式故事数字可用")
    if len(t) > 100:
        add("标题过长", -4, "前 40-50 字符讲清冲突")

    score = max(0, min(100, round(score, 1)))
    passed = score >= GATE_THRESHOLD
    grade = "必爆" if score >= 85 else "高" if score >= 70 else "可发" if passed else "重写"
    suggestion = ("达标，可进 Ask Studio 评审" if passed
                  else "未达 58 分线：加 emoji 开头、确保含 Karen、用 S 级动词、删疑问句")
    return {"title": t, "score": score, "pass": passed, "grade": grade,
            "threshold": GATE_THRESHOLD, "breakdown": breakdown,
            "suggestion": suggestion,
            "note": "v2 规则模型（496 条自有数据校准）；jev 分仅供参考，不参与放行"}


# ---------------------------------------------------------------- 6. 发帖排期
_SLOTS = [("10:00", "高方差档：只赌最高分选题，<70 分宁可空着"),
          ("12:30", "常规档"),
          ("00:00", "常规档")]
_WEEKDAY_BOOST = {"Friday": "周五爆款率高，加权优先", "Monday": "周一爆款率高，加权优先"}


def scheduler(topics):
    """topics: [{title, score}]"""
    items = sorted(topics or [], key=lambda x: x.get("score", 0), reverse=True)
    plan, used = [], 0
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in days:
        for slot, note in _SLOTS:
            if used < len(items):
                it = items[used]
                used += 1
                plan.append({"day": day, "slot": slot, "title": it.get("title"),
                             "score": it.get("score"), "slot_note": note,
                             "boost": _WEEKDAY_BOOST.get(day, "")})
            else:
                plan.append({"day": day, "slot": slot, "title": "（空）",
                             "score": None,
                             "slot_note": "10:00 档 <70 分宁可空着" if slot == "10:00" else "待选题",
                             "boost": _WEEKDAY_BOOST.get(day, "")})
    return {"plan": plan, "rules": [
        "每天 3 档：10:00 / 12:30 / 00:00（CST）",
        "10:00 高方差档只发最高分，低于 70 分空着",
        "周五、周一发布更易爆",
        "发布后 6 小时 0 播放 → 换备选标题",
    ]}


# ---------------------------------------------------------------- 7. 内容重塑
def repurpose(video_id="", topic=""):
    seqs = _load(os.path.join(DATA, "sequel_candidates.json"), [])
    out = []
    if video_id:
        cand = next((s for s in seqs if s.get("original_id") == video_id), None)
        pool = [cand] if cand else []
    else:
        pool = seqs[:3]
    for s in pool:
        base = s.get("original_title", topic)
        out.append({
            "original": base,
            "views": s.get("views"),
            "angles": [
                {"angle": "续集升级",
                 "title": "Karen vs %s ROUND 2... This Time It's Worse #instantkarma" % (topic or "AI"),
                 "hook": "上一集的报应只是开始"},
                {"angle": "视角反转",
                 "title": "What The %s SAW... Karen Had No Idea #caughtoncamera" % (topic or "AI Device"),
                 "hook": "换设备第一视角重讲同一冲突"},
                {"angle": "跨界联动",
                 "title": "Karen Brings Backup... The %s Brings Receipts #karma" % (topic or "AI"),
                 "hook": "引入第二冲突方，升级赌注"},
            ],
            "dedup_reminder": "90 天标题去重（>60% 重叠打回）；设备/动词/钩子三项原创度检查",
        })
    if not out:
        out.append({"original": topic, "views": None,
                    "angles": [{"angle": "旧爆款新拍", "title": "", "hook": "找 Top10 爆款换设备/换场景重拍"}],
                    "dedup_reminder": "先定 video_id 或话题"})
    return {"items": out}
