#!/usr/bin/env python3
"""muse-main 不健康时的 QQ box 自动降级桥（D20261028-006）。

取代已下掉的 nano 桥（dispatcher_nano_bridge）：muse-main 一旦不健康，
本脚本把任务自动切到 QQ box MCP 生成，而不是丢进已不存在的后端。

两路（均为 fail-closed，失败绝不丢任务）：
1. dispatcher 路：扫描 VPS pending 中 consumer=muse-main、超时未认领的
   generate_video 任务，经 QQ box muse_video 生成后交付 dispatcher
   （deliver_result + mark_pending_done），muse-main 恢复后也不会重复领。
   已认领（claimed）的任务不在此路扫描范围内——2026-10-28 17:05
   用户留置令（认领未交片先留着不动）不受影响。
2. pipeline 路：扫描 event_bus 中 status=qqbox_pending 的条目（由
   muse_or_nano.route() 在 muse-main 不健康时改派），经 QQ box 生成后
   写标准 done 文件并翻回 job_submitted，走 collect 原有 QC→上传流程。

安全 rails：
- 浓缩 prompt  deterministic：只用 hook / 场景句 / payoff 类别拼故事段，
  找不到场景句时 fail-closed（留任务不动、只记日志，不瞎编长模板直送——
  11k 模板原文直送必被 integrity_check_failed 拒绝，2026-10-28 实证）。
- 单轮最多处理 1 条（QQ box 账号与隧道节流），同一任务 QQ box 尝试上限 2 次，
  超限后留 pending、只告警，不再烧账号额度。
- 生成或交付任一步失败：不写 done、不改 pending、不标 failed，任务原地
  保留，muse-main 恢复后仍可认领；下轮 daemon 可重试（上限内）。
- 绝不调用 nano 相关代码，绝不改 muse-main 已认领任务，绝不公开上传。

用法：
  python3 qqbox_fallback.py --mode dispatcher --timeout-min 15 [--dry-run]
  python3 qqbox_fallback.py --mode pipeline [--dry-run]
  python3 qqbox_fallback.py --mode both --timeout-min 15 [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/hatch/data/perpetua")
DB = "/home/hatch/data/ops_center.db"
VEO_INBOX = Path("/home/hatch/data/veo_inbox")
MCP_DONE = Path("/home/hatch/data/mcp_jobs/done")
ATTEMPTS_PATH = BASE / "qqbox_bridge_attempts.json"
MAX_ATTEMPTS = 2
MAX_JOBS_PER_RUN = 1
QQBOX_ACCOUNT = "morgan_bennett@chaitgpt.org"

# 导入 QQ box 调用层之前先定隧道端点（laptop 脚本在 import 时读环境变量）。
os.environ.setdefault("MCP_ENDPOINT", "http://127.0.0.1:8748/mcp")
sys.path.insert(0, str(BASE))

PAYOFF_HINTS = {
    "CAT_1_LIQUID_FOAM": "the device answers with a harmless splash of liquid or foam",
    "CAT_2_MECHANICAL_IMPACT": "the device answers with a harmless mechanical block or jerk",
    "CAT_3_ACOUSTIC_PNEUMATIC": "the device answers with a loud funny sound blast or air gust",
    "CAT_4_CONTAINMENT_LOCKOUT": "the device briefly locks her out in a harmless comic trap",
    "CAT_5_POWDER_DISCHARGE": "the device answers with a harmless puff of powder or paper",
    "CAT_6_SOCIAL_EXPOSURE": "the device exposes her embarrassment to everyone around",
}


def _log(msg: str):
    print(f"[qqbox-fallback] {msg}", flush=True)


def _load_attempts() -> dict:
    try:
        return json.loads(ATTEMPTS_PATH.read_text())
    except Exception:
        return {}


def _save_attempts(data: dict):
    ATTEMPTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def _attempts_for(key: str) -> int:
    return int(_load_attempts().get(key, {}).get("attempts", 0))


def _record_attempt(key: str, ok: bool, err: str = ""):
    data = _load_attempts()
    if ok:
        data.pop(key, None)
    else:
        rec = data.get(key, {"attempts": 0})
        rec["attempts"] = int(rec.get("attempts", 0)) + 1
        rec["last_attempt"] = datetime.now(timezone.utc).isoformat()
        if err:
            rec["last_error"] = err[:300]
        data[key] = rec
    _save_attempts(data)


def _scene_sentence_from_prompt(prompt: str) -> str | None:
    """从 11k 模板里抽场景句。找不到则返回 None（fail-closed）。"""
    if not prompt:
        return None
    m = re.search(r"Conflict already in progress, zero setup:\s*(.+?)(?:\.|\n)",
                  prompt, re.S)
    if m:
        s = " ".join(m.group(1).split())
        if len(s) >= 20:
            return s
    m = re.search(r"the entitled woman programs the ([^,.;]+?) for ([^,.;]+?)[,.;]",
                  prompt)
    if m:
        return f"the entitled woman programs the {m.group(1)} for {m.group(2)}"
    return None


def concentrate_from_item(item: dict) -> str | None:
    """pipeline 条目 → 浓缩故事 prompt（约 350-450 字）。"""
    hook = (item.get("hook") or "").strip()
    scene = None
    if hook and len(hook) >= 20:
        scene = hook
    else:
        scene = _scene_sentence_from_prompt(item.get("prompt") or "")
    if not scene:
        return None
    scene = scene.replace("the entitled woman", "a middle-aged woman")
    if not scene.endswith("."):
        scene += "."
    payoff = PAYOFF_HINTS.get(item.get("payback_category") or "",
                               "the device responds with one unexpected, funny move")
    return (
        "Vertical short video, 10 seconds, with sound, CCTV-style footage. "
        f"{scene} She escalates, gesturing angrily and shouting. "
        f"Then {payoff}. She freezes mid-gesture in comic disbelief, "
        "caught on camera. Funny, exaggerated expressions."
    )


def concentrate_from_instruction(instruction: str) -> str | None:
    """dispatcher 任务 instruction（11k 模板）→ 浓缩故事 prompt。"""
    scene = _scene_sentence_from_prompt(instruction or "")
    if not scene:
        return None
    scene = scene.replace("the entitled woman", "a middle-aged woman")
    if not scene.endswith("."):
        scene += "."
    return (
        "Vertical short video, 10 seconds, with sound, CCTV-style footage. "
        f"{scene} She escalates, gesturing angrily and shouting. "
        "Then the device responds with one unexpected, funny move. "
        "She freezes mid-gesture in comic disbelief, caught on camera. "
        "Funny, exaggerated expressions."
    )


def call_qqbox(prompt: str, out_path: Path) -> tuple[str, int]:
    """调 QQ box muse_video 并拉回成片。返回 (box_filename, bytes)。"""
    import laptop_mcp_generate as lmg
    status, is_error, text = lmg.mcp_call(
        "muse_video",
        {"account": QQBOX_ACCOUNT, "prompt": prompt, "segments": 1, "timeout": 1200},
        timeout=1500)
    if is_error:
        raise RuntimeError(f"muse_video isError: {text[:300]}")
    try:
        parsed = json.loads(text[text.index("{"):])
    except Exception:
        raise RuntimeError(f"muse_video 结果不可解析: {text[:300]}")
    files = parsed.get("files") or []
    if not files:
        raise RuntimeError(f"muse_video 无文件: {text[:300]}")
    fname = files[0]["filename"]
    dl_url = (files[0].get("downloadUrl") or files[0].get("playUrl")
              or parsed.get("downloadUrl") or parsed.get("playUrl"))
    nbytes = lmg.mcp_download(fname, str(out_path), download_url=dl_url)
    if nbytes <= 10000 or not out_path.exists():
        raise RuntimeError(f"下载成片过小或缺失: {nbytes}")
    return fname, nbytes


def _deliver_dispatcher(client, job_id: str, local_file: str) -> str:
    """把成片交付 dispatcher（backend 标 qqbox-bridge，不冒充 nano）。"""
    import base64 as _b64
    filename = os.path.basename(local_file)
    remote_dir = f"/opt/mcp-b/data/output/{job_id}"
    client._ssh_run(f"mkdir -p {remote_dir}")
    from dispatcher_nano_bridge import SSH_KEY, PROXY, VPS_HOST
    r = subprocess.run(
        ["scp", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
         "-o", f"ProxyCommand={PROXY}", local_file, f"{VPS_HOST}:{remote_dir}/{filename}"],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"scp 失败: {r.stderr[-200:]}")
    result = {"job_id": job_id, "status": "done", "backend": "qqbox-bridge",
              "completed_at": datetime.now(timezone.utc).isoformat(),
              "file": filename}
    b64 = _b64.b64encode(json.dumps(result, ensure_ascii=False).encode()).decode()
    client._ssh_run(
        f"echo {b64} | base64 -d > /opt/mcp-b/data/mcp_jobs/done/{job_id}.result.json")
    return filename


def run_dispatcher(timeout_min: int, dry_run: bool) -> list[dict]:
    """dispatcher 路。返回每条处理结果（失败不丢任务）。"""
    from dispatcher_nano_bridge import DispatcherClient
    client = DispatcherClient()
    jobs = client.list_pending_jobs()
    results = []
    handled = 0
    for job in jobs:
        if handled >= MAX_JOBS_PER_RUN:
            break
        if job.consumer != "muse-main" or job.job_type != "generate_video":
            continue
        if client.job_already_done(job.job_id):
            continue
        age = job.age_minutes
        if age is None or age < timeout_min:
            continue
        key = f"dispatcher:{job.job_id}"
        if _attempts_for(key) >= MAX_ATTEMPTS:
            _log(f"跳过 {job.job_id}：QQ box 尝试已达上限 {MAX_ATTEMPTS}，留 pending 待人工")
            results.append({"job_id": job.job_id, "ok": False, "error": "attempts_exhausted"})
            continue
        raw = client.read_job_file(job.job_id)
        payload = raw.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        prompt = concentrate_from_instruction(payload.get("instruction", ""))
        if not prompt:
            _log(f"跳过 {job.job_id}：浓缩失败（无场景句），留 pending 不瞎送")
            results.append({"job_id": job.job_id, "ok": False, "error": "concentrate_failed"})
            continue
        if dry_run:
            _log(f"dry-run：{job.job_id} 将走 QQ box（prompt {len(prompt)} 字）")
            results.append({"job_id": job.job_id, "ok": True, "dry_run": True})
            handled += 1
            continue
        out_path = VEO_INBOX / f"qqbox_{job.job_id}.mp4"
        try:
            VEO_INBOX.mkdir(parents=True, exist_ok=True)
            fname, nbytes = call_qqbox(prompt, out_path)
            _deliver_dispatcher(client, job.job_id, str(out_path))
            client.mark_pending_done(job.job_id)
            _record_attempt(key, True)
            _log(f"QQ box 已交付 {job.job_id}：{fname} {nbytes}B → dispatcher done")
            results.append({"job_id": job.job_id, "ok": True, "file": str(out_path)})
            handled += 1
        except Exception as e:
            _record_attempt(key, False, str(e))
            _log(f"QQ box 失败 {job.job_id}（任务留 pending 不丢）：{e}")
            results.append({"job_id": job.job_id, "ok": False, "error": str(e)[:300]})
            break
    return results


def run_pipeline(dry_run: bool) -> list[dict]:
    """pipeline 路。返回每条处理结果。"""
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT id, payload FROM event_bus").fetchall()
    results = []
    handled = 0
    for row_id, payload_text in rows:
        if handled >= MAX_JOBS_PER_RUN:
            break
        try:
            item = json.loads(payload_text)
        except Exception:
            continue
        if item.get("status") != "qqbox_pending":
            continue
        key = f"pipeline:{row_id}"
        if _attempts_for(key) >= MAX_ATTEMPTS:
            _log(f"跳过 event_bus {row_id}：QQ box 尝试已达上限，留 qqbox_pending 待人工")
            results.append({"id": row_id, "ok": False, "error": "attempts_exhausted"})
            continue
        prompt = concentrate_from_item(item)
        if not prompt:
            _log(f"跳过 event_bus {row_id}：浓缩失败（无 hook/场景句），留 qqbox_pending")
            results.append({"id": row_id, "ok": False, "error": "concentrate_failed"})
            continue
        if dry_run:
            _log(f"dry-run：event_bus {row_id} 将走 QQ box（prompt {len(prompt)} 字）")
            results.append({"id": row_id, "ok": True, "dry_run": True})
            handled += 1
            continue
        jid = item.get("job_id") or f"qqbox-{row_id}"
        # 2026-10-29（pipeline 路 QQ box 接线补洞）：submit 侧 qqbox 分支
        # 一律写 job_id，但无 job_id 的存量 qqbox_pending 若不回填，
        # done 文件名（qqbox-<row_id>）与 collect 按 job_id 的查找键失配，
        # 翻回的 job_submitted 永不被捡。只补缺失值，绝不覆盖已有 job_id。
        if not item.get("job_id"):
            item["job_id"] = jid
        out_path = VEO_INBOX / f"qqbox_{row_id}.mp4"
        try:
            VEO_INBOX.mkdir(parents=True, exist_ok=True)
            fname, nbytes = call_qqbox(prompt, out_path)
            if not item.get("prompt_original"):
                item["prompt_original"] = item.get("prompt")
            item["prompt"] = prompt
            item["video_file"] = str(out_path)
            item["box_filename"] = fname
            item["box_path"] = "/data/home/muse/generated-videos/" + fname
            item["status"] = "job_submitted"
            item["gen_backend"] = "qqbox"
            item["submitted_at"] = datetime.now(timezone.utc).isoformat()
            item["gen_poll_count"] = 0
            item["qqbox_generated_at"] = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE event_bus SET payload=? WHERE id=?",
                       (json.dumps(item, ensure_ascii=False), row_id))
            db.commit()
            MCP_DONE.mkdir(parents=True, exist_ok=True)
            done = {"status": "done", "file": str(out_path), "backend": "qqbox",
                    "topic": item.get("topic")}
            (MCP_DONE / f"{jid}.result.json").write_text(
                json.dumps(done, ensure_ascii=False))
            _record_attempt(key, True)
            _log(f"QQ box 已生成 event_bus {row_id}：{fname} {nbytes}B → job_submitted 待 QC")
            results.append({"id": row_id, "ok": True, "file": str(out_path)})
            handled += 1
        except Exception as e:
            db.rollback()
            _record_attempt(key, False, str(e))
            _log(f"QQ box 失败 event_bus {row_id}（留 qqbox_pending 不丢）：{e}")
            results.append({"id": row_id, "ok": False, "error": str(e)[:300]})
            break
    db.close()
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="QQ box 自动降级桥（D20261028-006）")
    ap.add_argument("--mode", default="both", choices=["dispatcher", "pipeline", "both"])
    ap.add_argument("--timeout-min", type=int, default=15)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = {}
    if args.mode in ("dispatcher", "both"):
        try:
            out["dispatcher"] = run_dispatcher(args.timeout_min, args.dry_run)
        except Exception as e:
            _log(f"dispatcher 路异常（不阻塞 pipeline 路）：{e}")
            out["dispatcher"] = [{"ok": False, "error": str(e)[:300]}]
    if args.mode in ("pipeline", "both"):
        try:
            out["pipeline"] = run_pipeline(args.dry_run)
        except Exception as e:
            _log(f"pipeline 路异常：{e}")
            out["pipeline"] = [{"ok": False, "error": str(e)[:300]}]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
