#!/usr/bin/env python3
"""Arena jury 五用法自动调用（2026-10-10 用户批准）。

触发器（每次运行逐个评估，命中即 dispatch）：
  ep_prejury          新 private 长视频（>=10min，7天内上传）未陪审 -> 上线前预审
  title_thumbnail_rank ai_unhinged/title_options_*.json 有 >=2 备选未排序 -> 三选一
  kill_arbitration    2026-12-08 到达（one-shot）或连续14天观看小时pace<30%所需 -> kill/continue/pivot
  collapse_jury       最近2条发布视频>=48h且播放<50 -> 紧急诊断（比议会5条阈值更早的轻量预警）
  competitor_teardown 季度变化 -> 竞品拆解

dispatch 经 lmarena_agent.py（VM agent-browser，约4-25分钟/次）。
状态：perpetua/arena_jury_auto_state.json。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta

BASE = "/home/hatch/data"
PERP = os.path.join(BASE, "perpetua")
STATE = os.path.join(PERP, "arena_jury_auto_state.json")
PROMPT_DIR = os.path.join(PERP, "arena_agent", "jury_prompts")
RESULT_DIR = os.path.join(PERP, "arena_agent", "jury_results")
YPP_DAILY = os.path.join(BASE, "youtube", "ypp_daily.jsonl")
KILL_DATE = "2026-12-08"
YPP_DEADLINE = "2027-01-31"


def _now():
    return datetime.now(timezone.utc)


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(s):
    atomic_write_json(STATE, s)


def _api(url):
    """YouTube Data API GET，返回解析后的 dict，失败返回 None。"""
    sys.path.insert(0, os.path.join(BASE, "youtube"))
    from yt_upload import _load, _req, _refresh
    d = _load()
    try:
        token = _refresh(d)  # 用 refresh_token 换有效 access_token
    except Exception:
        token = d.get("token")
    if not token:
        return None
    try:
        return json.load(_req(url, token))
    except Exception:
        return None


def _recent_uploads(limit=10):
    """[(video_id, published_at, title, description)] 近期上传。"""
    try:
        ch = _api("https://www.googleapis.com/youtube/v3/channels?part=contentDetails&mine=true")
        items = (ch or {}).get("items") or []
        if not items:
            return None
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        r = _api("https://www.googleapis.com/youtube/v3/playlistItems"
                 "?part=snippet,contentDetails&playlistId=%s&maxResults=%d" % (uploads, limit)) or {}
        out = []
        for it in r.get("items", []):
            out.append((it["contentDetails"]["videoId"],
                        datetime.fromisoformat(it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00")),
                        it["snippet"].get("title", ""),
                        it["snippet"].get("description", "")))
        return out
    except Exception:
        return None


def _video_details(vids):
    """{video_id: (duration_sec, privacy)}。"""
    try:
        out = {}
        for i in range(0, len(vids), 50):
            chunk = vids[i:i + 50]
            r = _api("https://www.googleapis.com/youtube/v3/videos?part=contentDetails,status&id=" + ",".join(chunk)) or {}
            for it in r.get("items", []):
                dur = it["contentDetails"].get("duration", "PT0S")
                m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
                h, mi, s = (int(x) if x else 0 for x in m.groups()) if m else (0, 0, 0)
                out[it["id"]] = (h * 3600 + mi * 60 + s, it["status"].get("privacyStatus", "?"))
        return out
    except Exception:
        return {}


def _video_views(vids):
    try:
        out = {}
        for i in range(0, len(vids), 50):
            chunk = vids[i:i + 50]
            r = _api("https://www.googleapis.com/youtube/v3/videos?part=statistics&id=" + ",".join(chunk)) or {}
            for it in r.get("items", []):
                out[it["id"]] = int(it["statistics"].get("viewCount", 0))
        return out
    except Exception:
        return {}


def _newest_srt_head(n=800):
    import glob
    cands = sorted(glob.glob(os.path.join(PERP, "ai_unhinged", "*", "build", "*.srt"))
                   + glob.glob(os.path.join(PERP, "ai_unhinged", "*", "*.srt")),
                   key=os.path.getmtime, reverse=True)
    if not cands:
        return "(无字幕文件)"
    try:
        txt = open(cands[0], encoding="utf-8").read()
        txt = re.sub(r"\d+\n\d{2}:.*?\n", "", txt)  # 去时间轴
        return txt[:n]
    except Exception:
        return "(字幕读取失败)"


def _dispatch(trigger, prompt_text):
    """经 VM agent-browser 提交 jury prompt，返回结果文件路径（失败返回 None）。"""
    ts = _now().strftime("%Y%m%d%H%M%S")
    pf = os.path.join(PROMPT_DIR, "%s_%s.txt" % (trigger, ts))
    out = os.path.join(RESULT_DIR, "%s_%s.md" % (trigger, ts))
    with open(pf, "w", encoding="utf-8") as f:
        f.write(prompt_text)
    try:
        r = subprocess.run([sys.executable, os.path.join(PERP, "lmarena_agent.py"),
                            "--prompt-file", pf, "--out", out, "--timeout", "1500"],
                           capture_output=True, text=True, timeout=1750)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 200:
            print("DISPATCH_OK %s -> %s" % (trigger, out))
            return out
        print("DISPATCH_FAIL %s: %s" % (trigger, (r.stderr or "")[-200:]))
        return None
    except Exception as e:
        print("DISPATCH_EXC %s: %s" % (trigger, str(e)[:200]))
        return None


def trig_ep_prejury(st):
    """新 private 长视频未陪审。"""
    ups = _recent_uploads(10)
    if not ups:
        return
    vids = [v[0] for v in ups]
    det = _video_details(vids)
    reviewed = set(st.get("reviewed_ep_ids", []))
    now = _now()
    for vid, pub, title, desc in ups:
        if vid in reviewed:
            continue
        dur, priv = det.get(vid, (0, "?"))
        if dur < 600 or priv != "private":
            continue
        if (now - pub).days > 7:
            continue
        prompt = (
            "你是陪审团召集人。对以下未公开长视频成片做上线前陪审团预审：\n"
            "标题：%s\n描述：%s\n开场字幕：%s\n"
            "请组织多模型独立评审，给出：\n"
            "1. Hook 评分（前30秒，1-10分）+ 具体改进点\n"
            "2. 标题评分（1-10分）+ 3个备选标题\n"
            "3. 缩略图建议（文字/构图/表情三要素）\n"
            "4. 总 verdict：GO（可上线）/ FIX（列出必须改的点）/ HOLD（说明原因）\n"
            "只输出结构化结论，不输出过程讨论。"
            % (title, desc[:500], _newest_srt_head()))
        res = _dispatch("ep_prejury", prompt)
        if res:
            reviewed.add(vid)
            st["reviewed_ep_ids"] = sorted(reviewed)
            st["last_ep_prejury"] = {"video_id": vid, "result": res, "at": now.isoformat()}


def trig_title_rank(st):
    import glob
    files = sorted(glob.glob(os.path.join(PERP, "ai_unhinged", "title_options_*.json")))
    ranked = set(st.get("ranked_option_files", []))
    for fp in files:
        if fp in ranked:
            continue
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        titles = d.get("titles", [])
        if len(titles) < 2:
            continue
        thumbs = d.get("thumbnails", [])
        prompt = (
            "你是陪审团召集人。对以下标题/缩略图备选做排序优选：\n"
            "剧集：%s\n备选标题：\n%s\n备选缩略图描述：\n%s\n"
            "受众：英文 AI 喜剧观众，频道 @karenvsai。\n"
            "请多模型独立打分后排序，输出：排名、每项 1-10 分、"
            "第一名胜出的核心理由（一句话）。"
            % (d.get("episode", "?"),
               "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(titles)),
               "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(thumbs)) or "(无缩略图备选)"))
        res = _dispatch("title_rank", prompt)
        if res:
            ranked.add(fp)
            st["ranked_option_files"] = sorted(ranked)
            try:
                os.rename(fp, fp + ".consumed")
            except Exception:
                pass


def _ypp_pace():
    """返回 (current_hours, pace_14d, required_pace)。失败返回 None。"""
    try:
        rows = []
        with open(YPP_DAILY, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        if len(rows) < 2:
            return None
        def _h(r):
            try:
                return float(r["diagnostic_365d"]["videoOnDemand_hours_DIAGNOSTIC_ONLY"])
            except Exception:
                return None
        valid = [(r, _h(r)) for r in rows]
        valid = [(r, h) for r, h in valid if h is not None]
        if len(valid) < 2:
            return None
        r_new, now_h = valid[-1]
        r_old, old_h = valid[0]
        span = (datetime.fromisoformat(r_new["date"]) - datetime.fromisoformat(r_old["date"])).days
        if span < 10:
            return None  # 数据窗口不足 10 天，不做"连续2周不达标"判定
        days = max(1, span)
        pace = (now_h - old_h) / days
        days_left = max(1, (datetime.fromisoformat(YPP_DEADLINE).date() - _now().date()).days)
        required = max(0.0, (4000 - now_h)) / days_left
        return now_h, pace, required
    except Exception:
        return None


def trig_kill(st):
    now = _now()
    # 日期触发：one-shot
    if now.strftime("%Y-%m-%d") >= KILL_DATE and not st.get("kill_date_fired"):
        _kill_jury(st, "日期到达 kill 线前 7 天（2026-12-08）")
        st["kill_date_fired"] = now.isoformat()
        return
    # metric 触发：14天 pace < 30% 所需
    last = st.get("kill_metric_last_fired")
    if last:
        try:
            if (now - datetime.fromisoformat(last)).days < 14:
                return
        except Exception:
            pass
    p = _ypp_pace()
    if not p:
        return
    now_h, pace, required = p
    if required > 0 and pace < required * 0.3:
        _kill_jury(st, "连续14天 pace %.1f h/天 < 所需 %.1f h/天 的 30%%" % (pace, required))
        st["kill_metric_last_fired"] = now.isoformat()


def _kill_jury(st, reason):
    ups = _recent_uploads(10) or []
    det = _video_details([v[0] for v in ups]) if ups else {}
    eps = [v[2] for v in ups if det.get(v[0], (0, ""))[0] >= 600][:4]
    subs = 533
    try:
        rows = [json.loads(l) for l in open(YPP_DAILY, encoding="utf-8") if l.strip()]
        subs = rows[-1].get("subs", subs)
    except Exception:
        pass
    p = _ypp_pace()
    now_h, pace, required = p if p else (0, 0, 0)
    prompt = (
        "你是独立仲裁陪审团。频道 @karenvsai 的 YPP 冲刺 kill 线评估（触发原因：%s）：\n"
        "当前：%s 订阅，%.0f 诊断观看小时（目标 4000 小时，截止 2027-01-31）\n"
        "实际 pace：%.1f h/天，需要 pace：%.1f h/天\n"
        "已发布正片：%s\n"
        "请给出独立 verdict（三选一）：KILL（停长视频转 Plan C）/ CONTINUE（继续当前节奏）/ "
        "PIVOT（转方向，说明转什么）。必须给出量化依据，不接受模糊建议。"
        % (reason, subs, now_h, pace, required, "; ".join(eps) or "(无)"))
    res = _dispatch("kill_arbitration", prompt)
    if res:
        st["last_kill_verdict"] = {"result": res, "at": _now().isoformat(), "reason": reason}


def trig_collapse(st):
    last = st.get("collapse_last_fired")
    if last:
        try:
            if (_now() - datetime.fromisoformat(last)).days < 7:
                return
        except Exception:
            pass
    ups = _recent_uploads(5)
    if not ups:
        return
    now = _now()
    vids = [v[0] for v in ups[:2]]
    views = _video_views(vids)
    pubs = {v[0]: v[1] for v in ups}
    bad = [vid for vid in vids
           if (now - pubs[vid]).total_seconds() >= 48 * 3600 and views.get(vid, 0) < 50]
    if len(bad) == 2:
        ev = "; ".join("%s=%s播放" % (vid, views.get(vid, 0)) for vid in bad)
        prompt = (
            "你是紧急诊断陪审团。频道 @karenvsai 最近 2 条发布视频 48h 播放全部 <50"
            "（%s），远低于历史基线。请快速诊断：分发问题/内容问题/选题问题？"
            "按可能性排序，给出 1 条 24 小时内可执行的止血动作。要求简短 actionable。"
            % ev)
        res = _dispatch("collapse_jury", prompt)
        if res:
            st["collapse_last_fired"] = now.isoformat()


def trig_teardown(st):
    q = "%dQ%d" % (_now().year, (_now().month - 1) // 3 + 1)
    if st.get("last_quarter_teardown") == q:
        return
    prompt = (
        "你是竞品拆解陪审团。对标 AI 喜剧赛道头部账号（dandingles 等），"
        "输出本季度（%s）打法变化：\n"
        "1. 他们本季度爆款的 3 个共同特征；\n"
        "2. @karenvsai 可复制的 1 个打法；\n"
        "3. 必须避开的 1 个坑。\n"
        "约束（D20261010-010）：只分析公开可观察的内容结构形态；"
        "严禁点名攻击、人身评价、诽谤性表述；不做无根据推测。"
        "只输出结构化结论。" % q)
    res = _dispatch("competitor_teardown", prompt)
    if res:
        st["last_quarter_teardown"] = q


def main():
    st = _load_state()
    for fn in (trig_ep_prejury, trig_title_rank, trig_kill, trig_collapse, trig_teardown):
        try:
            fn(st)
        except Exception as e:
            print("TRIGGER_EXC %s: %s" % (fn.__name__, str(e)[:200]))
    _save_state(st)
    print("arena jury auto done")


if __name__ == "__main__":
    main()
