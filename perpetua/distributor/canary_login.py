#!/usr/bin/env python3
"""金丝雀专用：走 egress 代理启动浏览器，连 CDP 跑抖音扫码登录。
二维码回调把最新二维码复制到固定路径，方便发给用户扫。"""
import asyncio, os, shutil, sys

BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, "vendor")
sys.path.insert(0, VENDOR)
sys.path.insert(0, BASE)

COOKIE = os.path.join(BASE, "cookies", "douyin", "account.json")
QR_FIXED = "/tmp/douyin_login_qr.png"
# 经本地 socat 转发（127.0.0.1:3129 -> hatch-egress-proxy:3128）：
# Chromium 直连代理主机名会隧道失败（IPv6 解析问题），经本地转发则正常。
PROXY = "http://127.0.0.1:3129"


def qr_cb(payload):
    img = payload.get("image_path") or payload.get("image_data_url", "")
    try:
        if img and os.path.exists(str(img)):
            shutil.copy(str(img), QR_FIXED)
            print("QR_CB: 二维码已更新 ->", QR_FIXED, flush=True)
    except Exception as e:
        print("QR_CB 异常:", e, flush=True)


def _proxy_cfg():
    """走本地 socat 转发，无需认证（转发层已处理上游）。"""
    return {"server": PROXY}


async def main():
    from patchright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True, channel="chromium",
            proxy=_proxy_cfg(),
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--ignore-certificate-errors",
                  "--remote-debugging-port=19222"],
        )
        print("浏览器已启动（走代理），CDP 端口 19222", flush=True)
        # 给 CDP 一点时间就绪
        await asyncio.sleep(2)
        from uploader.douyin_uploader.main import douyin_cookie_gen
        result = await douyin_cookie_gen(
            COOKIE, qrcode_callback=qr_cb, headless=True,
            cdp_url="http://127.0.0.1:19222",
            poll_interval=2, max_checks=900,  # 30 分钟等待，二维码过期自动刷新
        )
        print("登录结果:", result.get("status"), "-", result.get("message"), flush=True)
        if result.get("success"):
            os.chmod(COOKIE, 0o600)
            print("cookie 已保存 600:", COOKIE, flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
