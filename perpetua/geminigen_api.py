#!/usr/bin/env python3
"""
GeminiGen 直接 API 调用生成（绕过网页 UI）
通过已登录的 Chrome 会话调 /api/ai/aimodel-api

双后端故障转移（2026-10-15 用户要求本机热备）：
- vps:   经 SSH 调 VPS 的 agent-browser（CDP 9222，共享 Chrome）
- local: 本机 agent-browser 直驱本机 Chrome（CDP 9335，VPS profile 复制版）
- auto:  vps 优先，失败自动切 local（无缝故障转移）

用法：
  python3 geminigen_api.py --prompt-file xxx.txt --job-id xxx --out-dir /home/hatch/data/veo_inbox/ [--aspect 9:16] [--backend auto|vps|local] [--free]

--free: 走免费档（modelName=ai-video-free，无需登录，每日约3条，本机即可）
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
VPS_CDP_PORT = os.environ.get("CDP_PORT", "9222")
VPS_CDP = f"http://127.0.0.1:{VPS_CDP_PORT}"
# 本机备用浏览器（VPS profile 复制版，2026-10-15）
LOCAL_CDP = "http://127.0.0.1:9335"
LOCAL_AB = "/usr/bin/agent-browser"
VPS_AB = "/usr/bin/agent-browser"
BACKEND = os.environ.get("GEMINIGEN_BACKEND", "auto")  # auto|vps|local

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
    """在 VPS Chrome 页面里执行 JS（带 cookie 凭据）"""
    import base64
    b64 = base64.b64encode(js.encode('utf-8')).decode('ascii')
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"j=base64.b64decode('{b64}').decode('utf-8');"
        f"r=subprocess.run(['{VPS_AB}','--cdp','{VPS_CDP}','eval',j],"
        f"capture_output=True,text=True,timeout=30);"
        f"print(r.stdout.strip())"
        f"\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=timeout+30)
    return r.stdout.strip()


def local_eval(js, timeout=30):
    """在本机 Chrome（9335）页面里执行 JS（2026-10-15 热备）"""
    r = subprocess.run(
        [LOCAL_AB, "--cdp", "9335", "eval", js],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "AGENT_BROWSER_PROXY": "http://127.0.0.1:3129"},
    )
    return r.stdout.strip()


def browser_eval(js, backend, timeout=30):
    """按后端选执行器"""
    if backend == "local":
        return local_eval(js, timeout)
    return vm_eval(js, timeout)


def api_generate(prompt, aspect="9:16", model="veo-3.1-fast", duration=8, backend="vps", free=False):
    """调用生成 API，返回 taskId。free=True 走免费档（ai-video-free，无需登录）。"""
    import base64
    # prompt 用 base64 避免转义问题
    prompt_b64 = base64.b64encode(prompt.encode('utf-8')).decode('ascii')
    if free:
        # 免费档请求体（2026-10-15 抓包实测）
        js = """
        (async () => {
            const prompt = atob('__PROMPT_B64__');
            const params = {
                prompt: prompt,
                aspectRatio: '__ASPECT__',
                modelName: 'ai-video-free',
                modelShowName: 'Free AI Video Maker',
                urlpath: '/',
                ispublish: true,
                isPromptHidden: false,
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
        """.replace('__PROMPT_B64__', prompt_b64).replace('__ASPECT__', aspect).replace('__DURATION__', str(duration))
    else:
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

    out = browser_eval(js, backend, timeout=30)
    # 解析 taskId
    try:
        data = _parse_json_out(out)
        # 免费额度耗尽时 data 里是 error
        err = data.get('error', '')
        if err:
            return '', err
        task_id = data.get('data', {}).get('taskId', '')
        if task_id:
            return task_id, ''
        print(f"  API 返回异常: {out[:200]}")
    except Exception as e:
        print(f"  解析失败: {e}, 原始: {out[:200]}")
    return '', 'parse_error'


def api_check_status(task_id, backend="vps"):
    """查询任务状态，返回 (status, resultUrls)"""
    js = """
    (async () => {
        const r = await fetch("/api/ai/aimodel-api?taskId=__TASKID__", {credentials: "include"});
        const t = await r.text();
        return t.slice(0, 800);
    })()
    """.replace('__TASKID__', task_id)

    out = browser_eval(js, backend, timeout=30)
    try:
        data = _parse_json_out(out)
        d = data.get('data', {})
        return d.get('status', ''), d.get('resultUrls') or []
    except Exception as e:
        print(f"  状态查询解析失败: {e}")
        return '', []


def _download_video(video_url, job_id, out_dir, backend):
    """按后端下载视频到本地，返回本地路径"""
    local_path = os.path.join(out_dir, f"geminigen_{job_id}.mp4")
    os.makedirs(out_dir, exist_ok=True)
    if backend == "local":
        # 本机直接下载
        env = {**os.environ, "https_proxy": "http://127.0.0.1:3129",
               "http_proxy": "http://127.0.0.1:3129"}
        r = subprocess.run(["curl", "-sL", "-o", local_path, video_url],
                           capture_output=True, text=True, timeout=120, env=env)
        if r.returncode != 0 or not os.path.exists(local_path):
            raise RuntimeError("本机下载失败")
    else:
        vm_path = f"/tmp/geminigen_{job_id}.mp4"
        dl_cmd = SSH_BASE + ["curl", "-sL", "-o", vm_path, video_url]
        r = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError("VM 下载失败")
        scp_cmd = [
            "scp", "-i", SSH_KEY,
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ProxyCommand={PROXY}",
            f"{VM_USER}@{VM_HOST}:{vm_path}",
            local_path,
        ]
        r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not os.path.exists(local_path):
            raise RuntimeError("scp 失败")
    size = os.path.getsize(local_path)
    return local_path, size


def _reflux_to_queue(job_id, fallback_id):
    """S3（2026-10-28）：geminigen 全败后除写浏览器 fallback 文件外，
    best-effort 把队列里对应的在途条目转 arena_manual（人工浏览器派发
    语义，与 fallback 文件的用途一致；G2 看门狗覆盖 arena_manual 的
    24h 告警/168h 升级）。只动 job_id 精确匹配且状态为 job_submitted /
    generating 的在途条目；无匹配、状态不对、任何异常 → 静默不动，
    绝不改写无关条目、不阻塞原有的 raise。返回 True 表示已回流。"""
    try:
        sys.path.insert(0, "/home/hatch/data/perpetua")
        import queue_db
        q = queue_db.pipeline_load()
        changed = False
        for it in q:
            if it.get("job_id") != job_id:
                continue
            if it.get("status") not in ("job_submitted", "generating"):
                continue
            it["status"] = "arena_manual"
            it["geminigen_fallback_id"] = fallback_id
            it["note"] = ((it.get("note") or "")
                          + f" [geminigen 全败回流 arena_manual {fallback_id}]")
            changed = True
        if changed:
            queue_db.pipeline_save(q)
        return changed
    except Exception:
        return False


def run_one_job(prompt_file, job_id, out_dir, aspect, model, duration, tag="",
                backend="auto", free=False):
    """跑单个生成任务，返回本地视频路径（失败抛异常）。
    backend=auto 时按 vps→local 顺序故障转移。"""
    with open(prompt_file) as f:
        prompt = f.read().strip()

    # GeminiGen "Karen" 拒收绕行（2026-10-11 用户批准"两个都要开"）：
    # 只替换提交副本，源 prompt 文件不动。
    if "Karen" in prompt:
        prompt = prompt.replace("Karen", "entitled middle-aged woman")
        prompt = prompt.replace("KAREN", "ENTITLED MIDDLE-AGED WOMAN")
        print(f"[{tag or job_id}] [绕行] 提交副本已替换 Karen（源文件不动）", flush=True)

    p = lambda s: print(f"[{tag or job_id}] {s}", flush=True)
    tier = "免费档" if free else model
    p(f"开始: {job_id}, prompt {len(prompt)} 字符, {tier}, {aspect}")

    # 后端顺序：auto 则 vps 优先、local 兜底
    backends = ["vps", "local"] if backend == "auto" else [backend]
    last_err = ""
    for be in backends:
        try:
            p(f"尝试后端: {be}...")
            # [1] 提交生成
            p("提交生成请求...")
            task_id, err = api_generate(prompt, aspect, model, duration, be, free)
            if not task_id:
                # 免费额度耗尽 / 未登录等：换下一个后端
                p(f"后端 {be} 提交失败: {err[:80]}，切换...")
                last_err = err
                continue
            p(f"taskId: {task_id} (后端 {be})")

            # [2] 轮询状态
            p("等待生成完成...")
            video_url = ''
            for i in range(20):  # 最多等 10 分钟
                time.sleep(30)
                status, urls = api_check_status(task_id, be)
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
            local_path, size = _download_video(video_url, job_id, out_dir, be)
            p(f"完成: {local_path} ({size//1024}KB) [后端 {be}]")
            return local_path
        except Exception as e:
            p(f"后端 {be} 异常: {e}，切换...")
            last_err = str(e)
            continue
    # 所有后端均失败 → 写平台浏览器 fallback 队列（2026-10-15 用户要求自动切换）
    # 主 agent (Dash) 的 cron 会发现这个队列并开平台浏览器任务生成
    try:
        import uuid
        from datetime import datetime, timezone
        fallback_dir = "/home/hatch/data/perpetua/platform_browser_fallback/queue"
        os.makedirs(fallback_dir, exist_ok=True)
        fallback_job = {
            "job_id": job_id,
            "prompt": prompt,
            "aspect": aspect,
            "model": model,
            "duration": duration,
            "out_dir": out_dir,
            "tag": tag,
            "free": free,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_error": last_err[:500],
            "source": "geminigen_api",
            "fallback_id": f"pfb-{uuid.uuid4().hex[:8]}",
        }
        fb_path = os.path.join(fallback_dir, f"{fallback_job['fallback_id']}.json")
        with open(fb_path, "w", encoding="utf-8") as f:
            json.dump(fallback_job, f, ensure_ascii=False, indent=2)
        p(f"已写入平台浏览器 fallback 队列: {fb_path}")
        # S3：fallback 文件仍是 watcher 的触发器（保留）；同时 best-effort
        # 回流队列（在途条目转 arena_manual），失败不影响原 raise。
        _reflux_to_queue(job_id, fallback_job["fallback_id"])
    except Exception as fb_e:
        p(f"写入 fallback 队列失败: {fb_e}")
    raise RuntimeError(f"所有后端均失败，最后错误: {last_err[:120]}")


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
    ap.add_argument("--backend", default=os.environ.get("GEMINIGEN_BACKEND", "auto"),
                    choices=["auto", "vps", "local"],
                    help="生成后端：auto（vps 优先，失败切 local）、vps、local")
    ap.add_argument("--free", action="store_true",
                    help="走免费档（ai-video-free，无需登录，每日约3条）")
    ap.add_argument("--qc", action="store_true",
                    help="生成完成后对每个视频跑 pre_upload_qc.py")
    args = ap.parse_args();

    # 免费档强制走 local（本机浏览器带 guest 身份；VPS 同理可走但本机优先）
    backend = args.backend

    prompt_files = [p.strip() for p in args.prompt_file.split(",") if p.strip()]
    n = len(prompt_files)
    print(f"=== GeminiGen API 生成: {args.job_id} (共 {n} 个任务{'，并行' if n > 1 else ''}) ===")
    print()

    results = {}
    if n == 1:
        try:
            local = run_one_job(prompt_files[0], args.job_id, args.out_dir,
                                args.aspect, args.model, args.duration,
                                backend=backend, free=args.free)
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
                                           tag=f"任务{idx+1}",
                                           backend=backend, free=args.free)
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
