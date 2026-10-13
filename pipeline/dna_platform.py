"""九平台真实数据 API。"""
import json, os, sys
sys.path.insert(0, "/home/hatch/data/perpetua")
MATRIX = "/home/hatch/data/perpetua/distributor/platform_matrix.json"

def api_platforms():
    m = json.load(open(MATRIX, encoding="utf-8"))
    out = []
    for key, v in m.get("platforms", {}).items():
        videos = v.get("videos", [])
        total_views = 0
        for x in videos:
            if isinstance(x, dict):
                vv = x.get("views") or x.get("play_count") or 0
                try: total_views += int(vv)
                except: pass
        out.append({
            "key": key,
            "name": v.get("name", key),
            "avatar": v.get("avatar", ""),
            "profile_url": v.get("profile_url", ""),
            "n_videos": len(videos),
            "total_views": total_views,
            "status": v.get("status", ""),
        })
    order = m.get("order", list(m.get("platforms", {}).keys()))
    out.sort(key=lambda x: order.index(x["key"]) if x["key"] in order else 99)
    return {"platforms": out, "updated_at": m.get("updated_at", "")}

if __name__ == "__main__":
    print(json.dumps(api_platforms(), ensure_ascii=False))
