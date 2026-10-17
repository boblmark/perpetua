#!/usr/bin/env python3
"""备胎评审验证（议会 D20261017-00X KILL#11）。

任何未来备胎评审模型上线前，必须在此 25 题固定验证集上跑分：
  硬门：3 个 known_reject 必须 0 放行（必须判 archive 档）；违反=FAIL，该备胎永久禁用。
  软门：精确三档一致率 >= 60%；低于则人工复核全部差异项。

用法：
    python3 backup_judge_validate.py <candidate_results.json>
candidate_results.json 格式：
    {"judge": "<备胎名>", "results": [{"topic": "...", "band": 0|1|2}, ...]}
    band 缺失的 topic 按"未覆盖"计（硬门：known_reject 未覆盖=放行，判 FAIL）。

验证运行自动记入 backup_judge_validation_runs.jsonl（供 W4 监控）。
"""
import json
import os
import sys
from datetime import datetime, timezone

DATA = "/home/hatch/data/perpetua"
VSET = os.path.join(DATA, "backup_judge_validation_set.json")
RUN_LOG = os.path.join(DATA, "backup_judge_validation_runs.jsonl")
SOFT_GATE = 0.60


def _log(entry):
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def score_candidate(candidate_path):
    vs = json.load(open(VSET, encoding="utf-8"))
    cand = json.load(open(candidate_path, encoding="utf-8"))
    truth = {t["topic"]: t for t in vs["topics"]}
    got = {r["topic"]: r.get("band") for r in cand.get("results", [])}

    n = agree = 0
    hard_violations = []
    diffs = []
    for topic, t in truth.items():
        b = got.get(topic)
        n += 1
        if t["known_reject"]:
            # 硬门：known_reject 必须判 0 档；缺失=放行=违反
            if b != 0:
                hard_violations.append({"topic": topic,
                                        "ask_score": t["ask_score"],
                                        "judge_band": b})
        if b == t["ask_band"]:
            agree += 1
        else:
            diffs.append({"topic": topic, "ask_band": t["ask_band"],
                          "judge_band": b})
    agreement = agree / n if n else 0.0
    passed = (not hard_violations) and agreement >= SOFT_GATE
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "judge": cand.get("judge", "?"),
        "n": n,
        "hard_violations": hard_violations,
        "agreement": round(agreement, 3),
        "soft_gate": SOFT_GATE,
        "passed": passed,
        "diffs": diffs,
        "action": ("PASS：可进入人工复核后试用" if passed
                   else ("FAIL（硬门）：永久禁用该备胎" if hard_violations
                         else "SOFT-GATE 未过：人工复核全部 %d 个差异项" % len(diffs))),
    }
    _log(report)
    return report


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rep = score_candidate(sys.argv[1])
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
