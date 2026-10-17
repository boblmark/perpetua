#!/usr/bin/env python3
"""geminigen cgb2025 OAuth 自动重试（温和版，2026-10-15）

背景：VPS 上 geminigen 的 cgb2025 会话过期，今早重登时误选成 Mark Bobl（0 额度）。
切回 cgb2025（6365 额度）时 Google OAuth 两次弹 "Verify it's you" reCAPTCHA，
且不提供其他验证方式（无手机验证、无邮箱验证），geminigen 又只有 Google 登录一种方式。

策略：每 6 小时试一次正常登录流程。Google 风控分会波动，今早 Mark Bobl 就没被拦。
铁律：绝不尝试解任何 CAPTCHA，见到 challenge 页立刻放弃，回 geminigen 首页等下轮。
成功时在 handoff 报告，由主 agent 负责把 9222 也切过去并通知用户。

输出：ALREADY_CGB2025 / SUCCESS / CHALLENGED / NO_SIGNIN_FOUND 等状态行
"""
import subprocess
import time
import os
import sys

VM_HOST = "192.166.82.123"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
SSH_BASE = [
    "ssh", "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", f"ProxyCommand={PROXY}",
    f"root@{VM_HOST}",
]
ENV = "export DISPLAY=:99 XAUTHORITY=/etc/Xvfb.auth"
AB = "agent-browser --cdp 9344"


def vps(shell_cmd, timeout=90):
    r = subprocess.run(
        SSH_BASE + [ENV + "; " + shell_cmd],  # 2026-10-17 修：export 后必须用分号隔断，否则 agent-browser 被当成 export 参数（not a valid identifier），此前所有轮次都是空跑
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout.strip()


def js_click_by_text(tag, text):
    """用 JS 按精确文本点元素，返回是否找到"""
    js = (
        "(function(){var els=[...document.querySelectorAll('%s')];"
        "var el=els.find(e=>e.textContent.trim()==='%s');"
        "if(el){el.click();return 'CLICKED';}return 'NOTFOUND';})()" % (tag, text)
    )
    import base64
    b64 = base64.b64encode(js.encode()).decode()
    out = vps(
        f"python3 -c \"import base64,subprocess;"
        f"j=base64.b64decode('{b64}').decode();"
        f"r=subprocess.run(['{AB}'.split()+['eval',j],capture_output=True,text=True,timeout=30);"
        f"print(r.stdout.strip().strip(chr(34)))\""
    )
    return "CLICKED" in out


def js_click_account():
    js = (
        "(function(){var els=[...document.querySelectorAll('a')];"
        "var el=els.find(e=>e.textContent.includes('cgb479023@gmail.com'));"
        "if(el){el.click();return 'CLICKED';}return 'NOTFOUND';})()"
    )
    import base64
    b64 = base64.b64encode(js.encode()).decode()
    out = vps(
        f"python3 -c \"import base64,subprocess;"
        f"j=base64.b64decode('{b64}').decode();"
        f"r=subprocess.run(['{AB}'.split()+['eval',j],capture_output=True,text=True,timeout=30);"
        f"print(r.stdout.strip().strip(chr(34)))\""
    )
    return "CLICKED" in out


def main():
    vps(f"{AB} open https://geminigen.link > /dev/null 2>&1")
    # header 会话态异步渲染：轮询最多 ~30s，等 avatar 或 Sign In 稳定后再判定
    # （2026-10-17 实测：6s 快照常撞到 "Sign In" 链接先渲染、avatar 后替换的中间态，
    #  导致已登录的 cgb2025 会话被误判为 NO_SIGNIN_FOUND）
    snap = ""
    settled_signin = False
    for _ in range(6):
        time.sleep(5)
        snap = vps(f"{AB} snapshot 2>&1")
        has_avatar = "cgb2025" in snap
        has_signin = "sign in" in snap.lower()
        if has_avatar and not has_signin:
            # 已是 cgb2025 登录态（Google 头像 + 全站无 Sign In 入口）
            print("ALREADY_CGB2025")
            return
        if has_signin:
            settled_signin = True
            break
    if not settled_signin and "cgb2025" not in snap:
        # 30s 后既无 avatar 也无 Sign In：页面异常，保持旧行为（尝试点击，失败即 NO_SIGNIN_FOUND）
        pass

    if not js_click_by_text("button", "Sign In"):
        print("NO_SIGNIN_FOUND")
        return
    time.sleep(4)
    if not js_click_by_text("button", "Sign in with Google"):
        print("NO_GOOGLE_BTN")
        return
    time.sleep(8)
    if not js_click_account():
        print("NO_ACCOUNT_CHOOSER")
        return
    time.sleep(10)

    url = vps(f"{AB} eval 'location.href' 2>&1").strip().strip('"')
    if "challenge" in url or "recaptcha" in url:
        # 见到验证页：放弃，回首页，不碰验证码
        vps(f"{AB} open https://geminigen.link > /dev/null 2>&1")
        print("CHALLENGED")
        return
    if "geminigen.link" in url:
        time.sleep(3)
        snap = vps(f"{AB} snapshot 2>&1")
        if "cgb2025" in snap:
            print("SUCCESS")
            return
    print("UNKNOWN_STATE:" + url[:80])


if __name__ == "__main__":
    main()
