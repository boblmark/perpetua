#!/usr/bin/env python3
"""主 Muse 视频自动分发（2026-10-10 落地）：spool 驱动 + 熔断器。

spool: perpetua/musemain_requests.jsonl，每行一个请求：
  {"request_id","prompt","purpose","status":"pending","created_at"}
状态机：pending -> submitted -> done | refused | failed

熔断器（任一不满足则 HOLD，本轮不提交）：
  1. 拒收率探针 musemain_refusal_probe.json 存在且 refusal_rate < 0.5
  2. 当日已提交 < 6（video_count 上限）
  3. 最近连续 refused < 2（否则 HALT 并写 inbox，需人工 reset）

请求来源：任何进程/人向 spool 追加一行即表示"缺素材"。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
SPOOL = os.path.join(BASE, "musemain_requests.jsonl")
PROBE = os.path.join(BASE, "musemain_refusal_probe.json")
STATE = os.path.join(BASE, "musemain_autodispatch_state.json")
INBOX = os.path.join(BASE, "..", "collab", "inbox")
DAILY_CAP = 6
MAX_REFUSAL_RATE = 0.5


def _now():
    return datetime.now(timezone.utc)


def _load_spool():
    rows = []
    if os.path.exists(SPOOL):
        with open(SPOOL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        pass
    return rows


def _save_spool(rows):
    with open(SPOOL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(s):
    atomic_write_json(STATE, s)


def _inbox(subject, body, priority="normal"):
    try:
        os.makedirs(INBOX, exist_ok=True)
        msg = {"id": "dash-%s" % _now().strftime("%Y%m%d%H%M%S"),
               "from": "dash", "to": "user", "subject": subject,
               "body": body, "priority": priority,
               "created_at": _now().isoformat()}
        atomic_write_json(os.path.join(INBOX, msg["id"] + ".json"), msg)
    except Exception:
        pass


def _breaker():
    """返回 (ok: bool, reason: str)。"""
    try:
        with open(PROBE, encoding="utf-8") as f:
            probe = json.load(f)
    except Exception:
        return False, "拒收率探针未完成，HOLD（请求继续积压）"
    rr = probe.get("refusal_rate")
    if rr is None or rr >= MAX_REFUSAL_RATE:
        return False, "拒收率 %.2f >= %.2f，HOLD" % (rr if rr is not None else -1, MAX_REFUSAL_RATE)
    st = _load_state()
    today = _now().strftime("%Y-%m-%d")
    if st.get("date") != today:
        st = {"date": today, "submitted_today": 0, "consecutive_refused": 0}
    if st.get("submitted_today", 0) >= DAILY_CAP:
        _save_state(st)
        return False, "今日已提交 %d 达上限，HOLD" % DAILY_CAP
    if st.get("consecutive_refused", 0) >= 2:
        return False, "连续拒收 %d 次，HALT（需人工 reset）" % st["consecutive_refused"]
    if st.get("halted"):
        return False, "HALT 状态未解除，需人工 reset"
    _save_state(st)
    return True, "ok"


def main():
    sys.path.insert(0, BASE)
    rows = _load_spool()
    changed = False
    # 1. 轮询已提交的
    try:
        from gen_video_musemain import check
        for r in rows:
            if r.get("status") != "submitted" or not r.get("muse_job_id"):
                continue
            try:
                outcome, detail = check(r["muse_job_id"])
            except Exception as e:
                r["note"] = "check 异常: %s" % str(e)[:100]
                changed = True
                continue
            # check 返回 (done|pending|failed, 明细)；拒收混在 failed 里，按关键词识别
            if outcome == "pending":
                continue
            if outcome == "done":
                r["status"] = "done"
                r["local_file"] = detail
                _bump_ok()
            else:
                low = str(detail).lower()
                if any(k in low for k in ("refus", "内容政策", "拒绝", "policy", "not allowed")):
                    r["status"] = "refused"
                    r["note"] = str(detail)[:200]
                    _bump_refused()
                else:
                    r["status"] = "failed"
                    r["note"] = str(detail)[:200]
                    _bump_ok()
            r["last_check"] = _now().isoformat()
            changed = True
    except Exception as e:
        print("poll 异常: %s" % e)

    # 2. 提交 pending
    pendings = [r for r in rows if r.get("status") == "pending"]
    if pendings:
        ok, reason = _breaker()
        if not ok:
            print("HOLD: %s（%d 条 pending 积压）" % (reason, len(pendings)))
            if "HALT" in reason:
                _inbox("主 Muse 自动分发 HALT", reason, priority="urgent")
        else:
            from gen_video_musemain import submit
            st = _load_state()
            for r in pendings:
                if st.get("submitted_today", 0) >= DAILY_CAP:
                    break
                try:
                    mjid = submit(r["prompt"], r["request_id"])
                    r["status"] = "submitted"
                    r["muse_job_id"] = mjid
                    r["submitted_at"] = _now().isoformat()
                    st["submitted_today"] = st.get("submitted_today", 0) + 1
                    print("SUBMITTED %s -> %s" % (r["request_id"], mjid))
                except Exception as e:
                    r["status"] = "failed"
                    r["note"] = "submit 异常: %s" % str(e)[:200]
                    print("SUBMIT_FAIL %s: %s" % (r["request_id"], str(e)[:100]))
                changed = True
            _save_state(st)
    if changed:
        _save_spool(rows)
    n_p = sum(1 for r in rows if r.get("status") == "pending")
    n_s = sum(1 for r in rows if r.get("status") == "submitted")
    print("spool: pending=%d submitted=%d" % (n_p, n_s))


def _bump_refused():
    st = _load_state()
    st["consecutive_refused"] = st.get("consecutive_refused", 0) + 1
    _save_state(st)
    if st["consecutive_refused"] >= 2:
        _inbox("主 Muse 自动分发 HALT：连续拒收",
               "连续 2 次 prompt 被拒收，已停止自动提交。请检查 prompt 措辞或联系用户。",
               priority="urgent")


def _bump_ok():
    st = _load_state()
    if st.get("consecutive_refused"):
        st["consecutive_refused"] = 0
        _save_state(st)


if __name__ == "__main__":
    main()
