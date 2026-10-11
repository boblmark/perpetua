#!/usr/bin/env python3
"""
deep_dive_extractor.py — deep_dive 报告结构化抽取（Commit 3）

解析 deep_dive_*.md → kb/deep_dive_findings.json
（device/issue/recommendation 结构化，给 B1 第一个代码读者）。

用法：
    python3 deep_dive_extractor.py [--all] [md_path ...]
    --all：处理全部 deep_dive_*.md
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PERPETUA = Path("/home/hatch/data/perpetua")
KB_DIR = PERPETUA / "kb"
FINDINGS_PATH = KB_DIR / "deep_dive_findings.json"

# 根因标题：### R1 — xxx
ROOT_CAUSE_RE = re.compile(r"^###\s+(R\d+)\s*[—–-]\s*(.+)$", re.M)
# 建议小节：## 五、流程优化建议 下的条目
SECTION_RE = re.compile(r"^##\s+(.+)$", re.M)

# 设备关键词（从标题/内容中识别）
DEVICE_KEYWORDS = {
    "smart meter": "smart_meter", "parking meter": "parking_meter",
    "self-driving": "self_driving", "doorbell": "doorbell",
    "self-checkout": "self_checkout", "gas pump": "gas_pump",
    "vending": "vending_machine", "drive-thru": "drive_thru",
    "robot vacuum": "robot_vacuum", "robovac": "robot_vacuum",
}


def _detect_device(text: str) -> str:
    low = text.lower()
    for kw, dev in DEVICE_KEYWORDS.items():
        if kw in low:
            return dev
    return "general"


def _extract_section(md: str, start_marker: str, end_marker: str | None) -> str:
    """抽取两个 ## 标题之间的内容"""
    lines = md.split("\n")
    in_sec, buf = False, []
    for ln in lines:
        if ln.startswith("## "):
            if in_sec:
                break
            if start_marker in ln:
                in_sec = True
            continue
        if in_sec:
            buf.append(ln)
    return "\n".join(buf)


def parse_file(md_path: str) -> list[dict]:
    """解析单个 deep_dive md，返回 findings 列表"""
    text = Path(md_path).read_text(encoding="utf-8")
    date_m = re.search(r"deep_dive_(\d{4}[-_]\d{2}[-_]\d{2}|\d{8})", md_path)
    date_str = date_m.group(1) if date_m else "unknown"

    findings = []

    # 1. 根因 R1-R7
    root_sec = _extract_section(text, "根因排序", None)
    for m in ROOT_CAUSE_RE.finditer(root_sec or text):
        rid, title = m.group(1), m.group(2).strip()
        # 取该 R 小节的前 500 字作 issue 摘要
        start = m.end()
        nxt = ROOT_CAUSE_RE.search(root_sec or text, start)
        end = nxt.start() if nxt else start + 800
        body = (root_sec or text)[start:end].strip()[:500]
        # 找推荐（同一小节内的"建议/应该/需要"句）
        rec_m = re.search(r"(建议|应该|需要|必须)([^。\n]{10,120})", body)
        recommendation = rec_m.group(0).strip() if rec_m else ""
        findings.append({
            "device": _detect_device(title + " " + body),
            "issue": f"{rid} {title}: {body[:200]}",
            "recommendation": recommendation,
            "source_file": Path(md_path).name,
            "source_date": date_str,
        })

    # 2. 流程优化建议（小改/大改条目）
    opt_sec = _extract_section(text, "流程优化建议", None)
    if opt_sec:
        for line in opt_sec.split("\n"):
            line = line.strip()
            m = re.match(r"^\d+\.\s+(.{20,200})", line)
            if m:
                item = m.group(1).strip()
                findings.append({
                    "device": _detect_device(item),
                    "issue": f"流程优化: {item[:150]}",
                    "recommendation": item[:300],
                    "source_file": Path(md_path).name,
                    "source_date": date_str,
                })

    return findings


def run(md_paths: list[str] | None = None) -> dict:
    if md_paths is None:
        # 默认处理最新的一个
        files = sorted(PERPETUA.glob("deep_dive_*.md"))
        md_paths = [str(files[-1])] if files else []

    all_findings = []
    for p in md_paths:
        try:
            all_findings.extend(parse_file(p))
        except Exception as e:
            print(f"WARN 解析失败 {p}: {e}", file=sys.stderr)

    # 去重（按 issue 前 60 字）
    seen, deduped = set(), []
    for f in all_findings:
        k = f["issue"][:60]
        if k not in seen:
            seen.add(k)
            deduped.append(f)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_files": md_paths,
        "findings": deduped,
    }
    KB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FINDINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(FINDINGS_PATH)
    return {"n_findings": len(deduped), "n_files": len(md_paths),
            "out": str(FINDINGS_PATH)}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--all":
        files = sorted(str(p) for p in PERPETUA.glob("deep_dive_*.md"))
        result = run(files)
    elif args:
        result = run(args)
    else:
        result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
