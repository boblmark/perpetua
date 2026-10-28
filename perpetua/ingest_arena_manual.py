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


def main():
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
