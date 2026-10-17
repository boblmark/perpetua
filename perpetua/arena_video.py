#!/usr/bin/env python3
"""
Arena.ai Video 生成后端（2026-10-17 接入）

经已登录的 Chrome 会话（bat08738@gmail.com）调用 https://arena.ai/video，
Battle 模式一次提交产出 2 条视频（2 个匿名模型），全部下载后返回。

双后端故障转移（沿用 geminigen_api.py 模式）：
- vps:   经 SSH 调 VPS 的 agent-browser（CDP 9222，共享 Chrome）
- local: 本机 agent-browser 直驱本机 Chrome（CDP 9335，VPS profile 复制版）
- auto:  vps 优先，失败自动切 local

用法：
  python3 arena_video.py --prompt "a cat playing piano, cinematic" --job-id xxx --out-dir /home/hatch/data/veo_inbox/ [--backend auto|vps|local]

输出 JSON：{"ok": true, "files": ["/path/a.mp4", "/path/b.mp4"], "battle_url": "..."}
失败：{"ok": false, "error": "..."}

注意：
- Battle 模式模型匿名，2 条都下载，由调用方/QC 决定取舍
- 无付费墙（2026-10-17 实测），但若页面弹出登录/付费则直接失败不重试
- 单次生成约 2-5 分钟，超时 15 分钟
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import uuid

VM_HOST = "192.166.82.123"
VM_USER = "root"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
VPS_CDP_PORT = os.environ.get("CDP_PORT", "9222")
VPS_CDP = f"http://127.0.0.1:{VPS_CDP_PORT}"
LOCAL_CDP = "http://127.0.0.1:9335"
LOCAL_AB = "/usr/bin/agent-browser"
VPS_AB = "/usr/bin/agent-browser"
BACKEND = os.environ.get("ARENA_BACKEND", "auto")  # auto|vps|local
ARENA_URL = "https://arena.ai/video"

SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", f"ProxyCommand={PROXY}",
    f"{VM_USER}@{VM_HOST}",
]


def vm_eval(js, timeout=60):
    """在 VPS Chrome 页面里执行 JS"""
    b64 = base64.b64encode(js.encode('utf-8')).decode('ascii')
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"j=base64.b64decode('{b64}').decode('utf-8');"
        f"r=subprocess.run(['{VPS_AB}','--cdp','{VPS_CDP}','eval',j],"
        f"capture_output=True,text=True,timeout={timeout});"
        f"print(r.stdout.strip())"
        f"\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=timeout+60)
    return r.stdout.strip()


def local_eval(js, timeout=60):
    """在本机 Chrome（9335）页面里执行 JS"""
    r = subprocess.run(
        [LOCAL_AB, "--cdp", "9335", "eval", js],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "AGENT_BROWSER_PROXY": "http://127.0.0.1:3129"},
    )
    return r.stdout.strip()


def browser_eval(js, backend, timeout=60):
    if backend == "local":
        return local_eval(js, timeout)
    return vm_eval(js, timeout)


def browser_open(url, backend):
    """在对应后端浏览器打开 URL，返回是否成功"""
    if backend == "local":
        r = subprocess.run(
            [LOCAL_AB, "--cdp", "9335", "open", url],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "AGENT_BROWSER_PROXY": "http://127.0.0.1:3129"},
        )
    else:
        b64 = base64.b64encode(f"window.location.href={json.dumps(url)}".encode()).decode()
        vm_py = (
            f"python3 -c \""
            f"import base64,subprocess;"
            f"j=base64.b64decode('{b64}').decode('utf-8');"
            f"r=subprocess.run(['{VPS_AB}','--cdp','{VPS_CDP}','eval',j],"
            f"capture_output=True,text=True,timeout=30);"
            f"print(r.stdout.strip())"
            f"\""
        )
        r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=90)
    return r.returncode == 0


def _parse_json_out(out):
    """稳健解析 vm_eval 返回的 JSON（处理双层转义，引自 geminigen_api.py）"""
    s = out.strip()
    # 先解一层（agent-browser 把 JS 返回值又包了一层 JSON）
    try:
        inner = json.loads(s)
        if isinstance(inner, str):
            return json.loads(inner)
        return inner
    except Exception:
        pass
    # 兜底：手动去转义
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    s = s.replace('\\\\"', '"').replace('\\\\', '\\')
    return json.loads(s)


def ab_run(args_list, backend, timeout=60):
    """跑一条 agent-browser 原生命令（真点击/填写，可信事件）"""
    if backend == "local":
        cmd = [LOCAL_AB, "--cdp", "9335"] + args_list
        env = {**os.environ, "AGENT_BROWSER_PROXY": "http://127.0.0.1:3129"}
    else:
        # VPS：经 SSH
        inner = " ".join(f"'{a}'" for a in [VPS_AB, "--cdp", VPS_CDP] + args_list)
        cmd = SSH_BASE + [inner]
        env = None
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.stdout.strip(), r.returncode


def find_refs(snapshot_text):
    """从 snapshot 里找 prompt 输入框和发送按钮的 ref"""
    import re
    box_ref, send_ref = None, None
    for m in re.finditer(r'@(\S+).*?(textarea|textbox).*?(Describe your video|prompt)', snapshot_text, re.I):
        box_ref = "@" + m.group(1)
        break
    for m in re.finditer(r'@(\S+).*?button.*?Send message', snapshot_text, re.I):
        send_ref = "@" + m.group(1)
        break
    return box_ref, send_ref


def try_backends(prompt, job_id, out_dir):
    """auto 模式：local 优先（有 arena 登录态），失败切 vps"""
    backends = ["local", "vps"] if BACKEND == "auto" else [BACKEND]
    last_err = ""
    for be in backends:
        try:
            return generate(prompt, job_id, out_dir, be), be
        except Exception as e:
            last_err = f"[{be}] {e}"
            print(f"backend {be} failed: {e}", file=sys.stderr)
    raise RuntimeError(f"all backends failed, last: {last_err}")


def generate(prompt, job_id, out_dir, backend):
    os.makedirs(out_dir, exist_ok=True)
    prompt_b64 = base64.b64encode(prompt.encode('utf-8')).decode('ascii')

    # 1. 打开 arena.ai/video
    if not browser_open(ARENA_URL, backend):
        raise RuntimeError("browser open failed")
    time.sleep(5)

    # 2. 确认页面就绪：找 prompt 输入框
    js_ready = """(() => {
        const els = document.querySelectorAll('textarea, [contenteditable="true"], input[type="text"]');
        for (const el of els) {
            const ph = (el.placeholder || el.getAttribute('aria-label') || '').toLowerCase();
            if (ph.includes('describe') || ph.includes('video') || ph.includes('prompt')) {
                return JSON.stringify({ok: true});
            }
        }
        // 兜底：找最大的 textarea
        if (els.length > 0) return JSON.stringify({ok: true, fallback: true});
        return JSON.stringify({ok: false, html_snippet: document.body.innerText.slice(0, 500)});
    })()"""
    out = browser_eval(js_ready, backend, 30)
    try:
        info = _parse_json_out(out)
    except Exception:
        raise RuntimeError(f"ready check parse failed: {out[:200]}")
    if not info.get("ok"):
        snippet = info.get("html_snippet", "")
        if any(k in snippet.lower() for k in ["sign in", "log in", "subscribe", "upgrade", "payment"]):
            raise RuntimeError(f"blocked by login/paywall: {snippet[:150]}")
        raise RuntimeError(f"prompt box not found: {snippet[:150]}")

    # 3. 填 prompt 并提交（用 agent-browser 原生命令：可信事件）
    snap, _ = ab_run(["snapshot"], backend, 30)
    box_ref, send_ref = find_refs(snap)
    if not box_ref:
        raise RuntimeError(f"snapshot 未找到 prompt 输入框")
    if not send_ref:
        raise RuntimeError(f"snapshot 未找到发送按钮")
    # 填写 prompt（原生 fill = 可信输入事件）
    _, rc = ab_run(["fill", box_ref, prompt], backend, 30)
    if rc != 0:
        raise RuntimeError("fill prompt 失败")
    time.sleep(2)
    # 重新 snapshot（按钮启用后 ref 可能变），找发送按钮再点
    snap2, _ = ab_run(["snapshot"], backend, 30)
    _, send_ref2 = find_refs(snap2)
    send_ref = send_ref2 or send_ref
    before_url = browser_eval("location.href", backend, 15).strip().strip('"')
    _, rc = ab_run(["click", send_ref], backend, 30)
    if rc != 0:
        raise RuntimeError("click 发送按钮失败")
    # 等待跳转（最多 30 秒）
    battle_url = before_url
    for _ in range(6):
        time.sleep(5)
        cur = browser_eval("location.href", backend, 15).strip().strip('"')
        if cur != before_url and "/c/" in cur:
            battle_url = cur
            break
    if battle_url == before_url:
        raise RuntimeError("submit did not navigate to battle page")

    # 4. 轮询等待两条视频完成（最长 15 分钟）
    js_poll = """(() => {
        const videos = document.querySelectorAll('video');
        const out = [];
        videos.forEach((v, i) => {
            out.push({src: (v.currentSrc || v.src || '').slice(0, 200),
                      ready: v.readyState, duration: v.duration || 0});
        });
        const body = document.body.innerText || '';
        const generating = /generating/i.test(body);
        return JSON.stringify({count: videos.length, videos: out, generating});
    })()"""
    deadline = time.time() + 900
    final_videos = []
    while time.time() < deadline:
        time.sleep(20)
        out = browser_eval(js_poll, backend, 30)
        try:
            st = _parse_json_out(out)
        except Exception:
            continue
        vids = [v for v in st.get("videos", []) if v.get("src")]
        # 两条都有 src 且不在 generating 状态
        if len(vids) >= 2 and not st.get("generating"):
            # 再确认一次（防半成品）
            time.sleep(10)
            out2 = browser_eval(js_poll, backend, 30)
            try:
                st2 = _parse_json_out(out2)
            except Exception:
                continue
            vids2 = [v for v in st2.get("videos", []) if v.get("src")]
            if len(vids2) >= 2 and not st2.get("generating"):
                final_videos = vids2
                break
    if not final_videos:
        raise RuntimeError("timeout waiting for videos (15min)")

    # 5. 下载视频
    files = []
    for i, v in enumerate(final_videos[:2]):
        src = v["src"]
        fname = f"arena_{job_id}_{chr(97+i)}.mp4"
        fpath = os.path.join(out_dir, fname)
        # 经浏览器下载（带 cookie）
        js_dl = f"""(async () => {{
            const url = {json.dumps(src)};
            const r = await fetch(url, {{credentials: 'include'}});
            if (!r.ok) return JSON.stringify({{ok: false, status: r.status}});
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let bin = '';
            const chunk = 8192;
            for (let i = 0; i < bytes.length; i += chunk) {{
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
            }}
            return JSON.stringify({{ok: true, b64: btoa(bin), size: bytes.length}});
        }})()"""
        out = browser_eval(js_dl, backend, 120)
        try:
            dl = _parse_json_out(out)
        except Exception:
            raise RuntimeError(f"download {i} parse failed")
        if not dl.get("ok"):
            raise RuntimeError(f"download {i} http {dl.get('status')}")
        with open(fpath, "wb") as f:
            f.write(base64.b64decode(dl["b64"]))
        files.append(fpath)

    return {"ok": True, "files": files, "battle_url": battle_url}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out-dir", default="/home/hatch/data/veo_inbox/")
    ap.add_argument("--backend", default=None, choices=["auto", "vps", "local"])
    ap.add_argument("--prompt-file")
    args = ap.parse_args()

    global BACKEND
    if args.backend:
        BACKEND = args.backend

    prompt = args.prompt
    if args.prompt_file:
        prompt = open(args.prompt_file, encoding="utf-8").read().strip()

    try:
        result, used = try_backends(prompt, args.job_id, args.out_dir)
        result["backend_used"] = used
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
