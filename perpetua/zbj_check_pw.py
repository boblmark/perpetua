#!/usr/bin/env python3
"""猪八戒配额检查（独立脚本版）：用 Playwright 打开技能管理页，读取可入驻名额。
由 MCP 工具 check_zbj_quota 触发，Marvis 可随时调用。

前置：需先运行 python3 zbj_auth.py 完成猪八戒登录（保存登录态）。
"""
import json, os, re, sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

AUTH_STATE = "/home/hatch/data/perpetua/.zbj_auth_state.json"
URL = "https://fws.zbj.com/skill?jdy=1"
CHROME = "/home/hatch/.cache/ms-playwright/chrome-linux64-manual/chrome-linux64/chrome"

def _launch_kwargs():
    return {
        "headless": True,
        "executable_path": CHROME,
        "proxy": {"server": "http://127.0.0.1:18888"},
        "args": ["--ignore-certificate-errors", "--disable-blink-features=AutomationControlled"],
    }

def _ensure_proxy():
    import socket, time, subprocess
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", 18888))
        s.close()
        return True
    except Exception:
        pass
    subprocess.Popen(["python3", "/home/hatch/data/perpetua/deploy/local_proxy.py"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(2)
    return True

def main():
    if not os.path.exists(AUTH_STATE):
        print(json.dumps({"ok": False, "error": "未登录",
            "msg": f"需先运行 zbj_auth.py 完成登录（{AUTH_STATE} 不存在）"},
            ensure_ascii=False))
        return
    _ensure_proxy()
    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_kwargs())
        ctx = browser.new_context(storage_state=AUTH_STATE)
        page = ctx.new_page()
        try:
            page.goto(URL, timeout=60000)
            page.wait_for_timeout(5000)
            text = page.inner_text("body")
            # 匹配 "已入驻X个，还可入驻Y个" 或类似表述
            m = re.search(r"还可入驻\s*(\d+)\s*个", text)
            if not m:
                m = re.search(r"可入驻\s*(\d+)", text)
            if m:
                quota = int(m.group(1))
                print(json.dumps({"ok": True, "quota": quota,
                    "alert": quota > 0,
                    "msg": f"当前可入驻 {quota} 个技能" + ("，名额已恢复！" if quota > 0 else "")},
                    ensure_ascii=False))
            else:
                print(json.dumps({"ok": False, "error": "未找到名额信息",
                    "msg": "页面结构可能变化，需人工检查", "page_snippet": text[:500]},
                    ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)[:200]}, ensure_ascii=False))
        finally:
            browser.close()

if __name__ == "__main__":
    main()
