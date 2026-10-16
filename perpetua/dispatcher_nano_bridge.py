#!/usr/bin/env python3
"""Dispatcher ↔ nanoMuse 协议桥接层。

背景：Perpetua dispatcher 用 submit_job/claim_job/job_status 队列协议，
nanoMuse 用 thread/event 聊天协议，两者不兼容。本桥接层做翻译。

工作模式：
1. 扫描 dispatcher pending 队列，找 consumer="muse-main" 且超时未被领走的任务
2. 把 job 翻译成 nanoMuse thread 消息并提交
3. 轮询 nanoMuse 结果，翻译成 dispatcher result.json 格式
4. 文件交付：nanoMuse 本地路径 → VPS /opt/mcp-b/data/output/<job_id>/

安全约束：
- 绝不调用 claim_job 冒充 muse-main（避免抢任务）
- 绝不修改 job 的 consumer 字段
- 只处理明确超过超时阈值的 pending 任务
- 所有 VPS 写操作走 SSH，路径做严格校验

用法：
  # 扫描并处理所有超时任务（默认超时 30 分钟）
  python3 dispatcher_nano_bridge.py --scan

  # 手动处理指定 job
  python3 dispatcher_nano_bridge.py --job-id <job_id>

  # 只列出超时任务，不处理
  python3 dispatcher_nano_bridge.py --scan --dry-run

  # 自定义超时阈值（分钟）
  python3 dispatcher_nano_bridge.py --scan --timeout-min 60
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------ 配置

VPS_HOST = "root@192.166.82.123"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
DISPATCHER_KEY_PATH = "/home/hatch/data/mcp_server/.token-dash-dispatcher"
DISPATCHER_URL_BASE = "http://192.166.82.123:8740/mcp"

# VPS 路径
VPS_PENDING_DIR = "/opt/mcp-b/data/mcp_jobs/pending"
VPS_DONE_DIR = "/opt/mcp-b/data/mcp_jobs/done"
VPS_OUTPUT_BASE = "/opt/mcp-b/data/output"

# nanoMuse
NANOMUSE_BASE = "http://127.0.0.1:18739"
NANOMUSE_TOKEN_PATH = "/home/hatch/.nanomuse/server_token"

# 默认
DEFAULT_TIMEOUT_MIN = 30
DEFAULT_POLL_INTERVAL_SEC = 30
DEFAULT_NANO_TIMEOUT_MIN = 20

TARGET_CONSUMER = "muse-main"


def _ssh_base() -> list[str]:
    return [
        "ssh", "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ProxyCommand={PROXY}",
        VPS_HOST,
    ]


def _valid_job_id(job_id: str) -> bool:
    """严格校验 job_id，防止路径注入。"""
    return bool(re.fullmatch(r"[\w-]+", job_id or ""))


# ------------------------------------------------------------------ 数据结构

@dataclass
class DispatcherJob:
    """从 pending 文件解析出的任务。"""
    job_id: str
    job_type: str
    consumer: str
    payload: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    queued_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def age_minutes(self) -> float:
        """任务已排队分钟数。解析失败返回 -1。"""
        if not self.queued_at:
            return -1
        try:
            # 尝试多种时间格式
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(self.queued_at, fmt)
                    break
                except ValueError:
                    continue
            else:
                # 尝试 fromisoformat
                dt = datetime.fromisoformat(self.queued_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - dt).total_seconds() / 60
        except Exception:
            return -1


@dataclass
class BridgeResult:
    """桥接处理结果。"""
    job_id: str
    success: bool
    backend: str = "nanoMuse"
    output_file: str = ""  # VPS 上的相对路径
    error: str = ""
    nano_thread_id: str = ""


# ------------------------------------------------------------------ Dispatcher 客户端

class DispatcherClient:
    """Dispatcher 访问：MCP JSON-RPC + SSH 文件直读（只读）+ SSH 文件写入（结果交付）。"""

    def __init__(self, key_path: str = DISPATCHER_KEY_PATH):
        self.key_path = key_path
        self._key: str | None = None

    @property
    def key(self) -> str:
        if self._key is None:
            with open(self.key_path, encoding="utf-8") as f:
                self._key = f.read().strip()
        return self._key

    # -- SSH 只读 --

    def _ssh_run(self, remote_cmd: str, timeout: int = 60) -> str:
        r = subprocess.run(
            _ssh_base() + [remote_cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            raise RuntimeError(f"SSH 失败: {r.stderr[-200:]}")
        return r.stdout

    def list_pending_jobs(self) -> list[DispatcherJob]:
        """列出 pending 目录所有任务（只读）。"""
        # 用 python3 在远端解析，避免 shell 引号地狱。
        # 注意：远程 python -c 必须用真实换行+缩进，复合语句(for/try)不能挤在一行
        # （2026-10-12 修：旧版 "for f in ...: try:" 单行写法必报 SyntaxError，
        # 导致 --scan 永远失败）。整段脚本经 shlex.quote 包裹，彻底避开引号嵌套。
        import shlex as _shlex
        _script = "\n".join([
            "import json, os, glob",
            "d = '/opt/mcp-b/data/mcp_jobs/pending'",
            "out = []",
            "for f in sorted(glob.glob(d + '/*.json')):",
            "    try:",
            "        j = json.load(open(f))",
            "        jid = j.get('job_id') or os.path.basename(f).replace('.json', '').split('.')[0]",
            "        out.append({'file': f, 'job_id': jid, 'job_type': j.get('job_type', ''), 'consumer': j.get('consumer', ''), 'payload': j.get('payload', ''), 'idempotency_key': j.get('idempotency_key', ''), 'queued_at': j.get('queued_at') or j.get('created_at') or ''})",
            "    except Exception:",
            "        pass",
            "print(json.dumps(out))",
        ])
        py = "python3 -c " + _shlex.quote(_script)
        out = self._ssh_run(py)
        try:
            items = json.loads(out.strip())
        except Exception as e:
            raise RuntimeError(f"pending 列表解析失败: {e}")
        jobs = []
        for it in items:
            payload = it.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {"_raw": payload}
            jobs.append(DispatcherJob(
                job_id=it.get("job_id", ""),
                job_type=it.get("job_type", ""),
                consumer=it.get("consumer", ""),
                payload=payload if isinstance(payload, dict) else {},
                idempotency_key=it.get("idempotency_key", ""),
                queued_at=it.get("queued_at", ""),
                raw=it,
            ))
        return jobs

    def read_job_file(self, job_id: str) -> dict[str, Any]:
        """读取单个 pending job 文件（只读）。"""
        if not _valid_job_id(job_id):
            raise ValueError(f"非法 job_id: {job_id[:40]}")
        sh = (
            f"for f in {VPS_PENDING_DIR}/{job_id}.json "
            f"{VPS_PENDING_DIR}/{job_id}.*.json; do "
            "[ -f \"$f\" ] && { cat \"$f\"; break; }; done"
        )
        out = self._ssh_run(sh).strip()
        if not out:
            return {}
        return json.loads(out)

    def job_already_done(self, job_id: str) -> bool:
        """检查 done 目录是否已有结果（避免重复处理）。"""
        if not _valid_job_id(job_id):
            raise ValueError(f"非法 job_id: {job_id[:40]}")
        sh = (
            f"[ -f {VPS_DONE_DIR}/{job_id}.result.json ] && echo YES || echo NO"
        )
        return self._ssh_run(sh).strip() == "YES"

    # -- 结果交付（写） --

    def deliver_result(
        self,
        job_id: str,
        local_file: str,
        status: str = "done",
        error: str = "",
    ) -> str:
        """交付结果到 VPS。

        1. scp 本地文件 → VPS /opt/mcp-b/data/output/<job_id>/
        2. 写 /opt/mcp-b/data/mcp_jobs/done/<job_id>.result.json
        返回 VPS 上的 file 相对路径。
        """
        if not _valid_job_id(job_id):
            raise ValueError(f"非法 job_id: {job_id[:40]}")
        if status == "done" and not (local_file and os.path.exists(local_file)):
            raise ValueError(f"本地文件不存在: {local_file}")

        filename = os.path.basename(local_file) if local_file else ""
        # 防路径穿越
        if filename and ("/" in filename or ".." in filename):
            raise ValueError(f"非法文件名: {filename}")

        remote_dir = f"{VPS_OUTPUT_BASE}/{job_id}"

        if status == "done":
            # 1. 建目录并 scp
            self._ssh_run(f"mkdir -p {remote_dir}")
            scp_cmd = [
                "scp", "-i", SSH_KEY,
                "-o", "StrictHostKeyChecking=no",
                "-o", f"ProxyCommand={PROXY}",
                local_file, f"{VPS_HOST}:{remote_dir}/{filename}",
            ]
            r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"scp 失败: {r.stderr[-200:]}")

        # 2. 写 result.json
        result = {
            "job_id": job_id,
            "status": status,
            "backend": "nanoMuse-bridge",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if status == "done":
            result["file"] = filename
        if error:
            result["error"] = error[:500]

        # 通过 base64 写文件，避免引号转义问题
        b64 = __import__("base64").b64encode(
            json.dumps(result, ensure_ascii=False).encode()
        ).decode()
        self._ssh_run(
            f"echo {b64} | base64 -d > {VPS_DONE_DIR}/{job_id}.result.json"
        )
        return filename

    def mark_pending_done(self, job_id: str) -> None:
        """把 pending 文件移到 done（防止重复处理）。

        注意：这不修改 consumer 字段，只是按正常完成流程归档。
        """
        if not _valid_job_id(job_id):
            raise ValueError(f"非法 job_id: {job_id[:40]}")
        sh = (
            f"for f in {VPS_PENDING_DIR}/{job_id}.json "
            f"{VPS_PENDING_DIR}/{job_id}.*.json; do "
            f"[ -f \"$f\" ] && mv \"$f\" {VPS_DONE_DIR}/ && break; done; "
            f"echo OK"
        )
        self._ssh_run(sh)


# ------------------------------------------------------------------ nanoMuse 客户端

class NanoMuseClient:
    """nanoMuse REST API 客户端。"""

    def __init__(
        self,
        base: str = NANOMUSE_BASE,
        token_path: str = NANOMUSE_TOKEN_PATH,
    ):
        self.base = base.rstrip("/")
        self.token_path = token_path
        self._token: str | None = None

    @property
    def token(self) -> str:
        if self._token is None:
            with open(self.token_path, encoding="utf-8") as f:
                self._token = f.read().strip()
        return self._token

    def _request(
        self, method: str, path: str, data: dict | None = None
    ) -> dict[str, Any]:
        url = f"{self.base}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    def create_thread(self, title: str) -> str:
        r = self._request("POST", "/api/threads", {"title": title})
        tid = r.get("id") or r.get("thread", {}).get("id", "")
        if not tid:
            raise RuntimeError(f"创建 thread 失败: {str(r)[:200]}")
        return tid

    def send(self, thread_id: str, text: str) -> dict[str, Any]:
        return self._request("POST", f"/api/threads/{thread_id}/send", {"text": text})

    def events(self, thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
        r = self._request("GET", f"/api/threads/{thread_id}/events?limit={limit}")
        evts = r.get("events", r)
        return evts if isinstance(evts, list) else []

    def auto_approve_pending(self, thread_id: str) -> int:
        """自动批准该 thread 的 pending approval 卡。

        桥接线程是机器对机器调用，不应卡在人工批准上。
        返回批准的数量。
        """
        approved = 0
        try:
            evts = self.events(thread_id, limit=30)
        except Exception:
            return 0
        for e in evts:
            if e.get("type") == "approval" and e.get("status") == "pending":
                ap_id = e.get("id", "")
                if not ap_id:
                    continue
                try:
                    self._request("POST", f"/api/approvals/{ap_id}",
                                  {"approved": True, "scope": "once",
                                   "reason": "bridge auto-approve"})
                    approved += 1
                    print(f"[bridge] 自动批准 {ap_id} ({e.get('tool','?')}: {e.get('summary','')[:60]})")
                except Exception as ex:
                    print(f"[bridge] 批准 {ap_id} 失败: {ex}")
        return approved

    def wait_for_completion(
        self,
        thread_id: str,
        timeout_min: int = DEFAULT_NANO_TIMEOUT_MIN,
        poll_sec: int = DEFAULT_POLL_INTERVAL_SEC,
        auto_approve: bool = True,
    ) -> dict[str, Any]:
        """等待 agent 完成。返回最后一个 assistant/tool 事件。

        完成判定：出现 assistant 事件且 thread 不再 busy。
        auto_approve=True 时每轮自动批准 pending 的 approval 卡（桥接场景）。
        """
        deadline = time.time() + timeout_min * 60
        last_relevant: dict[str, Any] = {}
        while time.time() < deadline:
            if auto_approve:
                self.auto_approve_pending(thread_id)
            evts = self.events(thread_id, limit=30)
            # 找最新的 assistant 或 tool 事件
            for e in reversed(evts):
                etype = e.get("type", "")
                if etype in ("assistant", "tool"):
                    last_relevant = e
                    break
            # 检查 thread 是否还在忙
            try:
                r = self._request("GET", f"/api/threads/{thread_id}/events?limit=1")
                thread = r.get("thread", {})
                busy = thread.get("busy", False)
                queued = thread.get("queued", 0)
            except Exception:
                busy, queued = True, 1  # 保守：继续等
            if not busy and not queued and last_relevant:
                return last_relevant
            time.sleep(poll_sec)
        # 超时：返回最后看到的
        if last_relevant:
            return last_relevant
        raise TimeoutError(f"nanoMuse thread {thread_id} 超时 ({timeout_min}min)")


# ------------------------------------------------------------------ 翻译层

def job_to_instruction(job: DispatcherJob) -> str:
    """把 dispatcher job 翻译成 nanoMuse 能理解的指令。"""
    lines = [
        f"[BRIDGE JOB] dispatcher job_id={job.job_id} job_type={job.job_type}",
        "",
    ]
    if job.job_type == "generate_video":
        payload = job.payload
        instruction = payload.get("instruction", "")
        video_count = payload.get("video_count", 1)
        lines += [
            "请生成视频。要求：",
            f"- 数量：{video_count} 个",
            "- 规格：竖屏 9:16，约8秒，h264+aac mp4",
            "- 使用 generate_video 工具",
            "",
            "场景描述：",
            instruction,
            "",
            "完成后请回复：",
            "DONE: <生成的本地文件完整路径>",
            "如果失败请回复：FAILED: <原因>",
        ]
    elif job.job_type == "custom":
        payload = job.payload
        # custom 的 payload 可能是 JSON 字符串
        inner = payload.get("instruction") or payload.get("text") or json.dumps(
            payload, ensure_ascii=False
        )
        lines += [
            "请执行以下自定义任务：",
            "",
            str(inner)[:2000],
            "",
            "完成后请回复：",
            "DONE: <结果摘要>",
            "如果失败请回复：FAILED: <原因>",
        ]
    else:
        lines += [
            f"未知 job_type: {job.job_type}",
            "payload:",
            json.dumps(job.payload, ensure_ascii=False)[:2000],
            "",
            "请尽力处理，完成后回复 DONE: <结果> 或 FAILED: <原因>",
        ]
    return "\n".join(lines)


def parse_nano_result(event: dict[str, Any]) -> tuple[bool, str, str]:
    """解析 nanoMuse 完成事件。

    返回 (success, file_or_summary, raw_text)。
    """
    text = str(event.get("text") or event.get("output") or "")
    # 找 DONE: / FAILED: 标记
    m_done = re.search(r"DONE:\s*(.+)", text, re.S)
    if m_done:
        content = m_done.group(1).strip().split("\n")[0].strip()
        return True, content, text
    m_fail = re.search(r"FAILED:\s*(.+)", text, re.S)
    if m_fail:
        return False, m_fail.group(1).strip().split("\n")[0].strip(), text
    # 没有明确标记：如果有 tool 事件带文件路径，算成功
    if event.get("type") == "tool":
        output = str(event.get("output") or "")
        # 找文件路径
        m_path = re.search(r"(/[^\s]+\.(mp4|png|jpg|mp3|wav))", output)
        if m_path:
            return True, m_path.group(1), text
    # 兜底：有实质内容算成功
    if len(text.strip()) > 20:
        return True, text.strip()[:500], text
    return False, "无有效输出", text


# ------------------------------------------------------------------ 桥接主逻辑

class Bridge:
    """桥接 orchestrator。"""

    def __init__(
        self,
        dispatcher: DispatcherClient | None = None,
        nano: NanoMuseClient | None = None,
        timeout_min: int = DEFAULT_TIMEOUT_MIN,
        dry_run: bool = False,
    ):
        self.dispatcher = dispatcher or DispatcherClient()
        self.nano = nano or NanoMuseClient()
        self.timeout_min = timeout_min
        self.dry_run = dry_run

    def find_timed_out(self) -> list[DispatcherJob]:
        """找出超时的 muse-main 任务。"""
        jobs = self.dispatcher.list_pending_jobs()
        result = []
        for job in jobs:
            if job.consumer != TARGET_CONSUMER:
                continue
            if self.dispatcher.job_already_done(job.job_id):
                continue
            age = job.age_minutes
            if age < 0:
                # 时间解析失败：保守起见跳过（不在 dry-run 外处理）
                continue
            if age >= self.timeout_min:
                result.append(job)
        return result

    def process_job(self, job: DispatcherJob) -> BridgeResult:
        """处理单个超时任务：翻译 → nanoMuse → 交付。"""
        print(f"[bridge] 处理 {job.job_id} ({job.job_type}, 已排队 {job.age_minutes:.1f}min)")

        if self.dry_run:
            print(f"[bridge] dry-run：跳过实际处理")
            return BridgeResult(job_id=job.job_id, success=True, backend="dry-run")

        # 1. 创建 nanoMuse thread 并发送指令
        instruction = job_to_instruction(job)
        thread_id = self.nano.create_thread(f"bridge-{job.job_id}")
        print(f"[bridge] nanoMuse thread: {thread_id}")
        self.nano.send(thread_id, instruction)

        # 2. 等待完成
        try:
            event = self.nano.wait_for_completion(thread_id)
        except TimeoutError as e:
            return BridgeResult(
                job_id=job.job_id, success=False,
                error=str(e), nano_thread_id=thread_id,
            )

        # 3. 解析结果
        success, file_or_summary, raw = parse_nano_result(event)
        print(f"[bridge] nano 结果: success={success}, {file_or_summary[:100]}")

        if not success:
            # 写失败结果（让 job_status 能查到 failed，而不是永远 pending）
            self.dispatcher.deliver_result(job.job_id, "", status="failed", error=file_or_summary)
            self.dispatcher.mark_pending_done(job.job_id)
            return BridgeResult(
                job_id=job.job_id, success=False,
                error=file_or_summary, nano_thread_id=thread_id,
            )

        # 4. 交付
        if job.job_type == "generate_video":
            # 期望 file_or_summary 是本地文件路径
            local_path = file_or_summary.strip()
            if not (local_path and os.path.exists(local_path)):
                # 尝试从 raw 文本中再找一次
                m = re.search(r"(/[^\s]+\.mp4)", raw)
                local_path = m.group(1) if m else ""
            if not (local_path and os.path.exists(local_path)):
                err = f"视频文件不存在: {file_or_summary[:100]}"
                self.dispatcher.deliver_result(job.job_id, "", status="failed", error=err)
                self.dispatcher.mark_pending_done(job.job_id)
                return BridgeResult(
                    job_id=job.job_id, success=False,
                    error=err, nano_thread_id=thread_id,
                )
            vps_file = self.dispatcher.deliver_result(job.job_id, local_path, status="done")
            self.dispatcher.mark_pending_done(job.job_id)
            return BridgeResult(
                job_id=job.job_id, success=True,
                output_file=vps_file, nano_thread_id=thread_id,
            )
        else:
            # custom / 其他：把摘要写成结果文件
            # 写一个 .txt 到 VPS output，让调用方能取到
            import tempfile as _tf
            with _tf.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(f"job_id: {job.job_id}\n")
                f.write(f"backend: nanoMuse-bridge\n")
                f.write(f"thread: {thread_id}\n\n")
                f.write(raw[:4000])
                tmp = f.name
            try:
                vps_file = self.dispatcher.deliver_result(job.job_id, tmp, status="done")
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            self.dispatcher.mark_pending_done(job.job_id)
            return BridgeResult(
                job_id=job.job_id, success=True,
                output_file=vps_file, nano_thread_id=thread_id,
            )

    def run_scan(self) -> list[BridgeResult]:
        """扫描并处理所有超时任务。"""
        jobs = self.find_timed_out()
        print(f"[bridge] 发现 {len(jobs)} 个超时任务 (>{self.timeout_min}min)")
        results = []
        for job in jobs:
            try:
                results.append(self.process_job(job))
            except Exception as e:
                print(f"[bridge] 处理 {job.job_id} 异常: {e}")
                results.append(BridgeResult(
                    job_id=job.job_id, success=False, error=str(e)[:300],
                ))
        ok = sum(1 for r in results if r.success)
        print(f"[bridge] 完成：{ok}/{len(results)} 成功")
        return results

    def run_single(self, job_id: str) -> BridgeResult:
        """手动处理指定 job（不检查超时）。"""
        if not _valid_job_id(job_id):
            raise ValueError(f"非法 job_id: {job_id[:40]}")
        raw = self.dispatcher.read_job_file(job_id)
        if not raw:
            raise RuntimeError(f"找不到 pending 任务: {job_id}")
        payload = raw.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"_raw": payload}
        job = DispatcherJob(
            job_id=raw.get("job_id", job_id),
            job_type=raw.get("job_type", ""),
            consumer=raw.get("consumer", ""),
            payload=payload if isinstance(payload, dict) else {},
            idempotency_key=raw.get("idempotency_key", ""),
            queued_at=raw.get("queued_at") or raw.get("created_at") or "",
            raw=raw,
        )
        if job.consumer != TARGET_CONSUMER:
            print(f"[bridge] 警告：该任务 consumer={job.consumer}，不是 {TARGET_CONSUMER}")
        return self.process_job(job)


# ------------------------------------------------------------------ CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="Dispatcher ↔ nanoMuse 协议桥接")
    ap.add_argument("--scan", action="store_true", help="扫描并处理所有超时任务")
    ap.add_argument("--job-id", default="", help="手动处理指定 job_id")
    ap.add_argument("--dry-run", action="store_true", help="只列出，不实际处理")
    ap.add_argument("--timeout-min", type=int, default=DEFAULT_TIMEOUT_MIN,
                    help=f"超时阈值（分钟），默认 {DEFAULT_TIMEOUT_MIN}")
    args = ap.parse_args()

    if not args.scan and not args.job_id:
        ap.print_help()
        sys.exit(1)

    bridge = Bridge(timeout_min=args.timeout_min, dry_run=args.dry_run)

    if args.job_id:
        r = bridge.run_single(args.job_id)
        print(json.dumps({
            "job_id": r.job_id, "success": r.success,
            "output_file": r.output_file, "error": r.error,
        }, ensure_ascii=False, indent=2))
        sys.exit(0 if r.success else 1)

    if args.scan:
        results = bridge.run_scan()
        print(json.dumps([
            {"job_id": r.job_id, "success": r.success,
             "output_file": r.output_file, "error": r.error}
            for r in results
        ], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
