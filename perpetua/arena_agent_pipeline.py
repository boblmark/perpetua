#!/usr/bin/env python3
"""Arena Agent 接入管线：把 arena agent 产出的 xlsx 分镜包解析 → 去重 → 入队送审。

流程：
  1. parse_xlsx()：读 arena_drops/*.xlsx 的 All_18_Storyboards_Veo3 / New_8_Bizarre_Devices
  2. 每条分镜 → build_viral_prompt(topic, hook, karma_payoff) 生成我方 v5.2 prompt
     （自带安全防火墙/视觉节拍/Karma Drop/Karen 清洗，不直接用 agent 的 Veo prompt）
  3. check_formula() 90 天去重（设备撞车/动词复用/钩子撞车）
  4. 通过 → pipeline_queue status=selected，等待 Ask Studio 评审（≥85 硬门不变）
  5. 处理完的 xlsx 移入 arena_archive/

用法：
  python3 arena_agent_pipeline.py --ingest <xlsx路径>
  python3 arena_agent_pipeline.py --ingest-drops   # 处理 drops/ 下全部
  python3 arena_agent_pipeline.py --dry-run <xlsx> # 只解析+去重检查，不入队
"""
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

DATA = "/home/hatch/data"
BASE = os.path.join(DATA, "perpetua", "arena_agent")
DROPS = os.path.join(BASE, "drops")
ARCHIVE = os.path.join(BASE, "archive")
QUEUE_PATH = os.path.join(DATA, "perpetua", "pipeline_queue.json")

sys.path.insert(0, os.path.join(DATA, "perpetua"))
from atomic_json import atomic_write, tolerant_read
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db

STORYBOARD_SHEETS = ["All_18_Storyboards_Veo3", "New_8_Bizarre_Devices"]

# 设备关键词 → 标题 emoji
EMOJI_MAP = [
    (("robotaxi", "car wash", "treadmill", "gym"), ("🚗", "😭")),
    (("bidet", "toilet"), ("🚽", "😱")),
    (("lawn mower", "grass"), ("🌱", "😂")),
    (("recycling", "bin"), ("♻️", "🤣")),
    (("cotton", "candy", "kiosk"), ("🍭", "😱")),
    (("pool", "lifeguard"), ("🏊", "💦")),
    (("airport", "bag", "boarding"), ("✈️", "😂")),
    (("checkout", "cart", "shopping"), ("🛒", "💥")),
    (("hotel", "delivery robot"), ("🏨", "🤣")),
    (("charger", "ev "), ("⚡", "🔥")),
    (("doorbell", "parcel"), ("📦", "😂")),
    (("gate", "bollard"), ("🚧", "💥")),
    (("drive-thru",), ("🍔", "😂")),
    (("parking meter",), ("🅿️", "💸")),
]
DEFAULT_EMOJI = ("🤖", "😂")

# 真实品牌 → 中性代称（进 prompt 前清洗）
BRAND_MAP = {
    "Amex": "premium credit card",
    "American Express": "premium credit card",
    "Louis Vuitton": "designer handbag",
    "iPhone": "smartphone",
    "Tesla": "electric car",
    "Starbucks": "coffee shop",
    "McDonald's": "fast-food joint",
    "Coca-Cola": "soda",
    "Nike": "sneakers",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def emoji_for(device_en):
    dl = device_en.lower()
    for keys, pair in EMOJI_MAP:
        if any(k in dl for k in keys):
            return pair
    return DEFAULT_EMOJI


def clean_brands(text):
    for b, rep in BRAND_MAP.items():
        text = re.sub(r"\b" + re.escape(b) + r"\b", rep, text, flags=re.IGNORECASE)
    return text


def normalize_topic(device_cell):
    """'Autonomous Robotaxi (L5全无人驾驶出租车)' → 'Autonomous Robotaxi'"""
    en = re.split(r"[（(]", device_cell or "")[0].strip()
    return en or (device_cell or "AI device")


def parse_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for sheet in STORYBOARD_SHEETS:
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[1]:
                continue
            out.append({
                "agent_id": row[0],
                "device": row[1],
                "episode_title": row[2],
                "escalation": row[5] or "",
                "trigger": row[6] or "",
                "pause": row[7] or "",
                "karma": row[8] or "",
                "audio": row[9] or "",
                "veo_prompt": row[10] or "",
                "jury_scores": [row[11], row[12], row[13], row[14], row[15]],
                "total_score": row[16],
                "est_apv": row[17],
                "critique": row[18] or "",
                "sheet": sheet,
            })
    # 按 agent_id 去重（18 集表已包含 8 设备表）
    seen, uniq = set(), []
    for sb in out:
        key = (normalize_topic(sb["device"]).lower(), (sb["episode_title"] or "").lower())
        if key not in seen:
            seen.add(key)
            uniq.append(sb)
    return uniq


def build_entry(sb):
    from viral_prompt import build_viral_prompt
    topic = normalize_topic(sb["device"])
    hook = clean_brands(f"{sb['episode_title']}: {sb['escalation']}".strip(": "))
    karma_payoff = clean_brands(sb["karma"])
    emoji_pair = emoji_for(topic)
    pkg = build_viral_prompt(topic, hook, karma_payoff=karma_payoff,
                             emoji_pair=emoji_pair)
    return {
        "topic": topic,
        "hook": hook,
        "title": pkg["title"],
        "description": pkg["description"],
        "prompt": pkg["prompt"],
        "status": "selected",
        "source": "arena_agent",
        "arena_agent_id": sb["agent_id"],
        "arena_score": sb["total_score"],
        "arena_est_apv": sb["est_apv"],
        "arena_critique": (sb["critique"] or "")[:300],
        "arena_episode": sb["episode_title"],
        "created_at": now_iso(),
        "review_attempt": 0,
    }


def ingest(path, dry_run=False):
    # B' 节流（2026-10-10 议会决议 D20261010-003）：独立短剧冻结，
    # arena 分镜不再入 pipeline_queue（Shorts 只走正片 teaser）。
    try:
        import sys as _sys, os as _os
        _pp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)))
        if _pp not in _sys.path:
            _sys.path.insert(0, _pp)
        from bprime_throttle import standalone_frozen
        if standalone_frozen():
            print("B' 冻结：arena ingest 跳过，不再向 pipeline_queue 添加独立短剧分镜")
            return {"added": [], "skipped": [("bprime_frozen", "all", "")]}
    except Exception as e:
        print(f"B' 门读取失败，fail-closed，本次不 ingest: {e}")
        return {"added": [], "skipped": [("bprime_gate_error", "all", "")]}
    from formula_dedup import check_formula
    sbs = parse_xlsx(path)
    print(f"解析 {len(sbs)} 条分镜 ← {os.path.basename(path)}")
    queue = queue_db.pipeline_load()  # D20261011-001 P1: 已迁 SQLite
    items = queue if isinstance(queue, list) else queue.get("items", [])
    # 幂等防重（2026-10-09）：同一文件重复 ingest 时，已在队列的 topic 直接跳过
    from formula_dedup import _normalize_device
    seen_topics = {_normalize_device(it.get("topic", "")) for it in items
                   if isinstance(it, dict)}
    added, skipped = [], []
    for sb in sbs:
        topic = normalize_topic(sb["device"])
        if _normalize_device(topic) in seen_topics:
            skipped.append((topic, "already_in_queue", ""))
            print(f"  SKIP 已在队列: {topic}")
            continue
    for sb in sbs:
        topic = normalize_topic(sb["device"])
        hook = clean_brands(f"{sb['episode_title']}: {sb['escalation']}".strip(": "))
        # 先去重（用 topic+hook，不依赖生成的 prompt）
        is_dup, reason, detail = check_formula(topic, hook)
        if is_dup:
            skipped.append((topic, reason, str(detail)[:80]))
            print(f"  SKIP 去重[{reason}]: {topic}")
            continue
        try:
            entry = build_entry(sb)
        except ValueError as e:
            skipped.append((topic, "title_purity", str(e)[:80]))
            print(f"  SKIP 标题纯度: {topic} ({e})")
            continue
        # 二次去重：用生成的完整 prompt 再查一次（动词/钩子级）
        is_dup2, reason2, detail2 = check_formula(topic, hook, entry["prompt"])
        if is_dup2:
            skipped.append((topic, reason2, str(detail2)[:80]))
            print(f"  SKIP 去重2[{reason2}]: {topic}")
            continue
        if not dry_run:
            items.append(entry)
            seen_topics.add(_normalize_device(topic))
        added.append((topic, entry["arena_score"]))
        print(f"  + 入队: {topic}（arena {entry['arena_score']}分）")
    if not dry_run:
        queue_db.pipeline_save(items)  # D20261011-001 P1: 已迁 SQLite（原子事务）
        # 归档
        os.makedirs(ARCHIVE, exist_ok=True)
        dst = os.path.join(ARCHIVE, os.path.basename(path))
        shutil.move(path, dst)
        print(f"归档 → {dst}")
    print(f"完成：入队 {len(added)}，跳过 {len(skipped)}")
    return added, skipped


def main():
    os.makedirs(DROPS, exist_ok=True)
    os.makedirs(ARCHIVE, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "--ingest-drops":
        files = sorted(f for f in os.listdir(DROPS) if f.endswith(".xlsx"))
        if not files:
            print("drops/ 为空")
            return
        for f in files:
            ingest(os.path.join(DROPS, f))
    elif cmd in ("--ingest", "--dry-run"):
        if not arg:
            print("需要文件路径参数")
            sys.exit(1)
        ingest(arg, dry_run=(cmd == "--dry-run"))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
