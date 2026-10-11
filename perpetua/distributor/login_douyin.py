#!/usr/bin/env python3
"""抖音扫码登录助手：生成登录二维码 -> 用户用抖音APP扫码 -> cookie 存到 cookies/douyin/account.json（600）。"""
import asyncio
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(BASE, "vendor")
sys.path.insert(0, VENDOR)

COOKIE = os.path.join(BASE, "cookies", "douyin", "account.json")


async def main():
    os.makedirs(os.path.dirname(COOKIE), exist_ok=True)
    from uploader.douyin_uploader.main import douyin_cookie_gen
    print("正在打开抖音创作者中心登录页，请用【档案管理员】账号的抖音APP扫码...")
    result = await douyin_cookie_gen(COOKIE, headless=True)
    print("登录结果:", result.get("status"), "-", result.get("message"))
    if result.get("success"):
        os.chmod(COOKIE, 0o600)
        print("cookie 已保存: %s（600）" % COOKIE)
    else:
        print("登录未完成，二维码可能过期，重跑本脚本即可。")


if __name__ == "__main__":
    asyncio.run(main())
