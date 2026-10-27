"""方案 3 CI 检查器：队列里出现的每个状态必须在 state_consumers.json 有
消费者（非终态）或属于终态表，否则 exit 1（孤儿状态拦截，Rule 15）。

跑法：python3 /home/hatch/data/perpetua/check_state_consumers.py
"""
import json
import sys

sys.path.insert(0, "/home/hatch/data/perpetua")
import queue_db

MAP = json.load(open("/home/hatch/data/perpetua/state_consumers.json"))
consumers = MAP["consumers"]
terminal = set(MAP["terminal"])

q = queue_db.pipeline_load()
present = sorted({i.get("status") for i in q if i.get("status")})
bad = [s for s in present if s not in consumers and s not in terminal]
print("present statuses:", present)
if bad:
    print("ORPHAN (no consumer, not terminal):", bad)
    sys.exit(1)
print("OK: every present status has a consumer or is terminal")
for s in present:
    print(f"  {s}: {consumers.get(s, 'TERMINAL')}")
