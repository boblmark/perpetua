#!/usr/bin/env python3
"""arena_manual 接手预检（只读 + 报告，不改队列状态、不跑 QC、不触上传链）。

2026-10-28 空转审计 G1 安全部分：为 ingest 接线准备核验数据。
- 只读队列（queue_db.pipeline_load），绝不写回。
- 逐项：跳过已有 youtube_video_id（已上传/已排期）；无 video_file 记待人工；
  有文件则 ffprobe 读时长/分辨率/帧率/大小，给出 ready/check/unreadable。
- 输出 JSON 报告 + 打印摘要。
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

REPORT_PATH = "/home/hatch/data/perpetua/ingest_arena_manual_precheck_20261028.json"
DATA = "/home/hatch/data"


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
    return path  # 原样返回，供报告标注“不存在”


def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration,size",
         "-show_entries", "stream=width,height,avg_frame_rate,codec_name",
         "-of", "json", path],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None, (r.stderr or "").strip()[:200]
    try:
        d = json.loads(r.stdout or "{}")
    except Exception as e:
        return None, f"ffprobe 输出解析失败: {e}"
    fmt = d.get("format", {})
    streams = [s for s in d.get("streams", []) if s.get("width")]
    v = streams[0] if streams else {}
    try:
        num, den = (v.get("avg_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0
    except Exception:
        fps = 0
    return {"duration": float(fmt.get("duration", 0) or 0),
            "size_mb": round(float(fmt.get("size", 0) or 0) / 1048576, 2),
            "width": v.get("width"), "height": v.get("height"),
            "fps": round(fps, 2), "codec": v.get("codec_name")}, ""


def main():
    q = queue_db.pipeline_load()
    items = q if isinstance(q, list) else q.get("items", [])
    out = {"checked_at": datetime.now(timezone.utc).isoformat(), "items": []}
    for it in items:
        if not isinstance(it, dict) or it.get("status") != "arena_manual":
            continue
        rec = {"id": it.get("id"), "topic": it.get("topic"),
               "job_id": it.get("job_id"),
               "video_file_raw": it.get("video_file")}
        if it.get("youtube_video_id"):
            rec["verdict"] = "skip_uploaded"
            rec["detail"] = f"已有 video_id {it['youtube_video_id']}，接手必须跳过"
        elif not it.get("video_file"):
            rec["verdict"] = "needs_file"
            rec["detail"] = "无 video_file，无法接手，待人工定去留"
        else:
            p = resolve(it["video_file"])
            rec["resolved"] = p
            if not p or not os.path.exists(p):
                rec["verdict"] = "missing_file"
                rec["detail"] = "video_file 指向的文件不存在"
            else:
                spec, err = probe(p)
                if spec is None:
                    rec["verdict"] = "unreadable"
                    rec["detail"] = f"ffprobe 失败：{err}"
                else:
                    rec["spec"] = spec
                    dev = []
                    if not (9.0 <= spec["duration"] <= 11.5):
                        dev.append(f"时长 {spec['duration']:.1f}s 偏离 10s")
                    if (spec["width"], spec["height"]) != (720, 1280):
                        dev.append(
                            f"分辨率 {spec['width']}x{spec['height']} 非 720x1280")
                    rec["verdict"] = "check" if dev else "ready"
                    rec["detail"] = "；".join(dev) if dev else "文件存在，规格符合 10s 竖屏"
        out["items"].append(rec)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for rec in out["items"]:
        print(f"{rec['topic']} | {rec['verdict']} | {rec['detail']}")
    print(f"报告：{REPORT_PATH}（共 {len(out['items'])} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
