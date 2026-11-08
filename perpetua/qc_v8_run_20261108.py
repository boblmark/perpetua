"""v8 full QC rerun (diagnostic, loop gate already evaluated once by pipeline:
pre_upload_qc.log line 250 -> loop 0.6626 < 0.75 fail, experience 30).
Mirrors the v7 rerun: run_qc(check_loop=False) to learn experience score and
Tier 1/2 hard items. Does NOT upload anything. Output -> qc_v8_20261108.json
"""
import json
import sys

sys.path.insert(0, "/home/hatch/data/perpetua")
from pre_upload_qc import run_qc

VIDEO = "/home/hatch/data/perpetua/videos/job-20261107135414-06bbd3.mp4"
OUT = "/home/hatch/data/perpetua/qc_v8_20261108.json"

result = run_qc(VIDEO, check_loop=False)
with open(OUT, "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print("passed:", result.get("passed"))
print("experience_score:", result.get("experience_score"))
print("rejects:", json.dumps(result.get("rejects", []), ensure_ascii=False))
print("saved:", OUT)
