#!/usr/bin/env python3
"""xiaohongshu 雷达轮询器 —— STUB（Phase 3，D20261017-002）。

本平台只接自己账号的官方 OAuth 数据。用户尚未完成开放平台应用注册与授权，
脚本当前不采集任何数据。完整接入步骤见 phase3_design.md。
"""
import sys
STEPS = {
    "douyin": "open.douyin.com 注册开发者→创建应用→申请 video.list/video.data scope→本人扫码授权→client_key/secret 进保险库",
    "weixin_channels": "视频号助手授权管理→第三方授权或开放平台 appid/secret→凭据进保险库",
    "kuaishou": "open.kuaishou.com 注册→创建应用→内容开放权限→快手 App 扫码授权→app_id/app_secret 进保险库",
    "xiaohongshu": "专业号/企业号认证→open.xiaohongshu.com 创建应用→笔记数据权限（或蒲公英后台 CSV 导出）→凭据进保险库",
}
if __name__ == "__main__":
    print(f"[STUB] xiaohongshu: 等待用户完成 OAuth 接入。步骤：{STEPS['xiaohongshu']}")
    print("[STUB] 接入完成后实现真实轮询器（复用 radar_lib，platform='xiaohongshu'），再建 daily cron。")
    sys.exit(0)
