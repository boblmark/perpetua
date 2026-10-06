#!/usr/bin/env python3
"""Perpetua 多租户管理：租户注册、数据隔离、配额"""
import json, os, shutil
from datetime import datetime, timezone

BASE = "/home/hatch/data/perpetua"
REGISTRY = f"{BASE}/tenants/registry.json"
# 迁移现有单租户为默认租户
DEFAULT_TENANT = "default"

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def load():
    if os.path.exists(REGISTRY):
        return json.load(open(REGISTRY))
    return {"tenants": {}}

def save(r):
    json.dump(r, open(REGISTRY, "w"), ensure_ascii=False, indent=2)

def create_tenant(name, youtube_channel_id="", plan="free", theme="",
                  keywords=None, content_style=""):
    """创建租户，返回 tenant_id"""
    r = load()
    tid = name.lower().replace(" ", "-")[:32]
    if tid in r["tenants"]:
        raise ValueError(f"租户 {tid} 已存在")
    tdir = f"{BASE}/tenants/{tid}"
    os.makedirs(f"{tdir}/data", exist_ok=True)
    # 每租户独立数据文件
    for sub in ["trends", "inbox"]:
        os.makedirs(f"{tdir}/{sub}", exist_ok=True)
    r["tenants"][tid] = {
        "id": tid, "name": name,
        "youtube_channel_id": youtube_channel_id,
        "youtube_channel_name": "",
        "plan": plan,  # free / pro / enterprise
        "quota": quota_for(plan),
        "theme": theme,
        "keywords": keywords or [],
        "content_style": content_style,
        "created": now_iso(),
        "data_dir": f"{tdir}/data",
        "oauth_file": f"{tdir}/.oauth.json",
        "status": "active",
    }
    save(r)
    return tid

def update_tenant(tid, **fields):
    """更新租户字段（theme/keywords/content_style/status/plan 等）"""
    r = load()
    if tid not in r["tenants"]:
        raise ValueError(f"租户 {tid} 不存在")
    r["tenants"][tid].update(fields)
    if "plan" in fields:
        r["tenants"][tid]["quota"] = quota_for(fields["plan"])
    save(r)
    return r["tenants"][tid]

def active_tenants():
    """返回所有 active 租户"""
    return [t for t in list_tenants() if t.get("status") == "active"]

def tenant_inbox_path(tid):
    """租户独立 inbox 路径（回退到全局 inbox）"""
    p = f"{BASE}/tenants/{tid}/inbox/inbox.json"
    if os.path.exists(p):
        return p
    return "/home/hatch/data/collab/inbox.json"

def quota_for(plan):
    return {
        "free": {"videos_per_day": 3, "ask_studio_per_day": 10, "channels": 1},
        "pro": {"videos_per_day": 10, "ask_studio_per_day": 50, "channels": 3},
        "enterprise": {"videos_per_day": 50, "ask_studio_per_day": 200, "channels": 10},
    }.get(plan, {})

def get_tenant(tid):
    return load()["tenants"].get(tid)

def list_tenants():
    return list(load()["tenants"].values())

def check_quota(tid, resource):
    """检查配额是否还有余量，返回 (ok, used, limit)"""
    t = get_tenant(tid)
    if not t:
        return False, 0, 0
    limit = t["quota"].get(resource, 0)
    # 用量从 billing 追踪读
    usage_file = f"{BASE}/billing/usage_{tid}.json"
    used = 0
    if os.path.exists(usage_file):
        u = json.load(open(usage_file))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        used = u.get(today, {}).get(resource, 0)
    return used < limit, used, limit

def migrate_default():
    """把现有单租户数据迁移为 default 租户"""
    r = load()
    if DEFAULT_TENANT in r["tenants"]:
        return "already migrated"
    tid = create_tenant("Default Channel", plan="pro")
    # 指向现有数据目录（软链接，不复制）
    tdir = f"{BASE}/tenants/{tid}"
    for link, target in [
        ("youtube_oauth", "/home/hatch/data/youtube/.oauth.json"),
        ("trends", "/home/hatch/data/trends"),
        ("ask_studio", "/home/hatch/data/ask_studio"),
    ]:
        lp = f"{tdir}/{link}"
        if not os.path.exists(lp) and os.path.exists(target):
            os.symlink(target, lp)
    return f"migrated as {tid}"

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "migrate":
        print(migrate_default())
    elif cmd == "create":
        print(create_tenant(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "",
                            sys.argv[4] if len(sys.argv) > 4 else "free"))
    elif cmd == "list":
        print(json.dumps(list_tenants(), ensure_ascii=False, indent=2))
    elif cmd == "quota":
        ok, used, limit = check_quota(sys.argv[2], sys.argv[3])
        print(json.dumps({"ok": ok, "used": used, "limit": limit}))
