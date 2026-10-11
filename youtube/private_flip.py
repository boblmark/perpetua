#!/usr/bin/env python3
"""
Private 预传 → Public 翻转调度器（2026-10-08 用户要求）

新流程：
1. QC 通过后立即上传为 private（不等排期）
2. 到排期时间（动态档，见 publish_slots.json：工作日 23:30/05:30+1，
   周末 22:30/04:00+1，北京时间，Ask Studio 协商确定）自动翻为 public
3. 算法黄金时刻可紧急即时翻 public（抢流量）

状态文件：/home/hatch/data/youtube/private_queue.json
格式：[{"video_id": "...", "title": "...", "scheduled_at": "ISO",
        "slot": "23:30"|"05:30(+1)"|...|"emergency", "status": "waiting"|"published"}]

运行：每 10 分钟由 cron 调用
紧急触发：python3 private_flip.py emergency <video_id>
"""
import json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path("/home/hatch/data")
sys.path.insert(0, str(BASE / "youtube"))
sys.path.insert(0, str(BASE / "perpetua"))
# P0修复4/5/6（2026-10-09）：统一原子写 + 容忍读 + 单飞锁 + 审计日志
from json_safe import atomic_write_json, tolerant_read_json, run_lock, audit_log
# 巡检架构 Commit 1（2026-10-09）：所有可见性写入走中央跃迁门（MUST-1）
from pipeline_state import (transition, is_exempt, VideoState, _admin_revert,
                            _new_record, load_state, save_state,
                            load_index, save_index, _global_state_lock)

# 定时翻转的 gate actor（Tier-3 自动操作者）
# 2026-10-09 起：scheduled_flip 路径豁免 QUIET_WINDOW（Ask Studio Q4 指令，
# 仅白天已过全部硬门禁、预传 private 的视频的纯可见性翻转）
GATE_ACTOR = "cron:private_flip"
# 紧急发布是用户显式动作，用 human actor（不受夜间静默窗口限制）
EMERGENCY_ACTOR = "human:emergency"
# 豁免兜底（与 zero_view_alert.py 一致；注册表优先）
EXEMPT_VIDEOS = {"d0CHRz8ubjk"}

QUEUE_FILE = BASE / "youtube" / "private_queue.json"  # D20261011-001 P1 已迁 SQLite，路径仅留作注释
LOG_FILE = BASE / "youtube" / "private_flip.log"
INBOX = BASE / "collab" / "inbox.json"
# D20261011-001 P1: private_queue 改走 SQLite（queue_db）；K3：不碰 auth/登录逻辑。
import sys as _sys
if "/home/hatch/data/perpetua" not in _sys.path:
    _sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

# 排期时间（CST）
SLOTS = ["12:30", "00:00"]


def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def load_queue():
    # P0修复4：容忍读；D20261011-001 P1 已迁 SQLite（原子事务）
    return queue_db.privateq_load()


def save_queue(q):
    queue_db.privateq_save(q)  # D20261011-001 P1: 已迁 SQLite（原子事务）


def is_exempt_vid(vid):
    """豁免检查：统一注册表优先，硬编码集合兜底（与 zero_view_alert 一致）。"""
    try:
        if is_exempt(f"yt:{vid}"):
            return True
    except Exception:
        pass
    return vid in EXEMPT_VIDEOS


def _ensure_scheduled_private(vkey):
    """无记录时以 INTENTIONAL_PRIVATE 建记录（排期待发的私享视频）。"""
    with _global_state_lock():
        state = load_state()
        if vkey not in state:
            state[vkey] = _new_record(vkey, VideoState.INTENTIONAL_PRIVATE,
                                      owner="exemption_owner")
            save_state(state)


def _rollback_idempotency(idempotency_key):
    """API 副作用失败时：删幂等索引条目，允许下一轮 cron 真实重试。"""
    try:
        index = load_index()
        if idempotency_key in index:
            del index[idempotency_key]
            save_index(index)
    except Exception as e:
        log(f"幂等回滚失败 {idempotency_key}: {e}")


def gated_flip_to_public(video_id, scheduled_at="", actor=GATE_ACTOR,
                         reason="scheduled_flip"):
    """经跃迁门翻为 public。返回 (ok, info)。

    - 豁免视频：跳过，不翻转
    - gate 拒绝：返回 ok=False + rejection_code（QUIET_WINDOW 等）
    - duplicate=True：幂等命中，不调 YouTube API
    - API 失败：管理回滚 gate 状态 + 清幂等索引，下一轮可重试
    """
    vkey = f"yt:{video_id}"
    # MUST-12：豁免视频不得自动翻公开
    if is_exempt_vid(video_id):
        audit_log("exempted_skip_flip", video_id, "waiting", "waiting",
                  "private_flip", {"reason": "exemption_registry"})
        log(f"SKIP 翻转（豁免）: {video_id}")
        return False, {"skipped": "exempt"}

    _ensure_scheduled_private(vkey)
    idem_key = f"private_flip:{video_id}:{scheduled_at or 'manual'}:{actor}"
    tr = transition(vkey, VideoState.INTENTIONAL_PRIVATE, VideoState.STABLE_LIVE,
                    actor, reason, idempotency_key=idem_key)
    if not tr["accepted"]:
        audit_log("gate_reject_flip", video_id, "waiting", "waiting",
                  "private_flip",
                  {"rejection": tr["rejection_code"],
                   "detail": tr.get("detail", "")})
        log(f"gate 拒绝翻转 {video_id}: {tr['rejection_code']}")
        return False, {"rejection": tr["rejection_code"],
                       "detail": tr.get("detail", "")}
    if tr.get("duplicate"):
        # 幂等：gate 已有成功记录，不重复调 YouTube API
        audit_log("flip_duplicate_skip", video_id, "waiting", "published",
                  "private_flip", {"seq": tr.get("seq")})
        log(f"幂等命中 {video_id}（seq={tr.get('seq')}），跳过 API 调用")
        return True, {"duplicate": True, "seq": tr.get("seq")}

    try:
        result = flip_via_api(video_id)
    except Exception as e:
        _admin_revert(vkey, VideoState.INTENTIONAL_PRIVATE,
                      f"flip_api_exception:{str(e)[:80]}")
        _rollback_idempotency(idem_key)
        log(f"翻转 API 异常 {video_id}: {e}")
        return False, {"error": str(e)}
    if not result.get("ok"):
        _admin_revert(vkey, VideoState.INTENTIONAL_PRIVATE,
                      f"flip_api_failed:{result.get('error', '')[:80]}")
        _rollback_idempotency(idem_key)
        log(f"❌ 翻转失败 {video_id}: {result.get('error')}")
        return False, {"error": result.get("error", "unknown")}
    return True, {"seq": tr.get("seq")}


def flip_to_public(video_id):
    """把视频翻为 public（经 update_metadata）"""
    from yt_upload import update_metadata
    try:
        result = update_metadata(video_id, privacy="public")
        if result.get("updated"):
            return {"ok": True, "video_id": video_id}
        return {"error": result.get("error", "unknown")}
    except Exception as e:
        log(f"翻转失败 {video_id}: {e}")
        return {"error": str(e)}


def flip_via_api(video_id):
    """翻为 public（统一走 update_metadata）"""
    return flip_to_public(video_id)


def send_inbox(title, body, priority="normal"):
    try:
        # 2026-10-11：经统一网关写 messages。注意：旧代码误把 inbox 当 list
        # 处理（dict.append 直接抛错），此函数此前实际从未写成功过。
        import inbox as inbox_gw
        inbox_gw.append_message({
            "from": "private-flip",
            "title": title,
            "body": body,
            "priority": priority,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        log(f"inbox 写入失败: {e}")


def check_and_flip():
    """检查到期的 private 视频并翻为 public"""
    queue = load_queue()
    now_utc = datetime.now(timezone.utc)
    # CST = UTC+8
    now_cst = now_utc + timedelta(hours=8)
    today_str = now_cst.strftime("%Y-%m-%d")
    current_time = now_cst.strftime("%H:%M")

    changed = False
    for item in queue:
        if item.get("status") != "waiting":
            continue

        scheduled = item.get("scheduled_at", "")
        try:
            sched_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
            # 到期了（当前时间 >= 排期时间）
            if now_utc >= sched_dt:
                vid = item["video_id"]
                # Gemini 语义评审门（2026-10-10 用户要求：翻 public 前必须过语义评审，
                # fail-closed；verdict 由 gemini-semantic-review cron 经 gemini.google.com 网页版写入）
                verdict = item.get("gemini_verdict", "")
                if verdict == "fail":
                    log(f"🛑 {vid} Gemini语义评审未通过，保持 private，等待人工处理")
                    item["gemini_hold"] = True
                    changed = True
                    send_inbox(
                        f"🛑 视频被Gemini语义评审拦截：{item.get('title','')[:30]}",
                        f"video_id：{vid}\n"
                        f"评审意见：{item.get('gemini_notes','')[:500]}\n"
                        f"处理：人工检查后可用 emergency 翻转，或打回重做。",
                        priority="urgent",
                    )
                    continue
                if verdict not in ("pass", "warn", "skip_longform"):
                    # skip_longform：长视频走人工/Browser深度评审，不经过Gemini语义评审
                    # （2026-10-11 用户批准加入白名单，避免EP1等长视频被误hold）
                    log(f"⏳ {vid} 等待Gemini语义评审，保持 private")
                    item["gemini_hold"] = True
                    changed = True
                    if not item.get("gemini_hold_alerted"):
                        send_inbox(
                            f"⏳ 视频等待Gemini语义评审：{item.get('title','')[:30]}",
                            f"video_id：{vid}\n翻转已暂缓，评审完成后自动继续。"
                            f"如需强行发布可用 emergency。",
                            priority="normal",
                        )
                        item["gemini_hold_alerted"] = True
                    continue
                log(f"翻转 {vid} ({item.get('title','')[:30]}) 为 public")
                # Commit 1（2026-10-09）：经中央跃迁门授权后再调 API
                ok, info = gated_flip_to_public(
                    vid, scheduled_at=scheduled,
                    reason=f"scheduled_flip:slot={item.get('slot')}")
                if ok:
                    item["status"] = "published"
                    item["published_at"] = now_utc.isoformat()
                    changed = True
                    # P0修复6：审计日志
                    audit_log("flip_to_public", vid, "waiting", "published",
                              "private_flip", {"slot": item.get("slot"),
                                               "gate_seq": info.get("seq"),
                                               "duplicate": info.get("duplicate", False)})
                    log(f"✅ {vid} 已公开")
                    # 2026-10-09 指标异常动作：engagement 异常时排队的引导首评，
                    # 公开后自动发出（API 不支持真置顶，发首评为可实现部分）
                    _maybe_post_pin_comment(vid)
                    send_inbox(
                        f"📢 视频已发布：{item.get('title','')[:30]}",
                        f"【自动发布·Public 上线成功】\n"
                        f"标题：{item.get('title','')}\n"
                        f"链接：https://youtu.be/{vid}\n"
                        f"排期档：{item.get('slot')}\n"
                        f"发布时间：{item.get('published_at','')[:16]}\n"
                        f"状态：public 已公开",
                        priority="normal",
                    )
                elif info.get("rejection") == "QUIET_WINDOW":
                    # 2026-10-09 起 scheduled_flip 已豁免静默窗口，此分支仅作兜底
                    # （豁免被关闭或 actor/reason 不匹配时仍保持 waiting 下轮重试）
                    log(f"⏳ {vid} 夜间静默窗口，延后重试")
                elif info.get("skipped") == "exempt":
                    # 豁免：保持 waiting，人工处理
                    pass
                else:
                    log(f"❌ 翻转失败 {vid}: {info.get('error') or info.get('rejection')}")
        except Exception as e:
            log(f"处理 {item.get('video_id')} 异常: {e}")

    if changed:
        save_queue(queue)
    return changed


def _maybe_post_pin_comment(video_id):
    """公开后评论/描述运营（API 不支持真置顶，发首评为可实现部分）。
    2026-10-09 议会 #2：首评用中性二选一辩论提问（去争议化），发布后 15-30s
    发出；affiliate 永不进首评（24h 内），改挂 description 末尾。
    2026-10-10 R5 死状态修复（用户授权）：此前队列唯一写入方是
    daily_metrics_monitor 的 engagement 异常分支（≥40 播放才入队），
    当前 0~12 播放永远触发不了 → 队列从未创建 → 没有视频收到首评。
    现改为：无 pending 时直接按模板入队一条（恢复"公开后发首评"设计意图）。
    防重：该 video_id 已有 done 记录则跳过。"""
    import json as _json
    pq = Path("/home/hatch/data/youtube/auto_pin_queue.json")
    try:
        queue = _json.loads(pq.read_text())
    except Exception:
        queue = []
    pending = [x for x in queue if x.get("status") == "pending"]
    # R5 修复：无 pending 时按模板自动入队一条（正常路径执行者）
    # 防重入：该 video 已发过则直接跳过
    if not pending:
        done_ids = {x.get("video_id") for x in queue if x.get("status") == "done"}
        if video_id in done_ids:
            log(f"首评已发过，跳过: {video_id}")
            return
        import random as _random
        _templates = [
            "Did the AI go too far, or was this deserved? 🤔👇",
            "Was the AI's reaction fair? Drop your take 👇",
            "Who was in the wrong here — the AI or the customer? 🤖👇",
        ]
        queue.append({
            "status": "pending",
            "text": _random.choice(_templates),
            "video_id": video_id,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "source": "auto_flip_r5",
        })
        pending = [x for x in queue if x.get("status") == "pending"]
    posted = False
    try:
        sys.path.insert(0, "/home/hatch/data/youtube")
        from yt_comment import post_comment
        if pending:
            post_comment(video_id, pending[0]["text"])
            pending[0]["status"] = "done"
            pending[0]["video_id"] = video_id
            pending[0]["done_at"] = datetime.now(timezone.utc).isoformat()
            pq.write_text(_json.dumps(queue, ensure_ascii=False, indent=1))
            log(f"已发引导首评: {video_id}")
            posted = True
    except Exception as e:
        log(f"引导首评发送失败 {video_id}: {e}")
    # P0 affiliate（独立开关，默认关闭）
    # 2026-10-09 议会 #2：affiliate 永不进首评（24h 内禁外链），改挂 description 末尾。
    try:
        aff = _json.loads(Path(
            "/home/hatch/data/youtube/affiliate_links.json").read_text())
    except Exception:
        aff = {}
    if aff.get("enabled") and aff.get("links"):
        links = aff["links"]
        if aff.get("rotate", True):
            # 按已发数量轮换
            n = aff.get("_sent_count", 0)
            link = links[n % len(links)]
            aff["_sent_count"] = n + 1
            Path("/home/hatch/data/youtube/affiliate_links.json").write_text(
                _json.dumps(aff, ensure_ascii=False, indent=1))
        else:
            link = links[0]
        try:
            sys.path.insert(0, "/home/hatch/data/youtube")
            from batch_fix_descriptions import (
                update_description_tags, get_video_details,
                _load_oauth, _refresh)
            d = _load_oauth()
            try:
                cur = get_video_details(video_id, d["token"])
            except PermissionError:
                d["token"] = _refresh(d)
                cur = get_video_details(video_id, d["token"])
            if cur and link not in (cur.get("description") or ""):
                new_desc = (cur.get("description") or "").rstrip() + \
                    f"\n\n🛠️ {link}"
                try:
                    update_description_tags(video_id, new_desc,
                                            cur.get("tags", []), d["token"])
                except PermissionError:
                    d["token"] = _refresh(d)
                    update_description_tags(video_id, new_desc,
                                            cur.get("tags", []), d["token"])
                log(f"已挂 affiliate 到描述: {video_id} -> {link[:40]}")
                posted = True
        except Exception as e:
            log(f"affiliate 描述挂载失败 {video_id}: {e}")
    return posted


def emergency_flip(video_id):
    """紧急即时发布（算法黄金时刻）——用户显式动作，走 human actor。"""
    queue = load_queue()
    for item in queue:
        if item.get("video_id") == video_id and item.get("status") == "waiting":
            log(f"🚨 紧急发布 {video_id}")
            # Commit 1（2026-10-09）：同样走跃迁门；human actor 不受静默窗口限制
            ok, info = gated_flip_to_public(
                video_id, scheduled_at=item.get("scheduled_at", ""),
                actor=EMERGENCY_ACTOR, reason="emergency_flip:user_approved")
            if ok:
                item["status"] = "published"
                item["published_at"] = datetime.now(timezone.utc).isoformat()
                item["slot"] = "emergency"
                # P0修复6：审计日志
                audit_log("emergency_flip", video_id, "waiting", "published",
                          "private_flip", {"slot": "emergency",
                                           "gate_seq": info.get("seq"),
                                           "duplicate": info.get("duplicate", False)})
                save_queue(queue)
                log(f"✅ 紧急发布成功 {video_id}")
                send_inbox(
                    f"🚨 紧急发布：{item.get('title','')[:30]}",
                    f"算法黄金时刻，视频已即时公开。"
                    f"https://youtu.be/{video_id}",
                    priority="urgent",
                )
                return True
            else:
                log(f"❌ 紧急发布失败: {info.get('error') or info.get('rejection')}")
                return False
    log(f"紧急发布：{video_id} 不在等待队列")
    return False


def add_to_queue(video_id, title, slot=None):
    """QC 通过后上传为 private，加入等待队列。

    2026-10-09 起：档位不再写死，从 publish_slots.json 动态取下一档
    （Ask Studio 协商：工作日 23:30/05:30+1，周末 22:30/04:00+1，北京时间）。
    slot 参数保留兼容（旧值忽略）。
    """
    import sys
    sys.path.insert(0, "/home/hatch/data/youtube")
    from slot_config import next_slot
    queue = load_queue()
    # 计算排期时间（下一个动态档）
    slot_label, target_cst = next_slot()
    # 转回 UTC
    target_utc = target_cst - timedelta(hours=8)

    queue.append({
        "video_id": video_id,
        "title": title,
        "scheduled_at": target_utc.isoformat(),
        "slot": slot,
        "status": "waiting",
        "queued_at": now_utc.isoformat(),
    })
    save_queue(queue)
    # P0修复6：审计日志
    audit_log("queue_add", video_id, "", "waiting", "private_flip",
              {"slot": slot_label})
    log(f"加入等待队列: {video_id} → {slot_label} ({target_utc.isoformat()})")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "emergency":
        if len(sys.argv) > 2:
            emergency_flip(sys.argv[2])
        else:
            print("用法: private_flip.py emergency <video_id>")
        return

    if len(sys.argv) > 2 and sys.argv[1] == "add":
        # add <video_id> <title> <slot>
        add_to_queue(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "",
                     sys.argv[4] if len(sys.argv) > 4 else "12:30")
        return

    # 默认：检查并翻转到期的
    log("=== 翻转检查启动 ===")
    changed = check_and_flip()
    log(f"检查完成，{'有翻转' if changed else '无到期'}")


if __name__ == "__main__":
    # P0修复5（2026-10-09）：单飞锁，防 cron 重叠执行
    with run_lock("private_flip"):
        main()
