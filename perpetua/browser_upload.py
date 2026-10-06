#!/usr/bin/env python3
"""Perpetua 浏览器上传备用通道（MoneyPrinterV2 作业）

当 YouTube Data API 上传失败（配额/token/网络）时，
用 Playwright 自动化 studio.youtube.com 上传。

用法：
  python3 browser_upload.py <video.mp4> "<标题>" "<描述>"

注意：首次运行需要手动登录一次，cookie 会持久化到
/home/hatch/data/perpetua/browser_profile/
"""
import json, os, sys, time
from pathlib import Path

BASE = "/home/hatch/data/perpetua"
PROFILE_DIR = f"{BASE}/browser_profile"
LOG_FILE = f"{BASE}/health/browser_upload.log"

def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps({"ts": ts, "msg": msg}) + "\n")
    print(msg)

def upload(video_path, title, description=""):
    from playwright.sync_api import sync_playwright

    video_path = str(Path(video_path).resolve())
    if not os.path.exists(video_path):
        return {"ok": False, "error": f"文件不存在: {video_path}"}

    os.makedirs(PROFILE_DIR, exist_ok=True)
    result = {"ok": False}

    # 沙箱代理：经本地转发代理（local_proxy.py :18888）
    try:
        import socket as _sock
        _s = _sock.socket()
        _s.connect(("127.0.0.1", 18888))
        _s.close()
    except Exception:
        import subprocess as _sp
        _sp.Popen(["python3", "/home/hatch/data/perpetua/deploy/local_proxy.py"],
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
        time.sleep(2)
    chrome_path = "/home/hatch/.cache/ms-playwright/chrome-linux64-manual/chrome-linux64/chrome"
    launch_kwargs = {
        "headless": True,
        "proxy": {"server": "http://127.0.0.1:18888"},
        "args": ["--disable-blink-features=AutomationControlled",
                 "--ignore-certificate-errors"],
    }
    if os.path.exists(chrome_path):
        launch_kwargs["executable_path"] = chrome_path

    with sync_playwright() as p:
        # 持久化 profile，登录态保留
        browser = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            **launch_kwargs,
        )
        page = browser.new_page()

        try:
            log(f"打开 YouTube Studio...")
            page.goto("https://studio.youtube.com", timeout=60000)
            time.sleep(3)

            # 检查是否需要登录
            if "accounts.google.com" in page.url:
                log("需要登录！请先手动运行一次 with headless=False 登录")
                result = {"ok": False, "error": "need_login",
                          "hint": "首次需手动登录，cookie 会保存"}
                browser.close()
                return result

            # 点 Create → Upload videos
            log("点击上传...")
            page.click('tp-yt-iron-icon[icon="add"]', timeout=15000)
            time.sleep(1)
            # 上传按钮
            page.click('text="Upload videos"', timeout=10000)
            time.sleep(2)

            # 选择文件
            log(f"选择文件: {video_path}")
            page.set_input_files('input[type="file"]', video_path)
            time.sleep(5)

            # 填标题
            log("填写标题...")
            title_box = page.locator('div[aria-label="Title"]').first
            # 清空默认标题
            title_box.click()
            page.keyboard.press("Control+a")
            page.keyboard.type(title[:100])  # YouTube 标题上限 100
            time.sleep(1)

            # 填描述
            if description:
                desc_box = page.locator('div[aria-label="Description"]').first
                desc_box.click()
                page.keyboard.press("Control+a")
                page.keyboard.type(description[:5000])
                time.sleep(1)

            # Shorts 不需要缩略图；点 Next 到可见性
            for i in range(3):
                log(f"下一步 {i+1}/3...")
                page.click('button:has-text("Next")', timeout=10000)
                time.sleep(2)

            # 设为公开
            log("设为公开...")
            try:
                page.click('tp-yt-paper-radio-button[name="PUBLIC"]', timeout=10000)
            except Exception:
                log("公开选项未找到，保持默认")

            # 发布
            log("发布...")
            page.click('button:has-text("Publish")', timeout=10000)
            time.sleep(5)

            # 取视频链接
            try:
                link = page.locator('a[href*="youtu.be"], a[href*="youtube.com/watch"]').first
                url = link.get_attribute("href")
            except Exception:
                url = ""

            result = {"ok": True, "method": "browser", "url": url}
            log(f"✅ 浏览器上传成功: {url}")

        except Exception as e:
            result = {"ok": False, "error": str(e)[:200]}
            log(f"❌ 浏览器上传失败: {e}")
        finally:
            browser.close()

    return result

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: browser_upload.py <video.mp4> \"<标题>\" \"<描述>\"")
        sys.exit(1)
    r = upload(sys.argv[1], sys.argv[2],
               sys.argv[3] if len(sys.argv) > 3 else "")
    print(json.dumps(r, ensure_ascii=False, indent=2))
