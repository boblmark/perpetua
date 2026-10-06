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

FORMAT_LOCK = (
    "Vertical 9:16 short, exactly 10 seconds, 30fps. Raw CCTV / dashcam / "
    "smart-camera aesthetic: high contrast, slightly desaturated daylight, "
    "timestamp HUD overlay in the top corner (e.g. 'CAM 03 - 14:22:07'). "
    "No black bars, no watermark, no cinematic letterbox."
)

KAREN_DESC = (
    "Karen: middle-aged white woman, blonde bob or messy bun, oversized "
    "sunglasses pushed up on her head, pink tracksuit top. Perpetually "
    "outraged: wide eyes, mouth open mid-rant, finger jabbing."
)

AI_CALM = (
    "The AI device stays perfectly calm while Karen escalates — its comedy "
    "comes from cold literal enforcement, never arguing back."
)

AUDIO_RULES = (
    "Audio (retention anchor): second 0 opens with ONE crisp Foley transient "
    "(glass crack, horn blip, sharp gasp) — preferably a mute-drop (sudden "
    "ambient hush) INTO the hit. SFX over music beds: naturalistic Foley + "
    "low CCTV current-hum, mobile-safe dynamic range, no clipping. NEVER a "
    "loud royalty-free upbeat track, NEVER harsh alarm blasts, NEVER silent "
    "for more than 1 second. "
    "On-screen text: max 3 overlays, each 6 words or fewer, ALL CAPS, "
    "yellow/white with black stroke, ALL inside the top-middle third of the "
    "frame (UI safe zone — never right edge or bottom 25%). CCTV timestamp "
    "HUD top-LEFT corner only. Burned-in subtitles for Karen's key rant "
    "line (60%+ watch muted). "
    "Hard cuts only — no slow motion, no fade-to-black, no static text-only "
    "openings. Karen ALWAYS loses; instant karma is the brand."
)

# Karma verb tiers — Ask Studio 2026-10-06: concrete slapstick BEATS abstract
# hyperbole; verb intensity must match the visual payoff magnitude.
KARMA_VERBS_TIER_S = [
    "TRAPPED", "SLAPPED", "SOAKED", "TOWED", "FLOODED",
    "TRIPPED", "LOCKED", "BOOTED", "SPRAYED",
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


def build_viral_prompt(topic, hook, karma_payoff=None, emoji_pair=("🤖", "😂")):
    """Build a complete viral Shorts package (v2: 9-11s, CCTV aesthetic).

    Args:
        topic: the AI device / scenario, e.g. "smart gas pump".
        hook: the 0-2s cold-collision hook, e.g. "Karen slams an expired
            coupon on the scanner mid-rant".
        karma_payoff: the 7-10s physical karma beat (tangible, sudden,
            executed in under 2s). If None, derived from the verb bank.
        emoji_pair: (lead_emoji, tail_emoji) for the title.

    Returns:
        dict with keys: prompt, title, description.

    Raises:
        ValueError: if the generated title fails purity checks
            (non-English chars, or missing Karen/AI).
    """
    topic = topic.strip()
    hook = hook.strip()

    # P0 纯化：topic 只查英文（内部场景参数）；hook 必须英文+含 Karen/AI（防偏题混语言）
    _check_purity(topic, context="topic", require_brand=False)
    _check_purity(hook, context="hook")
    lead, tail = emoji_pair

    verb = random.choice(PHYSICAL_KARMA_VERBS)
    if karma_payoff is None:
        karma_payoff = (
            f"sudden physical consequence in under 2 seconds — the {topic} "
            f"{verb.lower()}s Karen (tangible: spray, lock, trap, soak). "
            f"Karen left defeated on camera"
        )
    karma_payoff = karma_payoff.strip()

    topic_short = topic.replace("smart ", "").replace("AI ", "").strip()

    prompt = (
        f"{FORMAT_LOCK}\n\n"
        f"Cast: {KAREN_DESC} "
        f"AI device: a {topic} — an EVERYDAY automated friction point, not "
        f"a studio prop. Anthropomorphized just enough: glowing status light "
        f"and a small screen face showing deadpan text. {AI_CALM} "
        f"One bystander frozen mid-stare, phone out, selling the "
        f"'caught on camera' realism.\n\n"
        f"0-2s COLD COLLISION HOOK (conflict already in progress, zero "
        f"setup): {hook}. SENSORY hook, not narrative — the swipe decision "
        f"happens in 200-500ms, so frame 1 leads with visual incongruity / "
        f"motion delta (red pulse, LED flash, Karen mid-lunge) before any "
        f"story. Giant ALL-CAPS text overlay in the first second, 6 words "
        f"max, stating the absurdity. Visual jolt in second 1-2 — movement "
        f"in every frame, nothing static. {SAFE_ZONE_RULE}\n\n"
        f"2-6.5s RAPID ESCALATION: Karen pushes the {topic_short} to its "
        f"limit — the exact wrong move, louder, closer to camera, absurd "
        f"demand. The {topic_short} responds with cold literal logic: it "
        f"does not argue, it ENFORCES. Deadpan 0.5s pause before it acts — "
        f"the pause IS the joke.\n\n"
        f"6.5-7.5s CLIMAX — SUDDEN PHYSICAL KARMA (the punchline window, "
        f"highest-leverage second): {karma_payoff}. The consequence MUST "
        f"land inside 6.5-7.5s and be TANGIBLE and SUDDEN — spray, lock, "
        f"trap, soak, tow — never a purely verbal burn. Karen defeated: "
        f"slumped, silent, soaked, or escorted past the camera.\n\n"
        f"7.5-9s LOOP-OUT (max ~2s aftermath, then hard cut): AI chimes a "
        f"reset phrase ('NEXT CUSTOMER, PLEASE.') matching the opening "
        f"audio/frame. Final frame MUST visually rhyme with frame 1 (same "
        f"angle on the {topic_short}, Karen re-entering) — post-generation "
        f"verified by loop_check.py (similarity >= 0.85). No dead air: cut "
        f"the moment the karma lands + 2s.\n\n"
        f"{AUDIO_RULES}"
    )

    # Title: [emoji] tech context + Karen + PHYSICAL karma verb! + [emoji]
    # Front-load tension: scenario clear in first 40-50 chars.
    title = f"{lead} {topic_short.title()} {verb} Karen! {tail} #Shorts"
    if len(title) > 75:
        title = f"{lead} Karen: {verb}! {tail} #Shorts"

    article = "an" if topic[:1].lower() in "aeiou" else "a"
    description = (
        f"{title}\n\n"
        f"Karen vs AI — watch Karen get instant karma! 😂\n"
        f"Caught on cam: Karen picks a fight with {article} {topic} and gets {verb.lower()}.\n"
        f"#Shorts #AICustomerService #Comedy #TechHumor"
    )

    # P0：生成标题同样过纯化校验（防模板漂移）
    _check_purity(title, context="generated_title")

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
