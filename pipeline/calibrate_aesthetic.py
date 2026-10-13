#!/usr/bin/env python3
"""批量校准：一次 load 模型，给所有视频打分，输出分布 + 阈值建议。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aesthetic_gate import extract_frames, score_frames, ffprobe_duration

VIDEOS = {
    # hits: 通过 QC / 已发布
    "hit": [
        "/home/hatch/data/veo_inbox/geminigen_veo_drivethru_v52_final2.mp4",
        "/home/hatch/data/veo_inbox/h3_20261008_164144_seed2118693257.mp4",
        "/home/hatch/data/media-generation-pipe-20261006233407-a1c68a-ret-0-70c37e85-75d1-4334-a071-3cbbe3fb8021.mp4",
        "/home/hatch/data/veo_inbox/veo_v51_final.mp4",
        "/home/hatch/data/media-generation-karenvsai-pilot-01-0-7d1a1367-66bc-4c51-8d18-0b706e1d8ccd.mp4",
        "/home/hatch/data/perpetua/videos/teaser-20261010070639-88bc3f-teaser.mp4",
        "/home/hatch/data/perpetua/videos/teaser-20261010090640-b2c44d-teaser.mp4",
        "/home/hatch/data/perpetua/videos/teaser-20261010101013-2a8143-teaser.mp4",
    ],
    # rejects: 因视觉/体验原因被 QC 拒
    "reject": [
        "/home/hatch/data/veo_inbox/seedance_v2.mp4",
        "/home/hatch/data/veo_inbox/veo_v4_fixed.mp4",
        "/home/hatch/data/veo_inbox/veo_v4_shake.mp4",
        "/home/hatch/data/veo_inbox/veo_v51_8s_portrait.mp4",
        "/home/hatch/data/veo_inbox/h3_drivethru_20261008_174502_seed696162839.mp4",
        "/home/hatch/data/veo_inbox/h3_20261008_160708_seed28311100.mp4",
        "/home/hatch/data/veo_inbox/geminigen_veo_drivethru_v52_gg1.mp4",
        "/home/hatch/data/veo_inbox/geminigen_veo_drivethru_v52_gg2.mp4",
        "/home/hatch/data/veo_inbox/h3_gaspump_20261008_180553_seed119799149.mp4",
        "/home/hatch/data/veo_inbox/h3_robovac_20261008_182806_seed499271759.mp4",
        "/home/hatch/data/veo_inbox/h3_20261008_153541.mp4",
        "/home/hatch/data/veo_inbox/geminigen_paratest_193409_1.mp4",
    ],
}

results = []
for label, paths in VIDEOS.items():
    for p in paths:
        if not os.path.isfile(p):
            print(f"SKIP 缺文件: {p}", flush=True)
            continue
        try:
            dur = ffprobe_duration(p)
            with tempfile.TemporaryDirectory() as td:
                frames = extract_frames(p, 1.0, td)
                scores = score_frames(frames)
            mean = sum(scores) / len(scores)
            rec = {"label": label, "file": os.path.basename(p),
                   "n": len(scores), "mean": round(mean, 3),
                   "min": round(min(scores), 3)}
            results.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"label": label, "file": os.path.basename(p),
                              "error": str(e)[:100]}), flush=True)

out = "/home/hatch/data/perpetua/aesthetic_calibration.json"
json.dump(results, open(out, "w"), ensure_ascii=False, indent=1)
print(f"saved {len(results)} -> {out}", flush=True)
