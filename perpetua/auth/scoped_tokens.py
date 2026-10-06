#!/usr/bin/env python3
"""Perpetua 细粒度 Token：按角色授权，不再是一个 token 通吃

角色：
- viewer: 只读（查数据、看报告、问 Ask Studio）
- operator: viewer + 生成视频/图片、上传、换标题、回评论
- admin: operator + 租户管理、计费、改配置

每个 token 绑定：tenant_id + role + 过期时间
"""
import json, os, secrets, hashlib
from datetime import datetime, timezone, timedelta

BASE = "/home/hatch/data/perpetua"
TOKEN_FILE = f"{BASE}/auth/tokens.json"
AUDIT_LOG = f"{BASE}/audit/audit.jsonl"

# 角色 → 允许的工具
ROLE_TOOLS = {
    "viewer": [
        "youtube_stats", "youtube_recent", "youtube_analytics_traffic",
        "youtube_analytics_videos", "youtube_shorts_90d",
        "virality_score", "jev_score", "ask_studio_answer",
        "pipeline_latency_report", "post_publish_check",
        "read_file", "list_dir", "get_protocol",
    ],
    "operator": [
        "youtube_upload", "submit_job", "job_status",
        "ask_studio", "write_file",
        "web_search", "fetch_url",
    ],
    "admin": ["*"],
}
# operator 继承 viewer
ROLE_TOOLS["operator"] = ROLE_TOOLS["viewer"] + ROLE_TOOLS["operator"]

def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19] + "Z"

def _load():
    if os.path.exists(TOKEN_FILE):
        return json.load(open(TOKEN_FILE))
    return {"tokens": {}}

def _save(d):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    json.dump(d, open(TOKEN_FILE, "w"), ensure_ascii=False, indent=2)
    os.chmod(TOKEN_FILE, 0o600)

def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()[:32]

def issue(tenant_id, role, days=90, note=""):
    """签发 token，返回明文（只显示一次）"""
    assert role in ROLE_TOOLS, f"未知角色 {role}"
    raw = "pk_" + secrets.token_urlsafe(32)
    d = _load()
    d["tokens"][_hash(raw)] = {
        "tenant_id": tenant_id, "role": role,
        "created": now_iso(),
        "expires": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()[:19] + "Z",
        "note": note, "revoked": False,
    }
    _save(d)
    audit("token_issue", tenant_id, {"role": role, "note": note})
    return raw

def verify(raw):
    """验证 token，返回 (tenant_id, role) 或 (None, None)"""
    d = _load()
    t = d["tokens"].get(_hash(raw))
    if not t or t["revoked"]:
        return None, None
    if t["expires"] < now_iso():
        return None, None
    return t["tenant_id"], t["role"]

def can_call(raw, tool_name):
    """检查 token 是否有权调用某工具"""
    tid, role = verify(raw)
    if not tid:
        return False, None
    allowed = ROLE_TOOLS[role]
    ok = "*" in allowed or tool_name in allowed
    return ok, tid

def revoke(raw):
    d = _load()
    h = _hash(raw)
    if h in d["tokens"]:
        d["tokens"][h]["revoked"] = True
        _save(d)
        audit("token_revoke", d["tokens"][h]["tenant_id"], {})
        return True
    return False

def audit(action, tenant_id, detail):
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    entry = {"ts": now_iso(), "action": action,
             "tenant_id": tenant_id, "detail": detail}
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def list_tokens(tenant_id=None):
    d = _load()
    out = []
    for h, t in d["tokens"].items():
        if tenant_id and t["tenant_id"] != tenant_id:
            continue
        out.append({**t, "hash": h[:8] + "..."})
    return out

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1]
    if cmd == "issue":
        days = int(sys.argv[4]) if len(sys.argv) > 4 else 90
        note = sys.argv[5] if len(sys.argv) > 5 else ""
        token = issue(sys.argv[2], sys.argv[3], days, note)
        print(f"Token（只显示一次，请保存）:\n{token}")
    elif cmd == "verify":
        tid, role = verify(sys.argv[2])
        print(json.dumps({"tenant": tid, "role": role}))
    elif cmd == "can":
        ok, tid = can_call(sys.argv[2], sys.argv[3])
        print(json.dumps({"allowed": ok, "tenant": tid}))
    elif cmd == "revoke":
        print("revoked" if revoke(sys.argv[2]) else "not found")
    elif cmd == "list":
        tid = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(list_tokens(tid), ensure_ascii=False, indent=2))
