#!/usr/bin/env python3
"""Vids 全自动生成脚本 (agent-browser via SSH → VM)
流程: 传prompt到VM → 新建项目 → AI生成面板 → 设时长/720p/竖屏 → 粘贴prompt → 生成 → 等待 → 下载
用法: python3 vids_auto.py --prompt-file /path/to/prompt.txt --job-id veo_xxx --out-dir /home/hatch/data/veo_inbox/ [--duration 8]
注意: agent-browser 装在 VM (192.166.82.123) 上，本机经 SSH 调用。VM Chrome 需有 Google 登录态。
"""
import subprocess, time, sys, os, argparse, re, base64

# agent-browser 在 VM 上，本机经 SSH 调用（参考 vm_post_reel.py）
VM_HOST = "root@192.166.82.123"
SSH_BASE = [
    "ssh", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
    "-o", "StrictHostKeyChecking=no",
    "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
    VM_HOST,
]
AB = f"/usr/bin/agent-browser --cdp http://127.0.0.1:{os.environ.get('CDP_PORT', '9222')}"
# 并行支持：CDP_PORT=9223 时用第二个 Chrome 实例

def ab(cmd, timeout=60):
    """经 SSH 在 VM 上执行 agent-browser"""
    full = SSH_BASE + [AB] + cmd
    # AB 是带参数的字符串，需要 split
    full = SSH_BASE + AB.split() + cmd
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode

def js_eval(js, timeout=30):
    """在 VM Chrome 当前页面执行 JS（经 agent-browser eval），返回页面返回值字符串。

    2026-10-09 新增：用于 Bug 4 修复（JS 注入直接下载 AI 原片）。
    """
    import base64
    js_b64 = base64.b64encode(js.encode('utf-8')).decode('ascii')
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"js=base64.b64decode('{js_b64}').decode('utf-8');"
        f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
        f"capture_output=True,text=True,timeout={timeout});"
        f"print(r.stdout.strip())"
        f"\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=timeout+30)
    return r.stdout.strip()

def snap():
    out, _, _ = ab(["snapshot", "-i"])
    return out

def find_ref(pattern, snapshot_text):
    """在快照中找匹配的 ref"""
    for line in snapshot_text.split('\n'):
        if re.search(pattern, line, re.I):
            m = re.search(r'\[ref=(e\d+)\]', line)
            if m:
                return m.group(1)
    return None

def find_all_refs(pattern, snapshot_text):
    """找所有匹配的 refs"""
    refs = []
    for line in snapshot_text.split('\n'):
        if re.search(pattern, line, re.I):
            m = re.search(r'\[ref=(e\d+)\]', line)
            if m:
                refs.append((m.group(1), line.strip()[:100]))
    return refs

def _is_ref_error(out, err):
    combined = (out or "") + (err or "")
    return "Unknown ref" in combined or "unknown ref" in combined.lower()

def fill_js_fallback(text, desc="", max_retries=3):
    """用页面 JS 直接找 prompt 输入框并填写（绕过 snapshot/ref）。
    兼容 React：设置 value 后 dispatch input/change 事件。"""
    import base64
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    js_b64 = base64.b64encode("""
    (() => {
      const sels = [
        'textarea[aria-label*="escrib" i]', 'textarea[aria-label*="escrib" i]',
        'textarea:not([aria-label*="earch" i])',
        '[contenteditable="true"]', '[role="textbox"]'
      ];
      let el = null;
      // 优先找可见的大文本区（排除顶部搜索框）
      const tas = Array.from(document.querySelectorAll('textarea'))
        .filter(t => t.offsetParent !== null && !/search/i.test(t.getAttribute('aria-label')||''));
      if (tas.length) {
        tas.sort((a,b) => (b.rows||b.clientHeight) - (a.rows||a.clientHeight));
        el = tas[0];
      }
      if (!el) {
        const ces = Array.from(document.querySelectorAll('[contenteditable="true"]'))
          .filter(e => e.offsetParent !== null && (e.innerText||'').length < 500);
        if (ces.length) { ces.sort((a,b)=>b.clientHeight-a.clientHeight); el = ces[0]; }
      }
      if (!el) return 'NOTFOUND';
      el.focus();
      // React 兼容写法
      const setter = Object.getOwnPropertyDescriptor(
        el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLElement.prototype,
        el.tagName === 'TEXTAREA' ? 'value' : 'innerText')?.set
        || Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value')?.set;
      return 'FOUND:' + el.tagName;
    })()
    """.encode('utf-8')).decode('ascii')
    for attempt in range(max_retries):
        vm_py = (
            f"python3 -c \""
            f"import base64,subprocess;"
            f"t=base64.b64decode('{b64}').decode('utf-8');"
            f"js=base64.b64decode('{js_b64}').decode('utf-8');"
            f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
            f"capture_output=True,text=True,timeout=30);"
            f"print(r.stdout.strip())"
            f"\""
        )
        r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=60)
        out = r.stdout.strip()
        if "FOUND:" in out:
            tag = out.split("FOUND:")[1].split('"')[0].strip()
            # 第二步：实际填写
            fill_js = base64.b64encode(f"""
            (() => {{
              const t = atob('{b64}');
              const tas = Array.from(document.querySelectorAll('textarea'))
                .filter(x => x.offsetParent !== null && !/search/i.test(x.getAttribute('aria-label')||''));
              tas.sort((a,b) => (b.clientHeight) - (a.clientHeight));
              let el = tas[0];
              if (!el) {{
                const ces = Array.from(document.querySelectorAll('[contenteditable="true"]'))
                  .filter(e => e.offsetParent !== null);
                ces.sort((a,b)=>b.clientHeight-a.clientHeight); el = ces[0];
              }}
              if (!el) return 'NOTFOUND2';
              el.focus();
              if (el.tagName === 'TEXTAREA') {{
                const proto = Object.getPrototypeOf(el);
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                if (desc && desc.set) desc.set.call(el, t);
                else el.value = t;
                el.dispatchEvent(new Event('input', {{bubbles:true}}));
                el.dispatchEvent(new Event('change', {{bubbles:true}}));
              }} else {{
                el.innerText = t;
                el.dispatchEvent(new Event('input', {{bubbles:true}}));
              }}
              return 'FILLED:' + el.value.length;
            }})()
            """.encode('utf-8')).decode('ascii')
            vm_py2 = (
                f"python3 -c \""
                f"import base64,subprocess;"
                f"js=base64.b64decode('{fill_js}').decode('utf-8');"
                f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
                f"capture_output=True,text=True,timeout=60);"
                f"print(r.stdout.strip())"
                f"\""
            )
            r2 = subprocess.run(SSH_BASE + [vm_py2], capture_output=True, text=True, timeout=90)
            if "FILLED:" in r2.stdout:
                print(f"  填写 {desc}: OK (JS 直填)")
                return True
        print(f"  填写 {desc}: JS 未找到输入框 (尝试 {attempt+1}/{max_retries})")
        time.sleep(2)
    print(f"  填写 {desc}: JS 方式失败")
    return False

def fill_vids_prompt(text, desc="视频 prompt", max_retries=3):
    """Vids AI 面板 prompt 填写（2026-10-09 修复）。

    根因：Vids 的 prompt 输入框是 contenteditable DIV（[role=textbox]，
    class appsElementsRichTextInputContentEditable），不是 textarea。
    直接设 innerText + dispatch input 事件无法让 React 正确注册，
    Generate 按钮保持 disabled。必须用 document.execCommand('insertText')
    走浏览器编辑管线，React 才能捕获，按钮才会激活。
    """
    import base64
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    js_b64 = base64.b64encode("""
    (() => {
      const el = document.querySelector('[role="textbox"]');
      if (!el) return 'NO_TEXTBOX';
      el.focus();
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel.removeAllRanges(); sel.addRange(range);
      const t = atob('__B64__');
      const ok = document.execCommand('insertText', false, t);
      // 兜底：如果 execCommand 不可用，直接设 innerText
      if (!ok) { el.innerText = t; el.dispatchEvent(new Event('input',{bubbles:true})); }
      return 'DONE:' + el.innerText.length;
    })()
    """.replace('__B64__', b64).encode('utf-8')).decode('ascii')
    for attempt in range(max_retries):
        vm_py = (
            f"python3 -c \""
            f"import base64,subprocess;"
            f"js=base64.b64decode('{js_b64}').decode('utf-8');"
            f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
            f"capture_output=True,text=True,timeout=60);"
            f"print(r.stdout.strip())"
            f"\""
        )
        r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=90)
        out = r.stdout.strip()
        if "DONE:" in out:
            try:
                filled_len = int(out.split("DONE:")[1].split('"')[0])
            except ValueError:
                filled_len = 0
            # 校验：长度接近才算成功（允许富文本包装差异）
            if filled_len >= len(text) * 0.9:
                print(f"  填写 {desc}: OK (execCommand, {filled_len} 字符)")
                return True
            print(f"  填写 {desc}: 长度不足 ({filled_len}/{len(text)})，重试 {attempt+1}/{max_retries}")
        else:
            print(f"  填写 {desc}: 未找到输入框 ({out[:60]})，重试 {attempt+1}/{max_retries}")
        time.sleep(2)
    print(f"  填写 {desc}: 失败")
    return False


def set_vids_duration(target_sec):
    """设置 Vids 生成时长（2026-10-09 修复）。

    根因：时长滑块是无 aria-valuenow 的自定义组件，旧代码"已知无法调整"直接放弃。
    实测：focus 滑块后按 ArrowLeft 每次 -1 秒、ArrowRight 每次 +1 秒，
    Generation settings 按钮文本实时更新（如 "..., Portrait, 8 seconds"）。
    要求：调用前 Generation settings 面板已打开。
    """
    import base64
    # 当前值从按钮文本解析
    s = snap()
    m = re.search(r'Generation settings:[^"]*?(\d+)\s*seconds', s)
    cur = int(m.group(1)) if m else 10
    print(f"  当前时长: {cur}s，目标: {target_sec}s")
    if cur == target_sec:
        print("  时长已是目标值")
        return True
    if not 3 <= target_sec <= 10:
        print(f"  目标 {target_sec}s 超出范围 (3-10)，跳过")
        return False
    js_b64 = base64.b64encode("""
    (() => {
      const sls = Array.from(document.querySelectorAll('[role="slider"]'));
      const sl = sls.find(x => (x.getAttribute('aria-label')||'').includes('Video duration'));
      if (!sl) return 'NOSLIDER';
      sl.focus(); sl.scrollIntoView({block:'center'});
      return 'FOCUSED';
    })()
    """.encode('utf-8')).decode('ascii')
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"js=base64.b64decode('{js_b64}').decode('utf-8');"
        f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
        f"capture_output=True,text=True,timeout=30);"
        f"print(r.stdout.strip())"
        f"\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=60)
    if "FOCUSED" not in r.stdout:
        print("  未找到时长滑块")
        return False
    key = "ArrowLeft" if target_sec < cur else "ArrowRight"
    for _ in range(abs(target_sec - cur)):
        press_key(key, "时长微调")
        time.sleep(0.8)
    time.sleep(2)
    s2 = snap()
    m2 = re.search(r'Generation settings:[^"]*?(\d+)\s*seconds', s2)
    new_val = int(m2.group(1)) if m2 else -1
    ok = new_val == target_sec
    print(f"  时长已设为 {new_val}s {'OK' if ok else '（未达目标）'}")
    return ok


def click_smart(pattern, desc="", max_retries=3):
    """快照→查找→点击 原子操作，ref 失效自动重抓。返回 True/False"""
    for attempt in range(max_retries):
        s = snap()
        ref = find_ref(pattern, s)
        if not ref:
            if attempt == 0:
                print(f"  {desc}: 未找到匹配 '{pattern}' 的控件")
            time.sleep(2)
            continue
        # 找到后立刻点击，中间不做其他操作
        out, err, code = ab(["click", ref], timeout=15)
        if code == 0 and not _is_ref_error(out, err):
            print(f"  点击 {desc}: OK")
            return True
        print(f"  点击 {desc}: ref 失效，重抓 (尝试 {attempt+1}/{max_retries})")
        time.sleep(1)
    print(f"  点击 {desc}: 失败，已重试 {max_retries} 次")
    return False

def fill_smart(pattern, text, desc="", max_retries=3):
    """快照→查找→填写 原子操作。返回 True/False"""
    import base64
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    for attempt in range(max_retries):
        s = snap()
        ref = find_ref(pattern, s)
        if not ref:
            if attempt == 0:
                print(f"  {desc}: 未找到匹配 '{pattern}' 的输入框")
            time.sleep(2)
            continue
        vm_py = (
            f"python3 -c \""
            f"import base64,subprocess;"
            f"t=base64.b64decode('{b64}').decode('utf-8');"
            f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','fill','{ref}',t],"
            f"capture_output=True,text=True,timeout=60);"
            f"print('FILL_OK' if r.returncode==0 and 'Unknown ref' not in r.stderr else 'FILL_FAIL:'+r.stderr[:200])"
            f"\""
        )
        r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=90)
        out = r.stdout + r.stderr
        if "FILL_OK" in out:
            print(f"  填写 {desc}: OK ({len(text)} 字符)")
            return True
        print(f"  填写 {desc}: ref 失效，重抓 (尝试 {attempt+1}/{max_retries})")
        time.sleep(1)
    print(f"  填写 {desc}: 失败，已重试 {max_retries} 次")
    return False

def click_ref(ref, desc=""):
    out, err, code = ab(["click", ref], timeout=30)
    ok = code == 0
    print(f"  点击 {desc}({ref}): {'OK' if ok else 'FAIL'}")
    if not ok:
        print(f"    stderr: {err[:200]}")
    return ok

def fill_ref(ref, text, desc=""):
    """填写文本框 - 直接 SSH 到 VM 上执行，避免 agent-browser 命令限制"""
    import base64
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    # 直接经 SSH 在 VM 上跑 python，解码后调 agent-browser
    # b64 只含安全字符，可以直接拼进命令
    vm_py = (
        f"python3 -c \""
        f"import base64,subprocess;"
        f"t=base64.b64decode('{b64}').decode('utf-8');"
        f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','fill','{ref}',t],"
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

def press_key(key, desc=""):
    out, err, code = ab(["press", key], timeout=10)
    ok = code == 0
    print(f"  按键 {desc}({key}): {'OK' if ok else 'FAIL'}")
    return ok

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--out-dir", default="/home/hatch/data/veo_inbox/")
    ap.add_argument("--duration", type=int, default=8, help="视频时长秒数 (3-10)")
    args = ap.parse_args()

    prompt = open(args.prompt_file, encoding='utf-8').read().strip()
    print(f"=== Vids 自动生成: {args.job_id} ===")
    print(f"prompt 长度: {len(prompt)} 字符, 时长: {args.duration}s")

    # 把 prompt 传到 VM 上（agent-browser 在 VM 上运行，读不到本机文件）
    vm_prompt_path = f"/tmp/vids_prompt_{args.job_id}.txt"
    print(f"\n[0/9] 传 prompt 到 VM: {vm_prompt_path}...")
    scp_cmd = [
        "scp", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
        args.prompt_file, f"{VM_HOST}:{vm_prompt_path}",
    ]
    r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"  SCP 失败: {r.stderr[:200]}")
        return 1
    print("  传输 OK")

    # 1. 打开 Vids 首页
    print("\n[1/9] 打开 Vids...")
    ab(["open", "https://vids.google.com"], timeout=30)
    time.sleep(6)

    # 2. 新建：点 "+" tile → 直接点 "Create AI videos"（直达 AI 面板，无需进编辑器）
    # 2026-10-09 修复：Create AI videos 按钮直接打开 AI 视频面板，比进编辑器再找工具栏更可靠
    print("[2/9] 打开 AI 视频创建...")
    s = snap()
    ai_btn_ref = find_ref(r'"Create AI videos', s)
    if not ai_btn_ref:
        print("  对话框未开，点击 Start a new video (+)...")
        plus_clicked = False
        for pat in [r'Start a new video', r'Recently used templates']:
            s = snap()
            refs = find_all_refs(pat, s)
            if refs:
                tpl_ref = find_ref(r'clickable \[cursor:pointer\]', s)
                if tpl_ref:
                    if click_ref(tpl_ref, "Start new video (+)"):
                        plus_clicked = True
                        break
            time.sleep(2)
        if plus_clicked:
            time.sleep(4)
            s = snap()
            ai_btn_ref = find_ref(r'"Create AI videos', s)
    if ai_btn_ref:
        click_ref(ai_btn_ref, "Create AI videos")
        time.sleep(6)
        print("  AI 视频面板应已打开")
    else:
        print("  未找到 Create AI videos 按钮")
        # Fallback 到旧流程
        portrait_ref = find_ref(r'"Create a portrait video"', s)
        if portrait_ref:
            click_ref(portrait_ref, "Create a portrait video")
        elif not click_smart(r"Create a portrait video", "Create a portrait video"):
            # fallback: 模板方式
            print("  尝试模板方式...")
            s = snap()
            m = re.search(r'option \[ref=(e\d+)\][^\n]*\n\s*- generic \[ref=(e\d+)\] clickable', s)
            if m:
                click_ref(m.group(2), "模板")
            else:
                # 再 fallback：点 landscape
                click_smart(r"Create a landscape video", "Create a landscape video")
    time.sleep(8)

    # 3-4. 已在 AI 视频面板（Create AI videos 直达），验证面板
    # 2026-10-09：新流程直接进 AI 面板，跳过编辑器和工具栏
    print("[3/9] 确认 AI 视频面板...")
    s = snap()
    if "AI video clip" in s and "Describe your video" in s:
        print("  AI 视频面板已打开")
    else:
        print("  警告: AI 面板可能未打开，尝试旧流程...")
        # Fallback: 尝试从编辑器工具栏进入
        print("[4/9] 尝试从工具栏打开...")
        ai_clicked = False
        for pattern, desc in [
            (r"Generate an AI video clip", "AI视频按钮(全名)"),
            (r"AI video clip", "AI视频按钮(简称)"),
        ]:
            if click_smart(pattern, desc, max_retries=2):
                ai_clicked = True
                break
        if not ai_clicked:
            print("  未找到 AI 入口")
            return 1
        time.sleep(5)

    # 5. 打开 Generation settings，设置 Portrait + 时长
    # 2026-10-09 修复（顺序关键）：
    #  - 必须先点 Portrait，再调时长滑块。实测：调时长滑块后 radio 从
    #    accessibility tree 消失（面板重渲染），反向顺序则两者都保持。
    #  - Portrait 用纯 JS 点击（snapshot/ref 方式不稳定，时有时无；
    #    JS 直接找 [role=radio] 文本点击 100% 可靠）
    #  - 时长滑块用方向键调整（每次±1s）
    print(f"[5/9] 设置生成参数 (时长={args.duration}s, 竖屏)...")
    if click_smart(r"Generation settings", "Generation settings"):
        time.sleep(4)
        # 先 Portrait（纯 JS，不依赖 snapshot）
        portrait_ok = False
        js_portrait_b64 = base64.b64encode("""
        (() => {
          const rs = Array.from(document.querySelectorAll('[role="radio"]'));
          const p = rs.find(r => r.textContent.trim().startsWith('Portrait'));
          if (!p) return 'NOPORTRAIT:' + rs.length;
          p.click();
          return 'CLICKED';
        })()
        """.encode('utf-8')).decode('ascii')
        js_verify_b64 = base64.b64encode("""
        (() => {
          const rs = Array.from(document.querySelectorAll('[role="radio"]'));
          const p = rs.find(r => r.textContent.trim().startsWith('Portrait'));
          return p ? ('CHECKED:' + p.getAttribute('aria-checked')) : 'GONE';
        })()
        """.encode('utf-8')).decode('ascii')
        for _ in range(3):
            vm_py = (
                f"python3 -c \""
                f"import base64,subprocess;"
                f"js=base64.b64decode('{js_portrait_b64}').decode('utf-8');"
                f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
                f"capture_output=True,text=True,timeout=30);"
                f"print(r.stdout.strip())"
                f"\""
            )
            r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True, timeout=60)
            out = r.stdout.strip().strip('"')
            if "CLICKED" in out:
                time.sleep(2)
                vm_py2 = (
                    f"python3 -c \""
                    f"import base64,subprocess;"
                    f"js=base64.b64decode('{js_verify_b64}').decode('utf-8');"
                    f"r=subprocess.run(['/usr/bin/agent-browser','--cdp','http://127.0.0.1:9222','eval',js],"
                    f"capture_output=True,text=True,timeout=30);"
                    f"print(r.stdout.strip())"
                    f"\""
                )
                r2 = subprocess.run(SSH_BASE + [vm_py2], capture_output=True, text=True, timeout=60)
                if "CHECKED:true" in r2.stdout:
                    portrait_ok = True
                    print("  Portrait 已选中 (JS)")
                    break
                print(f"  Portrait 点击后未选中 ({r2.stdout.strip()[:40]})，重试...")
            else:
                print(f"  Portrait radio 未找到 ({out[:40]})，重试...")
            time.sleep(3)
        if not portrait_ok:
            print("  警告: 未能选中 Portrait，继续")
        # 再调时长
        set_vids_duration(args.duration)
        # 最终确认
        time.sleep(1)
        s = snap()
        m = re.search(r'Generation settings:\s*([^"]+)"', s)
        if m:
            print(f"  当前设置: {m.group(1)}")
        press_key("Escape", "关闭设置")
        time.sleep(2)
    else:
        print("  未找到 Generation settings")

    # 6. 粘贴 prompt（Vids 专用：contenteditable DIV + execCommand）
    # 2026-10-09 修复：输入框是 [role=textbox] 的 contenteditable DIV，
    # 不是 textarea；必须用 execCommand('insertText') 走浏览器编辑管线，
    # React 才能注册，Generate 按钮才会从 disabled 变为可用。
    print("[6/9] 粘贴 prompt...")
    filled = fill_vids_prompt(prompt, "视频 prompt")
    if not filled:
        # 兜底：旧通用 JS 方式
        print("  Vids 专用方式失败，尝试通用 JS 直填...")
        filled = fill_js_fallback(prompt, "视频 prompt (JS)")
    if not filled:
        print("  未找到 prompt 输入框")
        return 1

    # 7. 点击生成（原子操作）
    # 2026-10-09 修复：按钮文本就是 "Generate"（无 video 后缀）。
    # 旧正则 ^Generate$ 要求整行精确匹配，snapshot 行如
    # `- button "Generate" [ref=e18394]` 永远匹配不上。
    # 新模式精确匹配独立 Generate 按钮，排除 "Generate an..." 系列。
    print("[7/9] 开始生成...")
    if not click_smart(r'button "Generate" \[', "生成按钮"):
        print("  未找到生成按钮")
        s = snap()
        for r, line in find_all_refs(r'button', s)[:15]:
            print(f"    {r}: {line}")
        return 1
    print("  生成中，等待 90 秒...")
    time.sleep(90)

    # 8. 等待生成完成（轮询，最多 8 分钟）
    # Bug 1 修复（2026-10-09）：旧逻辑误报——快照常驻文本 "Generation settings: Omni, 720p"
    # 命中 `720p`、"Play (Ctrl+F5)" 按钮命中 `play`、menubar 的 menuitem "Insert" 命中 `Insert`，
    # 导致生成仅 30 秒就判"完成"，实际服务端渲染需 2-4 分钟。
    # 唯一可靠信号：AI 面板内出现 button "Generated video:（注意冒号，文本含 prompt 前缀）。
    print("[8/9] 等待生成完成...")
    generated = False
    for i in range(16):  # 16 x 30s = 8 分钟
        time.sleep(30)
        s = snap()
        if re.search(r'button "Generated video:', s):
            print(f"  生成完成 (等待 {(i+1)*30}s)")
            generated = True
            break
        else:
            print(f"  生成中... ({(i+1)*30}s)")
    if not generated:
        print("  警告: 8 分钟后仍未确认生成完成，继续尝试下载...")
    # 清理旧的下载文件，避免捡到上次的
    subprocess.run(SSH_BASE + ["rm", "-f", "/root/Downloads/*.mp4"],
                   capture_output=True, timeout=15)

    # 9. 直接下载 AI 原片（JS 注入，不走时间线渲染）
    # Bug 4 修复（2026-10-09 实测）：File > Download > MP4 渲染的是项目时间线
    # （慢，且受项目画布横/竖屏影响）；curl 原片 URL 被 Google 登录墙挡。
    # 可靠方案：页面 JS 注入 <a href=videoUrl download> 并 click，
    # 浏览器用自带 auth cookie 下载到 /root/Downloads/，720x1280 原片完整可用。
    print("[9/9] 直接下载 AI 原片（JS 注入）...")
    dl_js = """(function(){
      var vids = Array.from(document.querySelectorAll('video'))
        .filter(function(v){ return v.offsetParent !== null && (v.videoWidth||0) >= 480; });
      if (!vids.length) return 'NOVIDEO';
      vids.sort(function(a,b){ return (b.videoWidth*b.videoHeight)-(a.videoWidth*a.videoHeight); });
      var v = vids[0];
      var url = v.currentSrc || v.src;
      if (!url) return 'NOSRC';
      var a = document.createElement('a');
      a.href = url; a.download = 'vids_ai_clip.mp4';
      document.body.appendChild(a); a.click(); a.remove();
      return 'TRIGGERED:' + v.videoWidth + 'x' + v.videoHeight;
    })()"""
    dl_ok = False
    for attempt in range(3):
        out = js_eval(dl_js).strip().strip('"').strip("'")
        print(f"  JS 下载 (尝试 {attempt+1}/3): {out[:80]}")
        if out.startswith("TRIGGERED:"):
            dl_ok = True
            dims = out.split("TRIGGERED:")[1]
            print(f"  原片尺寸: {dims}")
            break
        time.sleep(5)
    if not dl_ok:
        print("  JS 下载失败（未找到预览视频元素），本次生成作废")
        return 1
    # 轮询等文件出现且大小稳定
    vm_file = ""
    last_size = 0
    stable_count = 0
    for w in range(20):  # 最多 10 分钟
        time.sleep(30)
        r = subprocess.run(
            SSH_BASE + ["bash", "-c",
                        "\"ls -t /root/Downloads/*.mp4 2>/dev/null | head -1\""],
            capture_output=True, text=True, timeout=15)
        cand = r.stdout.strip()
        if cand:
            r2 = subprocess.run(
                SSH_BASE + ["stat", "-c", "%s", cand],
                capture_output=True, text=True, timeout=15)
            try:
                size = int(r2.stdout.strip())
            except ValueError:
                size = 0
            if size > 100000:
                print(f"  下载中... ({(w+1)*30}s, {size//1024}KB)")
                if size == last_size:
                    stable_count += 1
                    if stable_count >= 2:
                        vm_file = cand
                        print("  下载完成（大小稳定）")
                        break
                else:
                    stable_count = 0
                last_size = size
            else:
                print(f"  等待文件增长... ({(w+1)*30}s, {size//1024}KB)")
        else:
            print(f"  等待文件出现... ({(w+1)*30}s)")
    else:
        print("  等待超时")
    if not vm_file:
        print("  未找到下载完成的 mp4 文件")
        return 1


    # 10. 回传视频到本机（vm_file 已由 JS 下载轮询确认为本次文件）
    print("\n[10/10] 回传视频到本机...")
    print(f"  VM 文件: {vm_file}")
    vm_mp4 = vm_file

    if not vm_mp4:
        print("  未找到本次下载的 mp4 文件（15 分钟内新建的）")
        return 1

    print(f"  VM 文件: {vm_mp4}")
    os.makedirs(args.out_dir, exist_ok=True)
    local_path = os.path.join(args.out_dir, f"vids_{args.job_id}.mp4")
    scp_cmd = [
        "scp", "-i", os.path.expanduser("~/.ssh/id_ed25519"),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ProxyCommand=nc -X connect -x 198.19.0.1:3128 %h %p",
        f"{VM_HOST}:{vm_mp4}", local_path,
    ]
    r = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(local_path):
        print(f"  SCP 失败: {r.stderr[:200]}")
        return 1

    size = os.path.getsize(local_path)
    print(f"  回传成功: {local_path} ({size//1024}KB)")

    # ffprobe 验证
    print("\n[验证] ffprobe 检查...")
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=width,height", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1", local_path],
        capture_output=True, text=True, timeout=30)
    print(f"  {r.stdout.strip().replace(chr(10), ', ')}")

    print(f"\n=== 完成: {args.job_id} ===")
    print(f"视频: {local_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
