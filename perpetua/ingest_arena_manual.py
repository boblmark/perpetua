#!/usr/bin/env python3
"""arena_manual 接手 QC（Stage 1，2026-10-28 用户批准实施）。

独立命令，不进 collect_results。只做 QC 并记录结果，绝不触发上传：
- 逐项 arena_manual：有 video_id 跳过；无 video_file 跳过（留给看门狗告警）；
- ffprobe：>11.5 秒非多段 teaser 记 needs_manual_qc，绝不调 run_qc
  （run_qc 会把超 11 秒自动裁到 11 秒，Rule 8 风险）；
- 否则调 run_qc：prompt_meta 不带 expected_duration（兜底项名义时长不可靠，
  实测时长为准，duration_match 跳过是 deliberate）；regen_fn 返回 None
  （不自动重生成）；repair_fn 复用接缝修复；repair_used 则 video_file 指
  向修复后文件；
- QC 通过 → 写 qc_report + qc_passed_at；QC 失败 → 写 qc_report + qc_error；
  两种情况 status 一律不变（仍 arena_manual），不打回 review_passed，
  不碰 requires_fallback_approval / fallback_approved，不设 ready_to_upload，
  不调上传，不进 private 队列。
- 已有通过 QC 且 video_file 未变者跳过（幂等）。

用法：python3 ingest_arena_manual.py [--dry-run] [--id <event_bus_id>]
Stage 2：python3 ingest_arena_manual.py approve_and_promote <event_bus_id>
（须用户按条目名批准；前置校验失败不改状态；本命令不调上传）
QC 引擎不可用时 fail-closed：直接退出，不动队列。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

DATA = "/home/hatch/data"
REPORT_PATH = "/home/hatch/data/perpetua/ingest_arena_manual_last_run.json"
MAX_SHORT_DUR = 11.5


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def resolve(path):
    if not path:
        return None
    if os.path.isabs(path) and os.path.exists(path):
        return path
    for cand in (path,
                 os.path.join(DATA, path.lstrip("/")),
                 os.path.join("/home/hatch", path.lstrip("/"))):
        if cand and os.path.exists(cand):
            return cand
    return None


def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None, (r.stderr or "").strip()[:200]
    try:
        d = json.loads(r.stdout or "{}")
        return float(d.get("format", {}).get("duration", 0) or 0), ""
    except Exception as e:
        return None, f"ffprobe 输出解析失败: {e}"


def _load_run_qc():
    from pre_upload_qc import run_qc
    return run_qc


def _qc_repair(video_path, similarity):
    try:
        from qc_repair import repair_loop_seam
    except ImportError:
        return None
    return repair_loop_seam(video_path, similarity)


def promote(item_id):
    """Stage 2 放行与提单（须用户按条目名批准，Dash 不自批）。

    前置校验任一不满足即拒绝、不改状态：status==arena_manual；
    Stage 1 通过的 qc_report（passed 且 qc_passed_at 在）；
    video_file 存在；无 youtube_video_id / video_id。
    效果：fallback_approved=True + 批准记录 + status=ready_to_upload；
    上传发生在下一轮 collect 的 ready_to_upload 循环（现有链路），
    本命令本身不调上传、不进 private 队列。
    """
    try:
        q = queue_db.pipeline_load()
    except Exception as e:
        print(f"读队列失败（不动队列）: {e}")
        return 2
    items = q if isinstance(q, list) else q.get("items", [])
    # 用户说的 id 是 event_bus 行 id（如 3574），payload 里没有 id 字段，
    # 只能经 event_bus 表取 _row_key 再定位；payload 自带 id 时也兼容。
    row_key = None
    try:
        import sqlite3
        con = sqlite3.connect(
            "file:/home/hatch/data/ops_center.db?mode=ro", uri=True)
        row = con.execute(
            "SELECT payload FROM event_bus WHERE id=? AND queue_name='pipeline'",
            (item_id,)).fetchone()
        con.close()
        if row:
            row_key = json.loads(row[0]).get("_row_key")
    except Exception as e:
        print(f"查 event_bus 行 id 失败（仍试 payload id 匹配）：{e}")
    target = None
    for it in items:
        if not isinstance(it, dict):
            continue
        if row_key and it.get("_row_key") == row_key:
            target = it
            break
    if target is None:
        # 兜底：payload 自带 id 的旧格式 / 隔离测试用假队列
        for it in items:
            if isinstance(it, dict) and it.get("id") == item_id:
                target = it
                break
    if target is None:
        print(f"拒绝：队列中没有 id={item_id}")
        return 2
    if target.get("status") != "arena_manual":
        print(f"拒绝：id={item_id} status={target.get('status')}，不是 arena_manual")
        return 2
    qc = target.get("qc_report") or {}
    if not (qc.get("passed") and target.get("qc_passed_at")):
        print(f"拒绝：id={item_id} 没有 Stage 1 通过的 qc_report/qc_passed_at")
        return 2
    vf = target.get("video_file")
    path = resolve(vf) if vf else None
    if not path:
        print(f"拒绝：id={item_id} video_file 不存在：{vf}")
        return 2
    if target.get("youtube_video_id") or target.get("video_id"):
        print(f"拒绝：id={item_id} 已有 video_id，禁止重复上传")
        return 2
    target["fallback_approved"] = True
    target["fallback_approved_at"] = now_iso()
    target["fallback_approval"] = {
        "approved_at": now_iso(), "approved_by": "user",
        "command": "approve_and_promote", "item_id": item_id,
        "qc_passed_at": target.get("qc_passed_at"),
        "video_file": path,
    }
    target.pop("upload_gate_held", None)
    target["status"] = "ready_to_upload"
    queue_db.pipeline_save(q)
    print(f"已放行：id={item_id} {target.get('topic')} → ready_to_upload，"
          f"下一轮 collect 自动 private 上传")
    try:
        inbox_path = "/home/hatch/data/collab/inbox.json"
        with open(inbox_path, encoding="utf-8") as f:
            inbox = json.load(f)
        inbox.setdefault("notices", []).append({
            "type": "stage2_promoted",
            "title": f"已放行：{target.get('topic')}",
            "message": (f"Stage 2 已放行 id={item_id}（{target.get('topic')}），"
                        f"下一轮 collect 自动 private 上传"),
            "created": now_iso(), "created_at": now_iso(), "for": "user",
            "item_id": item_id, "video_file": path,
        })
        with open(inbox_path, "w", encoding="utf-8") as f:
            json.dump(inbox, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"写 inbox 通知失败（提单本身已生效）：{e}")
    return 0


def main():
    # Stage 2 子命令：python3 ingest_arena_manual.py approve_and_promote <id>
    if len(sys.argv) >= 3 and sys.argv[1] == "approve_and_promote":
        try:
            item_id = int(sys.argv[2])
        except ValueError:
            print(f"拒绝：id 必须是整数：{sys.argv[2]}")
            return 2
        return promote(item_id)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--id", type=int, default=None,
                    help="只处理指定 event_bus id")
    args = ap.parse_args()

    try:
        run_qc = _load_run_qc()
    except ImportError as e:
        print(f"QC 引擎不可用（fail-closed，不动队列）: {e}")
        return 2

    try:
        q = queue_db.pipeline_load()
    except Exception as e:
        print(f"读队列失败（不动队列）: {e}")
        return 2
    items = q if isinstance(q, list) else q.get("items", [])

    results = []
    changed = False
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "arena_manual":
            continue
        if args.id is not None and it.get("id") != args.id:
            continue
        topic = it.get("topic", "?")
        rec = {"id": it.get("id"), "topic": topic}
        if it.get("youtube_video_id"):
            rec["verdict"] = "skip_uploaded"
            rec["detail"] = f"已有 video_id {it['youtube_video_id']}"
            results.append(rec)
            continue
        vf = it.get("video_file")
        if not vf:
            rec["verdict"] = "skip_no_file"
            rec["detail"] = "无 video_file，留给看门狗告警"
            results.append(rec)
            continue
        path = resolve(vf)
        if not path:
            rec["verdict"] = "skip_missing_file"
            rec["detail"] = f"video_file 不存在：{vf}"
            results.append(rec)
            continue
        # 幂等：已通过 QC 且文件未变 → 不重复跑
        if (it.get("qc_passed_at") and (it.get("qc_report") or {}).get("passed")
                and it.get("ingest_qc_video_file") == path):
            rec["verdict"] = "skip_already_passed"
            rec["detail"] = "已有通过 QC 记录且文件未变"
            results.append(rec)
            continue
        # 多段 teaser 不走 Shorts ingest（留人工）
        if it.get("teaser") or it.get("segments"):
            rec["verdict"] = "skip_teaser"
            rec["detail"] = "多段 teaser 不走 Shorts ingest，留人工"
            results.append(rec)
            continue
        dur, err = ffprobe_duration(path)
        if dur is None:
            rec["verdict"] = "skip_unreadable"
            rec["detail"] = f"ffprobe 失败：{err}"
            results.append(rec)
            continue
        rec["duration"] = round(dur, 2)
        if dur > MAX_SHORT_DUR:
            # Rule 8：绝不让 run_qc 把长视频静默裁到 11 秒
            rec["verdict"] = "needs_manual_qc"
            rec["detail"] = f"时长 {dur:.1f}s > {MAX_SHORT_DUR}s，拒调 run_qc，走手动 QC"
            if not args.dry_run:
                it["ingest_qc_at"] = now_iso()
                it["ingest_qc_verdict"] = "needs_manual_qc"
                changed = True
            results.append(rec)
            continue
        try:
            qc = run_qc(path, title=it.get("title", ""),
                        prompt_meta={},
                        regen_fn=lambda attempt: None,
                        repair_fn=_qc_repair)
        except Exception as e:
            rec["verdict"] = "qc_error"
            rec["detail"] = f"QC 异常：{str(e)[:200]}"
            if not args.dry_run:
                it["qc_error"] = str(e)[:200]
                it["ingest_qc_at"] = now_iso()
                it["ingest_qc_verdict"] = "qc_error"
                changed = True
            results.append(rec)
            continue
        report = {"passed": qc.get("passed"),
                  "warnings": len(qc.get("warnings", [])),
                  "rejects": qc.get("rejects", []),
                  "regen_used": qc.get("regen_used", 0),
                  "repair_used": qc.get("repair_used", 0)}
        rec["qc_report"] = report
        if qc.get("repair_used") and qc.get("output_file"):
            rec["repaired_to"] = qc["output_file"]
        if qc.get("passed"):
            rec["verdict"] = "qc_passed"
            rec["detail"] = "QC 通过（status 不变，仍 arena_manual）"
        else:
            rec["verdict"] = "qc_failed"
            rec["detail"] = f"QC 拒绝：{report['rejects'][:2]}（status 不变，人定去留）"
        if not args.dry_run:
            it["qc_report"] = report
            it["ingest_qc_at"] = now_iso()
            it["ingest_qc_video_file"] = path
            if qc.get("repair_used") and qc.get("output_file"):
                it["video_file"] = qc["output_file"]
                it["qc_repaired"] = True
            if qc.get("passed"):
                it["qc_passed_at"] = now_iso()
                it["ingest_qc_verdict"] = "qc_passed"
            else:
                it["qc_error"] = str(report["rejects"][:2])
                it["ingest_qc_verdict"] = "qc_failed"
            changed = True
        results.append(rec)

    for rec in results:
        print(f"{rec['topic']} | {rec['verdict']} | {rec['detail']}")
    n_pass = sum(1 for r in results if r["verdict"] == "qc_passed")
    print(f"共 {len(results)} 条：QC 通过 {n_pass} 条"
          f"{'（dry-run，未写队列）' if args.dry_run else ''}")
    report = {"run_at": now_iso(), "dry_run": args.dry_run,
              "items": results}
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"写运行报告失败（不影响队列）：{e}")
    if changed and not args.dry_run:
        queue_db.pipeline_save(q)
        print("队列已写回（仅 qc_report/qc_passed_at/qc_error 等字段，status 未变）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
