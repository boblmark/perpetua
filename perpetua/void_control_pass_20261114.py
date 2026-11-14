#!/usr/bin/env python3
"""Void an invalid control-group review pass (one-off correction, 2026-11-14).

Target: the 00:00-slot 'smart home hub' row whose Ask Studio score (72)
came from a 2500-char truncated question (qid iq_20261114141233_ed5fb06eed08,
prompt_review.py:106). Per council D20261113-001 truncated scores do not
count; the same answer also flags significant overlap with the 2026-11-04
upload 'Karen Screamed At The Slow trainee Cashier - Then the Kiosk Towed
Her Car While She Watched' (identical kiosk-towed-car payoff). The pipeline
marked it review_passed only via the B-steady control group (72 >= 70,
hash in 20%). A control-group pass cannot launder an invalid measurement,
and shipping a near-duplicate violates the channel dedup policy, so the
pass is voided: status review_passed -> archived, control_group cleared.
Score, qid and answer are kept on the row for audit. Reversible by
restoring /home/hatch/data/ops_center.db.bak-20261114-2258-reviewvoid.
"""
import sys

sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

QID = "iq_20261114141233_ed5fb06eed08"

q = queue_db.pipeline_load()
target = None
for r in q:
    if r.get("review_qid") == QID:
        target = r
        break
if target is None:
    print("TARGET NOT FOUND")
    sys.exit(1)
print("BEFORE:", target.get("topic"), "|", target.get("status"), "| slot:",
      target.get("slot"), "| score:", target.get("review_score"),
      "| control:", target.get("control_group"))
if target.get("status") != "review_passed":
    print("ALREADY NOT review_passed; no change made")
    sys.exit(0)
target["status"] = "archived"
target["control_group"] = False
target["archive_reason"] = (
    "control_pass_voided: truncated_review D20261113-001 "
    "(2500-char cut, score 72 invalid) + Ask Studio overlap vs "
    "2026-11-04 kiosk upload; do not submit"
)
queue_db.pipeline_save(q)
print("AFTER:", target.get("status"), "|", target.get("archive_reason"))
