import json
d = json.load(open("/home/hatch/data/perpetua/awaiting_approval.json"))
print("type:", type(d).__name__)
if isinstance(d, dict):
    print("keys:", list(d.keys()))
    for k, v in d.items():
        if isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
            for it in v[:6]:
                if isinstance(it, dict):
                    print("     -", str(it.get("title") or it.get("topic") or it)[:80],
                          "|", it.get("status", ""))
                else:
                    print("     -", str(it)[:80])
        else:
            print(f"  {k}: {str(v)[:120]}")
else:
    print("len:", len(d))
    for it in d[:8]:
        print("  -", json.dumps(it, ensure_ascii=False)[:200])
