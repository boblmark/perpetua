#!/usr/bin/env python3
"""48h 观众验证环（D20261010-008，2026-10-10 全权议会落地）。

状态机：
  teaser_validation --(submit, B'限流)--> teaser_generating
    --(muse-main done + QC通过 + 公开发布)--> teaser_published {video_id, published_at}
    --(48h后查数)--> GREEN: review_passed + format=longform + promoted_by_teaser
                     RED:   archived_permanent

诚实说明（v1 边界）：
  1. teaser 为 8s 竖屏 Short（muse-main 实际产能），非议会规格的 30-60s；
     验证环机制相同，时长待多 clip 拼接能力上线后再升级。
  2. VvS（viewed-vs-swiped）无 Analytics API 口径；GREEN 用
     averageViewPercentage>=75%（API 实测）+ 48h views>=30（分发证明）双门。
  3. B' 限流（滚动7天≤2条 Shorts）为硬约束，验证吞吐上限 2 条/周。
  4. GREEN 只进正片备选池（episode_backlog.json），20 分钟正片制作仍走
     ai_unhinged 独立流程，本模块不自动生成长视频。
"""
import json
import os
import re
import sys
import subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json

BASE = "/home/hatch/data/perpetua"
DATA = "/home/hatch/data"
QUEUE = os.path.join(BASE, "pipeline_queue.json")
EP_BACKLOG = os.path.join(BASE, "ai_unhinged", "episode_backlog.json")
sys.path.insert(0, BASE)
sys.path.insert(0, DATA)
# D20261011-001 P1: pipeline_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import queue_db

GREEN_AVD = 75.0   # averageViewPercentage >= 75%
# D20261011-002 B-稳 / Ask Studio 2026-10-11 实测 verdict：
# 30 播放是噪声不是信号（95% CI 下留存误差 ±15–18%）。
# GREEN/RED 判决至少 200 播放；<200 判 INCONCLUSIVE（没测开，不是 RED）。
GREEN_VIEWS = 200  # 48h views >= 200 才做 GREEN/RED 判决
# INCONCLUSIVE 悬置上限：14 天仍 <200 播放 → 判 RED（分发彻底没测开）
INCONCLUSIVE_MAX_AGE_H = 24 * 14
# Shorts 首要门：stayed（未划走）>= 65%（Ask Studio 2026-10-11）。
# 诚实注：YouTube Analytics API 当前不返回 viewed-vs-swiped 口径，
# 本门仅在数据源提供 teaser_stayed_pct 时执行；缺失时记 plog 并跳过，不阻断。
STAYED_THRESHOLD = 65.0


# 2026-10-10 用户纠正：muse-main 单次对话可产出 60 秒视频（6×10s 实证）。
# teaser 按议会 30-60s 规格改为 4 段式（4×10s≈40s），4 个独立 job 拼接。
TEASER_CLIPS = 4
TEASER_SEGMENT_BEATS = ["开场钩子（前10秒，强钩子抓人）", "冲突升级（矛盾加剧）",
                        "高潮/反转（爆点）",
                        "结尾悬念或行动号召（v5.3.1：禁退出跑道——不许拖沓/停顿/淡出/回落开场氛围，"
                        "必须悬念或CTA硬收尾）"]


def _segment_prompt(base_prompt, idx):
    beat = (TEASER_SEGMENT_BEATS[idx] if idx < len(TEASER_SEGMENT_BEATS)
            else "第%d段" % (idx + 1))
    return ("%s\n（本段为%d段式teaser的第%d段：%s；约10秒，竖屏9:16，"
            "与前后段同场景同人物保持视觉连续）"
            % (base_prompt, TEASER_CLIPS, idx + 1, beat))


def _concat_clips(clip_files, out_path):
    """ffmpeg 拼接多段。分辨率统一时尝试 -c copy，否则直接重编码。
    2026-10-10 修：-c copy 曾在分段分辨率不一（720x1280 vs 480x832）时产出
    video 32s / audio 42.7s 的错位文件且通过 QC。现拼后校验音视频时长差，
    >1s 则重编码兜底；分辨率不统一直接走重编码（统一缩放到首段分辨率）。"""
    import subprocess, json, os

    def _probe_streams(p):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=width,height,codec_type,duration",
                 "-of", "json", p],
                capture_output=True, text=True, timeout=30)
            return json.loads(r.stdout or "{}").get("streams", [])
        except Exception:
            return []

    def _av_ok(p):
        ss = _probe_streams(p)
        v = next((s for s in ss if s.get("codec_type") == "video"), {})
        a = next((s for s in ss if s.get("codec_type") == "audio"), {})
        try:
            vd, ad = float(v.get("duration") or 0), float(a.get("duration") or 0)
        except Exception:
            return False
        return bool(vd and ad and abs(vd - ad) <= 1.0)

    def _inputs_ok(files):
        res, no_audio = set(), []
        for f in files:
            ss = _probe_streams(f)
            v = next((s for s in ss if s.get("codec_type") == "video"), {})
            a = next((s for s in ss if s.get("codec_type") == "audio"), {})
            res.add((v.get("width"), v.get("height")))
            if not a:
                no_audio.append(f)
        return res, no_audio

    res_set, no_audio = _inputs_ok(clip_files)
    if no_audio:
        raise RuntimeError("拼接失败: 分段缺音频流 %s" % no_audio[0][:80])
    uniform = len(res_set) == 1
    W, H = next(iter(res_set)) if uniform else (720, 1280)

    lst = out_path + ".txt"
    with open(lst, "w") as f:
        for c in clip_files:
            f.write("file '%s'\n" % c.replace("'", "'\\''"))

    if uniform:
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-c", "copy", out_path],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(out_path) and _av_ok(out_path):
            try:
                os.remove(lst)
            except Exception:
                pass
            return out_path
        plog("concat", "warn", "copy 拼接产物异常（或音视频错位），转重编码")
    else:
        plog("concat", "warn", "分段分辨率不统一 %s，重编码统一到 %dx%d"
             % (sorted(res_set), W, H))
    # 重编码：统一分辨率 + 时间戳归一化
    filt = "".join(
        "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,"
        "crop=%d:%d,setsar=1[v%d];" % (i, W, H, W, H, i)
        for i in range(len(clip_files)))
    filt += "".join("[v%d][%d:a]" % (i, i) for i in range(len(clip_files)))
    filt += "concat=n=%d:v=1:a=1[v][a]" % len(clip_files)
    ins = []
    for c in clip_files:
        ins += ["-i", c]
    r = subprocess.run(
        ["ffmpeg", "-y"] + ins +
        ["-filter_complex", filt, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-movflags", "+faststart", out_path],
        capture_output=True, text=True, timeout=600)
    try:
        os.remove(lst)
    except Exception:
        pass
    if r.returncode != 0 or not os.path.exists(out_path) or not _av_ok(out_path):
        raise RuntimeError("拼接失败: " + (r.stderr or "")[-300:])
    return out_path


def _now():
    return datetime.now(timezone.utc)


def _iso():
    return _now().isoformat()


def load_queue():
    # D20261011-001 P1: pipeline_queue 已迁 SQLite（QUEUE 路径仅留作注释）
    return queue_db.pipeline_load()


def save_queue(items):
    queue_db.pipeline_save(items)  # D20261011-001 P1: 原子事务


def plog(stage, level, msg):
    print("[teaser][%s][%s] %s" % (stage, level, msg))


def submit_teaser_jobs():
    """teaser_validation → dispatcher 提交 → teaser_generating。B' 限流。"""
    from bprime_throttle import throttle_allows
    import gen_video_musemain as gvm
    queue = load_queue()
    # 在途上限：generating + 已发布未出 verdict 的 ≤3，避免无限积压
    in_flight = sum(1 for x in queue
                    if x.get("status") in ("teaser_generating",)
                    or (x.get("status") == "teaser_published"
                        and not x.get("teaser_verdict")))
    max_new = max(0, 3 - in_flight)
    n = 0
    for item in sorted(queue, key=lambda x: -(x.get("review_score") or 0)):
        if item.get("status") != "teaser_validation" or item.get("muse_job_id"):
            continue
        if n >= max_new:
            plog("submit", "ok", "在途已达上限，本轮不再提交")
            break
        allowed, reason = throttle_allows()
        if not allowed:
            plog("submit", "ok", "B' 限流：%s" % reason)
            break
        prompt = item.get("prompt", "")
        if not prompt:
            plog("submit", "error", "无 prompt，跳过 %s" % item.get("topic"))
            continue
        jid = "teaser-%s-%s" % (_now().strftime("%Y%m%d%H%M%S"),
                                os.urandom(3).hex())
        muse_job_ids = []
        submit_ok = True
        for seg in range(TEASER_CLIPS):
            seg_jid = "%s-s%d" % (jid, seg)
            try:
                mj = gvm.submit(_segment_prompt(prompt, seg), seg_jid)
                muse_job_ids.append(mj)
            except Exception as e:
                plog("submit", "error", "dispatcher 提交失败 %s seg%d: %s"
                     % (item.get("topic"), seg, str(e)[:120]))
                submit_ok = False
                break
        if not submit_ok or len(muse_job_ids) != TEASER_CLIPS:
            # 2026-10-10：提交异常一律视为通道级故障，整轮停摆。
            # 继续试下一个选题只会逐个留下“已建 job 但 item 未标记”的孤儿 job
            #（dispatcher 侧 job 已创建、id 已丢失，muse-main 照常消耗预算生成）。
            # 下一轮（30min）重试。
            plog("submit", "ok", "通道异常，本轮停止提交，下轮重试")
            break
        item["job_id"] = jid
        item["muse_job_ids"] = muse_job_ids  # 多段；老数据用 muse_job_id 单段
        item["teaser_clips"] = TEASER_CLIPS
        # 实验格式：前 3 条 40s 标记 experimental，走浏览器快检（v5.3.1）
        try:
            import json as _j
            _exp = _j.load(open("/home/hatch/data/perpetua/teaser_experiment.json"))
            _done = len(_exp.get("completed", []))
            if _done < 3:
                item["experimental"] = True
                item["experiment_n"] = _done + 1
        except Exception:
            pass
        item["gen_backend"] = "musemain"
        item["teaser_submitted_at"] = _iso()
        item["status"] = "teaser_generating"
        n += 1
        plog("submit", "ok", "teaser 已提交(%d段) %s"
             % (TEASER_CLIPS, item.get("topic", "")[:30]))
    if n:
        save_queue(queue)
    return n


def _run_qc(video_path, title, multi_clip=False):
    sys.path.insert(0, BASE)
    try:
        from pre_upload_qc import run_qc
    except Exception as e:
        return False, "qc import 失败: %s" % str(e)[:100]
    try:
        # 多段 teaser（40s）：时长上限 65s + 跳过 loop 检查（v5.3.1）；单段 8s 走默认
        kw = {"max_duration": 65, "check_loop": False} if multi_clip else {}
        # 2026-10-10 回归修复：run_qc 返回 dict（passed/rejects/warnings），不是 (ok, msg) 元组；
        # 旧写法 run_qc(...)[:2] 会抛 KeyError: slice → 所有 teaser 在 QC 环节被误判失败
        r = run_qc(video_path, title=title, **kw)
        ok = bool(r.get("passed"))
        rej = r.get("rejects") or []
        msg = "; ".join(rej[:2]) if rej else "体验分 %s/100" % r.get("experience_score")
        return ok, msg[:500]
    except Exception as e:
        return False, "qc 异常: %s" % str(e)[:150]


def _bprime_allows_publish():
    """发布前 B' 限流复查。返回 (allowed, reason)。

    2026-10-10 修：此前 B' 只在 submit_teaser_jobs 执行，发布路径
    （collect 主路径 + _collect_awaiting_check_publish）可绕过 72h 间隔/
    滚动7天≤2 直接公开发布，属待修的状态机缺口（当日日志已记录）。
    现 submit 与 publish 双执行；检查异常时 fail-closed。
    被限流的发布不判失败，留待下轮重试（不绕过、不丢弃）。
    """
    try:
        from bprime_throttle import throttle_allows
        return throttle_allows()
    except Exception as e:
        return False, "限流检查异常，fail-closed: %s" % str(e)[:80]


def _upload_public(video_file, title, description, topic):
    """经 mcp_server.youtube_upload 公开发布（全部硬门禁照常）。返回 video_id 或 ''。"""
    vid, _reason = _upload_public_with_reason(video_file, title, description, topic)
    return vid


# 2026-10-16 新增：永久失败 vs 临时失败分类（门铃 teaser #3 卡 6 天/290 轮教训）。
# 永久拒绝（标题超长/原创度撞车/审批未过/合规拦截/爆款分不足）靠重试永远好不了，
# 必须标记终态+升级，不能静默空转。唯一的时间型临时拒绝是 [gate1:错峰]。
_PERMANENT_REJECT_MARKERS = (
    "[gateway:",          # D1 网关结构性拒绝：title_long/占位标题/标签不足等
    "[原创度:",            # 90 天设备/钩子/笑点撞车
    "[pipeline_approval]", # 管线审批未过
    "[blocked]",          # 合规检查 fail-closed
    "[pre-upload-qc]",    # 上传前 QC 硬失败
    "爆款分",              # jev/v2 爆款门槛不足
)
_TRANSIENT_REJECT_MARKERS = (
    "[gate1:错峰]",        # 4 小时/120 分钟发布间隔门：时间到了自然解除
    "[gateway:spacing]",  # 2026-10-18 修：120 分钟发布间隔门（gateway 间隔拒绝），
                          # 时间型临时失败。注意检查顺序：transient 先于 "[gateway:"
                          # 永久前缀匹配，否则会被误判 permanent（robot lawnmower
                          # 2026-10-17 曾因此被错打入 teaser_publish_blocked 终态）。
)


def _classify_upload_failure(reason):
    """返回 'permanent' / 'transient' / 'unknown'。"""
    r = str(reason or "")
    if any(m in r for m in _TRANSIENT_REJECT_MARKERS):
        return "transient"
    if any(m in r for m in _PERMANENT_REJECT_MARKERS):
        return "permanent"
    return "unknown"


# 未知原因连续失败上限：24 轮（约 12h）仍失败 → 按永久处理并升级，
# 防止未知永久失败无限空转。
_UNKNOWN_FAIL_MAX_ATTEMPTS = 24


def _escalate_publish_blocked(item, reason, kind):
    """永久/超限失败升级：写 escalation inbox（12h 去重+风暴限流由 escalate 负责）。"""
    try:
        import sys as _sys, os as _os
        _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        from graded_assertions import escalate
        escalate(
            checker="teaser_validate",
            subject=str(item.get("topic", ""))[:40],
            condition="teaser_publish_blocked",
            severity="P2",
            detail="kind=%s reason=%s file=%s" % (
                kind, str(reason)[:200], str(item.get("teaser_video_file", ""))[:80]),
        )
    except Exception as e:
        plog("escalate", "error", "升级写入失败: %s" % str(e)[:80])


def _upload_public_with_reason(video_file, title, description, topic):
    """与 _upload_public 同逻辑，但返回 (video_id, reason)。
    成功时 reason=''；失败时 reason 为 youtube_upload 的拒绝原文（或异常摘要）。"""
    venv_py = "/home/hatch/data/mcp_server/venv/bin/python"
    code = (
        "import sys; sys.path.insert(0, '/home/hatch/data/mcp_server');"
        "import server, json;"
        f"r = server.youtube_upload({video_file!r}, {title!r}, {description!r}, "
        f"tags='Karen,InstantKarma,Shorts,Comedy,Viral', language='en', "
        f"ai_disclosure=True, privacy='public');"
        "print(json.dumps({'result': r}, ensure_ascii=False))"
    )
    r = subprocess.run([venv_py, "-c", code], capture_output=True,
                       text=True, timeout=300)
    out = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else "{}"
    try:
        res = json.loads(out).get("result", "")
    except Exception as e:
        return "", "upload_subprocess_parse_error: %s" % str(e)[:100]
    if res and not res.startswith("["):
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", res)
        if m:
            return m.group(1), ""
        if re.match(r"^[\w-]{11}$", res.strip()):
            return res.strip(), ""
    reason = str(res)[:300] if res else "empty_result"
    plog("upload", "error", "发布失败: %s" % reason[:150])
    return "", reason


def collect_teaser_results():
    """轮询 muse-main → QC → 公开发布 → teaser_published。"""
    import gen_video_musemain as gvm
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("status") != "teaser_generating":
            continue
        # B' 限流推迟态：成品已就绪，直接重试发布（跳过轮询/拼接/QC）
        # 2026-10-10 修：发布路径补 B' 检查，推迟不判失败。
        if item.get("teaser_publish_deferred") and item.get("teaser_video_file"):
            vf = item["teaser_video_file"]
            topic30 = str(item.get("topic", ""))[:30]
            if vf and os.path.exists(vf):
                allowed2, breason2 = _bprime_allows_publish()
                if not allowed2:
                    plog("collect", "ok", "B' 限流仍在，发布继续推迟 %s：%s"
                         % (topic30, breason2))
                    continue
                # 2026-10-16 P2-5 修（四脑议会 anti-idle）：defer 72h 年龄上限
                _defer_at = item.get("teaser_publish_deferred_at", "")
                try:
                    _ddt = datetime.fromisoformat(str(_defer_at).replace("Z", "+00:00"))
                    _dh = (datetime.now(timezone.utc) - _ddt).total_seconds() / 3600 \
                        if _ddt.tzinfo else 0
                except Exception:
                    _dh = 0
                if _dh > 72:
                    item["status"] = "teaser_failed"
                    item["teaser_error"] = "defer_72h_exceeded:B' 限流推迟超 72h"
                    item.pop("teaser_publish_deferred", None)
                    item.pop("teaser_publish_deferred_at", None)
                    plog("collect", "error", "teaser 推迟超 72h 转失败 %s" % topic30)
                    _escalate_publish_blocked(item, item["teaser_error"], "deferred_timeout")
                    changed = True
                    continue
                # 2026-10-16 P2-4 修：用 with_reason 版，保留拒绝原文
                vid, _reason = _upload_public_with_reason(
                    vf, item.get("title", ""),
                    item.get("description", ""),
                    item.get("topic", ""))
                item.pop("teaser_publish_deferred", None)
                item.pop("teaser_publish_deferred_at", None)
                if not vid:
                    item["status"] = "teaser_failed"
                    item["teaser_error"] = "公开发布失败: " + str(_reason)[:300]
                    plog("collect", "error", "teaser 发布失败 %s" % topic30)
                else:
                    item["status"] = "teaser_published"
                    item["teaser_video_id"] = vid
                    item["teaser_published_at"] = _iso()
                    plog("collect", "ok", "teaser 已公开发布 %s → https://youtu.be/%s"
                         % (topic30, vid))
                    try:
                        from bprime_throttle import record_publish
                        record_publish(vid, item.get("title", ""))
                    except Exception:
                        pass
                changed = True
                continue
            # 成品文件丢失：清推迟标记，回落正常轮询重建
            item.pop("teaser_publish_deferred", None)
            item.pop("teaser_publish_deferred_at", None)
        # 兼容：新数据 muse_job_ids（多段）/ 老数据 muse_job_id（单段 8s）
        job_ids = item.get("muse_job_ids") or (
            [item.get("muse_job_id")] if item.get("muse_job_id") else [])
        if not job_ids:
            continue
        clip_files = []
        all_done = True
        for mj in job_ids:
            try:
                state, info = gvm.check(mj)
            except Exception as e:
                plog("collect", "error", "轮询异常 %s: %s"
                     % (item.get("topic"), str(e)[:100]))
                all_done = False
                break
            if state == "pending":
                all_done = False
                break
            if state == "failed":
                item["status"] = "teaser_failed"
                item["teaser_error"] = "分段生成失败: " + str(info)[:200]
                plog("collect", "error", "teaser 生成失败 %s: %s"
                     % (item.get("topic"), str(info)[:100]))
                changed = True
                all_done = False
                break
            clip_files.append(info)
        if not all_done:
            continue
        if item.get("status") == "teaser_failed":
            continue
        # done → 多段拼接（单段直接用）
        try:
            if len(clip_files) > 1:
                out = "/home/hatch/data/perpetua/videos/%s-teaser.mp4" % item.get("job_id", "t")
                video_file = _concat_clips(clip_files, out)
                plog("collect", "ok", "teaser %d 段已拼接 %s"
                     % (len(clip_files), item.get("topic", "")[:30]))
            else:
                video_file = clip_files[0]
        except Exception as e:
            item["status"] = "teaser_failed"
            item["teaser_error"] = "拼接失败: " + str(e)[:200]
            plog("collect", "error", "teaser 拼接失败 %s" % item.get("topic"))
            changed = True
            continue
        is_multi = len(clip_files) > 1
        ok, msg = _run_qc(video_file, item.get("title", ""), multi_clip=is_multi)
        # 实验格式前 3 条 40s：QC 通过后转浏览器快检，不自动公开发布（v5.3.1）
        if ok and is_multi and item.get("experimental") and not item.get("browser_checked"):
            item["status"] = "teaser_awaiting_check"
            item["teaser_video_file"] = video_file
            plog("collect", "ok", "实验 teaser QC 通过，转浏览器快检 %s"
                 % item.get("topic", "")[:30])
            changed = True
            continue
        if not ok:
            item["status"] = "teaser_failed"
            item["teaser_error"] = "QC 未过: " + msg
            plog("collect", "error", "teaser QC 未过 %s: %s"
                 % (item.get("topic"), msg[:100]))
            changed = True
            continue
        # B' 限流：发布阶段同样执行（2026-10-10 修）。被限流不判失败，
        # 成品文件保留，下轮由推迟态直接重试发布。
        allowed, breason = _bprime_allows_publish()
        if not allowed:
            item["teaser_video_file"] = video_file
            item["teaser_publish_deferred"] = breason
            item["teaser_publish_deferred_at"] = _iso()
            plog("collect", "ok", "B' 限流，teaser 发布推迟下轮 %s：%s"
                 % (item.get("topic", "")[:30], breason))
            changed = True
            continue
        # 2026-10-16 P2-4 修：用 with_reason 版，保留拒绝原文
        vid, _reason = _upload_public_with_reason(
            video_file, item.get("title", ""),
            item.get("description", ""),
            item.get("topic", ""))
        if not vid:
            item["status"] = "teaser_failed"
            item["teaser_error"] = "公开发布失败: " + str(_reason)[:300]
            changed = True
            continue
        item["status"] = "teaser_published"
        item["teaser_video_id"] = vid
        item["teaser_published_at"] = _iso()
        item["teaser_video_file"] = video_file
        plog("collect", "ok", "teaser 已公开发布 %s → https://youtu.be/%s"
             % (item.get("topic", "")[:30], vid))
        try:
            from bprime_throttle import record_publish
            record_publish(vid, item.get("title", ""))
        except Exception:
            pass
        changed = True
    # v5.3.1 人工快检门：人工检查已过的 teaser 由本轮按硬门禁尝试发布
    if _collect_awaiting_check_publish(queue):
        changed = True
    if changed:
        save_queue(queue)


def _analytics_for_video(video_id, pub_at=None):
    """返回 (averageViewPercentage, views) 或 (None, None)。

    2026-10-17 修：查询窗口改为以发布为锚点的 [pub_date, pub_date+3d]
    （48h 窗口 +1 天 Analytics 回传缓冲）。之前用滚动最近 3 天，视频
    发布超过 3 天后恒返回空 rows → "数据未回传" 死循环，48h 判决永不
    到达，14 天超时也因 verdict 恒为空而失效。
    pub_at 为空时回退到滚动 3 天（kill-switch 等 24-48h 内场景）。
    """
    sys.path.insert(0, os.path.join(DATA, "youtube"))
    from yt_upload import _load, _refresh
    import urllib.request, urllib.parse
    d = _load()
    try:
        token = _refresh(d)
    except Exception:
        return None, None
    pub_date = None
    if pub_at:
        try:
            pub_date = datetime.fromisoformat(pub_at).date()
        except Exception:
            pub_date = None
    if pub_date:
        start = pub_date.isoformat()
        end = (pub_date + timedelta(days=3)).isoformat()
    else:
        end = _now().date().isoformat()
        start = (_now() - timedelta(days=3)).date().isoformat()
    params = {"ids": "channel==MINE", "startDate": start, "endDate": end,
              "metrics": "views,averageViewPercentage",
              "dimensions": "video",
              "filters": "video==%s" % video_id}
    url = ("https://youtubeanalytics.googleapis.com/v2/reports?"
           + urllib.parse.urlencode(params))
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": "Bearer " + token})
        # 2026-10-18 修：出口代理偶发截断连接（IncompleteRead / remote closed，
        # 实测截断字节数恰为完整响应长度），函数内自带 3 轮重试+退避，
        # 不让偶发抖动浪费整轮。3 轮全败才回 (None, None) 由上层按未知失败处理。
        rows = None
        last_err = None
        for attempt in range(3):
            try:
                rows = json.load(
                    urllib.request.urlopen(req, timeout=30)).get("rows", [])
                last_err = None
                break
            except Exception as e:
                last_err = e
                import time as _t
                _t.sleep(3 * (attempt + 1))
        if last_err is not None:
            raise last_err
        if not rows:
            return None, None
        # rows: [video, views, averageViewPercentage]
        return float(rows[0][2]), int(rows[0][1])
    except Exception as e:
        plog("metrics", "error", "Analytics 查询失败 %s: %s" % (video_id, str(e)[:100]))
        return None, None


def mark_teaser_manual_check_passed(topic_substr, verify_fixes=None):
    """人工浏览器快检通过后调用（Dash 手工执行）。

    同时设置 browser_checked=True 与上传网关要求的
    teaser_manual_check="passed"。2026-10-10 修：两字段曾不一致，
    导致 server.py _verify_pipeline_approval 以 [pipeline_approval]
    拒绝已快检 teaser 的发布。以后只调这一个函数，不手工改 JSON。
    D20261017-00X KILL#4：verify_fixes 非空时（reviewer_fixes.json 中
    该 topic 的 {"title","desc","prompt"}），先跑逐字比对核验；
    核验不通过 → 拒绝标记 ready（返回 False），差异记 item 字段。
    返回 True=找到并标记。
    """
    q = load_queue()
    items = q if isinstance(q, list) else q.get("items", [])
    hit = False
    for it in items:
        if topic_substr in str(it.get("topic", "")):
            if verify_fixes:
                try:
                    from reviewer_fix_verify import verify_item_against_reviewer_fixes
                    ok, report = verify_item_against_reviewer_fixes(it, verify_fixes)
                    it["verbatim_verify"] = {
                        "at": report["at"], "ok": ok,
                        "fields": report["fields"],
                        "compliance_adjustments": report.get("compliance_adjustments", []),
                    }
                    if not ok:
                        plog("manual_check", "error",
                             "逐字核验不通过，拒绝标记 ready %s" % topic_substr)
                        continue
                except Exception as e:
                    plog("manual_check", "error", "核验异常: %s" % str(e)[:100])
                    continue
            it["browser_checked"] = True
            it["teaser_manual_check"] = "passed"
            # D20261017-00X W3：ready 标记时间戳，供逐字核验跳过计数
            it["teaser_manual_check_at"] = _iso()
            hit = True
    if hit:
        save_queue(q)
        plog("manual_check", "ok", "已标记人工快检通过 %s" % topic_substr)
    return hit


def _collect_awaiting_check_publish(queue):
    """人工浏览器检查已通过（browser_checked=True）的 teaser，cron 轮询时按
    全部硬门禁公开发布（v5.3.1 人工快检门：检查由 Dash 人工完成，发布时机由
    cron + 硬门禁（如 120 分钟间隔门）决定，被拒则留待下轮）。"""
    changed = False
    for item in queue:
        if item.get("status") != "teaser_awaiting_check" or not item.get("browser_checked"):
            continue
        # 2026-10-11 用户批准：teaser_hold 的条目暂停自动发布（如等题材回暖），
        # 由 daily-topic-feedback 在题材解禁时自动释放
        if item.get("teaser_hold"):
            continue
        video_file = item.get("teaser_video_file")
        if not video_file:
            continue
        # B' 限流：人工快检发布路径同样执行（2026-10-10 修）。
        # 被限流不改状态，下轮重试；绝不绕过。
        allowed, breason = _bprime_allows_publish()
        if not allowed:
            plog("collect", "ok", "B' 限流，人工快检 teaser 发布推迟下轮 %s：%s"
                 % (item.get("topic", "")[:30], breason))
            continue
        vid, fail_reason = _upload_public_with_reason(
            video_file, item.get("title", ""),
            item.get("description", ""), item.get("topic", ""))
        if not vid:
            # 2026-10-16 修：永久失败不再静默空转。门铃 teaser #3 曾因此卡 6 天/290 轮。
            kind = _classify_upload_failure(fail_reason)
            attempts = int(item.get("teaser_publish_attempts", 0)) + 1
            item["teaser_publish_attempts"] = attempts
            item["teaser_last_fail_reason"] = str(fail_reason)[:300]
            if kind == "transient":
                plog("collect", "ok", "临时门禁（如 120min 间隔），下轮重试 %s"
                     % item.get("topic", "")[:30])
                changed = True
                continue
            if kind == "unknown" and attempts < _UNKNOWN_FAIL_MAX_ATTEMPTS:
                plog("collect", "ok", "未知原因失败（第 %d 轮），下轮重试 %s：%s"
                     % (attempts, item.get("topic", "")[:30], str(fail_reason)[:80]))
                changed = True
                continue
            # permanent，或 unknown 超过 24 轮上限 → 终态 + 升级，不再重试
            item["status"] = "teaser_publish_blocked"
            item["teaser_block_kind"] = kind
            item["teaser_block_reason"] = str(fail_reason)[:300]
            item["teaser_blocked_at"] = _iso()
            plog("collect", "error", "发布永久阻塞，转终态 %s：%s"
                 % (item.get("topic", "")[:30], str(fail_reason)[:120]))
            _escalate_publish_blocked(item, fail_reason, kind)
            changed = True
            continue
        item["status"] = "teaser_published"
        item["teaser_video_id"] = vid
        item["teaser_url"] = "https://youtu.be/" + vid
        item["teaser_published_at"] = _iso()
        item.pop("teaser_publish_attempts", None)
        item.pop("teaser_last_fail_reason", None)
        changed = True
        plog("collect", "ok", "人工快检 teaser 已公开发布 %s %s"
             % (vid, item.get("topic", "")[:30]))
        try:
            from bprime_throttle import record_publish
            record_publish(vid, item.get("title", ""))
        except Exception:
            pass
        try:
            _exp = json.load(open("/home/hatch/data/perpetua/teaser_experiment.json"))
            # 注：queue 的 experiment_n 按 completed[] 计数可能与实验记录错位，
            # 故取首个未发布实验位写入，不按 n 匹配。
            for e in _exp.get("experiments", []):
                if e.get("status") == "published":
                    continue
                e["status"] = "published"
                e["video_id"] = vid
                e["url"] = "https://youtu.be/" + vid
                e["published_at"] = _iso()
                e["topic"] = item.get("topic", "")
                e["manual_check"] = item.get("manual_check", "")
                atomic_write_json("/home/hatch/data/perpetua/teaser_experiment.json", _exp)
                break
        except Exception as e:
            plog("collect", "error", "实验记录更新失败: %s" % str(e)[:80])
    return changed


def check_teaser_killswitch():
    """24h kill-switch（议会 D20261017-00X KILL#2 修订）。

    teaser_published 满 24h 但未满 48h、尚无终局 verdict：
      数据可得且 views == 0 → 提前 RED 永久归档，不占满 48h 窗口。
    数据不可得（avd is None）→ fail-open 跳过，下轮重试，绝不因探针
    故障误杀（Rule 14）。
    48h 终审规则（D20261010-008）不变。
    """
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("status") != "teaser_published":
            continue
        if item.get("teaser_verdict") not in (None, "", "INCONCLUSIVE"):
            continue
        pub_at = item.get("teaser_published_at", "")
        try:
            age_h = (_now() - datetime.fromisoformat(pub_at)).total_seconds() / 3600
        except Exception:
            continue
        if age_h < 24 or age_h >= 48:
            continue
        if item.get("teaser_killswitch_checked_at"):
            continue
        vid = item.get("teaser_video_id", "")
        avd, views = _analytics_for_video(vid)
        if avd is None:
            # 无数据：fail-open，不杀
            plog("killswitch", "ok", "%s 24h 数据未回传，跳过 kill-switch" % vid)
            continue
        item["teaser_killswitch_checked_at"] = _iso()
        item["teaser_views_24h"] = views
        if views == 0:
            item["status"] = "archived_permanent"
            item["teaser_verdict"] = "RED"
            item["teaser_red_reason"] = "killswitch_24h_zero_views"
            plog("killswitch", "ok",
                 "RED %s 24h views=0 → 提前终止归档（kill-switch）" % vid)
            changed = True
        else:
            plog("killswitch", "ok",
                 "%s 24h views=%d avd=%.1f → 存活，继续 48h 终审" % (vid, views, avd))
            changed = True
    if changed:
        save_queue(queue)


def check_teaser_metrics():
    """48h+ 的 teaser 查数 → GREEN/RED/INCONCLUSIVE 流转。

    D20261011-002 B-稳（Ask Studio 2026-10-11 实测）：
      views >= 200 且 avd >= 75 → GREEN（转正片备选）
      views >= 200 且 avd < 75 → RED（永久归档）
      views < 200 → INCONCLUSIVE（没测开：不断案、不归档，留待下轮复查；
        14 天仍 <200 则判 RED，死因=low_distribution_timeout）
      stayed 门（>=65%）：仅在 teaser_stayed_pct 可用时执行，否则跳过。
    """
    queue = load_queue()
    changed = False
    for item in queue:
        if item.get("status") != "teaser_published":
            continue
        # 已有终局 verdict（GREEN/RED）的不再查；INCONCLUSIVE 允许复查
        if item.get("teaser_verdict") not in (None, "", "INCONCLUSIVE"):
            continue
        # INCONCLUSIVE 复查：verdict 为空才进；INCONCLUSIVE 的下轮继续查
        pub_at = item.get("teaser_published_at", "")
        try:
            age_h = (_now() - datetime.fromisoformat(pub_at)).total_seconds() / 3600
        except Exception:
            continue
        if age_h < 48:
            continue
        # INCONCLUSIVE 悬置上限
        if (item.get("teaser_verdict") == "INCONCLUSIVE"
                and age_h > INCONCLUSIVE_MAX_AGE_H):
            vid = item.get("teaser_video_id", "")
            views = item.get("teaser_views_48h", 0)
            item["status"] = "archived_permanent"
            item["teaser_verdict"] = "RED"
            item["teaser_red_reason"] = "low_distribution_timeout"
            plog("metrics", "ok",
                 "RED %s views=%d 14天未达可测样本 → 永久归档（low_distribution）"
                 % (vid, views))
            changed = True
            continue
        vid = item.get("teaser_video_id", "")
        avd, views = _analytics_for_video(vid, pub_at=pub_at)
        if avd is None:
            plog("metrics", "ok", "%s 数据未回传，下轮重试" % vid)
            continue
        item["teaser_avd_48h"] = avd
        item["teaser_views_48h"] = views
        item["teaser_checked_at"] = _iso()
        # stayed 首要门（仅数据源可用时）
        stayed = item.get("teaser_stayed_pct")
        if stayed is not None and stayed < STAYED_THRESHOLD:
            item["status"] = "archived_permanent"
            item["teaser_verdict"] = "RED"
            item["teaser_red_reason"] = "stayed_below_threshold"
            plog("metrics", "ok",
                 "RED %s stayed=%.1f%% < 65%% → 永久归档" % (vid, stayed))
            changed = True
            continue
        if views < GREEN_VIEWS:
            # 没测开：不断案、不归档，下轮继续查
            item["teaser_verdict"] = "INCONCLUSIVE"
            plog("metrics", "ok",
                 "INCONCLUSIVE %s avd=%.1f views=%d <200 → 未测开，下轮复查"
                 % (vid, avd, views))
            changed = True
            continue
        if avd >= GREEN_AVD:
            # GREEN → 正片备选（绕过 ≥85 门）
            item["status"] = "review_passed"
            item["format"] = "longform"
            item["promoted_by_teaser"] = True
            item["teaser_verdict"] = "GREEN"
            plog("metrics", "ok",
                 "GREEN %s avd=%.1f views=%d → 转正片备选" % (vid, avd, views))
            _append_episode_backlog(item)
        else:
            item["status"] = "archived_permanent"
            item["teaser_verdict"] = "RED"
            item["teaser_red_reason"] = "avd_below_threshold"
            plog("metrics", "ok",
                 "RED %s avd=%.1f views=%d → 永久归档" % (vid, avd, views))
        changed = True
    if changed:
        save_queue(queue)


def _append_episode_backlog(item):
    try:
        bl = []
        if os.path.exists(EP_BACKLOG):
            bl = json.load(open(EP_BACKLOG, encoding="utf-8"))
        bl.append({
            "topic": item.get("topic"),
            "title": item.get("title"),
            "teaser_video_id": item.get("teaser_video_id"),
            "teaser_avd_48h": item.get("teaser_avd_48h"),
            "teaser_views_48h": item.get("teaser_views_48h"),
            "review_score": item.get("review_score"),
            "promoted_at": _iso(),
        })
        os.makedirs(os.path.dirname(EP_BACKLOG), exist_ok=True)
        atomic_write_json(EP_BACKLOG, bl)
    except Exception as e:
        plog("backlog", "error", "episode backlog 写入失败: %s" % str(e)[:100])


def main():
    n_sub = submit_teaser_jobs()
    collect_teaser_results()
    check_teaser_killswitch()
    check_teaser_metrics()
    print("teaser_validate done (submit=%d)" % n_sub)


if __name__ == "__main__":
    main()
