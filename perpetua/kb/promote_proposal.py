#!/usr/bin/env python3
"""KB 提案审核脚本（staging → 正式知识库，全人工）。
用法：
  python3 promote_proposal.py list
  python3 promote_proposal.py approve <proposal_id> [--target deep_dive_findings]
  python3 promote_proposal.py reject <proposal_id> --reason "..."
审核策略：全人工（2026-10-09 用户决策：先跑两周看提案质量，再定是否放自动）。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

KB_DIR = Path("/home/hatch/data/perpetua/kb")
STAGING = KB_DIR / "staging"
PROPOSALS = STAGING / "proposals.jsonl"
FINDINGS = KB_DIR / "deep_dive_findings.json"


def _load() -> list:
    recs = []
    if PROPOSALS.exists():
        for line in PROPOSALS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    return recs


def _save(recs: list) -> None:
    tmp = PROPOSALS.with_suffix(".tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                   encoding="utf-8")
    tmp.replace(PROPOSALS)


def cmd_list() -> None:
    recs = _load()
    pend = [r for r in recs if r.get("status") == "pending"]
    rej = sum(1 for r in recs if r.get("status") == "rejected")
    appr = sum(1 for r in recs if r.get("status") == "approved")
    print(f"pending: {len(pend)} / approved: {appr} / rejected: {rej} / total: {len(recs)}")
    for r in pend:
        print(f"- {r['proposal_id']} [{r.get('device') or 'general'}] by {r.get('proposer')}")
        print(f"  Q: {r['problem'][:100]}")
        print(f"  A: {r['solution'][:100]}")


def cmd_approve(pid: str, target: str = "deep_dive_findings") -> None:
    recs = _load()
    hit = next((r for r in recs if r.get("proposal_id") == pid), None)
    if not hit:
        print(f"[not found] {pid}")
        sys.exit(1)
    if hit.get("status") != "pending":
        print(f"[skip] {pid} 状态={hit.get('status')}，不重复处理")
        sys.exit(1)
    if target == "deep_dive_findings":
        d = json.loads(FINDINGS.read_text(encoding="utf-8"))
        d["findings"].append({
            "device": hit.get("device") or "general",
            "issue": hit["problem"],
            "recommendation": hit["solution"],
            "source_agent": hit.get("proposer", "mcp:external"),
            "source_file": f"staging/{pid}",
            "approved_at": datetime.now(timezone.utc).isoformat(),
        })
        tmp = FINDINGS.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(FINDINGS)
    else:
        print(f"[error] 未知 target: {target}")
        sys.exit(1)
    hit["status"] = "approved"
    hit["approved_at"] = datetime.now(timezone.utc).isoformat()
    _save(recs)
    print(f"[ok] {pid} → {target}")


def cmd_reject(pid: str, reason: str) -> None:
    recs = _load()
    hit = next((r for r in recs if r.get("proposal_id") == pid), None)
    if not hit:
        print(f"[not found] {pid}")
        sys.exit(1)
    if hit.get("status") != "pending":
        print(f"[skip] {pid} 状态={hit.get('status')}，不重复处理")
        sys.exit(1)
    hit["status"] = "rejected"
    hit["reject_reason"] = reason
    _save(recs)
    print(f"[ok] {pid} rejected: {reason}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "approve" and len(sys.argv) >= 3:
        target = "deep_dive_findings"
        if "--target" in sys.argv:
            target = sys.argv[sys.argv.index("--target") + 1]
        cmd_approve(sys.argv[2], target)
    elif cmd == "reject" and len(sys.argv) >= 3:
        if "--reason" not in sys.argv:
            print("[error] reject 需要 --reason")
            sys.exit(1)
        cmd_reject(sys.argv[2], sys.argv[sys.argv.index("--reason") + 1])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
