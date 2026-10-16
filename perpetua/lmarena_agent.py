#!/usr/bin/env python3
"""LMArena Agent 模式自动化（经 SSH 调 VM 上的 agent-browser）。

用户 2026-10-09 要求：arena agent 接入管线，用 agent-browser 全自动驱动。
已验证（2026-10-09）：click 聚焦 + keyboard type / eval execCommand('insertText')
两种手法均可；"Reply with exactly: OK" 端到端 45s 跑通。

流程：open 新鲜会话（绝不进旧会话）→ eval 插入 prompt → click Send →
  等新 /agent/<id> → 轮询等 agent 完成 → 抓取输出文本。

用法：
  python3 lmarena_agent.py --prompt-file xxx.txt [--timeout 1500] [--json]
      [--out out.md]

退出码：0=拿到输出，1=失败。

注意：
  - 每次调研真实消耗 LMArena 额度，调用方负责限频（建议每周一次或按需）。
  - 用户隔离偏好：每次从干净落地页开始，不复用任何旧会话/用户本地链接
    （用户本地建的会话在 VM 侧打不开，只能 VM 侧自建）。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time

VM_HOST = "192.166.82.123"
VM_USER = "root"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
CDP = "http://127.0.0.1:9222"
AGENT_BROWSER = "/usr/bin/agent-browser"
LANDING = "https://arena.ai/agent"

SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", f"ProxyCommand={PROXY}",
    f"{VM_USER}@{VM_HOST}",
]


def ab(args, timeout=30):
    cmd = SSH_BASE + [AGENT_BROWSER, "--cdp", CDP] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode


def js(expr, timeout=30):
    """在页面 JS 上下文求值，返回 stdout。表达式经 base64 过 SSH，避免 shell 转义问题。"""
    b64 = base64.b64encode(expr.encode("utf-8")).decode("ascii")
    vm_py = (
        "python3 -c \""
        "import base64,subprocess;"
        f"e=base64.b64decode('{b64}').decode('utf-8');"
        f"r=subprocess.run(['{AGENT_BROWSER}','--cdp','{CDP}','eval',e],"
        "capture_output=True,text=True,timeout=60);"
        "print(r.stdout,end='');"
        "\""
    )
    r = subprocess.run(SSH_BASE + [vm_py], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"eval 失败: {r.stderr[:200]}")
    raw = r.stdout.strip()
    # agent-browser 的 eval 按 JSON 编码返回值（字符串带引号），解码一层
    try:
        val = json.loads(raw)
        if isinstance(val, str):
            return val
    except (json.JSONDecodeError, ValueError):
        pass
    return raw


def find_ref(snap, keyword):
    for line in snap.split("\n"):
        if keyword.lower() in line.lower():
            m = re.search(r"\[ref=(e\d+)\]", line)
            if m:
                return m.group(1)
    return None


def wait_url_change(old, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            href = js("(function(){return location.href})()")
        except RuntimeError:
            href = ""
        if href and href != old and "/agent/" in href and href.rstrip("/") != LANDING.rstrip("/"):
            return href
        time.sleep(5)
    return None


def wait_completion(timeout):
    """agent 输出稳定即判完成：连续 3 次（90s）正文长度不变。"""
    last_len, stable = -1, 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            n = int(js("(function(){return document.body.innerText.length})()") or 0)
        except (RuntimeError, ValueError):
            n = 0
        if n == last_len and n > 0:
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
        last_len = n
        time.sleep(30)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    prompt = open(a.prompt_file, encoding="utf-8").read().strip()
    if not prompt:
        print("prompt 为空", file=sys.stderr)
        sys.exit(1)

    log = []

    def say(m):
        log.append(m)
        print(m, file=sys.stderr)

    # 1. 打开新鲜会话
    ab(["open", LANDING], timeout=60)
    time.sleep(4)
    href = js("(function(){return location.href})()")
    if "/agent/" in href and href.rstrip("/") != LANDING.rstrip("/"):
        # 落在了旧会话上，强制回落地页
        say(f"警告：落在了旧会话 {href}，强制回干净落地页")
        ab(["open", LANDING], timeout=60)
        time.sleep(4)
        href = js("(function(){return location.href})()")
    say(f"落地页：{href}")

    # 1b. 激活 arena tab（2026-10-16 修）：9222 浏览器多 tab 共享（FB/Gemini/arena），
    #     后台 tab 的 React 被节流、ProseMirror 编辑器不挂载 → NO_EDITOR。
    #     经 CDP 激活 arena.ai/agent 的 page target，并关闭同 URL 的重复 tab。
    def _activate_arena_tab():
        try:
            r = subprocess.run(SSH_BASE + ["curl", "-s", "http://127.0.0.1:9222/json/list"],
                               capture_output=True, text=True, timeout=30)
            targets = [t for t in json.loads(r.stdout)
                       if t.get("type") == "page" and "arena.ai/agent" in (t.get("url") or "")]
            if not targets:
                say("激活 arena tab：未找到 arena.ai/agent 的 page target")
                return False
            first = targets[0]["id"]
            subprocess.run(SSH_BASE + ["curl", "-s", "-X", "POST",
                                       "http://127.0.0.1:9222/json/activate/%s" % first],
                           capture_output=True, text=True, timeout=30)
            for t in targets[1:]:
                # 只关停留在落地页的重复 tab，不碰 /agent/<id> 会话
                if (t.get("url") or "").rstrip("/") == LANDING.rstrip("/"):
                    subprocess.run(SSH_BASE + ["curl", "-s", "-X", "PUT",
                                               "http://127.0.0.1:9222/json/close/%s" % t["id"]],
                                   capture_output=True, text=True, timeout=30)
            say("已激活 arena tab（%d 个，关闭 %d 个重复）" % (len(targets), max(0, len(targets) - 1)))
            return True
        except Exception as e:
            say("激活 arena tab 异常: %s" % str(e)[:100])
            return False

    _activate_arena_tab()
    time.sleep(3)

    # 2. 等编辑器挂载 + eval 插入 prompt（长文本瞬间插入，比逐字快）
    #    2026-10-16 修：真根因是后台 tab 的 React 被浏览器节流、ProseMirror 不挂载
    #    （9222 与 FB/Gemini 自动化共享），非单纯懒加载。step 1b 已激活 tab，
    #    这里再轮询确认（单次 eval 必须 <25s，agent-browser CDP 超时上限）。
    #    插入幂等：编辑器已有文本则视为已插入。
    b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    ins = ""
    editor_state = "NONE"
    for attempt in range(20):
        try:
            editor_state = js(
                "(function(){var el=document.querySelector('.tiptap.ProseMirror,[contenteditable]');"
                "return el?(el.innerText.trim().length>0?'HAS_TEXT':'EMPTY'):'NONE'})()",
                timeout=30)
        except RuntimeError as e:
            say("找编辑器尝试 %d 异常: %s" % (attempt + 1, str(e)[:80]))
            editor_state = "NONE"
        if editor_state in ("HAS_TEXT", "EMPTY"):
            say("找编辑器尝试 %d: %s" % (attempt + 1, editor_state))
            break
        if attempt == 2:
            # 点一次 composer，触发编辑器挂载
            try:
                js("(function(){var els=Array.from(document.querySelectorAll('button'));"
                   "var send=els.find(function(b){return /send message/i.test(b.getAttribute('aria-label')||'')});"
                   "if(!send)return 'NOSEND';var r=send.getBoundingClientRect();"
                   "var c=document.elementFromPoint(r.x-300,r.y-20);"
                   "if(!c)return 'NOEL';c.click();return 'CLICKED';})()",
                   timeout=30)
            except RuntimeError:
                pass
        time.sleep(5)
    if editor_state == "HAS_TEXT":
        ins = "INSERTED:already"
    elif editor_state == "EMPTY":
        expr = (
            "(function(){var bin=atob('" + b64 + "');"
            "var bytes=Uint8Array.from(bin,function(c){return c.charCodeAt(0)});"
            "var t=new TextDecoder().decode(bytes);"
            "var el=document.querySelector('.tiptap.ProseMirror,[contenteditable]');"
            "if(!el)return 'NO_EDITOR';el.focus();"
            "if(el.innerText.trim().length===0)document.execCommand('insertText',false,t);"
            "return 'INSERTED:'+el.innerText.length})()"
        )
        try:
            ins = js(expr, timeout=30)
        except RuntimeError as e:
            say("插入异常: %s" % str(e)[:80])
            ins = ""
    say("插入结果：%s" % ins[:60])
    if not ins.startswith("INSERTED:"):
        print(json.dumps({"ok": False, "error": "输入框插入失败", "log": log},
                         ensure_ascii=False))
        sys.exit(1)

    # 3. 点 Send（2026-10-16 修：此页 a11y 快照几乎为空，snapshot 取不到 ref，
    #    改用 DOM 直接点 aria-label="Send message" 的按钮）
    send_clicked = js(
        "(function(){var els=Array.from(document.querySelectorAll('button'));"
        "var m=els.find(function(b){return /send message/i.test(b.getAttribute('aria-label')||'')});"
        "if(!m)return 'NOSEND';m.click();return 'SENT_CLICKED';})()",
        timeout=30)
    say("点击 Send：%s" % send_clicked[:40])
    if send_clicked != "SENT_CLICKED":
        print(json.dumps({"ok": False, "error": "找不到 Send 按钮", "log": log},
                         ensure_ascii=False))
        sys.exit(1)
    say("已点击 Send")

    # 4. 等新会话 URL
    new_url = wait_url_change(href, timeout=120)
    if not new_url:
        print(json.dumps({"ok": False, "error": "发送后未跳转到新会话", "log": log},
                         ensure_ascii=False))
        sys.exit(1)
    say(f"新会话：{new_url}")

    # 5. 等 agent 完成
    done = wait_completion(a.timeout)
    say(f"完成：{done}")

    # 6. 抓输出
    text = js("(function(){return document.body.innerText})()", timeout=60)
    result = {"ok": True, "session_url": new_url, "completed": done,
              "text": text, "log": log}
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text)
        say(f"输出已写入 {a.out}")
    if a.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(text)
    sys.exit(0)


if __name__ == "__main__":
    main()
