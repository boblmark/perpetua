import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from pre_upload_qc import run_qc
FILES = [
    "/home/hatch/data/perpetua/videos/job-20261113020219-a6f7b9.mp4",
    "/home/hatch/data/perpetua/videos/job-20261113020219-a6f7b9_loopfix.mp4",
]
for f in FILES:
    print("FILE", f.split("/")[-1], flush=True)
    r = run_qc(f)
    print("passed", r.get("passed"), "score", r.get("experience_score"),
          "regen", r.get("regen_used"), "repair", r.get("repair_used"),
          "needs_regen", r.get("needs_regen"), flush=True)
    print("rejects", r.get("rejects"), flush=True)
    print("warnings", r.get("warnings"), flush=True)
    for c in r.get("checks", []):
        print("  check", c, flush=True)
print("DONE", flush=True)
