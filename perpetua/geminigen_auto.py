#!/usr/bin/env python3
"""
GeminiGen 网页自动化视频生成
经 SSH 调 VM 上的 agent-browser（本机无 agent-browser --cdp）
流程：打开 veo31 页面 → 选 9:16 → 关 Publish to Explore → 填 prompt → 生成 → 等待 → 下载
用法：
  python3 geminigen_auto.py --prompt-file xxx.txt --job-id xxx --out-dir /home/hatch/data/veo_inbox/
"""
import argparse
import base64
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
# 并行支持：CDP_PORT=9223 时用第二个 Chrome 实例（/tmp/chrome-parallel-profile）

SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", f"ProxyCommand={PROXY}",
    f"{VM_USER}@{VM_HOST}",
]

def ab(args, timeout=30):
    """在 VM 上执行 agent-browser 命令"""
    cmd = SSH_BASE + [AGENT_BROWSER, "--cdp", CDP] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode

def snapshot():
    out, _, _ = ab(["snapshot"], timeout=30)
    return out

def find_ref(snap, keyword, kind=None):
    """在 snapshot 中找包含关键词的 ref"""
    for line in snap.split("\n"):
        if keyword.lower() in line.lower():
            if kind and kind not in line:
                continue
            # 提取 [ref=eXXXX]
            import re
            m = re.search(r'\[ref=(e\d+)\]', line)
            if m:
                return m.group(1)
    return None

def fill_ref(ref, text, desc=""):
    """填写文本框 - 直接 SSH 到 VM 上执行，避免 shell 转义"""
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"t=base64.b64decode('{b64}').decode('utf-8');"
        f"r=subprocess.run(['{AGENT_BROWSER}','--cdp','{CDP}','fill','{ref}',t],"
        f"capture_output=True,text=True,timeout=60);"
        f"print('FILL_OK' if r.returncode==0 else 'FILL_FAIL:'+r.stderr[:200])"
        f"\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=90)
    out = r.stdout + r.stderr
    ok = "FILL_OK" in out
    print(f"  填写 {desc}({ref}): {'OK' if ok else 'FAIL'} ({len(text)} 字符)")
    if not ok:
        print(f"    输出: {out[:300]}")
    return ok

def click_ref(ref, desc=""):
    out, err, code = ab(["click", ref], timeout=20)
    ok = code == 0
    print(f"  点击 {desc}({ref}): {'OK' if ok else 'FAIL'}")
    return ok

def fill_react_textarea(ref, text, desc=""):
    """通过 React onChange 填写 textarea（agent-browser fill 写不进 React state）"""
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    js = """
    (() => {
        const ta = document.querySelector('textarea');
        if (!ta) return 'NO_TEXTAREA';
        const key = Object.keys(ta).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (!key) return 'NO_FIBER';
        let fiber = ta[key];
        let depth = 0;
        while (fiber && depth < 25) {
            const props = fiber.memoizedProps;
            if (props && props.onChange) {
                const val = atob('__B64__');
                props.onChange({target: {value: val}, currentTarget: {value: val}});
                return 'OK:' + document.querySelector('textarea').value.length;
            }
            fiber = fiber.return;
            depth++;
        }
        return 'NO_ONCHANGE';
    })()
    """.replace('__B64__', b64)
    out = eval_js(js)
    ok = out.strip().strip('"').startswith('OK:')
    print(f"  填写 {desc}: {'OK' if ok else 'FAIL'} ({out.strip()[:30]})")
    return ok

def click_react_generate():
    """通过 React onClick 触发生成按钮（agent-browser click 不触发）"""
    js = """
    (() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const gen = btns.find(b => b.textContent.trim() === 'Generate with Veo 3.1 Video Generator');
        if (!gen) return 'GEN_NOT_FOUND';
        if (gen.disabled) return 'GEN_DISABLED';
        const key = Object.keys(gen).find(k => k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (!key) return 'NO_FIBER';
        let fiber = gen[key];
        let depth = 0;
        while (fiber && depth < 20) {
            const props = fiber.memoizedProps;
            if (props && props.onClick) {
                props.onClick({preventDefault:()=>{}, stopPropagation:()=>{}, target:gen, currentTarget:gen});
                return 'CLICKED';
            }
            fiber = fiber.return;
            depth++;
        }
        return 'NO_ONCLICK';
    })()
    """
    out = eval_js(js)
    result = out.strip().strip('"')
    print(f"  生成按钮: {result}")
    return result == 'CLICKED'

def eval_js(js, desc=""):
    """在 VM 上执行 JS - base64 编码避免 SSH shell 转义问题"""
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
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()

def set_aspect_916():
    """设置宽高比为 9:16（原生 DOM click，走 React 合成事件）。

    2026-10-09 修复：
    1. 必须在最后一次页面加载之后调用（[4] 的跳转会重置表单）。
    2. 用原生 click 不用 fiber 直调：fiber 只改按钮文字不更新提交参数，
       导致后端仍出 1280x720（连续两次实测证实）。
    返回 True 表示 trigger 显示 9:16。
    """
    import time
    ar_js = """
    (() => {
        const btns = Array.from(document.querySelectorAll('button'));
        const trigger = btns.find(x => {
            const t = x.textContent.trim();
            return t === '16:9' || t === '9:16' || t === '1:1';
        });
        if (!trigger) return 'TRIGGER_NOT_FOUND';
        if (trigger.textContent.trim() === '9:16') return 'ALREADY_916';
        trigger.click();
        return 'DROPDOWN_OPENED';
    })()
    """
    out = eval_js(ar_js)
    result = out.strip().strip('"')
    if result == 'ALREADY_916':
        print("  已是 9:16")
        return True
    if result != 'DROPDOWN_OPENED':
        print(f"  警告: 未找到宽高比控件 ({result})")
        return False
    time.sleep(2)
    # 2026-10-09 修订：改用原生 DOM click（走 React 合成事件系统），
    # 不再用 fiber 直调 props.onClick。实测 fiber 点击只改按钮文字，
    # 不更新提交参数（连续两次出 1280x720 横屏）；原生点击走完整事件流。
    opt_js = """
    (() => {
        const opts = Array.from(document.querySelectorAll('[role=option]'));
        const target = opts.find(o => o.textContent.trim() === '9:16');
        if (!target) return 'OPT_NOT_FOUND';
        target.click();
        return 'CLICKED';
    })()
    """
    out2 = eval_js(opt_js)
    time.sleep(2)
    # 关掉下拉（点 Escape），避免遮挡后续操作
    eval_js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
    time.sleep(1)
    verify_js = """
    Array.from(document.querySelectorAll('button'))
        .map(b => b.textContent.trim())
        .filter(t => /^(16:9|9:16|1:1)$/.test(t)).join(',')
    """
    out3 = eval_js(verify_js)
    ok = '9:16' in out3
    print(f"  {'已切换到 9:16' if ok else '警告: 宽高比切换可能失败 (当前: ' + out3.strip() + ')'}")
    return ok

def get_video_url():
    """用 JS 在页面上找 video 元素的 src"""
    js = """
    (() => {
        const vids = document.querySelectorAll('video');
        for (const v of vids) {
            if (v.src && v.src.includes('.mp4')) return v.src;
            const s = v.querySelector('source');
            if (s && s.src) return s.src;
        }
        // 也找下载链接
        const links = document.querySelectorAll('a[href*=".mp4"]');
        for (const a of links) return a.href;
        return '';
    })()
    """
    out = eval_js(js)
    # 清理输出中的引号和转义
    url = out.strip().strip('"').replace('\\/', '/')
    return url if url.startswith('http') else ''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out-dir", default="/home/hatch/data/veo_inbox/")
    ap.add_argument("--model", default="veo 3.1 fast")
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--skip-aspect", action="store_true", help="跳过宽高比设置（测试用）")
    args = ap.parse_args()

    with open(args.prompt_file, encoding="utf-8") as f:
        prompt = f.read().strip()

    # GeminiGen "Karen" 拒收绕行（2026-10-11 用户批准"两个都要开"）：
    # 只替换提交给 GeminiGen 的副本，源 prompt 文件不动。
    # GeminiGen 把 "Karen" 误判为 prominent public figure 导致生成被拒；
    # 这是平台政策层面的提交副本替换，不是改内容。
    _KAREN_WORKAROUND = True
    if _KAREN_WORKAROUND and "Karen" in prompt:
        prompt = prompt.replace("Karen", "entitled middle-aged woman")
        prompt = prompt.replace("KAREN", "ENTITLED MIDDLE-AGED WOMAN")
        print("  [绕行] 提交副本已替换 Karen → entitled middle-aged woman（源文件不动）")

    print(f"=== GeminiGen 自动生成: {args.job_id} ===")
    print(f"prompt 长度: {len(prompt)} 字符, 模型: {args.model}, 比例: {args.aspect}")
    print()

    # [1] 打开 veo31 页面
    print("[1/7] 打开 Veo 3.1 生成页...")
    ab(["open", "https://geminigen.link/app/veo31"], timeout=30)
    time.sleep(5)

    snap = snapshot()
    # 检查是否登录（找 API Keys 或用户标识）
    if "api-keys" not in snap.lower() and "sign in" in snap.lower():
        print("  警告: 可能未登录，请检查")
    else:
        print("  页面已加载")

    # [2] 确认模型是 veo 3.1 fast（默认应该就是）
    print("[2/7] 确认模型...")
    if "veo 3.1 fast" in snap.lower():
        print("  模型已是 veo 3.1 fast")
    else:
        print("  警告: 未找到 veo 3.1 fast 标识")

    # [3] 宽高比设置移到 [4] 之后（页面跳转会重置表单）。
    # 2026-10-09 修复：在 [3] 只做一次尝试性设置，真正生效的设置在 [4] 返回后。
    print("[3/7] 设置宽高比 9:16（预设，[4] 返回后会重新确认）...")
    if args.skip_aspect:
        print("  跳过（测试模式）")
    else:
        set_aspect_916()

    # [4] 关闭 Publish to Explore，同时记录已有视频 URL（用于下载时识别新视频）
    print("[4/7] 关闭 Publish to Explore...")
    snap = snapshot()
    pub_ref = find_ref(snap, "publish to explore", "switch")
    if pub_ref:
        # 检查是否已开启
        for line in snap.split("\n"):
            if pub_ref in line and "checked=true" in line:
                click_ref(pub_ref, "Publish 开关")
                print("  已关闭 Publish to Explore")
                break
        else:
            print("  Publish 已是关闭状态")
    else:
        print("  未找到 Publish 开关，跳过")

    # 记录生成前的已有视频，用于后续识别新视频
    print("  记录已有视频列表...")
    ab(["open", "https://geminigen.link/myallcreations"], timeout=30)
    time.sleep(6)
    existing_js = """
    (() => {
        const vids = document.querySelectorAll('video');
        const urls = [];
        vids.forEach((v) => {
            let src = v.src || (v.querySelector('source')||{}).src || '';
            if (src && src.includes('roomai.link/video')) urls.push(src.slice(0,100));
        });
        return urls.join('\\n');
    })()
    """
    existing_out = eval_js(existing_js)
    existing_urls = set(existing_out.strip().strip('"').split('\\n')) if existing_out else set()
    print(f"  已有 {len(existing_urls)} 个视频")
    # 回到生成页
    ab(["open", "https://geminigen.link/app/veo31"], timeout=30)
    time.sleep(6)

    # [3'] 重新确认 9:16（[4] 的页面跳转会重置表单，这里是真正生效的一次）
    # 2026-10-09 修复：根因是跳转重置，此处必须在最后一次页面加载后设置
    if not args.skip_aspect:
        print("[3'/7] 跳转后重新确认宽高比 9:16...")
        set_aspect_916()

    # [5] 填写 prompt（通过 React onChange，agent-browser fill 无效）
    print("[5/7] 填写 prompt...")
    if not fill_react_textarea(None, prompt, "视频 prompt"):
        print("  错误: prompt 填写失败")
        sys.exit(1)

    # [6] 点击生成（通过 React onClick，agent-browser click 不触发）
    print("[6/7] 开始生成...")
    if not click_react_generate():
        print("  错误: 生成按钮点击失败")
        sys.exit(1)
    print("  生成中，等待 120 秒...")
    time.sleep(120)

    # [7] 从 My Creations 页面获取新视频并下载（排除生成前已有的）
    print("[7/7] 从 My Creations 获取新视频并下载...")
    video_url = ''
    for attempt in range(6):  # 最多等 3 分钟
        ab(["open", "https://geminigen.link/myallcreations"], timeout=30)
        time.sleep(8)
        js = """
        (() => {
            const vids = document.querySelectorAll('video');
            const urls = [];
            vids.forEach((v) => {
                let src = v.src || (v.querySelector('source')||{}).src || '';
                if (src && src.includes('roomai.link/video')) {
                    if (!src.endsWith('.mp4')) src += '-0.mp4';
                    urls.push(src);
                }
            });
            return urls.join('\\n');
        })()
        """
        out = eval_js(js)
        for line in out.strip().strip('"').split('\\n'):
            line = line.strip().replace('\\/', '/')
            # 只取新视频：不在生成前的已有列表中
            short = line[:100]
            if line.startswith('http') and short not in existing_urls:
                video_url = line
                break
        if video_url:
            print(f"  找到新视频 URL: {video_url[:80]}...")
            break
        print(f"  等待新视频出现在 My Creations... ({attempt+1}/6)")
        time.sleep(30)

    if not video_url:
        print("  错误: My Creations 中未找到新视频（可能生成失败）")
        sys.exit(1)

    # 在 VM 上 curl 下载，然后 scp 回本地
    vm_path = f"/tmp/geminigen_{args.job_id}.mp4"
    print(f"  VM 上下载到 {vm_path}...")
    dl_cmd = SSH_BASE + ["curl", "-sL", "-o", vm_path, video_url]
    r = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"  VM 下载失败: {r.stderr[:200]}")
        sys.exit(1)

    # scp 回本地
    local_path = os.path.join(args.out_dir, f"geminigen_{args.job_id}.mp4")
    os.makedirs(args.out_dir, exist_ok=True)
    print(f"  传回本地: {local_path}...")
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
        print(f"  下载成功: {local_path} ({size//1024}KB)")
    else:
        print(f"  scp 失败: {r.stderr[:200]}")
        sys.exit(1)

    print()
    print(f"=== 完成: {args.job_id} ===")
    print(f"视频: {local_path}")

if __name__ == "__main__":
    main()
