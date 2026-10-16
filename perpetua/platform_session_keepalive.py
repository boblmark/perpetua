#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八平台 session 保活：告警落盘 helper。

范围（2026-10-17 与 platform-session-keepalive cron body 对齐）：
抖音 / B站 / 小红书 / 快手 / YouTube / Facebook / TikTok / X。

架构说明（2026-10-11 实测结论）：
- browser.spawn_task 用的 Chromium profile 是 server-side（runtime 托管），
  cookie 不落本机磁盘。本机能找到的 Cookies SQLite（ask_studio/browser_profile、
  chrome-for-testing 的 scoped_dir）都是空/近空的，不是任务实际用的 profile。
- 因此做不到"本机 curl + cookie"的登录态检查。登录态检查必须走浏览器任务
 （见 cron platform-session-keepalive 的 body），本脚本只负责把掉线告警
  写进 collab/inbox.json，格式与现有 urgent 通知一致。
- 只读、不登录、不发布、不修改任何平台状态。脚本内不出现任何密码/cookie 明文。

用法：
  python3 platform_session_keepalive.py suspect --platform 抖音 --detail "创作者中心跳登录页"
  # worker 只能报 suspect（疑似掉线），由主 agent 用自己派发的浏览器任务复核后
  # 再定论。原因：2026-10-11 实测 worker 派发的浏览器任务会被路由到无登录态槽位，
  # 出现过"四平台同时掉线"的误报，而主 agent 派发 6/6 正常。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

INBOX = "/home/hatch/data/collab/inbox.json"

RECOVERY = {
    "B站": "有密码登录：保险库已入库则可自动重登；若密码卡未填，需用户先填保险库密码卡",
    "抖音": "无密码登录，需用户用抖音 App 扫码或手机验证码重登",
    "快手": "无密码登录，需用户扫码/手机验证码重登",
    "小红书": "无密码登录选项，需用户手机验证码或 App 扫码重登",
    "YouTube": "保险库有 google.com 登录，主 agent 可经批准自动重登",
    "Facebook": "保险库有 facebook.com 登录，主 agent 可经批准自动重登",
    "TikTok": "Google SSO 重登",
    "X": "保险库 x.com 用户名密码直接登录，不要走 Google（Google SSO 从本浏览器 consistently 报 unexpected error）",
}

BASELINES = {
    "抖音": "创作者中心 dashboard，抖音号 43833679345（2026-10-11 19:30 主 agent 复核在登录态）",
    "B站": "主站 avatar + 创作中心 dashboard，昵称 bili_33246131808（2026-10-11 19:30 主 agent 复核在登录态）",
    "小红书": "创作服务平台 dashboard，昵称 档案管理员（2026-10-11 19:30 主 agent 复核在登录态）",
    "快手": "创作者服务平台 dashboard，账号正常（2026-10-11 13:00 实测在登录态；19:31 浏览器任务成功提交视频待审核，账号可用）",
    "YouTube": "YouTube Studio dashboard，Ask Studio 面板可用（2026-10-11 主 agent 复核在登录态）",
    "Facebook": "个人账号 Mark Bobl，名下有 Page \"Mark Bobl - Karen vs AI\"（2026-10-11 主 agent 复核在登录态）",
    "TikTok": "账号 @cgb20250（2026-10-11 主 agent 复核在登录态）",
    "X": "@cgb2025194995，显示名 Cyber Detective 2026（2026-10-11 主 agent 复核在登录态）",
}


def load_inbox():
    with open(INBOX, "r", encoding="utf-8") as f:
        return json.load(f)


def save_inbox(d):
    # v2.0.0 KILL3: 原子写
    sys.path.insert(0, "/home/hatch/data/perpetua")
    from atomic_json import atomic_write
    atomic_write(INBOX, d)


def write_notice(ntype, title, message, nid):
    sys.path.insert(0, "/home/hatch/data/perpetua")
    import inbox as inbox_gw
    now = datetime.now(timezone.utc).isoformat()
    notice = {
        "id": nid,
        "type": ntype,
        "for": "dash_main",
        "read": False,
        "created": now,
        "title": title,
        "message": message,
    }
    inbox_gw.append_notice(notice)
    print(json.dumps({"written": nid}, ensure_ascii=False))


def suspect(platforms, detail):
    now = datetime.now(timezone.utc).isoformat()
    names = "、".join(platforms)
    lines = [
        f"疑似掉线平台（worker 浏览器任务回报，未经主 agent 复核）：{names}",
        f"检查时间（UTC）：{now}",
        f"页面所见：{detail}",
        "",
        "注意：2026-10-11 实测 worker 派发的浏览器任务可能被路由到无登录态槽位",
        "（当日出现过多平台同时掉线的误报，主 agent 亲测同期全部在登录态）。",
        "请主 agent 用自己派发的浏览器任务复核后再定论，定论前不要打扰用户。",
        "",
        "若复核确认真掉线，恢复方式：",
    ]
    for p in platforms:
        lines.append(f"- {p}：{RECOVERY.get(p, '需人工处理')}")
    nid = "session_suspect_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    write_notice("platform_session_logout_suspect",
                 f"疑似掉线待复核：{names}", "\n".join(lines), nid)


def alert(platforms, detail):
    # 保留给主 agent 复核确认后使用：定论掉线
    now = datetime.now(timezone.utc).isoformat()
    names = "、".join(platforms)
    lines = [
        f"掉线平台（已复核确认）：{names}",
        f"检查时间（UTC）：{now}",
        f"现象：{detail}",
        "",
        "恢复方式：",
    ]
    for p in platforms:
        lines.append(f"- {p}：{RECOVERY.get(p, '需人工处理')}")
        if p in BASELINES:
            lines.append(f"  上次正常基线：{BASELINES[p]}")
    nid = "session_logout_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    write_notice("platform_session_logout",
                 f"创作平台掉线：{names}（需恢复登录）", "\n".join(lines), nid)


def clear(notice_id, detail):
    """复核完成后关闭疑似掉线告警。

    2026-10-11 19:31 新增：主 agent 用 clear 失败——脚本没有这个子命令，
    导致已复核确认为误报的 suspect 仍挂在 inbox 里。clear 只做一件事：
    给指定 notice 写 resolved + 标 read=True，不改其他内容。
    """
    d = load_inbox()
    target = None
    for n in d.get("notices", []):
        if n.get("id") == notice_id:
            target = n
            break
    if target is None:
        print(json.dumps({"ok": False, "error": f"notice {notice_id} not found"},
                         ensure_ascii=False))
        sys.exit(1)
    if target.get("resolved"):
        print(json.dumps({"ok": False, "error": "already resolved",
                          "resolved": target["resolved"]}, ensure_ascii=False))
        sys.exit(1)
    now = datetime.now(timezone.utc).isoformat()
    target["resolved"] = f"{detail}（closed {now}）"
    target["read"] = True
    save_inbox(d)
    print(json.dumps({"ok": True, "closed": notice_id}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("suspect")
    a.add_argument("--platform", action="append", required=True,
                   choices=["抖音", "B站", "小红书", "快手",
                            "YouTube", "Facebook", "TikTok", "X"])
    a.add_argument("--detail", default="")
    b = sub.add_parser("alert")  # 主 agent 复核确认后用
    b.add_argument("--platform", action="append", required=True,
                   choices=["抖音", "B站", "小红书", "快手",
                            "YouTube", "Facebook", "TikTok", "X"])
    b.add_argument("--detail", default="")
    c = sub.add_parser("clear")  # 复核确认误报/真掉线已恢复后关闭 suspect
    c.add_argument("--notice-id", required=True)
    c.add_argument("--detail", required=True)
    args = ap.parse_args()
    if args.cmd == "suspect":
        # 去重保序
        seen = list(dict.fromkeys(args.platform))
        suspect(seen, args.detail)
    elif args.cmd == "alert":
        seen = list(dict.fromkeys(args.platform))
        alert(seen, args.detail)
    elif args.cmd == "clear":
        clear(args.notice_id, args.detail)


if __name__ == "__main__":
    main()
