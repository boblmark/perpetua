#!/usr/bin/env python3
"""
GeminiGen 直接 API 调用生成（绕过网页 UI）
通过 VM 上已登录的 Chrome 会话调 /api/ai/aimodel-api

用法：
  python3 geminigen_api.py --prompt-file xxx.txt --job-id xxx --out-dir /home/hatch/data/veo_inbox/ [--aspect 9:16]

相比 geminigen_auto.py（网页自动化）：
- 更快：无浏览器 UI 开销
- 更稳：不依赖 React state 操作
- 9:16 可靠：直接传 aspectRatio 参数
"""
import argparse
import json
import os
import subprocess
import sys
import time

VM_HOST = "192.166.82.123"
VM_USER = "root"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
CDP_PORT = os.environ.get("CDP_PORT", "9222")
CDP = f"http://127.0.0.1:{CDP_PORT}"
AGENT_BROWSER = "/usr/bin/agent-browser"

SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", f"ProxyCommand={PROXY}",
    f"{VM_USER}@{VM_HOST}",
]

def _parse_json_out(out):
    """稳健解析 vm_eval 返回的 JSON（处理转义和引号包裹）"""
    s = out.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    # 处理 \" 转义
    s = s.replace('\\"', '"').replace('\\\\', '\\')
    return json.loads(s)


def vm_eval(js, timeout=30):
    """在 VM Chrome 页面里执行 JS（带 cookie 凭据）"""
    import base64
    b64 = base64.b64encode(js.encode('utf-8')).decode('ascii')
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"j=base64.b64decode('{b64}').decode('utf-8');"
        f"r=subprocess.run(['{AGENT_BROWSER}','--cdp','{CDP}','eval',j],"
        f"capture_output=True,text=True,timeout=30);"
        f"print(r.stdout.strip())"
        f"\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=timeout+30)
    return r.stdout.strip()


def api_generate(prompt, aspect="9:16", model="veo-3.1-fast", duration=8):
    """调用生成 API，返回 taskId"""
    import base64
    # prompt 用 base64 避免转义问题
    prompt_b64 = base64.b64encode(prompt.encode('utf-8')).decode('ascii')
    js = """
    (async () => {
        const prompt = atob('__PROMPT_B64__');
        const params = {
            prompt: prompt,
            model: '__MODEL__',
            aspectRatio: '__ASPECT__',
            duration: __DURATION__
        };
        const r = await fetch("/api/ai/aimodel-api", {
            method: "POST",
            credentials: "include",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(params)
        });
        const t = await r.text();
        return t.slice(0, 500);
    })()
    """.replace('__PROMPT_B64__', prompt_b64).replace('__MODEL__', model).replace('__ASPECT__', aspect).replace('__DURATION__', str(duration))

    out = vm_eval(js, timeout=30)
    # 解析 taskId
    try:
        data = _parse_json_out(out)
        task_id = data.get('data', {}).get('taskId', '')
        if task_id:
            return task_id
        print(f"  API 返回异常: {out[:200]}")
    except Exception as e:
        print(f"  解析失败: {e}, 原始: {out[:200]}")
    return ''


def api_check_status(task_id):
    """查询任务状态，返回 (status, resultUrls)"""
    js = """
    (async () => {
        const r = await fetch("/api/ai/aimodel-api?taskId=__TASKID__", {credentials: "include"});
        const t = await r.text();
        return t.slice(0, 800);
    })()
    """.replace('__TASKID__', task_id)

    out = vm_eval(js, timeout=30)
    try:
        data = _parse_json_out(out)
        d = data.get('data', {})
        return d.get('status', ''), d.get('resultUrls') or []
    except Exception as e:
        print(f"  状态查询解析失败: {e}")
        return '', []


def run_one_job(prompt_file, job_id, out_dir, aspect, model, duration, tag=""):
    """跑单个生成任务，返回本地视频路径（失败抛异常）"""
    with open(prompt_file) as f:
        prompt = f.read().strip()

    # GeminiGen "Karen" 拒收绕行（2026-10-11 用户批准"两个都要开"）：
    # 只替换提交副本，源 prompt 文件不动。
    if "Karen" in prompt:
        prompt = prompt.replace("Karen", "entitled middle-aged woman")
        prompt = prompt.replace("KAREN", "ENTITLED MIDDLE-AGED WOMAN")
        print(f"[{tag or job_id}] [绕行] 提交副本已替换 Karen（源文件不动）", flush=True)

    p = lambda s: print(f"[{tag or job_id}] {s}", flush=True)
    p(f"开始: {job_id}, prompt {len(prompt)} 字符, {model}, {aspect}")

    # [1] 提交生成
    p("提交生成请求...")
    task_id = api_generate(prompt, aspect, model, duration)
    if not task_id:
        raise RuntimeError("未获取到 taskId")
    p(f"taskId: {task_id}")

    # [2] 轮询状态
    p("等待生成完成...")
    video_url = ''
    for i in range(20):  # 最多等 10 分钟
        time.sleep(30)
        status, urls = api_check_status(task_id)
        p(f"轮询 [{i+1}/20]: {status}")
        if status == 'success' and urls:
            video_url = urls[0]
            p(f"视频 URL: {video_url[:80]}...")
            break
        elif status in ('failed', 'error'):
            raise RuntimeError(f"生成失败: {status}")

    if not video_url:
        raise RuntimeError("生成超时")

    # [3] 下载
    p("下载视频...")
    vm_path = f"/tmp/geminigen_{job_id}.mp4"
    dl_cmd = SSH_BASE + ["curl", "-sL", "-o", vm_path, video_url]
    r = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("VM 下载失败")

    local_path = os.path.join(out_dir, f"geminigen_{job_id}.mp4")
    os.makedirs(out_dir, exist_ok=True)
    scp_cmd = [
        "scp", "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ProxyCommand={PROXY}",
        f"{VM_USER}@{VM_HOST}:{vm_path}",
        local_path,
    ]
    r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode == 0 and os.path.exists(local_path):
        size = os.path.getsize(local_path)
        p(f"完成: {local_path} ({size//1024}KB)")
    else:
        raise RuntimeError("scp 失败")
    return local_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True,
                    help="prompt 文件，多个用逗号分隔（并行）")
    ap.add_argument("--job-id", required=True,
                    help="任务 id；并行时作为前缀，实际为 <job-id>_1, <job-id>_2...")
    ap.add_argument("--out-dir", default="/home/hatch/data/veo_inbox/")
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--model", default="veo-3.1-fast")
    ap.add_argument("--duration", type=int, default=8)
    ap.add_argument("--qc", action="store_true",
                    help="生成完成后对每个视频跑 pre_upload_qc.py")
    args = ap.parse_args()

    prompt_files = [p.strip() for p in args.prompt_file.split(",") if p.strip()]
    n = len(prompt_files)
    print(f"=== GeminiGen API 生成: {args.job_id} (共 {n} 个任务{'，并行' if n > 1 else ''}) ===")
    print()

    results = {}
    if n == 1:
        try:
            local = run_one_job(prompt_files[0], args.job_id, args.out_dir,
                                args.aspect, args.model, args.duration)
            results[args.job_id] = local
        except Exception as e:
            print(f"任务失败 {args.job_id}: {e}")
            sys.exit(1)
    else:
        import threading
        errors = {}
        def worker(idx, pf):
            jid = f"{args.job_id}_{idx+1}"
            try:
                results[jid] = run_one_job(pf, jid, args.out_dir,
                                           args.aspect, args.model, args.duration,
                                           tag=f"任务{idx+1}")
            except Exception as e:
                errors[jid] = str(e)
                print(f"[任务{idx+1}] 失败 {jid}: {e}", flush=True)
        threads = [threading.Thread(target=worker, args=(i, pf))
                   for i, pf in enumerate(prompt_files)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print()
        print(f"=== 并行完成: 成功 {len(results)}/{n} ===")
        for jid, path in results.items():
            print(f"  {jid}: {path}")
        if errors:
            for jid, err in errors.items():
                print(f"  {jid} 失败: {err}")

    # QC
    if args.qc and results:
        import re
        print()
        print("=== QC 质检 ===")
        qc_script = "/home/hatch/data/perpetua/pre_upload_qc.py"
        for jid, path in results.items():
            print(f"--- QC: {jid} ---")
            r = subprocess.run(
                ["python3", qc_script, path],
                capture_output=True, text=True, timeout=300)
            out = r.stdout or ""
            m = re.search(r'\{.*\}', out, re.S)
            if m:
                try:
                    d = json.loads(m.group(0))
                    print(f"  passed: {d.get('passed')} | 体验分: {d.get('experience_score')}")
                    for c in d.get('checks', []):
                        print(f"    {c['name']}: {c['status']}")
                    if d.get('rejects'):
                        print(f"  rejects: {d['rejects']}")
                    if d.get('needs_regen'):
                        print(f"  → 需要重生成")
                except Exception as e:
                    print(f"  QC 解析失败: {e}")
                    print(out[-800:])
            else:
                print(out[-800:])
            if r.returncode != 0:
                print(f"  QC 退出码: {r.returncode}（fail-closed）")

    print()
    print("=== 全部完成 ===")


if __name__ == "__main__":
    main()
