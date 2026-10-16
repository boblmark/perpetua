#!/usr/bin/env python3
"""经 GitHub REST API 推送（git HTTPS 不接受 surrogate token，故走 API）。

合并语义（2026-10-16 定）：
- 远端 perpetua/* 之外的路径（pipeline/、youtube/、deploy/、.github/ 等）原样保留，
  一个 blob 都不重建，GitHub 侧的手工改动不会被覆盖。
- 本地 repo/perpetua/ 镜像（由 github_sync.sh 从运行系统 rsync 而来）全量接管
  远端 perpetua/*：新增/更新/删除都以本地为准。
- 无变化时零写操作。

用法：python3 github_push_api.py <repo_dir> "<commit message>" [--dry-run]
成功 -> 打印新 commit SHA；无变化 -> 打印 NO_CHANGES。
Token 经 authd 保险库实时获取，永不打印、永不落盘。
"""
import base64
import fnmatch
import hashlib
import json
import os
import sys
import urllib.request
import urllib.error

OWNER, REPO, BRANCH = "boblmark", "perpetua", "main"
API = "https://api.github.com"
MANAGED_PREFIX = "perpetua/"

# 镜像准入：代码与文档扩展名；状态/日志/备份/大体积目录一律排除
INCLUDE_EXTS = {".py", ".html", ".js", ".css", ".sh", ".md", ".txt",
                ".yaml", ".yml", ".service", ".ini", ".tar.gz"}
EXCLUDE_NAME_PATS = ["*.bak*", "*.lock", "*.log", "*.json"]
EXCLUDE_DIRS = {"videos", "snapshots", "db_backups", "deleted_backup", "artifacts",
                "logs", "hidden_logs", "audit", "auth", "tenants", "billing",
                "models", "jobs", "__pycache__", ".git", "repo", "build", "dist",
                "node_modules", "img_cache", ".venv", "venv"}


def get_token():
    for _p in ("/opt/hatch/skills/skill-creator/bin",
               "/opt/hatch/workflow-skills/custom-connector-setup/bin",
               "/opt/muse/skills/custom-connector-setup/bin"):
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)
    from dynamic_credentials import dynamic_credential_entry
    return dynamic_credential_entry("custom.github")["surrogate"]


TOKEN = get_token()


def api(method, path, data=None, retries=4):
    # 2026-10-16 实测：api.github.com 间歇性 RemoteDisconnected，必须重试
    import http.client
    import time
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            API + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + TOKEN,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "Perpetua-Dash"})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {e.read().decode()[:300]}")
        except (http.client.RemoteDisconnected, http.client.IncompleteRead,
                ConnectionError, TimeoutError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"网络闪断重试 {retries} 次仍失败 {method} {path}: {last}")


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def excluded_dir(dirname):
    return dirname in EXCLUDE_DIRS


def excluded_file(rel):
    base = os.path.basename(rel)
    for pat in EXCLUDE_NAME_PATS:
        if fnmatch.fnmatch(base, pat):
            return True
    low = rel.lower()
    if not any(low.endswith(ext) for ext in INCLUDE_EXTS):
        return True
    return False


def collect_managed(mirror_root):
    """walk 本地镜像目录 -> {remote_path: bytes}"""
    files = {}
    for dirpath, dirnames, filenames in os.walk(mirror_root):
        dirnames[:] = [d for d in dirnames if not excluded_dir(d)]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), mirror_root)
            if excluded_file(rel):
                continue
            with open(os.path.join(dirpath, fn), "rb") as fh:
                files[MANAGED_PREFIX + rel] = fh.read()
    return files


def main():
    repo_dir = sys.argv[1]
    message = sys.argv[2]
    dry_run = "--dry-run" in sys.argv

    ref = api("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")
    remote_sha = ref["object"]["sha"]
    rtree = api("GET", f"/repos/{OWNER}/{REPO}/git/trees/{remote_sha}?recursive=1")
    remote = {t["path"]: t for t in rtree.get("tree", []) if t["type"] == "blob"}

    managed = collect_managed(os.path.join(repo_dir, "perpetua"))
    local_sha = {p: git_blob_sha(d) for p, d in managed.items()}

    def remote_excluded(rel):
        """远端 perpetua/* 下命中本地排除规则的 -> 视为保留，不删除"""
        sub = rel[len(MANAGED_PREFIX):]
        parts = sub.split("/")
        if any(p in EXCLUDE_DIRS for p in parts[:-1]):
            return True
        return excluded_file(sub)

    preserved = {p: t for p, t in remote.items()
                 if not p.startswith(MANAGED_PREFIX) or remote_excluded(p)}
    remote_managed = {p: t for p, t in remote.items()
                      if p.startswith(MANAGED_PREFIX) and not remote_excluded(p)}

    added = [p for p in managed if p not in remote_managed]
    deleted = [p for p in remote_managed if p not in managed]
    updated = [p for p in managed
               if p in remote_managed and local_sha[p] != remote_managed[p]["sha"]]

    if not added and not deleted and not updated:
        print("NO_CHANGES")
        return

    print(f"[plan] 新增 {len(added)} / 更新 {len(updated)} / 删除 {len(deleted)} / "
          f"保留 {len(preserved)}（非 perpetua/* 原样不动）")
    if dry_run:
        for p in sorted(added)[:15]:
            print("  +", p)
        for p in sorted(updated)[:15]:
            print("  ~", p)
        for p in sorted(deleted)[:15]:
            print("  -", p)
        return

    blob_sha = {}
    for p, data in managed.items():
        if p in remote_managed and local_sha[p] == remote_managed[p]["sha"]:
            blob_sha[p] = remote_managed[p]["sha"]
            continue
        try:
            body, enc = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            body, enc = base64.b64encode(data).decode(), "base64"
        b = api("POST", f"/repos/{OWNER}/{REPO}/git/blobs",
                {"content": body, "encoding": enc})
        blob_sha[p] = b["sha"]

    mirror_root = os.path.join(repo_dir, "perpetua")
    entries = [{"path": p, "mode": t.get("mode", "100644"),
                "type": "blob", "sha": t["sha"]}
               for p, t in sorted(preserved.items())]
    for p in sorted(managed):
        full = os.path.join(mirror_root, os.path.relpath(p, MANAGED_PREFIX))
        entries.append({"path": p,
                        "mode": "100755" if os.access(full, os.X_OK) else "100644",
                        "type": "blob", "sha": blob_sha[p]})
    new_tree = api("POST", f"/repos/{OWNER}/{REPO}/git/trees", {"tree": entries})
    commit = api("POST", f"/repos/{OWNER}/{REPO}/git/commits",
                 {"message": message, "tree": new_tree["sha"],
                  "parents": [remote_sha],
                  "author": {"name": "Dash", "email": "dash@viralloopapp.com"}})
    new_sha = commit["sha"]
    # 注意：GitHub 更新 ref 用复数 /git/refs/，读取用单数 /git/ref/（两处不一样）
    api("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", {"sha": new_sha})
    print(new_sha)


if __name__ == "__main__":
    main()
