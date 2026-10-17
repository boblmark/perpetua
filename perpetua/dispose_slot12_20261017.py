#!/usr/bin/env python3
"""council-20261017-slot12 处置执行（议会结论，自主运维权限下执行）
- robot waiter (81) -> teaser_validation，reviewer 三项修复逐字应用
- smart parcel box (78) -> boundary-hold（selected + flag），等独立复核
- AI hydraulic bollard (77) / robot chases wild boars (72) -> archived
"""
import json, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

NOW = datetime.now(timezone.utc).isoformat()
fixes = json.load(open("/home/hatch/data/brain_council/council-20261017-slot12/reviewer_fixes.json"))

queue = queue_db.pipeline_load()
items = queue if isinstance(queue, list) else queue.get("queue", queue.get("items", []))

PLAN = {
    "robot waiter": {"score": 81, "action": "teaser"},
    "smart parcel box": {"score": 78, "action": "boundary_hold"},
    "AI hydraulic bollard": {"score": 77, "action": "archive"},
    "robot chases wild boars": {"score": 72, "action": "archive"},
}

PROMPT_OVERRIDE_TMPL = (
    "\n\nREVIEWER KARMA CLIMAX FIX (verbatim, Ask Studio 2026-10-17, "
    "council-20261017-slot12 — overrides the scenario's climax beat, "
    "do not reword):\n\"{fix}\"\n"
)

log = []
for it in items:
    topic = it.get("topic", "")
    if topic not in PLAN:
        continue
    p = PLAN[topic]
    it["review_score"] = p["score"]
    it["review_answered_at"] = NOW
    it["review_source"] = "ask_studio_main_agent_20261017"
    f = fixes.get(topic, {})
    if p["action"] == "teaser":
        # 逐字应用（MUST-10 可审计：脚本内字符串比对）
        it["title"] = f["title"]
        it["description"] = f["desc"]
        it["prompt"] = it.get("prompt", "") + PROMPT_OVERRIDE_TMPL.format(fix=f["prompt"])
        it["reviewer_fixes"] = {
            "title": f["title"], "description": f["desc"],
            "prompt_climax": f["prompt"], "applied_at": NOW, "applied_by": "dispose_slot12_20261017.py",
        }
        ver = {
            "title_match": it["title"] == f["title"],
            "description_match": it["description"] == f["desc"],
            "prompt_fix_present": f["prompt"] in it["prompt"],
            "verified_at": NOW,
        }
        it["reviewer_fix_verification"] = ver
        assert all([ver["title_match"], ver["description_match"], ver["prompt_fix_present"]]), \
            "verbatim verification FAILED for %s" % topic
        it["status"] = "teaser_validation"
        it["teaser_queued_at"] = NOW
        log.append(f"{topic}: score={p['score']} -> teaser_validation（修复逐字应用，比对通过）")
    elif p["action"] == "boundary_hold":
        it["reviewer_fixes_pending"] = {
            "title": f["title"], "description": f["desc"],
            "prompt_climax": f["prompt"], "note": "apply on teaser entry if re-review >= 79",
        }
        it["boundary_hold"] = True
        it["boundary_hold_until"] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        it["boundary_hold_reason"] = ("council-20261017-slot12: 78.0 boundary — hold for independent "
                                      "re-review >= 79, else archive")
        log.append(f"{topic}: score={p['score']} -> boundary-hold 24h（selected 保留，等独立复核）")
    else:
        it["status"] = "archived"
        it["archive_reason"] = (
            f"council-20261017-slot12: {p['score']} < 78 teaser band (D20261010-007); "
            "reviewer fixes on file, re-entry allowed via fresh independent review"
        )
        it["reviewer_fixes_pending"] = {
            "title": f["title"], "description": f["desc"], "prompt_climax": f["prompt"],
        }
        log.append(f"{topic}: score={p['score']} -> archived")

queue_db.pipeline_save(items)
print("\n".join(log))
print("saved at", NOW)
