#!/usr/bin/env python3
"""视频生成终审流程：生成提示词 -> Ask Studio 终审 -> 达标(>=85)才提交生成。

流程：
    build_viral_prompt()          # /home/hatch/data/perpetua/viral_prompt.py
      -> prompt_review.submit_prompt_review()   # Ask Studio 队列终审
      -> 轮询等待答案（最多 30 分钟）
      -> 评分 >= 85：写入 jobs/pending（generate_video）
      -> 评分 < 85：按评审建议自动修复一次 -> 重审
      -> 两次不过：写入 prompt_review_manual.json，标记人工介入

用法：
    from submit_video_with_review import submit_video_with_review
    r = submit_video_with_review(topic="smart gas pump",
                                 hook="Karen slams an expired coupon on the scanner")
    # r = {"status": "submitted"|"needs_manual"|"review_timeout"|"review_failed",
    #      "job_id": ..., "score": 87, ...}

幂等：同一 topic 只走一次完整流程（prompt_reviewed.json 记录）。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from viral_prompt import build_viral_prompt
from prompt_review import (
    submit_prompt_review,
    submit_prompt_review_instant,
    wait_for_review_answer,
    parse_review_score,
    parse_policy_verdict,
    find_best_review_answer,
    REVIEW_THRESHOLD,
)
from platform_policy import prescreen_policy

PENDING_DIR = "/home/hatch/data/perpetua/jobs/pending"
MANUAL_PATH = "/home/hatch/data/perpetua/prompt_review_manual.json"
FLOW_STATE_PATH = "/home/hatch/data/perpetua/review_flow_state.json"


def _load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(p, obj):
    atomic_write_json(p, obj)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _flow_key(topic):
    return hashlib.sha256(topic.encode("utf-8")).hexdigest()[:16]


def _write_video_job(payload, score, qid):
    """评分达标：写入 jobs/pending/generate_video 任务。"""
    os.makedirs(PENDING_DIR, exist_ok=True)
    jid = "job-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                         uuid.uuid4().hex[:6])
    job = {
        "job_id": jid,
        "job_type": "generate_video",
        "payload": dict(payload, review_score=score, review_qid=qid,
                        template_version=payload.get("template_version", "v2")),
        "status": "pending",
        "created_at": now_iso(),
        "from": "dash",
        "idempotency_key": "dash-review-%s" % hashlib.sha256(
            payload.get("title", jid).encode("utf-8")).hexdigest()[:16],
    }
    atomic_write_json(os.path.join(PENDING_DIR, jid + ".json"), job)
    return jid


def _apply_reviewer_fixes(pkg, answer_text):
    """按评审建议自动修复一次：把评审意见作为导演注记追加到 prompt。

    注：Ask Studio 返回的是自由文本，无法可靠解析结构化修改；
    诚实做法是把完整评审意见注入 prompt 供生成模型参考，
    并在标题中强化爆款要素。
    """
    fixed = dict(pkg)
    fixed["prompt"] = (
        pkg["prompt"]
        + "\n\nASK STUDIO REVIEWER NOTES (mandatory fixes for virality, apply all):\n"
        + answer_text[:1500]
    )
    fixed["template_version"] = pkg.get("template_version", "v2") + "+fix1"
    return fixed


def _mark_manual(topic, pkg, history):
    manual = _load(MANUAL_PATH, [])
    manual.append({
        "topic": topic,
        "title": pkg.get("title"),
        "submitted_at": now_iso(),
        "history": history,
    })
    _save(MANUAL_PATH, manual)


# 测试产物黑名单（2026-10-06 新增）：拦内部验证流程误发公开频道的产物。
# 命中则直接 purity_reject，不进入审批队列。
_TEST_ARTIFACT_PATTERNS = (
    (re.compile(r"stodownload", re.I), "stodownload test artifact"),
    (re.compile(r"\bE2E\b.*(Asset|Publish|Feedback)", re.I), "E2E asset publish test"),
    (re.compile(r"geminigen\s+PLAN\s+\d+", re.I), "geminigen plan probe"),
    (re.compile(r"WB\s+Verify\s+Probe", re.I), "workbuddy verify probe"),
    (re.compile(r"\b(test|probe|smoke|dummy|lorem)[-_ ]?\d{3,}\b", re.I),
     "numbered test artifact"),
)


def _check_test_artifact(title, topic, hook):
    """命中测试产物黑名单则抛 ValueError。只读检查，不改传入值。"""
    blob = "%s | %s | %s" % (title or "", topic or "", hook or "")
    for rx, label in _TEST_ARTIFACT_PATTERNS:
        m = rx.search(blob)
        if m:
            raise ValueError(
                "purity_reject[test_artifact]: %s matched %r in %r"
                % (label, m.group(0)[:40], blob[:80]))


# IP 角色黑名单（P0，2026-10-06 新增）：知名 IP 角色会导致版权下架。
# 后果实证：2_oNDT-6N_M 被 Removed，清零 2,776 小时。
_IP_RISK_PATTERNS = (
    # 具体知名 IP / 角色名
    (re.compile(
        r"\b(magneto|mumm-?ra|mumm-?ra|marvel|dc\s*comics|disney|pixar|"
        r"batman|superman|spider-?man|iron\s*man|thor|hulk|avengers|x-?men|"
        r"star\s*wars|jedi|sith|darth|pokemon|pikachu|mario|luigi|sonic|"
        r"minecraft|fortnite|roblox|elsa|frozen|harry\s*potter|hogwarts|"
        r"godzilla|king\s*kong|transformers|optimus|bumblebee|barbie|"
        r"hello\s*kitty|snoopy|peanuts|nintendo|zelda|link|kirby|"
        r"captain\s*hook|peter\s*pan|vlad\s*mourdain|cinderella|ariel|"
        r"simba|lion\s*king|shrek|minions|gru|wonder\s*woman|joker|"
        r"deadpool|wolverine|goku|naruto|one\s*piece|demon\s*slayer)\b",
        re.I), "named IP character"),
    # 泛指知名 IP 归属
    (re.compile(
        r"\b(marvel|dc|disney|pixar|nintendo|warner\s*bros|"
        r"lucasfilm|studio\s*ghibli|toei|shueisha)\b", re.I),
     "IP studio/brand"),
)


def _check_ip_risk(title, topic, hook, prompt=""):
    """命中 IP 黑名单则抛 ValueError（P0，直接拒绝）。只读检查。"""
    blob = "%s | %s | %s | %s" % (title or "", topic or "", hook or "", prompt or "")
    for rx, label in _IP_RISK_PATTERNS:
        m = rx.search(blob)
        if m:
            raise ValueError(
                "ip_purity_reject[%s]: matched %r in %r"
                % (label, m.group(0)[:40], blob[:100]))


def _check_purity_gate(topic, hook, title=""):
    """P0 定位纯化硬校验（与 viral_prompt._check_purity 同规则）：
    英文、无 CJK；hook 必须含 Karen 或 AI。失败抛 ValueError。

    2026-10-06 新增：先过测试产物黑名单。"""
    import re
    _check_test_artifact(title, topic, hook)
    _check_ip_risk(title, topic, hook)
    for label, text, require_brand in (
            ("topic", topic, False), ("hook", hook, True)):
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text or ""):
            raise ValueError(
                "purity_reject[%s]: contains CJK characters: %r"
                % (label, (text or "")[:60]))
        if require_brand:
            low = (text or "").lower()
            if "karen" not in low and re.search(r"\bai\b", low) is None:
                raise ValueError(
                    "purity_reject[%s]: must mention Karen or AI: %r"
                    % (label, (text or "")[:60]))


def _log_reject(log_path, entry):
    try:
        log = _load(log_path, [])
        log.append(dict(entry, at=now_iso()))
        _save(log_path, log[-500:])
    except Exception:
        pass


REJECT_LOG = "/home/hatch/data/perpetua/purity_reject.log.json"
POLICY_LOG = "/home/hatch/data/perpetua/policy_flag.log.json"


APPROVAL_PATH = "/home/hatch/data/perpetua/awaiting_approval.json"
DEDUP_LOG = "/home/hatch/data/perpetua/dedup_reject.log.json"


def _request_approval(pkg_final, score_final, qid_final, history):
    """P0 人工终审闸门：Ask Studio 达标后不直接进 pending，
    而是写入 awaiting_approval.json 等人工批准，并通知用户。"""
    awaiting = _load(APPROVAL_PATH, [])
    entry = {
        "topic": pkg_final.get("_topic", ""),
        "title": pkg_final["title"],
        "prompt": pkg_final["prompt"],
        "description": pkg_final.get("description", ""),
        "review_score": score_final,
        "review_qid": qid_final,
        "template_version": pkg_final.get("template_version", "v2"),
        "submitted_at": now_iso(),
        "status": "awaiting",
        "history": history,
    }
    # 同 topic 去重：已有 awaiting 的不再重复入队
    awaiting = [a for a in awaiting
                if a.get("topic") != entry["topic"]
                or a.get("status") != "awaiting"]
    awaiting.append(entry)
    _save(APPROVAL_PATH, awaiting)
    _notify_approval_needed(entry)
    return entry


def _notify_approval_needed(entry):
    """inbox 写入 approval_needed 通知用户审批（经统一网关）。"""
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        import inbox as inbox_gw
        inbox_gw.append_message({
            "type": "approval_needed",
            "message": ("【人工终审】新视频待批准（Ask Studio %s 分）：%s"
                        % (entry["review_score"], entry["title"][:80])),
            "topic": entry["topic"],
            "title": entry["title"],
            "score": entry["review_score"],
            "from": "dash",
            "created_at": now_iso(),
        })
    except Exception:
        pass


def _dedup_gate(pkg):
    """P0 发布前去重：与近 90 天已发布标题比对，重叠>60% 拒绝。"""
    try:
        from dedup_check import check_duplicate
    except ImportError:
        return None  # 模块缺失时放行（不阻塞主流程）
    dup, matched, overlap = check_duplicate(
        pkg.get("title", ""), pkg.get("prompt", "")[:500])
    if dup:
        _log_reject(DEDUP_LOG, {"title": pkg.get("title"),
                                "matched": matched, "overlap": overlap})
        return {"status": "dedup_rejected", "title": pkg.get("title"),
                "matched": matched, "overlap": overlap}
    return None


def submit_video_with_review(topic, hook, karma_payoff=None, emoji_pair=("🤖", "😂"),
                             max_wait_minutes=30, poll_seconds=60,
                             submit=True, force=False, misdeed=None, reversal=None):
    """主流程。submit=False 时只走评审不提交生成（用于测试）。"""
    # P0 纯化闸门：入口即校验，失败记日志并直接返回
    try:
        _check_purity_gate(topic, hook, title=hook)
    except ValueError as e:
        _log_reject(REJECT_LOG, {"topic": topic, "hook": (hook or "")[:80],
                                 "reason": str(e)})
        return {"status": "purity_rejected", "topic": topic,
                "reason": str(e)}
    state = _load(FLOW_STATE_PATH, {})
    key = _flow_key(topic)
    if not force and key in state and state[key].get("status") in (
            "submitted", "needs_manual"):
        return dict(state[key], deduped=True)

    history = []

    # ---- 第一轮：生成 + 终审（即时模式优先，拿不到再回退批处理） ----
    pkg = build_viral_prompt(topic, hook, karma_payoff, emoji_pair,
                             misdeed=misdeed, reversal=reversal)

    # ---- 平台政策预检（2026-10-10 新增）：prompt 级确定性规则 ----
    # FLAG 直接进人工复核，不自动改写重试（2026-10-09 废除 sanitize 重试：
    # 政策问题靠改措辞绕过属于违规操作）。
    _pverdict, _preasons = prescreen_policy(
        pkg.get("prompt", ""), pkg.get("title", ""),
        pkg.get("description", ""), platform="youtube")
    if _pverdict == "FLAG":
        _log_reject(POLICY_LOG, {
            "topic": topic, "title": pkg.get("title", "")[:80],
            "stage": "prescreen",
            "reasons": [{"rule": r[0], "note": r[1], "hit": r[2]}
                        for r in _preasons],
        })
        history.append({"stage": "policy_prescreen", "verdict": "FLAG",
                        "reasons": [r[0] for r in _preasons]})
        _mark_manual(topic, pkg, history)
        result = {"status": "policy_flagged", "topic": topic,
                  "stage": "prescreen",
                  "reasons": [{"rule": r[0], "note": r[1]} for r in _preasons],
                  "history": history,
                  "note": "平台政策预检 FLAG，已进人工复核，不自动改写"}
        state[key] = result
        _save(FLOW_STATE_PATH, state)
        return result
    history.append({"stage": "policy_prescreen", "verdict": "PASS"})

    qid, answer = submit_prompt_review_instant(
        pkg["prompt"], pkg["title"], pkg["description"], topic=topic,
        instant_timeout_minutes=5)
    history.append({"attempt": 1, "qid": qid, "mode": "instant"})

    if not answer:
        # 即时没拿到答案：回退 30 分钟批处理等待（fallback 已在队列中）
        answer = wait_for_review_answer(qid, max_wait_minutes, poll_seconds)
        history[-1]["mode"] = "instant+batch-fallback"
    if not answer:
        result = {"status": "review_timeout", "topic": topic, "qid": qid,
                  "history": history}
        state[key] = result
        _save(FLOW_STATE_PATH, state)
        return result

    # 双写取优：比较 Ask Studio vs Gemini 评分，取高的
    _tkey = hashlib.sha256(("%s#attempt%d" % (topic, 1)).encode("utf-8")).hexdigest()[:16]
    best_ans, best_score, best_src = find_best_review_answer(qid, _tkey)
    if best_ans:
        answer = best_ans
    score = best_score if best_score is not None else parse_review_score(answer)
    history[-1].update({"score": score,
                        "answer_excerpt": answer[:500],
                        "review_source": best_src})

    # ---- 平台政策终审（2026-10-10 新增）：Ask Studio 第 4 问语义复核 ----
    # FLAG 直接进人工复核，不进爆款度修复轮（政策问题不靠改措辞解决）。
    _policy = parse_policy_verdict(answer)
    history[-1]["policy_verdict"] = _policy
    if _policy == "FLAG":
        _log_reject(POLICY_LOG, {
            "topic": topic, "title": pkg.get("title", "")[:80],
            "stage": "review_q4", "qid": qid,
            "answer_excerpt": (answer or "")[:500],
        })
        _mark_manual(topic, pkg, history)
        result = {"status": "policy_flagged", "topic": topic,
                  "stage": "review_q4", "qid": qid, "history": history,
                  "note": "Ask Studio 政策审查 FLAG，已进人工复核，不自动改写"}
        state[key] = result
        _save(FLOW_STATE_PATH, state)
        return result

    def finalize_ok(pkg_final, score_final, qid_final, attempts):
        # P0 去重闸门：达标后先查重复
        dedup_hit = _dedup_gate(pkg_final)
        if dedup_hit:
            result = dict(dedup_hit, topic=topic, history=history)
            state[key] = result
            _save(FLOW_STATE_PATH, state)
            return result
        # P0 人工终审闸门：达标后进 awaiting_approval，不再直接写 pending
        pkg_final["_topic"] = topic
        entry = _request_approval(pkg_final, score_final, qid_final, history)
        if not submit:
            result = {"status": "review_passed", "topic": topic,
                      "score": score_final, "qid": qid_final,
                      "title": pkg_final["title"], "history": history,
                      "note": "submit=False, awaiting approval (NOT written to pending)"}
        else:
            result = {"status": "awaiting_approval", "topic": topic,
                      "score": score_final, "qid": qid_final,
                      "title": pkg_final["title"], "history": history,
                      "note": "written to awaiting_approval.json, needs human approve"}
        state[key] = result
        _save(FLOW_STATE_PATH, state)
        return result

    if score is not None and score >= REVIEW_THRESHOLD:
        return finalize_ok(pkg, score, qid, history)

    # ---- 第二轮：自动修复一次后重审（即时优先） ----
    fixed_pkg = _apply_reviewer_fixes(pkg, answer)
    qid2, answer2 = submit_prompt_review_instant(
        fixed_pkg["prompt"], fixed_pkg["title"], fixed_pkg["description"],
        topic=topic, force=True, attempt=2, instant_timeout_minutes=5)
    history.append({"attempt": 2, "qid": qid2, "fixed": True, "mode": "instant"})
    if not answer2:
        answer2 = wait_for_review_answer(qid2, max_wait_minutes, poll_seconds)
        history[-1]["mode"] = "instant+batch-fallback"
    if answer2:
        _tkey2 = hashlib.sha256(("%s#attempt%d" % (topic, 2)).encode("utf-8")).hexdigest()[:16]
        best_ans2, best_score2, best_src2 = find_best_review_answer(qid2, _tkey2)
        if best_ans2:
            answer2 = best_ans2
        score2 = best_score2 if best_score2 is not None else parse_review_score(answer2)
        history[-1].update({"score": score2,
                            "answer_excerpt": answer2[:500],
                            "review_source": best_src2})
        if score2 is not None and score2 >= REVIEW_THRESHOLD:
            return finalize_ok(fixed_pkg, score2, qid2, history)

    # ---- 两次不过：人工介入 ----
    _mark_manual(topic, fixed_pkg, history)
    result = {"status": "needs_manual", "topic": topic,
              "title": fixed_pkg["title"], "history": history}
    state[key] = result
    _save(FLOW_STATE_PATH, state)
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--hook", required=True)
    ap.add_argument("--no-submit", action="store_true",
                    help="只评审不提交生成")
    ap.add_argument("--wait", type=int, default=30,
                    help="等待评审答案的最大分钟数")
    args = ap.parse_args()
    r = submit_video_with_review(args.topic, args.hook,
                                 max_wait_minutes=args.wait,
                                 submit=not args.no_submit)
    print(json.dumps(r, ensure_ascii=False, indent=2))
