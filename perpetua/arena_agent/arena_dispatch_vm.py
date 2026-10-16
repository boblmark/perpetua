#!/usr/bin/env python3
"""Arena Agent 月度调研 —— VM 本机 agent-browser 全自动化派发

运行位置: 本机 (hatch)，经 SSH 驱动 VM (192.166.82.123) 上的 agent-browser，
操作 VM Chrome 里已登录的 arena.ai Agent 会话。

流程:
  1. VM Chrome 打开 https://arena.ai/agent（全新会话，校验输入框为空）
  2. 粘贴提示词全文并发送（prompt 经 scp 传到 VM，VM 侧 python heredoc 粘贴，
     不走 shell 参数，避免引用转义坑）
  3. 轮询 Workspace 面板出现 .xlsx（最长 90 分钟）
  4. 用 agent-browser download 下到 VM 本地
  5. scp 拉回本机 /home/hatch/data/perpetua/arena_agent/drops/，打印最终路径

用法:
  python3 arena_dispatch_vm.py --prompt-file <path> --job-id <id> [--max-wait-min 90]

退出码:
  0 成功（打印本机最终路径）
  1 参数/环境错误
  2 VM SSH/CDP 不可达
  3 arena.ai 需要登录（VM Chrome 无登录态）——报告现状，不注册、不绕过
  4 粘贴提示词失败
  5 发送失败
  6 90 分钟内未产出 xlsx（超时）
  7 VM 侧下载失败
  8 scp 回传失败
"""
import argparse
import os
import re
import subprocess
import sys
import time

VM_HOST = "root@192.166.82.123"
SSH_BASE = [
    "ssh", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=15",
    "-o", "BatchMode=yes",
    "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
    VM_HOST,
]
AB = ["/usr/bin/agent-browser", "--cdp", "http://127.0.0.1:9222"]
ARENA_URL = "https://arena.ai/agent"
VM_DL_DIR = "/root/arena_dl"
LOCAL_DROPS = "/home/hatch/data/perpetua/arena_agent/drops"


def ssh_run(cmd, timeout=60):
    r = subprocess.run(SSH_BASE + [cmd], capture_output=True, text=True, timeout=timeout)
    return r


def ab(*args, timeout=60):
    r = subprocess.run(SSH_BASE + AB + list(args), capture_output=True, text=True, timeout=timeout)
    return r


def die(code, msg):
    print(f"ERROR[{code}]: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def snapshot(timeout=45):
    r = ab("snapshot", timeout=timeout)
    if r.returncode != 0:
        return None
    return r.stdout


def find_ref(snap, *keywords):
    """找包含所有关键词的元素的第一个 ref"""
    for line in snap.splitlines():
        if all(k in line for k in keywords):
            m = re.search(r"\[ref=(e\d+)\]", line)
            if m:
                return m.group(1), line.strip()[:120]
    return None, None


def composer_ref(snap):
    """agent 输入框：contenteditable 的元素"""
    for line in snap.splitlines():
        if "contenteditable" in line and "editable" in line:
            m = re.search(r"\[ref=(e\d+)\]", line)
            if m:
                return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--max-wait-min", type=int, default=90)
    args = ap.parse_args()

    if not os.path.isfile(args.prompt_file):
        die(1, f"prompt 文件不存在: {args.prompt_file}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.job_id):
        die(1, f"job-id 只允许字母数字/_/-: {args.job_id}")

    with open(args.prompt_file, encoding="utf-8") as f:
        prompt_text = f.read().strip()
    if not prompt_text:
        die(1, "prompt 文件为空")

    job_dir = f"{VM_DL_DIR}/{args.job_id}"

    # --- 0. VM 连通性 ---
    print("== 0. 检查 VM 连通性 ==", flush=True)
    r = ssh_run("echo vm-ok", timeout=30)
    if r.returncode != 0 or "vm-ok" not in r.stdout:
        die(2, f"VM SSH 不可达: {r.stderr.strip()[:200]}")
    r = ab("snapshot", timeout=30)
    if r.returncode != 0:
        die(2, f"VM Chrome CDP 不可达: {r.stderr.strip()[:200]}")
    r = ssh_run(f"mkdir -p {job_dir}", timeout=30)
    if r.returncode != 0:
        die(2, f"VM 建目录失败: {r.stderr.strip()[:200]}")

    # --- 1. 传 prompt 到 VM ---
    print("== 1. 传 prompt 到 VM ==", flush=True)
    r = subprocess.run(
        ["scp", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
         "-o", "StrictHostKeyChecking=no",
         "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
         args.prompt_file, f"{VM_HOST}:{job_dir}/prompt.txt"],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        die(2, f"scp prompt 到 VM 失败: {r.stderr.strip()[:200]}")

    # --- 2. 打开全新会话 ---
    print("== 2. 打开 arena.ai/agent 全新会话 ==", flush=True)
    r = ab("open", ARENA_URL, timeout=60)
    if r.returncode != 0:
        die(2, f"打开页面失败: {r.stderr.strip()[:200]}")

    snap = None
    for _ in range(12):
        time.sleep(5)
        snap = snapshot()
        if snap and ("contenteditable" in snap or "What would you like to do" in snap):
            break
    if not snap:
        die(2, "页面快照持续失败")

    # 登录态检查：出现登录按钮且没有输入框 → 无登录态
    if ("Log in" in snap or "Sign in" in snap) and "contenteditable" not in snap:
        die(3, "VM Chrome 在 arena.ai 无登录态（页面要求登录）。请人工在 VM Chrome 登录后重试；脚本不做注册或绕过。")

    cref = composer_ref(snap)
    if not cref:
        # 再等一轮
        time.sleep(10)
        snap = snapshot() or ""
        cref = composer_ref(snap)
    if not cref:
        die(3, f"未找到 agent 输入框（可能登录态异常）。快照前 800 字符:\n{snap[:800]}")

    # 必须全新会话：输入框应为空（占位符 "Ask anything" 在即为空）
    if "Ask anything" not in snap:
        die(5, "输入框非空或非全新会话状态，拒绝复用旧会话（已中止，未发送）。")

    # --- 3. 聚焦 + 粘贴 ---
    print("== 3. 粘贴提示词 ==", flush=True)
    r = ab("focus", f"@{cref}", timeout=30)
    if r.returncode != 0:
        r = ab("click", f"@{cref}", timeout=30)
    time.sleep(1)

    # VM 侧 python heredoc 粘贴：prompt 只以文件内容形式流动，不经过 shell 参数
    paste_py = (
        "python3 - <<'ARENA_PASTE_EOF'\n"
        "import subprocess\n"
        f"text = open('{job_dir}/prompt.txt', encoding='utf-8').read()\n"
        "r = subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222',"
        "'keyboard','inserttext',text], capture_output=True, text=True, timeout=120)\n"
        "print('PASTE_RC=' + str(r.returncode))\n"
        "ARENA_PASTE_EOF\n"
    )
    r = subprocess.run(SSH_BASE + ["bash", "-s"], input=paste_py,
                       capture_output=True, text=True, timeout=180)
    if "PASTE_RC=0" not in r.stdout:
        die(4, f"粘贴失败: stdout={r.stdout.strip()[:200]} stderr={r.stderr.strip()[:200]}")

    time.sleep(3)
    snap = snapshot() or ""
    # 粘贴成功的标志：Send 按钮变为可用（不再 disabled），且快照里出现提示词片段
    probe = prompt_text[:24].replace("\n", " ")
    sent_marker = probe[:18]
    if sent_marker not in snap:
        die(4, f"粘贴后输入框未出现提示词内容（快照无匹配）。可能粘贴未生效。")

    # --- 4. 发送 ---
    print("== 4. 发送 ==", flush=True)
    sref, _ = find_ref(snap, "Send message")
    sent = False
    if sref:
        r = ab("click", f"@{sref}", timeout=30)
        sent = r.returncode == 0
    if not sent:
        # 兜底：回车发送
        ab("press", "Enter", timeout=30)
    time.sleep(8)
    snap = snapshot() or ""
    if "Stop generating" not in snap and "Ask anything" not in snap and sent_marker in snap:
        # 可能还在输入框里没发出去
        die(5, "发送后未检测到 agent 运行迹象（无 Stop generating），提示词仍在输入框。")
    print("   发送成功，agent 运行中", flush=True)

    # --- 5. 轮询 Workspace 出现 xlsx ---
    print(f"== 5. 轮询 xlsx（最长 {args.max_wait_min} 分钟） ==", flush=True)
    deadline = time.time() + args.max_wait_min * 60
    dl_ref = None
    poll_n = 0
    while time.time() < deadline:
        poll_n += 1
        time.sleep(60)
        snap = snapshot(timeout=60)
        if not snap:
            print(f"   [{poll_n}] 快照失败，继续", flush=True)
            continue
        # 会话失败信号
        if "Something went wrong" in snap and "Download file" not in snap:
            print(f"   [{poll_n}] 页面报错，继续观察", flush=True)
        ref, line = find_ref(snap, "Download file")
        if ref:
            dl_ref = ref
            print(f"   [{poll_n}] 发现 Download file: {line}", flush=True)
            break
        # 顺带找 .xlsx 文件名行
        m = re.search(r"([\w\-\.]+\.xlsx)", snap)
        if m:
            print(f"   [{poll_n}] 看到 xlsx 文件名: {m.group(1)}", flush=True)
        if poll_n % 10 == 0:
            print(f"   [{poll_n}] 等待中…（已 {poll_n} 分钟）", flush=True)

    if not dl_ref:
        die(6, f"{args.max_wait_min} 分钟内 Workspace 未出现可下载的 xlsx。agent 可能仍在跑或已失败，请人工检查 VM Chrome 的 arena.ai 会话。")

    # --- 6. 下载到 VM ---
    print("== 6. 下载 xlsx 到 VM ==", flush=True)
    vm_xlsx = f"{job_dir}/result.xlsx"
    r = ab("download", f"@{dl_ref}", vm_xlsx, timeout=180)
    if r.returncode != 0:
        die(7, f"agent-browser download 失败: {r.stderr.strip()[:300]}")
    time.sleep(2)
    r = ssh_run(f"ls -la {vm_xlsx} && file {vm_xlsx}", timeout=30)
    if r.returncode != 0 or ".xlsx" not in vm_xlsx:
        die(7, f"VM 上下载文件校验失败: {r.stdout.strip()[:200]} {r.stderr.strip()[:200]}")
    print(f"   VM 文件: {r.stdout.strip().splitlines()[0]}", flush=True)

    # --- 7. scp 回本机 drops/ ---
    print("== 7. 回传本机 drops/ ==", flush=True)
    os.makedirs(LOCAL_DROPS, exist_ok=True)
    local_path = os.path.join(LOCAL_DROPS, f"{args.job_id}.xlsx")
    r = subprocess.run(
        ["scp", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
         "-o", "StrictHostKeyChecking=no",
         "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
         f"{VM_HOST}:{vm_xlsx}", local_path],
        capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not os.path.isfile(local_path):
        die(8, f"scp 回传失败: {r.stderr.strip()[:300]}")

    size = os.path.getsize(local_path)
    if size < 1024:
        die(8, f"回传文件过小（{size}B），疑似损坏: {local_path}")
    print(f"SUCCESS: {local_path} ({size}B)", flush=True)


if __name__ == "__main__":
    main()
