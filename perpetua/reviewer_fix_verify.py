#!/usr/bin/env python3
"""reviewer 修复文本逐字粘贴核验（议会 D20261017-00X KILL#4/#7 修订）。

KILL#4：逐字粘贴核验必须是机器可审计的——精确字符串比对，
    由执行 teaser 的生产 agent 在标记 ready 前运行，差异非零则 blocked，
    结果（含时间戳）写进 item 字段。
KILL#7 carve-out："永不改写"开例外——仅允许平台硬性限制
    （标题字符截断、非法字符）的最小必要调整，调整内容必须 log，
    语义不得变。

用法：
    from reviewer_fix_verify import verify_verbatim, compliance_trim
    ok, report = verify_verbatim(
        {"title": t, "description": d, "prompt": p},
        {"title": ft, "description": fd, "prompt": fp})
    # ok=False → blocked，不许标记 ready
"""
import json
import os
from datetime import datetime, timezone

DATA = "/home/hatch/data/perpetua"
VERIFY_LOG = os.path.join(DATA, "verbatim_verify.log.jsonl")

# YouTube Shorts 标题硬性上限（平台限制，carve-out 允许的唯一调整类型）
TITLE_MAX_LEN = 100


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _log(entry):
    try:
        with open(VERIFY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def compliance_trim(text, max_len=TITLE_MAX_LEN, field="title"):
    """KILL#7 carve-out：仅因平台硬性限制做的最小必要调整。

    允许：超长截断（max_len）、移除控制字符/非法字符。
    不允许：任何语义改写。返回 (adjusted_text, adjustments: list)。
    adjustments 为空表示无需调整（可直接逐字使用）。
    """
    text = str(text or "")
    adjustments = []
    # 非法控制字符
    cleaned = "".join(c for c in text if c == "\n" or not (ord(c) < 32))
    if cleaned != text:
        adjustments.append({
            "type": "illegal_char_removed",
            "field": field,
            "removed": repr(text[len(cleaned):])[:80],
        })
        text = cleaned
    # 超长截断
    if len(text) > max_len:
        adjustments.append({
            "type": "length_truncate",
            "field": field,
            "from_len": len(text),
            "to_len": max_len,
        })
        text = text[:max_len]
    return text, adjustments


def verify_verbatim(item_fields, fix_fields, topic="", allow_compliance_trim=True):
    """精确字符串比对核验。

    item_fields: {"title","description","prompt"}（teaser 实际采用值）
    fix_fields:  {"title","description","prompt"}（reviewer 原文）
    空 fix 值视为"无此项要求"，跳过不判。
    返回 (ok, report)。report 含每项 diff 详情；结果自动记 log。
    """
    report = {"topic": topic, "at": _now_iso(), "fields": {}, "ok": True,
              "compliance_adjustments": []}
    for key in ("title", "description", "prompt"):
        fix = fix_fields.get(key) if isinstance(fix_fields, dict) else None
        if not fix:
            report["fields"][key] = {"checked": False, "reason": "no_fix_text"}
            continue
        actual = str((item_fields or {}).get(key) or "")
        fix_s = str(fix)
        if actual == fix_s:
            report["fields"][key] = {"checked": True, "match": True}
            continue
        # KILL#7 carve-out：允许平台硬性限制的最小调整
        if allow_compliance_trim and key == "title":
            adjusted, adj = compliance_trim(fix_s)
            if actual == adjusted and adj:
                report["fields"][key] = {
                    "checked": True, "match": True,
                    "via": "compliance_trim", "adjustments": adj}
                report["compliance_adjustments"].extend(adj)
                continue
        report["fields"][key] = {
            "checked": True, "match": False,
            "expected": fix_s[:200], "actual": actual[:200],
            "expected_len": len(fix_s), "actual_len": len(actual)}
        report["ok"] = False
    _log(report)
    return report["ok"], report


def verify_item_against_reviewer_fixes(item, fixes):
    """便捷入口：item 为 pipeline_queue 条目，fixes 为 reviewer_fixes.json
    中该 topic 的 {"title","desc","prompt"}。返回 (ok, report)。"""
    item_fields = {
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "prompt": item.get("prompt", ""),
    }
    fix_fields = {
        "title": (fixes or {}).get("title", ""),
        "description": (fixes or {}).get("desc", "") or (fixes or {}).get("description", ""),
        "prompt": (fixes or {}).get("prompt", ""),
    }
    return verify_verbatim(item_fields, fix_fields,
                           topic=str(item.get("topic", "")))
