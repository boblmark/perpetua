#!/usr/bin/env python3
"""Perpetua 合规：上传前内容政策检查 + AI 生成标识 + 审计追踪

检查项：
1. 违禁词扫描（暴力/仇恨/色情/诈骗关键词）
2. 版权风险提示（标题含知名 IP/品牌名）
3. AI 生成内容标识（YouTube 要求披露）
4. 所有检查记审计日志
"""
import json, os, re
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"
AUDIT_LOG = f"{BASE}/audit/audit.jsonl"

# 违禁词（上传前拦截）
BLOCKED_PATTERNS = [
    r"\b(kill|murder|suicide|bomb|terrorist)\b",
    r"\b(hate\s+\w+|racial slur)\b",
    r"\b(porn|xxx|nude|sex\s+video)\b",
    r"\b(scam|fraud|ponzi|pyramid\s+scheme)\b",
    r"\b(get\s+rich\s+quick|guaranteed\s+profit)\b",
]

# 版权/品牌风险词（警告，不拦截）
BRAND_PATTERNS = [
    r"\b(disney|marvel|netflix|nintendo|pokemon)\b",
    r"\b(coca-?cola|nike|apple\s+iphone|tesla)\b",
    r"\b(taylor\s+swift|beyonce|messi|ronaldo)\b",
]

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def audit(action, tenant_id, detail):
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    entry = {"ts": now_iso(), "action": action,
             "tenant_id": tenant_id, "detail": detail}
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def check_content(title, description="", tenant_id="default"):
    """上传前合规检查，返回 (pass, warnings, blocked_reason)"""
    text = f"{title} {description}".lower()
    # 1. 违禁词 → 拦截
    for pat in BLOCKED_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            reason = f"违禁词拦截: '{m.group()}'"
            audit("compliance_block", tenant_id,
                  {"title": title[:60], "reason": reason})
            return False, [], reason
    # 2. 品牌词 → 警告
    warnings = []
    for pat in BRAND_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            warnings.append(f"品牌/IP 风险词: '{m.group()}'，可能触发版权审查")
    # 3. AI 标识提醒
    warnings.append("AI 生成内容：YouTube Studio 上传时需勾选 'Altered content' 披露")
    audit("compliance_check", tenant_id,
          {"title": title[:60], "pass": True, "warnings": len(warnings)})
    return True, warnings, ""

def ai_disclosure_text():
    """标准 AI 披露文本（放视频描述末尾）"""
    return ("\n\n---\n"
            "🤖 This video was created with AI assistance "
            "(Perpetua by ViralLoop).")

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1]
    if cmd == "check":
        title = sys.argv[2]
        desc = sys.argv[3] if len(sys.argv) > 3 else ""
        tid = sys.argv[4] if len(sys.argv) > 4 else "default"
        ok, warns, reason = check_content(title, desc, tid)
        print(json.dumps({"pass": ok, "warnings": warns,
                          "blocked_reason": reason}, ensure_ascii=False, indent=2))
    elif cmd == "disclosure":
        print(ai_disclosure_text())
