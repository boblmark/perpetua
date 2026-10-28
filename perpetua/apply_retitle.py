#!/usr/bin/env python3
"""P3（2026-10-28，空转审计根治）：已批准 auto_retitle 条目的应用动作。

消费链：auto_retitle.py / bypass_audit.queue_retitle 写 awaiting_approval.json
（type=auto_retitle, status=awaiting）→ 人工 approve_video.py approve
（P3 分支：只标 approved，不建 generate 任务）→ 本脚本取 alt_titles[0]
调 yt_upload.update_metadata 换标题 → 条目标 applied。

调用方：dead_state_watchdog.py 每 30 分钟一轮 best-effort 调用
apply_approved()（异常绝不拖垮看门狗）；也可手工跑：
  python3 apply_retitle.py              # 应用全部已批准条目
  python3 apply_retitle.py --dry-run    # 只打印不改标题、不改状态

安全栏：
- 只处理 status=approved 的 auto_retitle 条目；awaiting/rejected/expired/applied 不动。
- 先 get_status 读当前标题：已是 alt[0] 则直接标 applied（幂等，不重复调 API）；
  当前标题既非 old_title 又非 alt[0]（批准后被人改过）→ 判定 stale，保留
  approved 并记日志，绝不覆盖人工改过的标题（P4 去重修好后可由新条目重走流程）。
- update_metadata 失败（返回 error 或抛错）→ 保留 approved 下轮重试，
  不标 applied；失败计数 apply_fail_count 累计，供看门狗 12h 去重告警。
- bypass_audit 写入的条目无 alt_titles：回落用 auto_retitle.gen_alt_titles
  现场生成，取第 1 条应用（批准本身按 topic，不按备选文本）。
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/hatch/data/perpetua")
sys.path.insert(0, "/home/hatch/data/youtube")

APPROVAL_PATH = "/home/hatch/data/perpetua/awaiting_approval.json"
LOG_PATH = "/home/hatch/data/perpetua/apply_retitle.log.json"


def _load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(p, obj):
    from json_safe import atomic_write_json
    atomic_write_json(p, obj)


def _log(entry):
    log = _load(LOG_PATH, [])
    log.append(dict(entry, at=datetime.now(timezone.utc).isoformat()))
    _save(LOG_PATH, log[-200:])


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def apply_approved(dry_run=False):
    """应用全部已批准条目。返回 (applied, failed, stale) 三个条目列表。"""
    from yt_upload import update_metadata, get_status
    approvals = _load(APPROVAL_PATH, [])
    if not isinstance(approvals, list):
        return [], [], []
    applied, failed, stale = [], [], []
    changed = False
    for a in approvals:
        if not isinstance(a, dict):
            continue
        if a.get("type") != "auto_retitle" or a.get("status") != "approved":
            continue
        vid = a.get("video_id", "")
        if not vid:
            a["apply_fail_count"] = int(a.get("apply_fail_count", 0) or 0) + 1
            a["apply_last_error"] = "missing video_id"
            failed.append(a)
            changed = True
            continue
        alts = a.get("alt_titles") or []
        if not alts:
            try:
                from auto_retitle import gen_alt_titles
                alts = gen_alt_titles(a.get("old_title") or a.get("title", ""), vid)
            except Exception as e:
                alts = []
                print(f"  WARN: 生成备选标题失败 {vid}: {e}")
        if not alts:
            a["apply_fail_count"] = int(a.get("apply_fail_count", 0) or 0) + 1
            a["apply_last_error"] = "no alt_titles"
            failed.append(a)
            changed = True
            continue
        new_title = alts[0]
        old_title = a.get("old_title") or a.get("title", "")
        try:
            cur = get_status(vid)
        except Exception as e:
            a["apply_fail_count"] = int(a.get("apply_fail_count", 0) or 0) + 1
            a["apply_last_error"] = f"get_status failed: {str(e)[:120]}"
            failed.append(a)
            changed = True
            continue
        if cur.get("error"):
            a["apply_fail_count"] = int(a.get("apply_fail_count", 0) or 0) + 1
            a["apply_last_error"] = str(cur.get("error"))[:120]
            failed.append(a)
            changed = True
            continue
        cur_title = cur.get("title", "")
        if cur_title == new_title:
            a["status"] = "applied"
            a["applied_at"] = _now_iso()
            a["applied_title"] = new_title
            a["apply_note"] = "already applied (current title matches)"
            applied.append(a)
            changed = True
            _log({"video_id": vid, "applied_title": new_title, "note": "already"})
            continue
        if old_title and cur_title != old_title:
            # 批准后标题已被人改过：不覆盖，留 approved + stale 标记供人工看
            if not a.get("stale_noted"):
                a["stale_noted"] = True
                a["stale_reason"] = (
                    f"当前标题与批准时 old_title 不符（现标题：{cur_title[:60]}）")
                changed = True
            stale.append(a)
            _log({"video_id": vid, "stale": True,
                  "current_title": cur_title[:80], "old_title": old_title[:80]})
            continue
        if dry_run:
            print(f"  DRY-RUN: {vid} → {new_title}")
            continue
        try:
            res = update_metadata(vid, title=new_title)
        except Exception as e:
            res = {"error": str(e)[:200]}
        if res.get("updated"):
            a["status"] = "applied"
            a["applied_at"] = _now_iso()
            a["applied_title"] = new_title
            a.pop("apply_fail_count", None)
            a.pop("apply_last_error", None)
            applied.append(a)
            changed = True
            _log({"video_id": vid, "applied_title": new_title})
            print(f"  APPLIED: {vid} → {new_title}")
        else:
            a["apply_fail_count"] = int(a.get("apply_fail_count", 0) or 0) + 1
            a["apply_last_error"] = str(res.get("error", "unknown"))[:200]
            failed.append(a)
            changed = True
            print(f"  FAILED: {vid}: {a['apply_last_error']}")
    if changed and not dry_run:
        _save(APPROVAL_PATH, approvals)
    return applied, failed, stale


def main():
    dry = "--dry-run" in sys.argv
    applied, failed, stale = apply_approved(dry_run=dry)
    print(json.dumps({"applied": len(applied), "failed": len(failed),
                      "stale": len(stale), "dry_run": dry}, ensure_ascii=False))


if __name__ == "__main__":
    main()
