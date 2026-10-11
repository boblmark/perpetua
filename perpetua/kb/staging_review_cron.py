#!/usr/bin/env python3
"""KB staging 审核提醒（每天 09:30 cron）：扫 pending 提案，有新增则写 inbox 通知提醒人工审核。
只提醒新增（seen.json 去重），无新增静默退出。
审核动作：python3 /home/hatch/data/perpetua/kb/promote_proposal.py list|approve|reject
"""
import json
from datetime import datetime, timezone
from pathlib import Path

KB_DIR = Path("/home/hatch/data/perpetua/kb")
STAGING = KB_DIR / "staging"
PROPOSALS = STAGING / "proposals.jsonl"
SEEN = STAGING / "seen.json"
INBOX = Path("/home/hatch/data/collab/inbox.json")


def main() -> None:
    pending = []
    if PROPOSALS.exists():
        for line in PROPOSALS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "pending":
                pending.append(r)
    if not pending:
        print("no pending proposals")
        return

    seen = set()
    if SEEN.exists():
        try:
            seen = set(json.loads(SEEN.read_text(encoding="utf-8")))
        except Exception:
            seen = set()
    new = [r for r in pending if r.get("proposal_id") not in seen]
    if not new:
        print(f"pending: {len(pending)}, no new")
        return

    import sys
    sys.path.insert(0, "/home/hatch/data/perpetua")
    import inbox as inbox_gw
    lines = "\n".join(
        f"{i+1}. [{r.get('device') or 'general'}] {r['problem'][:80]}（by {r.get('proposer')}）"
        for i, r in enumerate(new)
    )
    inbox_gw.append_notice({
        "type": "kb_proposal_review",
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": f"知识库有 {len(new)} 条新提案待审核",
        "message": f"staging 有 {len(new)} 条 pending 提案待人工审核，通过后进正式知识库：\n{lines}\n审核命令：python3 /home/hatch/data/perpetua/kb/promote_proposal.py list",
        "for": "user",
        "read": False,
    })
    SEEN.write_text(json.dumps(sorted(seen | {r["proposal_id"] for r in new}), ensure_ascii=False),
                    encoding="utf-8")
    print(f"notified {len(new)} new proposals")


if __name__ == "__main__":
    main()
