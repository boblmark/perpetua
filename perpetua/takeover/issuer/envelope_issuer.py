#!/usr/bin/env python3
"""信封签发端独立策略校验器（全接管议会 D20261020-002 v2，红队 KILL 1 修订）

部署隔离：本模块位于 takeover/issuer/，与任何执行器、与快照推送器
（takeover/snapshot_push.py）不同目录、不同文件、不同密钥对。
签发私钥只存在于此目录 keys/（600），执行端只应拿到 issuer_public.pem。

两道硬门（顺序不可换）：
  1. 硬编码天花板校验（check_ceilings）——验签只证明"是授权人签的"，
     本校验器证明"签的内容没越过全局天花板"；任一越界直接拒绝签发。
  2. Ed25519 签名（系统 OpenSSL 原生 Ed25519）——对信封 canonical JSON
     （不含 operator_signature 字段）签名。

硬编码天花板（改这些常量 = 改代码 = 必须重新评审，不接受运行时参数绕过）：
  - max_daily_publishes   ≤ 2
  - max_total_publishes   ≤ 6（且 ≥ max_daily_publishes）
  - expires_at - issued_at ≤ 7 天，且 expires_at > issued_at
  - 白名单动作只能 ⊆ {flip_public, private_upload, comment_draft, degrade_schedule}
    出现 delete / spend / generate / qc / 任何其他动作 → 拒绝签发
  - permissions.allow_delete_operation 恒 False、allow_auto_comment_post 恒 False
    （评论只准草稿、永不自动发布 —— 与用户既定评论人工门一致）
  - auth_channel_mode 恒 ISOLATED_BACKUP_OAUTH（v2 定版；HOST_API_PROXY
    等于变相共用凭据，红队 KILL 3 已否决）

validate_envelope() 为执行端独立校验函数：验天花板 + 验签名，两者全过才
返回 (True, "ok")。撤销状态不在此校验（撤销是 VPS 侧运行时状态，执行端
须按 v2 修订 5 在每次写前同步查撤销 + 本地缓存 TTL≤30s、不可达 fail-closed）。
"""
import base64
import json
import os
import secrets
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIV = HERE / "keys" / "issuer_private.pem"
PUB = HERE / "keys" / "issuer_public.pem"

# ---- 硬编码全局天花板（红队 KILL 1：签发期机器把关） ----
CEIL_MAX_DAILY_PUBLISHES = 2
CEIL_MAX_TOTAL_PUBLISHES = 6
CEIL_MAX_TTL_DAYS = 7
ALLOWED_ACTIONS = frozenset(
    {"flip_public", "private_upload", "comment_draft", "degrade_schedule"})
FORBIDDEN_ACTIONS = frozenset(
    {"delete", "spend", "generate", "qc", "review", "title_edit", "publish_comment"})
REQUIRED_AUTH_CHANNEL_MODE = "ISOLATED_BACKUP_OAUTH"


class EnvelopeRejected(Exception):
    """天花板校验未过：拒绝签发。"""


def _canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _parse_ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def check_ceilings(params) -> None:
    """对拟签发参数做天花板校验；越界抛 EnvelopeRejected（列全所有问题）。"""
    problems = []
    limits = params.get("limits") or {}
    daily = limits.get("max_daily_publishes")
    total = limits.get("max_total_publishes")
    if not isinstance(daily, int) or daily < 1 or daily > CEIL_MAX_DAILY_PUBLISHES:
        problems.append(
            f"max_daily_publishes={daily!r} 越界（须 1..{CEIL_MAX_DAILY_PUBLISHES}）")
    if not isinstance(total, int) or total < 1 or total > CEIL_MAX_TOTAL_PUBLISHES:
        problems.append(
            f"max_total_publishes={total!r} 越界（须 1..{CEIL_MAX_TOTAL_PUBLISHES}）")
    if isinstance(daily, int) and isinstance(total, int) and total < daily:
        problems.append("max_total_publishes < max_daily_publishes（自相矛盾）")
    stock = limits.get("min_stock_level_alert")
    if stock is not None and (not isinstance(stock, int) or stock < 0):
        problems.append(f"min_stock_level_alert={stock!r} 非法")
    try:
        issued = _parse_ts(params["issued_at"])
        expires = _parse_ts(params["expires_at"])
        if expires <= issued:
            problems.append("expires_at <= issued_at")
        elif expires - issued > timedelta(days=CEIL_MAX_TTL_DAYS):
            problems.append(
                f"信封有效期 > {CEIL_MAX_TTL_DAYS} 天（红队天花板）")
    except Exception as e:
        problems.append(f"issued_at/expires_at 不可解析: {e}")
    actions = params.get("actions")
    if not actions or not isinstance(actions, (list, tuple, set)):
        problems.append("actions 缺失或为空（空信封无意义）")
    else:
        bad = [a for a in actions if a not in ALLOWED_ACTIONS]
        if bad:
            problems.append(
                f"白名单外动作拒绝签发: {bad}（含 delete/spend 等一律不签）")
    if params.get("auth_channel_mode", REQUIRED_AUTH_CHANNEL_MODE) \
            != REQUIRED_AUTH_CHANNEL_MODE:
        problems.append(
            "auth_channel_mode 必须 ISOLATED_BACKUP_OAUTH（HOST_API_PROXY 已被红队否决）")
    if problems:
        raise EnvelopeRejected("; ".join(problems))


def _sign(data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    try:
        r = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(PRIV),
             "-rawin", "-in", tmp], capture_output=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"openssl sign failed: {r.stderr.decode()[:200]}")
        return r.stdout
    finally:
        os.unlink(tmp)


def _verify(data: bytes, sig: bytes, pubkey: Path) -> bool:
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(data)
        tmp_data = tf.name
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(sig)
        tmp_sig = tf.name
    try:
        r = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pubkey),
             "-rawin", "-in", tmp_data, "-sigfile", tmp_sig],
            capture_output=True, timeout=30)
        return r.returncode == 0
    finally:
        os.unlink(tmp_data)
        os.unlink(tmp_sig)


def issue_envelope(params) -> dict:
    """params: {limits:{max_daily_publishes,max_total_publishes,
    min_stock_level_alert}, actions:[...], expires_at(可选, 默认+7d 内),
    revocation_check_url(可选), auth_channel_mode(可选, 恒定版值)}。
    先过天花板，再签名，返回完整信封 dict（字段按议会规格 B 节）。
    本函数只签发、不落盘、不推送 —— 签发是用户专属动作的机器把关层。"""
    now = datetime.now(timezone.utc)
    p = dict(params)
    p.setdefault("issued_at", now.isoformat())
    p.setdefault("expires_at", (now + timedelta(days=CEIL_MAX_TTL_DAYS)).isoformat())
    p.setdefault("auth_channel_mode", REQUIRED_AUTH_CHANNEL_MODE)
    check_ceilings(p)  # 先校验，后签名；越界直接抛 EnvelopeRejected
    actions = list(p["actions"])
    env = {
        "envelope_id": str(uuid.uuid4()),
        "issued_at": p["issued_at"],
        "expires_at": p["expires_at"],
        "revocation_nonce": secrets.token_hex(16),
        "revocation_check_url": p.get("revocation_check_url"),
        "limits": {
            "max_total_publishes": p["limits"]["max_total_publishes"],
            "max_daily_publishes": p["limits"]["max_daily_publishes"],
            "min_stock_level_alert": p["limits"].get("min_stock_level_alert", 4),
        },
        "actions": actions,
        "permissions": {
            "allow_flip_public": "flip_public" in actions,
            "allow_private_upload": "private_upload" in actions,
            "allow_delete_operation": False,   # const False，永不签发
            "allow_auto_comment_post": False,  # const False，评论只准草稿
        },
        "auth_channel_mode": REQUIRED_AUTH_CHANNEL_MODE,
    }
    env["operator_signature"] = base64.b64encode(_sign(_canonical(env))).decode()
    return env


def validate_envelope(envelope, pubkey_path=None):
    """执行端独立校验：天花板复核 + Ed25519 验签。
    返回 (ok: bool, reason: str)。任一不过即 False，执行端必须拒绝执行。"""
    env = dict(envelope)
    sig_b64 = env.pop("operator_signature", None)
    if not sig_b64:
        return False, "missing operator_signature"
    try:
        check_ceilings({
            "limits": env.get("limits"),
            "actions": env.get("actions"),
            "issued_at": env.get("issued_at"),
            "expires_at": env.get("expires_at"),
            "auth_channel_mode": env.get("auth_channel_mode"),
        })
    except EnvelopeRejected as e:
        return False, f"ceiling: {e}"
    perms = env.get("permissions") or {}
    if perms.get("allow_delete_operation") is not False \
            or perms.get("allow_auto_comment_post") is not False:
        return False, "permissions const violation (delete/auto_comment must be false)"
    try:
        sig = base64.b64decode(sig_b64)
    except Exception:
        return False, "signature not base64"
    pub = Path(pubkey_path) if pubkey_path else PUB
    if not _verify(_canonical(env), sig, pub):
        return False, "signature verify failed"
    return True, "ok"
