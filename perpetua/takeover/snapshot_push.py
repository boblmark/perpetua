#!/usr/bin/env python3
"""已质检私有库存快照推送器（全接管议会 D20261020-002 v2，Phase 1.5）

职责（只读生产 + 只写 takeover 自己的文件与 VPS snapshot 目录）：
  1. 从真相源 queue_db.privateq_load() 读取 private 队列；
     口径：入队点在 auto_pipeline._enqueue_private_flip —— QC 通过后
     自动上传 private 成功才入队，status=="waiting" == 已质检 + private
     待翻转库存（render 完成是入队前置）。published/flip_blocked 不入快照。
  2. 生成快照 JSON（version 单调递增，记录在 takeover/state/）；
  3. Ed25519 签名（系统 OpenSSL 3.x 原生 Ed25519，私钥 keys/ 600）；
  4. 经既有 SSH 通道（代理 + id_ed25519，与 gen_video_musemain 同参数）
     推送到 VPS /opt/mcp-b/data/takeover/snapshot/（临时名上传后远端 mv，
     原子替换）。

铁律：任何失败只记日志（takeover/logs/snapshot_push.log），绝不修改任何
生产状态；本脚本从不写 queue_db / private_queue / pipeline 任何文件。

用法：
  python3 snapshot_push.py            # 正式跑：生成+签名+推送
  python3 snapshot_push.py --dry-run  # 自测：内存生成+本地验签，不落盘 version、不推送
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/hatch/data/perpetua/takeover")
KEYS = BASE / "keys"
PRIV = KEYS / "ed25519_private.pem"
PUB = KEYS / "ed25519_public.pem"
STATE_FILE = BASE / "state" / "snapshot_state.json"
CURRENT = BASE / "current"
LOG_FILE = BASE / "logs" / "snapshot_push.log"

VPS = "root@192.166.82.123"
REMOTE_DIR = "/opt/mcp-b/data/takeover/snapshot"
SSH_OPTS = [
    "-i", "/home/hatch/.ssh/id_ed25519",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
    "-o", "ConnectTimeout=25",
]

sys.path.insert(0, "/home/hatch/data/perpetua")


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_items(version):
    """读真相源，导出已质检 + private（status==waiting）库存条目。"""
    import queue_db  # 只读 load，绝不 save

    items = []
    for e in queue_db.privateq_load():
        if e.get("status") != "waiting":
            continue
        vf = e.get("video_file")
        digest = None
        file_missing = False
        if vf and os.path.isfile(vf):
            digest = sha256_file(vf)
        else:
            file_missing = True
        items.append({
            "video_id": e.get("_row_key") or e.get("video_id"),
            "youtube_video_id": e.get("video_id"),
            "title": e.get("title"),
            "content_sha256": digest,
            "content_file_missing": file_missing,
            "scheduled_slot": e.get("slot"),
            "scheduled_at": e.get("scheduled_at"),
            "qc_score": e.get("review_score"),
            "version": version,
        })
    items.sort(key=lambda x: (x.get("scheduled_at") or "", x.get("youtube_video_id") or ""))
    return items


def canonical_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def openssl_sign(data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(data)
        tmp = tf.name
    try:
        r = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(PRIV),
             "-rawin", "-in", tmp],
            capture_output=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"openssl sign failed: {r.stderr.decode()[:200]}")
        return r.stdout
    finally:
        os.unlink(tmp)


def openssl_verify(data: bytes, sig: bytes) -> bool:
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(data)
        tmp_data = tf.name
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(sig)
        tmp_sig = tf.name
    try:
        r = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(PUB),
             "-rawin", "-in", tmp_data, "-sigfile", tmp_sig],
            capture_output=True, timeout=30)
        return r.returncode == 0
    finally:
        os.unlink(tmp_data)
        os.unlink(tmp_sig)


def read_version():
    try:
        return int(json.loads(STATE_FILE.read_text())["version"])
    except Exception:
        return 0


def push(local_json: Path, local_sig: Path):
    subprocess.run(["ssh"] + SSH_OPTS + [VPS, f"mkdir -p {REMOTE_DIR}"],
                   capture_output=True, timeout=60, check=True)
    for src, name in [(local_json, "snapshot.json"), (local_sig, "snapshot.sig"),
                      (PUB, "snapshot.pub.pem")]:
        subprocess.run(["scp"] + SSH_OPTS + [str(src), f"{VPS}:{REMOTE_DIR}/.{name}.tmp"],
                       capture_output=True, timeout=120, check=True)
        subprocess.run(["ssh"] + SSH_OPTS + [VPS, f"mv {REMOTE_DIR}/.{name}.tmp {REMOTE_DIR}/{name}"],
                       capture_output=True, timeout=60, check=True)


def main():
    dry = "--dry-run" in sys.argv
    version = read_version() + 1
    items = collect_items(version)
    snapshot = {
        "schema": "takeover.inventory_snapshot/v1",
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "dash:snapshot_push",
        "source": "queue_db.privateq_load status==waiting (QC passed + uploaded private)",
        "item_count": len(items),
        "items": items,
    }
    data = canonical_bytes(snapshot)
    sig = openssl_sign(data)
    if not openssl_verify(data, sig):
        log("ERROR 本地验签失败，中止")
        return 1
    sig_b64 = base64.b64encode(sig).decode()
    if dry:
        log(f"DRY-RUN ok version={version} items={len(items)} "
            f"snapshot_sha256={hashlib.sha256(data).hexdigest()[:16]} sig_b64_len={len(sig_b64)} "
            f"verify=PASS (未落盘、未推送)")
        for it in items:
            log(f"DRY-RUN item {it['youtube_video_id']} slot={it['scheduled_slot']} "
                f"qc={it['qc_score']} sha={'ok' if it['content_sha256'] else 'MISSING'}")
        return 0
    CURRENT.mkdir(parents=True, exist_ok=True)
    local_json = CURRENT / "snapshot.json"
    local_sig = CURRENT / "snapshot.sig"
    local_json.write_bytes(data)
    local_sig.write_text(sig_b64 + "\n", encoding="utf-8")
    try:
        push(local_json, local_sig)
    except Exception as e:
        log(f"ERROR 推送 VPS 失败（本地快照已留存，未改任何生产状态）: {e}")
        return 1
    STATE_FILE.write_text(json.dumps({"version": version,
                                      "pushed_at": snapshot["generated_at"]}),
                          encoding="utf-8")
    log(f"PUSH ok version={version} items={len(items)} -> VPS:{REMOTE_DIR}/snapshot.json")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 兜底：只记日志，不改生产状态
        log(f"ERROR 未捕获异常: {e}")
        sys.exit(1)
