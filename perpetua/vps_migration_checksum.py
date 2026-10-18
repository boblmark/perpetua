#!/usr/bin/env python3
"""VPS 迁移包漂移检测的唯一校验口径。
覆盖迁移包实际装运的全部源码范围：/home/hatch/data/perpetua 递归全量，
排除运行时/状态/密钥/大体积目录（与 build_vps_migration_package.sh 的
rsync 排除清单保持一致，任一变化都要同步改两处）。
用法：python3 vps_migration_checksum.py  -> 打印 sha256 hex
"""
import hashlib
import os
import re

SRC = "/home/hatch/data/perpetua"

# 目录排除（相对路径前缀）
EXCLUDE_DIRS = {
    "repo", ".git", "videos", "snapshots", "logs", "hidden_logs",
    "artifacts", "db_backups", "deleted_backup", "models", "jobs",
    "tenants", "billing", "audit", "auth", "__pycache__",
    "distributor/cookies", "distributor/vendor/cookies",
    "distributor/matrix_pending", "distributor/pending_manual",
    "platform_browser_fallback", "ai_unhinged/ep1", "ai_unhinged/pilots",
    "ep1_qc/qc_out_20261010", "vps_console/img_cache",
    "deploy/perpetua-linux",
    "build", "teaser_splice_check", "gemini_fallback_review",
    "selftest/.thumbnails", "evolution_reports",  # 日报持续追加，运行时产物
    "arena_agent/jury_prompts",  # 2026-10-18: 陪审团 timestamped prompt/结果，cron 周期生成累积，运行时产物（曾致每轮 jury 后误报漂移重建）
}

# 文件名/后缀排除
EXCLUDE_SUFFIXES = (".log", ".pyc", ".bak", ".tmp", "~", ".mp4", ".webm", ".mov", ".avi")
EXCLUDE_NAMES = {
    "queue.db", "ops_center.db", "commander_chat_token",
    ".github_push_pending",
    "vps_traffic.jsonl", "viralloop_oa_live_cache.json", "video_quota.json",
    "formula_dedup_reject.log.json",
}
# 运行时状态 JSON（快照由 snapshot.sh 在迁移窗口实时生成，永不烘焙进包）
STATE_JSON_RES = (
    re.compile(r".*_queue\.json$"),
    re.compile(r".*_ledger\.json$"),
    re.compile(r".*_inbox\.json$"),
    re.compile(r".*_state\.json$"),
    re.compile(r".*_runs\.json$"),
    re.compile(r".*_heartbeat\.json$"),
    re.compile(r"^review_budget_.*\.json$"),
    re.compile(r"^collect_run_.*\.json$"),
    re.compile(r"^\.tmp_.*\.json$"),  # 2026-10-17: auto_pipeline 运行快照，cron 周期写入的新文件累积，运行时产物
)
# 运行时日报 markdown（cron 持续追加/重写，永不烘焙进包；evolution_reports/ 走目录排除）
RUNTIME_MD_RES = (
    re.compile(r"^deep_dive_\d{4}-\d{2}-\d{2}\.md$"),
)
STATE_JSON_NAMES = {
    "private_queue.json", "anomaly_ledger.json", "escalation_inbox.json",
    "command_queue.json", "commander_chat_queue.json", "cron_ops_queue.json",
    "executed_commands.json", "pipeline_runs.json",
    "dead_state_alert_dedup.json", "matrix_history.json",
    "qc_orphan_alerted.json",  # 死状态看门狗运行时告警记录，非源码
    "platform_matrix.json",  # 矩阵同步每5分钟重写，运行时状态
    "prompt_reviewed.json",  # 2026-10-17: 评审提交台账，cron 周期追加，运行时产物
    "awaiting_approval.json",  # 2026-10-17: 待审批评审项，管线状态，运行时产物
    "reject_window.json",  # 2026-10-17: 拒绝窗口时间戳，cron 周期写入，运行时产物
    "formula_dedup_daily.json",  # 2026-10-17: 每日去重统计，cron 每天重写，运行时产物
}

INCLUDE_EXTS = {
    ".py", ".sh", ".md", ".txt", ".yaml", ".yml", ".json", ".service",
    ".html", ".js", ".css", ".ini", ".conf", ".example", ".sample",
}


def included(relpath):
    parts = relpath.split(os.sep)
    # 目录前缀排除
    for i in range(1, len(parts)):
        if os.sep.join(parts[:i]) in EXCLUDE_DIRS:
            return False
    name = parts[-1]
    if name in EXCLUDE_NAMES:
        return False
    if name.lower().endswith(EXCLUDE_SUFFIXES) or ".bak-" in name:
        return False
    if name.endswith(".md") and any(r.match(name) for r in RUNTIME_MD_RES):
        return False
    if name.endswith(".json") and (
        name in STATE_JSON_NAMES
        or any(r.match(name) for r in STATE_JSON_RES)
    ):
        return False
    if os.sep.join(parts[:2]) == "deploy/perpetua-linux":
        return False
    ext = os.path.splitext(name)[1].lower()
    return ext in INCLUDE_EXTS


def checksum():
    files = []
    for root, dirs, filenames in os.walk(SRC):
        # 剪枝：跳过排除目录
        rel_root = os.path.relpath(root, SRC)
        if rel_root == ".":
            rel_root = ""
        def _is_excluded_dir(rp):
            return any(rp == x or rp.startswith(x + "/") for x in EXCLUDE_DIRS)
        if rel_root and _is_excluded_dir(rel_root):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs
                   if not _is_excluded_dir((rel_root + "/" + d).lstrip("/"))]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(root, fn), SRC)
            if included(rel):
                files.append(os.path.join(root, fn))
    h = hashlib.sha256()
    for f in sorted(files):
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest(), len(files)


if __name__ == "__main__":
    digest, n = checksum()
    print(digest)
