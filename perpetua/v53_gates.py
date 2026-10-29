"""v5.3 硬门禁（2026-10-10 三脑会诊结论落地）。

三个门：
1. 标题剧透（D20261030-001 已解除：结果前置可用，保点击优先；本模块仅保留空值与长度检查）
2. 标题语法门（title grammar gate）：畸形动词变形自动打回
3. 报应轮换（payback rotation）：6 类报应，滚动 1-in-5 硬上限，永久执行

所有函数返回 (ok: bool, reason: str|None)。ok=False 表示打回。
"""

import json
import re
import sys
from pathlib import Path

if "/home/hatch/data/perpetua" not in sys.path:
    sys.path.insert(0, "/home/hatch/data/perpetua")
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db

BASE = Path("/home/hatch/data/perpetua")

# ---------------------------------------------------------------------------
# Gate 1: 标题剧透 -- VOID per D20261030-001 (kept for reference only)
# ---------------------------------------------------------------------------
SPOILER_RE = re.compile(
    r"(?i)\b(soak(s|ed|ing)?|spray(s|ed|ing)?|blast(s|ed|ing)?|"
    r"drench(es|ed|ing)?|wet|wash(es|ed|ing)?|hit(s)?|slap(s|ped|ping)?|"
    r"karma|regret(s)?|fail(s|ed|ing)?|ruin(s|ed|ing)?|destroy(s|ed|ing)?|"
    r"zapp(ed|ing)?|electrocute(d|s)?|lock(ed|s|ing)?|trap(s|ped|ping)?|"
    r"splash(es|ed|ing)?|drop(s|ped|ping)?|smash(es|ed|ing)?|owned|"
    r"(scream|fight|strike)(s|ed|ing)?\s+back)\b"
)

# v2 悬念结构：[emoji]Karen [作恶]—Then [反转] [emoji]，且反转不能是剧透词
def check_title_spoiler(title: str):
    """标题剧透检查（D20261030-001：禁剧透门已解除）。
    仅保留空值与长度检查（25-100，阈值不动）；剧透词一律放行。
    放行时 reason 为 spoiler_allowed_D20261030_001。
    """
    if not title or not title.strip():
        return False, "title_empty"
    t = title.strip()
    if not (25 <= len(t) <= 100):
        return False, f"title_length_{len(t)}"
    # SPOILER_RE retained for reference only; NOT enforced (D20261030-001).
    return True, "spoiler_allowed_D20261030_001"


# ---------------------------------------------------------------------------
# Gate 2: 标题语法门
# ---------------------------------------------------------------------------
# 畸形动词：生成器 bug 产出的双重变形（Thied/Complimentaried/64ed/...）
MALFORMED_VERB_RE = re.compile(
    r"(?i)\b(thied|complimentaried|unauthorizeded|hoaed|\d+ed|holded|zoned|"
    r"convertibled|speaked|turboed|ied|doubled|sittinged)\b"
)
# 通用双重变形：小写词干 + ed，且词干本身以常见过去式结尾的变体
DOUBLE_INFLECT_RE = re.compile(
    r"(?i)\b([a-z]{3,})(ieded|eed|deded)\b"
)

def check_title_grammar(title: str):
    """标题语法门。返回 (ok, reason)。"""
    if not title or not title.strip():
        return False, "title_empty"
    t = title.strip()
    m = MALFORMED_VERB_RE.search(t) or DOUBLE_INFLECT_RE.search(t)
    if m:
        return False, f"title_grammar:{m.group(0)}"
    # 被动语态 / 过去时主语结构
    if re.search(r"(?i)\bKaren\s+(was|were|got|had been)\b", t):
        return False, "title_passive_voice"
    return True, None


def check_title(title: str):
    """标题门（剧透已解除 D20261030-001 + 语法）。返回 (ok, reason)。"""
    ok, reason = check_title_spoiler(title)
    if not ok:
        return False, reason
    return check_title_grammar(title)


# ---------------------------------------------------------------------------
# Gate 3: 报应轮换（6 类，滚动 1-in-5）
# ---------------------------------------------------------------------------
PAYBACK_CATEGORIES = {
    "CAT_1_LIQUID_FOAM": [
        "water", "spray", "soak", "foam", "jet", "geyser", "deluge",
        "sprinkler", "hose", "wash",
    ],
    "CAT_2_MECHANICAL_IMPACT": [
        "gate arm", "barrier", "turnstile", "bollard", "conveyor",
        "mechanical arm", "swing", "pinch", "jerk",
    ],
    "CAT_3_ACOUSTIC_PNEUMATIC": [
        "speaker", "siren", "blast", "air gust", "air curtain",
        "feedback", "horn",
    ],
    "CAT_4_CONTAINMENT_LOCKOUT": [
        "lock", "trap", "shutter", "airlock", "barricade", "containment",
    ],
    "CAT_5_POWDER_DISCHARGE": [
        "powder", "receipt avalanche", "coin", "confetti",
    ],
    "CAT_6_SOCIAL_EXPOSURE": [
        "receipt", "footage", "group chat", "license plate", "big screen",
        "wall of shame", "search history", "everyone", "public",
        "announcement", "displayed",
    ],
}

ROTATION_WINDOW = 5  # 滚动窗口：类别在最近 4 条内出现过则打回（即 1-in-5）


def classify_payback(text: str) -> str:
    """按关键词把报应归入 6 类之一。返回类别 id，未命中返回 CAT_2_MECHANICAL_IMPACT。"""
    t = (text or "").lower()
    scores = {}
    for cat, kws in PAYBACK_CATEGORIES.items():
        scores[cat] = sum(1 for kw in kws if kw in t)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "CAT_2_MECHANICAL_IMPACT"


def _recent_categories(n: int = ROTATION_WINDOW - 1):
    """读最近 n 条已发/排队包的报应类别。"""
    cats = []
    # 1. pipeline_queue.json（排队/已发）——D20261011-001 P1 已迁 SQLite
    try:
        items = queue_db.pipeline_load()
        if isinstance(items, dict):
            items = items.get("items", [])
        for it in items:
            if it.get("status") in ("uploaded", "review_passed", "job_submitted",
                                     "ready_to_upload", "waiting"):
                c = it.get("payback_category")
                if not c:
                    c = classify_payback(
                        f"{it.get('title','')} {it.get('prompt','')[:500]}")
                cats.append(c)
                if len(cats) >= n:
                    break
    except Exception:
        pass
    return cats[:n]


def check_payback_rotation(category: str):
    """报应轮换门。返回 (ok, reason)。"""
    recent = _recent_categories()
    if category in recent:
        return False, f"payback_rotation:{category}_in_last_{len(recent)}"
    return True, None


# ---------------------------------------------------------------------------
# 一站式：新选题三门全检
# ---------------------------------------------------------------------------
def check_title_formula(title: str):
    """标题公式自查（WARN-ONLY，未接入硬门禁）。
    公式（criteria.json title_formula）：emoji 开头 + 含 Karen/AI。
    未接入原因：build_suspense_title 规格要求 emoji 禁开头，与公式直接冲突；
    硬接入会把全部生成标题打回。待 parent 裁决 emoji 开头 vs 末尾后再定。
    返回 (ok, warnings)；ok=False 仅表示自查有警告，不代表打回。
    """
    t = (title or "").strip()
    if not t:
        return False, ["title_empty"]
    warnings = []
    if t[0].isascii() and t[0].isalnum():
        warnings.append("formula_no_emoji_opening")
    if "Karen" not in t and "AI" not in t:
        warnings.append("formula_no_karen_ai")
    return (len(warnings) == 0), warnings


def check_v53_package(title: str, prompt: str = "", payback_category: str = None):
    """v5.3 新选题三门全检。返回 (ok, reason, detail)。"""
    ok, reason = check_title(title)
    if not ok:
        return False, reason, {"gate": "title"}
    cat = payback_category or classify_payback(f"{title} {prompt[:800]}")
    ok, reason = check_payback_rotation(cat)
    if not ok:
        return False, reason, {"gate": "payback_rotation", "category": cat}
    return True, None, {"gate": "all_pass", "category": cat}
