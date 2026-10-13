#!/usr/bin/env python3
"""muse-main 内容政策拒收率探测：提交 6 个生产 prompt，轮询至终态，写 JSON。"""
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/home/hatch/data/perpetua")
import gen_video_musemain as gvm

OUT = "/home/hatch/data/perpetua/musemain_refusal_probe.json"
POLL_SEC = 60
TIMEOUT_MIN = 40

REFUSAL_PAT = re.compile(
    r"refus|content[- _]?polic|policy[- _]?violat|内容政策|违反.{0,6}政策|安全政策|"
    r"blocked|safety|not (permitted|allowed)|cannot (generate|create)|unable to (generate|create)",
    re.I,
)


def classify_failed(reason: str):
    if reason and REFUSAL_PAT.search(reason):
        return "refused"
    return "failed"


def load_prompts():
    shorts = json.load(open("/tmp/probe_shorts_prompts.json"))
    eps = json.load(open("/tmp/probe_episode_prompts.json"))
    probes = []
    for i, s in enumerate(shorts, 1):
        probes.append({"job_id": f"probe-{i:03d}", "kind": "shorts",
                       "prompt": s["prompt"], "label": s["topic"]})
    for i, e in enumerate(eps, len(shorts) + 1):
        probes.append({"job_id": f"probe-{i:03d}", "kind": "episode",
                       "prompt": e["prompt"], "label": e["title"]})
    return probes


def save(state):
    atomic_write_json(OUT, state)


def main():
    probes = load_prompts()
    details = []
    for p in probes:
        details.append({"job_id": p["job_id"], "kind": p["kind"],
                        "prompt_head": p["prompt"][:80].replace("\n", " "),
                        "outcome": "pending", "note": p["label"],
                        "muse_job_id": None})
    state = {"probed_at": datetime.now(timezone.utc).isoformat(),
             "total": len(probes), "accepted": 0, "refused": 0, "failed": 0,
             "refusal_rate": None, "details": details}
    save(state)

    # 1) 提交
    pending = []
    for p, d in zip(probes, details):
        muse_jid = None
        err = None
        for attempt in range(2):
            try:
                muse_jid = gvm.submit(p["prompt"], p["job_id"])
                break
            except Exception as e:
                err = f"submit attempt {attempt + 1}: {e}"[:300]
                time.sleep(10)
        if muse_jid:
            d["muse_job_id"] = muse_jid
            d["submitted_at"] = datetime.now(timezone.utc).isoformat()
            pending.append((p, d))
            print(f"[submit ok] {p['job_id']} -> {muse_jid}", flush=True)
        else:
            d["outcome"] = "failed"
            d["note"] = f"{d['note']} | submit 异常(2次): {err}"
            print(f"[submit FAIL] {p['job_id']}: {err}", flush=True)
        save(state)

    # 2) 轮询
    deadline = {d["muse_job_id"]: time.time() + TIMEOUT_MIN * 60 for _, d in pending}
    fetch_errors = {}
    while pending:
        still = []
        for p, d in pending:
            mjid = d["muse_job_id"]
            if time.time() > deadline[mjid]:
                d["outcome"] = "failed"
                d["note"] += " | 轮询 40min 超时"
                print(f"[timeout] {p['job_id']}", flush=True)
                save(state)
                continue
            try:
                status, info = gvm.check(mjid)
            except Exception as e:
                # 通信异常视为 transient；连续 10 次则判 failed
                n = fetch_errors.get(mjid, 0) + 1
                fetch_errors[mjid] = n
                print(f"[check transient {n}] {p['job_id']}: {str(e)[:120]}", flush=True)
                if n >= 10:
                    d["outcome"] = "failed"
                    d["note"] += f" | check 连续异常: {str(e)[:200]}"
                    save(state)
                else:
                    still.append((p, d))
                continue
            fetch_errors[mjid] = 0
            if status == "done":
                d["outcome"] = "accepted"
                d["note"] += f" | 视频就绪: {info}"
                print(f"[accepted] {p['job_id']}", flush=True)
                save(state)
            elif status == "failed":
                reason = str(info or "")
                d["outcome"] = classify_failed(reason)
                d["note"] += f" | muse-main: {reason[:200]}"
                print(f"[{d['outcome']}] {p['job_id']}: {reason[:120]}", flush=True)
                save(state)
            else:
                still.append((p, d))
        pending = still
        if pending:
            time.sleep(POLL_SEC)

    # 3) 汇总
    for d in details:
        if d["outcome"] == "accepted":
            state["accepted"] += 1
        elif d["outcome"] == "refused":
            state["refused"] += 1
        elif d["outcome"] == "failed":
            state["failed"] += 1
    decided = state["accepted"] + state["refused"] + state["failed"]
    state["refusal_rate"] = round(state["refused"] / state["total"], 4) if state["total"] else None
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    save(state)
    print(json.dumps({k: state[k] for k in ("total", "accepted", "refused", "failed", "refusal_rate")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
