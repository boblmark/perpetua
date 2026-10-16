#!/usr/bin/env python3
"""Update one platform status in matrix_sync_job.json. Usage: update_job.py <platform> <status>"""
import json, sys, os
JOB = "/home/hatch/data/perpetua/distributor/matrix_sync_job.json"
platform, status = sys.argv[1], sys.argv[2]
assert status in ("done", "stale", "error")
with open(JOB) as f:
    job = json.load(f)
job["platforms"][platform] = status
terminal = {"done", "stale", "error"}
if all(v in terminal for v in job["platforms"].values()):
    from datetime import datetime, timezone
    job["status"] = "done"
    job["finished_at"] = datetime.now(timezone.utc).isoformat()
with open(JOB, "w") as f:
    json.dump(job, f, ensure_ascii=False, indent=1)
print(f"{platform} -> {status}; job status now {job['status']}")
