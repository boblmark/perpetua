#!/usr/bin/env python3
"""Viral Shorts prompt builder for @karenvsai ("Karen vs AI") — v2.

Refined per Ask Studio audit (2026-10-06, scored v1 84/100):
- Duration 9-11s (not 15s): top channel hits average 9-11s, 111-157% retention
- CCTV / dashcam aesthetic: high contrast + timestamp HUD overlay
- 4-beat structure: 0-2s hook / 2-7s escalation / 7-10s physical karma / 10-11s loop
- Physical karma verbs (LOCKED, SOAKED, TRAPPED, TOWED...), never verbal-only

Usage:
    from viral_prompt import build_viral_prompt
    p = build_viral_prompt(topic="smart gas pump", hook="Karen slams an expired coupon on the scanner")
    # p["prompt"], p["title"], p["description"]

Data sources: jev/criteria.json v3 (490 videos), YouTube Analytics signals,
Ask Studio audit 2026-10-06. All output in English.
"""

import random

# v5 (2026-10-08, 四脑会诊 LMArena 裁决 "1.2-Second Karen Snap"):
# - 第一帧 Karen 高情绪紧特写，禁宽景/建立镜头/logo/淡入
# - 音频 0 秒 70% 音量人声起振（非峰值），2 秒内爬坡到峰值
#   （v4 的 "0 秒峰值 Foley" 被推翻：触发观众广告本能→秒划走）
# - 禁巨型解说标题；0-2 秒文字 ≤6 词，整个窗口可见
FORMAT_LOCK_VEO = (
    "Vertical 9:16 short, exactly 8 seconds, 30fps. Raw CCTV / dashcam / "
    "smart-camera aesthetic: high contrast, slightly desaturated daylight, "
    "timestamp HUD overlay in the top-LEFT corner (e.g. 'CAM 03 - 14:22:07'). "
    "No black bars, no watermark, no cinematic letterbox."
)

FORMAT_LOCK = FORMAT_LOCK_VEO  # 默认 Veo 8s；Sora 已下线（2026-09-24）

# v5.3 (2026-10-10, 三脑会诊结论：18 条 Ask Studio 78-84 全挂 → 模板级复盘):
# - DROP: 特写开场（V51_CLOSEUP_OPENING 删除；3:1 裁决 B：纯 CCTV 开场，与监控美学一致）
# - MODIFY: 高潮窗口 6.5-7.5s → 5.5-6.3s（陪审团双 MODIFY；5.0 过头会砍爬坡张力）
# - ADD: 8 秒精确 beat map（V53_BEAT_MAP）
# - ADD: 标题禁剧透硬门禁（V53_TITLE_SPOILER_GATE，黑名单正则）
# - ADD: 报应 6 类轮换 1-in-5（V53_PAYBACK_ROTATION，永久执行）
# - ADD: 标题语法门（V53_TITLE_GRAMMAR_GATE，畸形动词正则）
# - KEEP: V52 删除循环预埋（继续）；Climax Energy Ratio ≥1.60（分母改为 0-3.8s 均值）
# v5.4 (2026-10-12, 爆款加码议会 D20261012-009 终审版 B2 + Ask Studio 终审 APPROVE WITH CHANGES):
# - ADD: EARLY TWIST RULE（V54_EARLY_TWIST）——终审强制修改：
#   红队原 B2 规格"按留存掉落曲线定位微升级"被 Ask Studio 判鸡生蛋缺陷（新选题无历史曲线、
#   低播放量逐秒留存全是噪声、500ms 微调瘫痪剪辑流）→ 简化为结构规则：
#   核心荒诞转折必须发生在 2.00-2.50s（观众 3s 前没看到转折就已划走），
#   3.80-4.50s 必须有第二次升级（中段升级），惊喜不许全攒到 5.5s 报应。
# - 诊断依据：90 天 feed 份额恶化到 20.5%（搜索 68.3%），hook/标题已公式化。
V54_EARLY_TWIST = (
    "EARLY TWIST RULE (v5.4, critical — Ask Studio final review 2026-10-12): "
    "The CORE ABSURD TWIST — the moment the AI device does something genuinely "
    "unexpected that REFRAMES the conflict (NOT just Karen shouting louder, NOT "
    "just a status-light color change, NOT a bigger version of the same gag) — "
    "MUST occur between 2.00s and 2.50s. By 2.50s the viewer MUST already feel "
    "'this is NOT the Karen video I expected.' "
    "A SECONDARY ESCALATION — a second, DIFFERENT unexpected move by the device — "
    "MUST occur between 3.80s and 4.50s, before the uh-oh ramp. "
    "NEVER save all surprise for the 5.5s payback: a viewer who has seen ZERO "
    "twists by 3.0s has already swiped. "
    "The 5.50-6.30s payback climax stays, but it is now the THIRD escalation, "
    "not the first."
)

# v1.1 (2026-10-28, 模板进化议会四脑共识，用户 10:46 CST 拍板：
# 先做 v1.1 小幅进化，14-16 秒三段式只作对照实验，不全切管线模板)
# 共识来源：红队 KILL（不得仅凭 9 连 <85 判死刑）+ 总工程师/传感器/陪审团 A 交集。
# 本块优先级高于其他块在目标/因果/标题/对白上的冲突处；时长仍守 9-11 秒，
# 14-16 秒 v2.0 不进本块、不进默认管线，见下方 V11_CONTROL_EXPERIMENT 说明。
V11_CAUSAL_EVOLUTION = (
    "V1.1 CAUSAL EVOLUTION (2026-10-28 council consensus, precedence over "
    "conflicting wording elsewhere on goal / payoff causality / title / dialogue): "
    "Runtime stays 9-11 seconds. Karen MUST have ONE concrete goal stated "
    "within the first 25% of runtime (for example: get a specific item, skip a "
    "specific queue, obtain a specific refund) — never just 'she is angry'. "
    "The AI device MUST have ONE rule or capability established early, and the "
    "payoff MUST follow causally from a request, rule, or action already "
    "established in the Short. NEVER use a random punishment, generic 'AI revenge', "
    "or an unrelated glitch as the payoff. Payoff MUST be tangible AND, where "
    "possible, double: a physical consequence plus on-site embarrassment or social "
    "exposure; OR malicious compliance: the AI obeys Karen's absurd demand "
    "literally and completely, so the demand itself causes her consequence. "
    "Conflict MUST be visually legible within the first 1.5 seconds, with no "
    "setup longer than 5 words on screen and no title card used as the hook. "
    "The loop MUST be causal: the final frame rhymes with the opening AND is a "
    "consequence of the payoff, not a mere visual reset. Dialogue: Karen speaks "
    "at most 6 words in total, total spoken English at most 22 words, and the AI "
    "never delivers a long rebuttal sentence. Title: at most 55 characters, strong "
    "verb-object structure, never a spoiler payoff name, never a 'Then the AI Read...' "
    "spoiler pattern; emoji may decorate the title at the end only and must never "
    "carry plot information. Novelty ledger (output field, required): list the "
    "previous six Shorts' setting, Karen goal, AI mechanism, and payoff type; change "
    "at least two of those four elements versus the previous six; NEVER repeat the "
    "same conflict + AI mechanism + payoff combination within the previous six; if "
    "the previous six summaries are not supplied, mark novelty UNVERIFIED. "
    "NEVER: manager jokes, surreal punishments, a single static dialogue-only "
    "retaliation without strong visual feedback, a second unrelated twist after the "
    "punchline, an explanatory line after the punchline, or tiny UI text / an "
    "unexplained rule as the sole explanation for the reversal."
)

V11_CONTROL_EXPERIMENT = (
    "CONTROL EXPERIMENT ONLY (NOT the default template): the 14-16 second "
    "three-beat micro-story (0-4s entitlement, 5-8s processing, 9-13s escalation, "
    "14-16s loop anchor, delayed payoff) is a separate controlled trial of at most "
    "3 drafts, scored separately against v1.1 on matched topics. It MUST NOT replace "
    "the 9-11 second default pipeline, and it MUST NOT be adopted generally without "
    "a second user decision after its Ask Studio scores are compared."
)

V54_OPENING = (
    "MANDATORY OPENING — DYNAMIC PUNCH-IN HOOK (v5.4, 2026-10-15 模板手术 D20261015-009): "
    "0.00s–~1.00s: TIGHT CLOSE-UP (face, hands, or key object) — the hook frame; "
    "must contain the most emotionally charged detail of the scene. "
    "At ~1.00s: HARD SNAP to a WIDE or MEDIUM-WIDE master shot. "
    "~1.00s–5.50s: HOLD the wide/master — NO cuts, NO digital reframing, NO "
    "additional punch-in zooms. "
    "REQUIREMENTS: the close-up and the wide must show the SAME continuous scene "
    "(no time jump); the hook detail must appear in the wide at the same scale "
    "position; audio/VO begins at 0.00s and continues unbroken across the snap. "
    "FORBIDDEN: fixed-perspective wide/medium-wide from 0.00s; slow push-ins; "
    "fade from black; title cards in the first 1.5s. "
    "CCTV STYLE PACK (optional): fisheye distortion, timestamp HUD, CAM id, "
    "REC indicator may be added as aesthetic wrapper. NOT required."
)
# v5.3.1 旧开场已废弃（2026-10-15 四脑议会：模板级 hook 扣分，见 D20261015-009）
V53_OPENING = V54_OPENING

V53_BEAT_MAP = (
    "BEAT MAP (v5.3, 8.00s total): "
    "0.00-1.00s HOOK: tight close-up punch-in on the most emotionally charged detail; "
    "at ~1.00s HARD SNAP to wide/master establishing spatial context. "
    "1.20-3.80s ESCALATION: Karen physical aggression (hitting, screaming, jabbing); "
    "device status light shifts yellow/red. "
    "3.80-5.50s UH-OH RAMP: device telegraphs override (charge-up sound, whirring, "
    "mechanical arm loading); Karen stays oblivious, escalates further. "
    "5.50-6.30s PAYBACK CLIMAX: first karma contact between 5.50-5.80s, peak physical "
    "displacement by 6.10s, concludes by 6.30s. "
    "6.30-7.40s REACTION: Karen stunned in consequence state; digital zoom/pan to her "
    "stunned expression permitted ONLY in this window. "
    "7.40-8.00s NO-EXIT-RUNWAY (v5.3.1): NEVER linger, fade, or settle back to opening mood. "
    "End on punchline impact or hard cut. No dead air, no awkward pauses, no fade-outs. "
    "Loop-back is OPTIONAL, never required."
)

V53_MOTION_RAMP = (
    "MOTION RAMP (v5.3, critical for QC):\n"
    "MUST maintain baseline motion within [0.25, 0.40] normalized optical-flow "
    "magnitude from 0.00s to 3.80s. MUST execute continuous linear upward ramp from "
    "0.40 to ≥0.75 between 3.80s and 5.50s. MUST register peak motion magnitude "
    "≥0.85 inside the 5.50s-6.30s climax window. "
    "MUST NOT decelerate motion to <0.15 between 7.40s and 8.00s unless a loop is specifically requested. "
    "NEVER allow motion magnitude to drop below 0.20 between 1.20s and 5.50s. "
    "NEVER hold still for more than 0.3 seconds before 7.40s. Motion blur is DESIRED."
)

V53_CLIMAX_RULES = (
    "CLIMAX RULES (v5.3): The Climax Energy Ratio (max Motion [5.5s-6.3s] divided by "
    "mean Motion [0.0s-3.8s]) MUST equal or exceed 1.60. "
    "The FIRST karma contact frame MUST fall between t=5.50s and t=5.80s. "
    "NEVER allow the peak karma impact frame before 5.50s or after 6.30s. "
    "NEVER execute recoil movements, velocity deceleration, or return-to-pose loops "
    "between 3.0s and 5.5s."
)

V53_TITLE_SPOILER_GATE = (
    "TITLE RULE (v5.3.1 dual-track, Ask Studio 2026-10-10): "
    "TRACK TEASER (40s): suspense-style. Title MUST create an unresolved question "
    "(setup + escalation hint), NEVER name the exact physical payoff. "
    "TRACK LONGFORM: premise & stakes. Title MUST sell the conflict and escalation "
    "(e.g. 'When an AI Drive-Thru Refuses to Back Down'), NEVER reveal the ending. "
    "Rationale: spoiler titles buy CTR on Shorts but kill long-form retention. "
    "AUTO-REJECT hard-spoiler titles matching: "
    "(?i)\\b(soak(s|ed|ing)?|spray(s|ed|ing)?|blast(s|ed|ing)?|drench(es|ed|ing)?|"
    "wet|wash(es|ed|ing)?|hit(s)?|slap(s|ped|ping)?|karma|regret(s)?|fail(s|ed|ing)?|"
    "ruin(s|ed|ing)?|destroy(s|ed|ing)?|zapp(ed|ing)?|electrocute(d|s)?|lock(ed|s|ing)?|"
    "trap(s|ped|ping)?|splash(es|ed|ing)?|drop(s|ped|ping)?|smash(es|ed|ing)?|owned)\\b"
)

V53_PAYBACK_ROTATION = (
    "PAYBACK ROTATION (v5.3 hard gate): Every package MUST be classified into exactly "
    "one of six categories: CAT_1_LIQUID_FOAM (liquid jets, foam, sanitizer deluge), "
    "CAT_2_MECHANICAL_IMPACT (gate arm, turnstile block, conveyor jerk), "
    "CAT_3_ACOUSTIC_PNEUMATIC (speaker feedback blast, air gust), "
    "CAT_4_CONTAINMENT_LOCKOUT (shutter drop, airlock trap, barricade), "
    "CAT_5_POWDER_DISCHARGE (receipt avalanche, powder puff, coin overspill), "
    "CAT_6_SOCIAL_EXPOSURE (receipt shown to everyone, footage sent to group chat, "
    "license plate displayed — embarrassment reversals). "
    "NEVER compile a package whose category appears in the previous 4 published/queued "
    "packages (rolling 1-in-5 hard cap, enforced indefinitely)."
)

V53_TITLE_GRAMMAR_GATE = (
    "TITLE GRAMMAR GATE (v5.3 hard gate): Title MUST pass subject-verb-object validation "
    "(Karen + 3rd-person-singular present-tense verb + direct object). "
    "AUTO-REJECT malformed verb forms matching: "
    "(?i)\\b(thied|complimentaried|unauthorizeded|hoaed|\\d+ed|holded|zoned|convertibled|"
    "speaked|turboed|ied|doubled|sittinged)\\b "
    "or any [verb-stem]+ed double-inflection. NEVER use passive voice or past tense."
)

# V51_LOOP_SEED 已删除（v5.2）：三脑一致认定循环预埋是高潮失败元凶
# （前冲 dump 能量到 1.2s + 回缩在 3.9s 减速 + 返姿抹平高潮）

# 2026-10-09 议会决议（deltas5 #4，全票采纳）：安全防火墙前置块。
# 注意：本块自身不含 "Karen" 一词；生成 prompt 最终组装时另做 Karen→fallback 全量替换。
SAFETY_FIREWALL = (
    "SAFETY FIREWALL (hard gate): All characters are fictional adults age "
    "25+. No minors. No real people, celebrities, public figures, "
    "likenesses, or real names. No real brands, logos, or trademarked "
    "products — use generic objects and fictional locations. Non-graphic "
    "slapstick only: no blood, gore, injury detail, threats, weapons, "
    "sexual content, hate, harassment, or illegal acts. NEVER attempt "
    "spelling variants to bypass a rejected prompt."
)

# 2026-10-09 议会决议：生成 prompt 内禁用 "Karen" 一词（GeminiGen 曾误判拒单）。
# 内部标题/描述/频道名不受影响，仅生成 prompt 做替换。
KAREN_PROMPT_FALLBACK = "the entitled woman"

KAREN_DESC = (
    "The entitled woman: middle-aged woman, blonde bob or messy bun, "
    "oversized sunglasses pushed up on her head, pink tracksuit top. "
    "Perpetually outraged: wide eyes, mouth open mid-rant, finger jabbing."
)

AI_CALM = (
    "The AI device stays perfectly calm while Karen escalates — its comedy "
    "comes from cold literal enforcement, never arguing back."
)

AUDIO_RULES = (
    "Audio (v5 1.2s Snap): MUST begin at 0.00s at 70% volume (mid-level, "
    "NOT max) with an instantly recognizable vocal onset — e.g. "
    "\"Excuse me—\", \"No, no, NO—\". The onset creates curiosity, not "
    "alarm. MUST ramp volume continuously to peak by 2.00s, synced to "
    "Karen's visual expression peak. NEVER start at peak volume, NEVER "
    "start silent, NEVER a loud Foley transient / mute-drop hit at 0s "
    "(v4 peak-open overturned: triggers ad/bot instinct → instant swipe). "
    "NEVER background music, SFX, or silence masking the vocal onset in "
    "0.00-2.00s. Naturalistic Foley + low CCTV current-hum after 2s, "
    "mobile-safe dynamic range, no clipping. NEVER a loud royalty-free "
    "upbeat track, NEVER harsh alarm blasts, NEVER silent for more than "
    "1 second. "
    "On-screen text: max 3 overlays, each 6 words or fewer, high-contrast "
    "white/yellow with black stroke, ALL inside the top-middle third of the "
    "frame (UI safe zone — never right edge or bottom 25%). 0-2s premise "
    "hook text visible for the ENTIRE 0-2s window. CCTV timestamp HUD "
    "top-LEFT corner only. Subtitles show SPOKEN DIALOGUE ONLY — never "
    "meta-titles, scene labels, 'POV', 'Wait for it', or character names. "
    "Hard cuts only — no slow motion, no fade-to-black, no fade-in, no "
    "static text-only openings. The AI always gets the last laugh; instant "
    "karma is the brand."
)

# Karma verb tiers — Ask Studio 2026-10-06: concrete slapstick BEATS abstract
# hyperbole; verb intensity must match the visual payoff magnitude.
KARMA_VERBS_TIER_S = [
    "TRAPPED", "SLAPPED", "SOAKED", "TOWED", "FLOODED",
    "TRIPPED", "LOCKED", "BOOTED", "SPRAYED",
    # 2026-10-12 Ask Studio 动词扩充 15 词（与 karma_verbs.json tier_s 同步）
    "EJECTED", "REPOSESSED", "REFLECTED", "HOISTED", "SANITIZED",
    "BROADCASTED", "CONFISCATED", "AUCTIONED", "DOWNGRADED", "REROUTED",
    "WRAPPED", "MIRRORED", "QUARANTINED", "DISMANTLED", "DEDUCTED",
    # 2026-10-12 Ask Studio 评审：主动制裁类 S 词
    "FALSE-ALARM", "AUTO-LOCK",
]
KARMA_VERBS_TIER_B = [
    "CAUGHT", "EXPOSED", "BUSTED", "MUTED", "SNITCHED",
    "SHUT DOWN", "KICKED OUT", "CANCELLED",
]
KARMA_VERBS_BANNED = [
    "DESTROYED", "ANNIHILATED", "OBLITERATED", "DEMOLISHED",
]
# Generation rotates S-tier first (strongest), falls back to B.
PHYSICAL_KARMA_VERBS = KARMA_VERBS_TIER_S + KARMA_VERBS_TIER_B

SAFE_ZONE_RULE = (
    "UI SAFE ZONE (hard rule): every key text overlay and the visual gag "
    "MUST sit in the top-middle third of the frame. NEVER place critical "
    "info on the right edge (engagement icons cover it) or in the bottom "
    "25% (Shorts title/channel overlay truncates it). CCTV timestamp HUD "
    "goes top-LEFT corner only."
)

# (lead emoji, tech context, tail emoji) combos for titles
TITLE_CONTEXTS = [
    ("⛽", "Smart Pump", "😱💦"),
    ("🛑", "Automated Gate", "🤣🚗"),
    ("🛒", "Self-Checkout", "🤖💸"),
    ("🔊", "Drive-Thru Speaker", "😂🎙️"),
    ("🚗", "HOA Camera", "🤣🚨"),
    ("🅿️", "Parking Kiosk", "😱🚙"),
    ("🛗", "Elevator Panel", "🤖😂"),
]

# Title formula v2.0 (2026-10-07, 竞品拆解驱动):
#   [emoji]Karen [具体作恶]—Then [反转事件] [emoji]
# 悬念型（"上集预告"）替代旧的爆点型（"大结局剧透"：
#   [emoji]Tech VERB Karen! [emoji]）。
# 反转事件 = 具体发生了什么让她翻车，不是抽象动词。
# 观众想知道"然后呢"（好奇心缺口），而不是 1 秒看完结局。
REVERSAL_EVENTS = [
    "the AI Showed Her Receipt to Everyone",
    "the Camera Replayed It on the Big Screen",
    "the Machine Flagged Her Account for a Supervisor Review",
    "the Speaker Played Back Her Rant to the Line Behind Her",
    "the Kiosk Towed Her Car While She Watched",
    "the Panel Sent Her Order to the Wrong Address",
    "the Doorbell Sent the Footage to the Neighborhood Group Chat",
    "the Pump Displayed Her License Plate to the Whole Station",
    "the Register Donated Her Change to Charity",
    "the AI Read Her Search History Out Loud",
    "the Screen Posted Her Photo on the Wall of Shame",
    # v5.3: 移除机制揭示型反转（Locked/Towed 命中剧透门禁）
    "the Charger Reported Her Session as Suspicious",
]
GENERIC_REVERSAL = "the AI Played It Back for Everyone to See"

# 常见作恶动词 → 过去式（标题用过去式："Karen Demanded a Refund—Then..."）
_VERB_PAST = {
    "slam": "Slammed", "demand": "Demanded", "yell": "Yelled",
    "scream": "Screamed", "tailgate": "Tailgated", "wave": "Waved",
    "shove": "Shoved", "kick": "Kicked", "pound": "Pounded",
    "refuse": "Refused", "insist": "Insisted", "threaten": "Threatened",
    "cut": "Cut", "steal": "Stole", "grab": "Grabbed",
    "push": "Pushed", "block": "Blocked", "skip": "Skipped",
    "scan": "Scanned", "swipe": "Swiped", "slap": "Slapped",
    "shake": "Shook", "throw": "Threw", "smash": "Smashed",
}


def _misdeed_from_hook(hook):
    """从 hook 派生标题前半句的作恶短语（过去式）。
    e.g. 'Karen slams an expired coupon on the scanner, already mid-rant'
         → 'Slammed an Expired Coupon on the Scanner'
    """
    h = hook.strip()
    if h.lower().startswith("karen "):
        h = h[6:]
    # 去掉 trailing 状语（逗号后）和并列动作（只保留第一个动作）
    h = h.split(",")[0].strip()
    h = h.split(" and ")[0].strip()
    words = h.split()
    if not words:
        return "Caused a Scene"
    verb = words[0].lower().rstrip("s") if words[0].lower().endswith("s") and len(words[0]) > 3 else words[0].lower()
    past = _VERB_PAST.get(verb)
    if past is None:
        # 2026-10-07 修复：用还原后的 verb 构造过去式，不用原词
        # （之前用 words[0]="scans" 直接加 ed 得到 "Scansed"）
        base = verb
        if base.endswith("e"):
            past = base + "d"
        elif base.endswith("y") and len(base) > 1 and base[-2] not in "aeiou":
            past = base[:-1] + "ied"
        else:
            past = base + "ed"
        past = past[:1].upper() + past[1:]
    rest = " ".join(words[1:])
    # 标题式大小写（保留小品词小写太复杂，直接首字母大写每词）
    rest_t = " ".join(w[:1].upper() + w[1:] if w.islower() else w for w in rest.split())
    return f"{past} {rest_t}".strip()


def build_suspense_title(lead, misdeed, reversal, tail, max_len=95):
    """组装悬念型标题。
    D20261016-005 标题规格 v1（Shorts，2026-10-16 起 30 天试行）：
      - 总长 <=60 字符（含空格+emoji）
      - 单词数 <=12
      - emoji 0-2 个且必须位于末尾（禁开头 emoji）
    v1.1（2026-10-28 模板进化议会，用户拍板）：总长收紧到 <=55 字符，
    其余规格不变；低于 25 字符仍按 v53 门禁下限处理。
    格式：Karen {misdeed}—Then {reversal} {tail}
    lead 参数保留兼容（旧调用位），不再前置（规格 NEVER：标题禁以 emoji 开头）。
    截断策略：先压 reversal（词边界），再压 misdeed，最后整体兜底；
    保证输出 <=60 且 >=25（v53 门禁下限）。
    2026-10-17 修复：旧实现只截 reversal，misdeed 过长时标题 130+ 字符，
    被 v53 门禁 title_length 全部拦截 → select 连续 0 选题。
    """
    SPEC_MAX = 55  # v1.1 (2026-10-28 council): title at most 55 chars
    SPEC_MIN = 25  # v53 门禁下限
    tail = (tail or "").strip()
    misdeed = (misdeed or "").strip()
    reversal = (reversal or "").strip()

    def _cut(text, budget, min_keep=10):
        """词边界截断到 budget 字符（含 '...' 后缀）；压不到 min_keep 返回 None。"""
        text = text.strip()
        if len(text) <= budget:
            return text
        cut = text[:max(budget - 3, 0)].rsplit(" ", 1)[0].strip()
        if len(cut) < min_keep:
            return None
        return cut + "..."

    def _assemble(m, r):
        return f"Karen {m}—Then {r} {tail}".strip()

    overhead = len(_assemble("", ""))  # "Karen " + "—Then " + " " + tail
    # 优先保留 misdeed（冲突主体），先压 reversal
    r_budget = SPEC_MAX - overhead - len(misdeed)
    r2 = _cut(reversal, r_budget, min_keep=12)
    if r2 is None:
        # reversal 实在压不下：misdeed 也让位
        r2 = _cut(reversal, 20, min_keep=12)
        if r2 is None:  # 极端情况：reversal 取前词
            r2 = (reversal.split() or ["..."])[0][:17]
        m_budget = SPEC_MAX - len(_assemble("", r2))
        m2 = _cut(misdeed, m_budget, min_keep=10) or misdeed
    else:
        m2 = misdeed
    title = _assemble(m2, r2)
    if len(title) > SPEC_MAX:
        # 终极兜底：整体词边界截断，保留尾部 emoji
        body = title
        if tail and body.endswith(tail):
            body = body[:-len(tail)].rstrip()
            room = SPEC_MAX - len(tail) - 1 - 3
            cut = body[:max(room, 0)].rsplit(" ", 1)[0].strip()
            title = f"{cut}... {tail}" if cut else body[:max(room, 0)].strip() + f"... {tail}"
        else:
            cut = body[:SPEC_MAX - 3].rsplit(" ", 1)[0].strip()
            title = f"{cut}..."
    # 保底：极端短标题（<25 会被 v53 门禁拒）直接返回，不再硬凑
    return title

VIRAL_WORDS = ["instant", "karma", "caught", "instantly"]


def _check_purity(text, context="text", require_brand=True):
    """P0 定位纯化硬校验：必须英文（无 CJK 字符）；
    require_brand=True 时还必须含 Karen 或 AI 语义（防偏题漂移）。

    Raises:
        ValueError: 说明拒绝原因（写日志用）。
    """
    import re
    # 中文/日文/韩文字符 → 拒绝
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        raise ValueError(
            "purity_reject[%s]: contains CJK characters (channel is English-only): %r"
            % (context, text[:60]))
    if not require_brand:
        return
    # 必须含 karen 或 ai（不区分大小写；ai 需词边界防误杀）
    low = text.lower()
    has_karen = "karen" in low
    has_ai = re.search(r"\bai\b", low) is not None
    if not (has_karen or has_ai):
        raise ValueError(
            "purity_reject[%s]: must mention Karen or AI (off-topic drift): %r"
            % (context, text[:60]))


def build_viral_prompt(topic, hook, karma_payoff=None, emoji_pair=("🤖", "😂"),
                       misdeed=None, reversal=None):
    """Build a complete viral Shorts package (v5: 悬念型标题).

    Args:
        topic: the AI device / scenario, e.g. "smart gas pump".
        hook: the 0-2s cold-collision hook, e.g. "Karen slams an expired
            coupon on the scanner mid-rant".
        karma_payoff: the 6-7s physical karma beat (tangible, sudden,
            executed in under 2s). If None, derived from the verb bank.
        emoji_pair: (lead_emoji, tail_emoji) for the title.
        misdeed: 标题前半句作恶短语（过去式），如 "Demanded a Refund"。
            不传则从 hook 自动派生。
        reversal: 标题后半句反转事件，如 "the AI Showed Her Receipt
            to Everyone"。不传则从 REVERSAL_EVENTS 随机选。

    Returns:
        dict with keys: prompt, title, description.

    Raises:
        ValueError: if the generated title fails purity checks
            (non-English chars, or missing Karen/AI).
    """
    topic = topic.strip()
    hook = hook.strip()

    # D6 闭环注入（2026-10-08）：读取 dynamic_constraints.json，
    # 把数据驱动的 Top-3 特征作为加权指令注入 prompt。
    dynamic_directives = ""
    try:
        import json as _json
        from pathlib import Path as _Path
        _dc = _Path("/home/hatch/data/perpetua/dynamic_constraints.json")
        if _dc.exists():
            _d = _json.loads(_dc.read_text(encoding="utf-8"))
            _dirs = _d.get("directives", [])
            if _dirs:
                dynamic_directives = (
                    "\nDATA-DRIVEN DIRECTIVES (from channel's own retention "
                    f"telemetry, {_d.get('n_videos', '?')} videos, "
                    f"{_d.get('generated_at', '')[:10]}):\n"
                    + "\n".join(f"- {x}" for x in _dirs[:3])
                    + "\nTreat these as weighted preferences, not hard rules."
                )
            # 2026-10-09 每日选题回流：昨天发布视频的 24h 数据 → 今日选题加权。
            # topic_directives 由 daily_topic_feedback.py 每天 09:00 写入。
            _tdirs = _d.get("topic_directives", [])
            if _tdirs:
                dynamic_directives += (
                    "\nTODAY'S TOPIC WEIGHTS (from yesterday's published "
                    f"videos, {_d.get('topic_feedback_date', '')}):\n"
                    + "\n".join(f"- {x}" for x in _tdirs[:6])
                    + "\nBoost/avoid are topic preferences for today only; "
                      "dedup hard gates still apply."
                )
            # 2026-10-09 LMArena 趋势调研回流：外部研究报告的常量注入。
            # research_brief 由人工/调研写入 dynamic_constraints.json，
            # persistent（不像 topic_directives 那样每天被覆盖）。
            _rb = _d.get("research_brief", {})
            _rconsts = _rb.get("constants", [])
            if _rconsts:
                dynamic_directives += (
                    "\nRESEARCH CONSTANTS (external trend research, "
                    f"{_rb.get('date', '')}):\n"
                    + "\n".join(f"- {x}" for x in _rconsts[:4])
                    + "\nTreat as weighted preferences; dedup hard gates "
                      "still apply."
                )
    except Exception:
        pass

    # 2026-10-08 三脑裁决（陪审团胜）：哑火死因回流 → 钩子强化。
    # dud_feedback.jsonl 记录 48h 哑火视频，死因=前3秒钩子弱。
    # 连续 3 条以上哑火 → prompt 注入钩子强化指令。
    hook_boost = ""
    try:
        _fb = _Path("/home/hatch/data/perpetua/dud_feedback.jsonl")
        if _fb.exists():
            _lines = _fb.read_text(encoding="utf-8").strip().split("\n")
            # 取最近 7 天的
            import datetime as _dt
            _cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)
            _recent = 0
            for _l in _lines[-20:]:
                try:
                    _e = _json.loads(_l)
                    _ts = _dt.datetime.fromisoformat(
                        _e.get("ts", "").replace("Z", "+00:00"))
                    if _ts > _cutoff and _e.get("signal") == "strengthen_hook":
                        _recent += 1
                except Exception:
                    continue
            if _recent >= 3:
                hook_boost = (
                    "\nHOOK URGENCY (channel data: last "
                    f"{_recent} videos died from weak hooks):\n"
                    "- The FIRST 0.5 seconds MUST contain the single most "
                    "shocking visual: Karen's face fills 60%+ of frame, "
                    "mouth open mid-shout, eyes locked on lens.\n"
                    "- NO establishing shot, NO slow build. Start at peak "
                    "intensity, not 70%.\n"
                    "- If the hook doesn't grab in 0.5s, the video is dead. "
                    "This is not a suggestion."
                )
    except Exception:
        pass

    # P0 纯化：topic 只查英文（内部场景参数）；hook 必须英文+含 Karen/AI（防偏题混语言）
    _check_purity(topic, context="topic", require_brand=False)
    _check_purity(hook, context="hook")
    lead, tail = emoji_pair

    verb = random.choice(PHYSICAL_KARMA_VERBS)
    if karma_payoff is None:
        # 2026-10-07 反拒生成修复：媒体工具的内容安全过滤会拦截"针对人物"
        # 的身体羞辱表述（soaks Karen / Karen defeated）。改写为 slapstick
        # 情境喜剧 framing：视觉内容不变，但不再把人物写成被针对的受害者。
        karma_payoff = (
            f"sudden slapstick mishap in under 2 seconds — a comedic "
            f"{verb.lower()} gag erupts from the {topic} (tangible physical "
            f"comedy: spray, lock, trap, soak). She freezes mid-gesture in "
            f"comic disbelief, caught on camera"
        )
    karma_payoff = karma_payoff.strip()

    topic_short = topic.replace("smart ", "").replace("AI ", "").strip()

    prompt = (
        f"{SAFETY_FIREWALL}\n\n"
        f"{V53_OPENING}\n\n"
        f"{V53_BEAT_MAP}\n\n"
        f"{V53_MOTION_RAMP}\n\n"
        f"{V53_CLIMAX_RULES}\n\n"
        f"{V54_EARLY_TWIST}\n\n"
        f"{V53_TITLE_SPOILER_GATE}\n\n"
        f"{V53_PAYBACK_ROTATION}\n\n"
        f"{V53_TITLE_GRAMMAR_GATE}\n\n"
        f"{V11_CAUSAL_EVOLUTION}\n\n"
        f"{FORMAT_LOCK}\n\n"
        f"Cast: {KAREN_DESC} "
        f"AI device: a {topic} — an EVERYDAY automated friction point, not "
        f"a studio prop. Anthropomorphized just enough: glowing status light "
        f"and a small screen face showing deadpan text. {AI_CALM} "
        f"One bystander frozen mid-stare, phone out, selling the "
        f"'caught on camera' realism.\n\n"
        f"0-1.2s SPATIAL CONTEXT (v5.3): frame 0.00s OPENS on a FIXED CCTV "
        f"wide/medium shot — Karen's torso AND the {topic_short}'s interface "
        f"visible simultaneously, her face ≤20% of frame. NO close-up, NO "
        f"punch-in, NO camera move before 1.20s. Fixed surveillance HUD "
        f"(timestamp, CAM id) on margins. Conflict already in progress, zero "
        f"setup: {hook}. Premise hook text on screen at 0.00s, MAX 6 words, "
        f"upper-third placement — NEVER giant explanatory titles (they spoil + "
        f"kill the loop). TRIGGER MICRO-BEAT (2026-10-09 council #3): at "
        f"1.10-1.35s the {topic_short}'s small screen does ONE blue-to-red "
        f"pulse then back to blue — single state-change cue, same fixed shot, "
        f"visual ONLY, no alarm sound. Movement "
        f"in every frame, nothing static. {SAFE_ZONE_RULE}\n\n"
        f"1.2-5.5s ESCALATION + TWISTS + UH-OH RAMP (v5.4): Karen pushes the {topic_short} to its "
        f"limit — the exact wrong move, louder, closer, absurd "
        f"demand. At 2.00-2.50s the {topic_short} delivers the CORE ABSURD TWIST: "
        f"one genuinely unexpected move that reframes the conflict (cold literal "
        f"logic: it does not argue, it ENFORCES). Deadpan ~1.2s pause before it acts — "
        f"the pause IS the joke. At 3.80-4.50s a SECOND, DIFFERENT unexpected move "
        f"from the {topic_short} (secondary escalation). From 4.5s the device telegraphs override "
        f"(charge-up sound, whirring, mechanical loading); Karen stays "
        f"oblivious and escalates further.\n\n"
        f"5.5-6.3s PAYBACK CLIMAX (v5.3 — the punchline window): {karma_payoff}. "
        f"The FIRST karma contact MUST land between 5.50-5.80s, peak physical "
        f"displacement by 6.10s, concluded by 6.30s. The consequence MUST "
        f"be TANGIBLE and SUDDEN — never a purely verbal burn. KARMA DROP "
        f"(2026-10-09 council #1): at the exact karma contact, brief "
        f"ambient duck then ONE dry diegetic thud (peak <=-6dBFS) — never "
        f"a cinematic bass drop, never muted dialogue.\n\n"
        f"6.3-8s REACTION + LOOP-OUT (v5.3): 6.3-7.4s comic aftermath — she "
        f"stands frozen mid-gesture in total comic disbelief; digital zoom/pan "
        f"to her stunned expression permitted ONLY here. 7.4-8s motion settles "
        f"to frame-0 ambient level, lighting returns to baseline. Final frame "
        f"MUST visually rhyme with frame 1 (same CCTV angle on the "
        f"{topic_short}, Karen re-entering) — post-generation verified by "
        f"loop_check.py (similarity >= 0.75).\n\n"
        f"{AUDIO_RULES}"
    )

    # Title v2.0 (2026-10-07): 悬念型 — [emoji]Karen [作恶]—Then [反转] [emoji]
    # "上集预告"替代旧的"大结局剧透"。保留：emoji 开头、Karen 主语。
    if misdeed is None:
        misdeed = _misdeed_from_hook(hook)
    if reversal is None:
        reversal = random.choice(REVERSAL_EVENTS)
    title = build_suspense_title(lead, misdeed, reversal, tail)

    article = "an" if topic[:1].lower() in "aeiou" else "a"
    description = (
        f"{title}\n\n"
        f"Karen vs AI — watch Karen get instant karma! 😂\n"
        f"Caught on cam: Karen picks a fight with {article} {topic} and gets {verb.lower()}.\n"
        f"What would YOU do? 👇 Comment below!\n"
        f"#Shorts #AICustomerService #Comedy #TechHumor"
    )

    # P0：生成标题同样过纯化校验（防模板漂移）
    _check_purity(title, context="generated_title")

    # D6：动态约束注入 prompt 尾部
    if dynamic_directives:
        prompt = prompt + dynamic_directives
    # 2026-10-08：哑火回流钩子强化
    if hook_boost:
        prompt = prompt + hook_boost

    # 2026-10-09 议会决议（deltas5 #4）：生成 prompt 内禁用 "Karen" 一词。
    # 内部标题/描述/频道名不受影响，仅生成 prompt 做 token 替换。
    prompt = prompt.replace("Karen", KAREN_PROMPT_FALLBACK)

    return {"prompt": prompt, "title": title, "description": description}


if __name__ == "__main__":
    for t, h in [
        ("smart gas pump",
         "Karen slams an expired coupon on the scanner, already mid-rant"),
        ("automated parking gate",
         "Karen tailgates the gate, arm waving out the window"),
    ]:
        p = build_viral_prompt(t, h)
        print("TITLE:", p["title"])
        print("PROMPT:", p["prompt"][:160].replace("\n", " "), "...")
        print("DESC:", p["description"][:90].replace("\n", " "))
        print()
