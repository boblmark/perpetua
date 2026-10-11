#!/usr/bin/env python3
"""抖音扫码登录（带二维码回调）：二维码存到固定路径，登录成功后 cookie 落盘。"""
import asyncio
import os
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "vendor"))

COOKIE = os.path.join(BASE, "cookies", "douyin", "account.json")
QR_OUT = "/home/hatch/data/douyin/login_qrcode.png"
QR_READY = "/home/hatch/data/douyin/login_qrcode.ready"


def on_qrcode(image_path):
    try:
        shutil.copy(image_path, QR_OUT)
        open(QR_READY, "w").write("ready")
        print("二维码已就绪: %s" % QR_OUT, flush=True)
    except Exception as e:
        print("二维码回调失败: %s" % e, flush=True)


async def main():
    os.makedirs(os.path.dirname(COOKIE), exist_ok=True)
    for f in (QR_READY,):
        try:
            os.remove(f)
        except OSError:
            pass
    # patchright 不读系统代理，在类级别注入 egress 代理（带认证）
    import urllib.parse
    from patchright.async_api import BrowserType

    _orig_launch = BrowserType.launch

    async def _launch_with_proxy(self, *a, **kw):
        purl = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if purl and "proxy" not in kw:
            u = urllib.parse.urlparse(purl)
            kw["proxy"] = {
                "server": f"{u.scheme}://{u.hostname}:{u.port}",
                "username": urllib.parse.unquote(u.username or ""),
                "password": urllib.parse.unquote(u.password or ""),
            }
        return await _orig_launch(self, *a, **kw)

    BrowserType.launch = _launch_with_proxy

    from uploader.douyin_uploader.main import douyin_cookie_gen
    print("正在打开抖音创作者中心，请稍候...", flush=True)
    result = await douyin_cookie_gen(
        COOKIE, qrcode_callback=on_qrcode,
        poll_interval=3, max_checks=40, headless=True)
    print("登录结果: %s - %s" % (result.get("status"), result.get("message")), flush=True)
    if result.get("success"):
        os.chmod(COOKIE, 0o600)
        print("COOKIE_OK", flush=True)
    else:
        print("COOKIE_FAIL", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
