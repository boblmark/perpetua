#!/usr/bin/env python3
"""Ask Studio 终审：视频生成提示词爆款度评审（0-100）。

用法：
    from prompt_review import submit_prompt_review, parse_review_score, wait_for_review_answer

    qid = submit_prompt_review(prompt, title, description, topic="smart gas pump")
    # 之后用 wait_for_review_answer(qid) 轮询 queue.json 等答案
    # 用 parse_review_score(answer_text) 解析评分
"""
from json_safe import atomic_write_json
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

QUEUE_PATH = "/home/hatch/data/ask_studio/queue.json"
REVIEWED_PATH = "/home/hatch/data/perpetua/prompt_reviewed.json"
# 双写评审记录：{key: {qid, gemini_qid, topic, ...}}
DUAL_PATH = "/home/hatch/data/perpetua/prompt_review_dual.json"

REVIEW_THRESHOLD = 85  # 达标线：>=85 才发

# 即时模式：ask_now() 走 instant_queue，由 parent agent 的浏览器任务秒级提问；
# 拿不到即时答案时回退到 30 分钟批处理。
try:
    sys.path.insert(0, "/home/hatch/data/ask_studio")
    from ask_now import ask_now as _ask_now, check_instant_answer as _check_now
    _INSTANT_OK = True
except Exception:
    _INSTANT_OK = False
    _ask_now = None
    _check_now = None


def submit_prompt_review_instant(prompt, title, description, topic=None,
                                 force=False, attempt=1,
                                 instant_timeout_minutes=5):
    """即时终审：走 instant_queue（parent 浏览器任务秒级提问）。

    返回 (qid, answer_or_None)。拿不到即时答案时返回 (qid, None)，
    调用方可再用 wait_for_review_answer(qid) 等批处理 fallback。
    幂等规则与 submit_prompt_review 一致。
    """
    q_text = review_question(prompt, title, description)
    topic = (topic or title[:40]).strip()
    key = _topic_key("%s#attempt%d" % (topic, attempt))
    reviewed = _load(REVIEWED_PATH, {})
    if not force and key in reviewed:
        qid = reviewed[key]["qid"]
    else:
        qid = None

    if _INSTANT_OK and _ask_now:
        r = _ask_now(q_text, priority="high", asked_by="dash", force=force)
        iid = r.get("iid")
        if not force or True:
            reviewed[key] = {"qid": iid, "topic": topic, "title": title,
                             "attempt": attempt, "submitted_at": now_iso(),
                             "mode": "instant"}
            _save(REVIEWED_PATH, reviewed)
        ans = _check_now(iid, timeout_minutes=instant_timeout_minutes)
        if ans:
            return iid, ans
        return iid, None

    # 本环境无 instant 能力：回退批处理
    qid = submit_prompt_review(prompt, title, description, topic=topic,
                               force=force, attempt=attempt)
    return qid, None


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


def review_question(prompt, title, description):
    """构造英文评审问题：要求首行给出 VIRALITY SCORE: N/100。"""
    # 截断过长的 prompt，避免单次提问超限
    p = prompt.strip()
    if len(p) > 2500:
        p = p[:2500] + "\n[...truncated...]"
    return (
        "Review this YouTube Shorts video package for virality. "
        "Channel: @karenvsai (532 subs, 'Karen vs AI' comedy theme).\n"
        "START your answer with exactly this line: VIRALITY SCORE: <number>/100\n\n"
        f"VIDEO PROMPT:\n{p}\n\n"
        f"TITLE:\n{title}\n\n"
        f"DESCRIPTION:\n{description}\n\n"
        "Then answer:\n"
        "1) One-paragraph justification for the score, referencing hook strength, "
        "retention mechanics, and title quality.\n"
        "2) If the score is BELOW 85, give exactly 3 specific, actionable fixes "
        "(quote the line to change and the replacement).\n"
        "3) Originality check (does NOT change the score, but always answer): "
        "does this package overlap significantly with this channel's recent uploads "
        "in scenario, AI device, or gag mechanism? If yes, name the overlapping "
        "video(s) and say exactly where the overlap is. If no, say 'No significant overlap.'\n"
        "4) Platform policy compliance check (does NOT change the score, but always answer): "
        "review this package against YouTube's Community Guidelines — misinformation, "
        "dangerous or harmful behavior imitation, hate/harassment, child safety, "
        "deceptive practices. Specifically also check: (a) harassment/cyberbullying — "
        "does the scenario sustain mockery, humiliation, or targeting of an identifiable "
        "real group, profession, or appearance trait (beyond the fictional Karen archetype)? "
        "(b) spam/deceptive practices — does the title or thumbnail promise something the "
        "video does not deliver (clickbait mismatch)? Also flag if the scenario realistically "
        "depicts a real person, celebrity, brand, or trademarked product, or involves minors. "
        "Start this section with exactly one of these lines: POLICY: PASS or POLICY: FLAG. "
        "If FLAG, quote the violating line and name the policy area."
    )


def _topic_key(topic):
    return hashlib.sha256(topic.encode("utf-8")).hexdigest()[:16]


def submit_prompt_review(prompt, title, description, topic=None, force=False, attempt=1):
    """向 ask_studio queue 提交评审问题，返回 question id。

    幂等：同一 topic（默认取 title 前 40 字符）只审一次，
    除非 force=True（用于修复后重审，此时 attempt 参与 key）。
    """
    topic = (topic or title[:40]).strip()
    key = _topic_key("%s#attempt%d" % (topic, attempt))

    reviewed = _load(REVIEWED_PATH, {})
    if not force and key in reviewed:
        return reviewed[key]["qid"]

    q = _load(QUEUE_PATH, {"pending": [], "answered": []})
    qid = "q_review_%s_%s" % (
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"), key[:8]
    )
    item = {
        "id": qid,
        "question": review_question(prompt, title, description),
        "asked_by": "dash",
        "priority": "high",
        "created": now_iso(),
        "status": "pending",
        "batch_key": "prompt_review",
        "review_of": topic,
        "attempt": attempt,
        "title_under_review": title,
    }
    q.setdefault("pending", []).append(item)
    _save(QUEUE_PATH, q)

    reviewed[key] = {"qid": qid, "topic": topic, "title": title,
                     "attempt": attempt, "submitted_at": now_iso()}
    _save(REVIEWED_PATH, reviewed)

    # 双写：同时走 Gemini（如果有 key），取评分高的
    # Ask Studio 走上面的 queue；Gemini 直接调 API，结果存 DUAL_PATH
    try:
        import sys
        sys.path.insert(0, "/home/hatch/data/ask_studio")
        from gemini_client import ask_gemini, gemini_available
        if gemini_available():
            g_ans = ask_gemini(review_question(prompt, title, description))
            if g_ans:
                g_score = parse_review_score(g_ans)
                dual = _load(DUAL_PATH, {})
                dual[key] = {
                    "qid": qid, "topic": topic, "title": title,
                    "attempt": attempt,
                    "gemini_answer": g_ans[:4000],
                    "gemini_score": g_score,
                    "submitted_at": now_iso(),
                }
                _save(DUAL_PATH, dual)
    except Exception:
        pass  # Gemini 失败不影响主流程

    return qid


def find_best_review_answer(qid, key=None):
    """双写取优：比较 Ask Studio 答案和 Gemini 答案的评分，返回 (answer, score, source)。

    key：prompt_reviewed.json 中的 topic key，用于查 DUAL_PATH。
    无 Gemini 答案时退化为单 Ask Studio。
    """
    # Ask Studio 答案
    as_ans = find_review_answer(qid)
    as_score = parse_review_score(as_ans) if as_ans else None

    # KB 激活（2026-10-09 三脑评审 C 方案 Commit 1）：评审前拉取知识库上下文
    # （publish_cadence 结构化阈值、相关脑会结论等）。失败不阻塞原流程。
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua/kb")
        from kb_context import get_context as _kb_get_context
        _kb_ctx = _kb_get_context("review", video_key=key,
                                  decision_hint="review_threshold_adjust")
    except Exception:
        _kb_ctx = []

    # Gemini 答案
    g_ans, g_score = None, None
    if key:
        dual = _load(DUAL_PATH, {})
        rec = dual.get(key, {})
        g_ans = rec.get("gemini_answer")
        g_score = rec.get("gemini_score")

    cands = []
    if as_ans and as_score is not None:
        cands.append((as_score, as_ans, "ask_studio"))
    elif as_ans:
        cands.append((-1, as_ans, "ask_studio"))
    if g_ans and g_score is not None:
        cands.append((g_score, g_ans, "gemini_api"))
    elif g_ans:
        cands.append((-1, g_ans, "gemini_api"))

    if not cands:
        return None, None, None
    cands.sort(key=lambda x: x[0], reverse=True)
    score, ans, src = cands[0]
    return ans, (score if score >= 0 else None), src


def find_review_answer(qid):
    """在 queue.json 的 answered 里找某评审问题的答案，返回 answer dict 或 None。"""
    q = _load(QUEUE_PATH, {"pending": [], "answered": []})
    for item in q.get("answered", []):
        if item.get("id") == qid:
            ans = item.get("answer")
            if isinstance(ans, dict):
                return ans.get("section") or ans.get("full")
            return ans
    return None


def wait_for_review_answer(qid, max_wait_minutes=30, poll_seconds=60):
    """轮询等待评审答案。返回 answer 文本；超时返回 None。"""
    deadline = time.time() + max_wait_minutes * 60
    while time.time() < deadline:
        ans = find_review_answer(qid)
        if ans and str(ans).strip():
            return str(ans).strip()
        time.sleep(poll_seconds)
    return None


def parse_review_score(answer_text):
    """从评审答案文本解析 0-100 评分，解析失败返回 None。"""
    import re
    if not answer_text:
        return None
    t = str(answer_text)
    # 1) 优先匹配我们要求的首行格式
    m = re.search(r"VIRALITY\s*SCORE\s*[:：]\s*(\d{1,3})\s*/\s*100", t, re.I)
    if m:
        return min(100, int(m.group(1)))
    # 2) 常见变体
    for pat in [
        r"virality[^0-9]{0,20}(\d{1,3})\s*/\s*100",
        r"(?:score|rating|grade)\s*[:：]\s*(\d{1,3})\s*/\s*100",
        r"(?:score|rating)\s*(?:of|is)?\s*(\d{1,3})\s*out of 100",
        r"(\d{1,3})\s*/\s*100",
    ]:
        m = re.search(pat, t, re.I)
        if m:
            v = int(m.group(1))
            if 0 <= v <= 100:
                return v
    return None


def parse_policy_verdict(answer_text):
    """从评审答案文本解析平台政策合规结论。

    返回 "PASS" | "FLAG" | None（未找到明确结论）。
    保守原则：含糊不清视为 None（由调用方决定是否人工复核），
    明确 FLAG 才阻塞。
    """
    import re
    if not answer_text:
        return None
    t = str(answer_text)
    m = re.search(r"POLICY\s*[:：]\s*(PASS|FLAG)", t, re.I)
    if m:
        return m.group(1).upper()
    return None


if __name__ == "__main__":
    import sys
    # 自检：解析逻辑
    samples = [
        "VIRALITY SCORE: 84/100\nStrengths: ...",
        "Virality score: 92 / 100 - great hook",
        "I give this a score of 78 out of 100.",
    ]
    for s in samples:
        print(parse_review_score(s), "<-", s[:40])
