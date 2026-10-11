import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json

a1 = {
"heading": "AI Comedy Shorts Ideas",
"context": "trending: automated service chaos, car tech meltdowns, smart kiosk fails; audiences love escalating relatable everyday conflicts where obstinate characters meet unbothered overly-literal AI",
"concepts": [
{"title": "Karen Demands Store Manager But The AI Self Checkout Becomes The Boss",
"desc": "Retail Karen demands the manager after a scan error; the kiosk projects a smug hologram manager that audits her entire cart",
"why": "self-checkout/cashier drama consistently drives strong comments and debates over whether the AI or customer went too far"},
{"title": "Karen Tries To Tow A Smart Electric Car That Locks Its Own Tires",
"desc": "Enraged neighbor calls an illegal tow on a smart EV; autopilot activates evasive defense mode and outsmarts the tow driver",
"why": "smart vehicle defense and parking disputes are standout performers, high retention around dramatic visual payoffs"},
{"title": "Karen Argues With Fast Food AI Drive Thru That Translates Her Insults Into Compliments",
"desc": "Aggressive driver screams demands into the mic; the polite AI keeps interpreting every insult as custom menu modifications",
"why": "drive-thru bot mixups actively buzzing in short-form comedy; quick pacing, hilarious audio/dialogue contrast"}
]
}
a2 = {
"channel_stats": {"stayed_vs_swiped": "69.6%", "avg_view_percentage": "237.5%"},
"optimizations": [
"First 1.5s: top Shorts hook with clear physical stakes (81.8% stayed on parking-meter soak, 100% on gas-line soak). Start mid-motion/mid-argument; no slow title cards or pans. Bold high-contrast text <=5 words summarizing conflict; half of feed viewers scroll muted.",
"9-12 seconds: channel gets 150-200%+ APV on punchy compact Shorts. End on the punchline/instant-karma, cut within 0.5s of reaction shot for seamless loop. Pacing: 0-2s conflict, 3-7s AI reacts/retaliates, 8-10s karma + loop.",
"Instant physical karma: AI's immediate physical retaliation (soaked, towed, meters fighting back) significantly out-retains verbal dialogue or generic AI tests. Use relatable everyday tech that malfunctions/outsmarts Karen."
]
}
a3 = {"best_practices": [
"Zero-second hook: start mid high-tension action; bold readable first-frame premise text.",
"High APV: 10-15s Short at 150%+ retention beats a 45s Short with drop-off; seamless audio/visual loops prompt re-watches.",
"Engagement: relatable conflicts spark comments/shares; pinned comment with a dilemma question (e.g. 'Did the AI go too far here?').",
"Thumbnail & title: expressive frame + curiosity title; under 50 characters best on mobile."
]}

doc = {
"date": "2026-10-11", "task": "ask-studio-daily", "status": "ok",
"channel": "Karen vs AI | Unhinged AI Videos",
"login_note": "worker 5 连报登录死/需 2FA 均系误报；主 agent 浏览器任务首次导航直达 dashboard",
"questions": [
"What are the trending topics for AI comedy Shorts this week? Give me 3 specific video concepts for my channel 'Mark Bobl | Karen vs AI'.",
"What should I optimize in my Shorts this week to get more Shorts feed distribution? Be specific.",
"Any YouTube algorithm updates or best practices for Shorts I should know about right now?"
],
"answers": [a1, a2, a3]
}
fp = "/home/hatch/data/ask_studio/2026-10-11.json"
atomic_write_json(fp, doc)
print("saved", fp)

msg = ("Ask Studio 给出 3 个本周概念："
"1）自助结账机投射全息经理反手审计 Karen 的购物车（收银吵架题材评论区最爱）；"
"2）Karen 叫拖车拖智能电车，电车锁胎+自动驾驶戏耍拖车司机（车辆防御类本频道留存最高）；"
"3）Karen 对快餐 AI 得来速破口大骂，AI 把 insult 热情翻译成定制菜单（反差梗，短平快）。\n"
"频道 69.6% 留下率 / 237.5% 平均播放比。要求：前 1.5 秒见血，开场即动作+5 词内大字标题（半数静音刷）；"
"时长 9-12 秒，0-2s 立冲突、3-7s AI 反击、8-10s 即时报应+无缝回环；死磕 instant physical karma，纯嘴炮完播差。\n"
"零秒钩子+150%+ APV；置顶评论放争议提问引战；标题移动端 50 字符内最易扫读。")
notice = {"type": "ask_studio", "for": "marvis", "read": False,
"date": "2026-10-11",
"title": "Ask Studio 每日问答 2026-10-11：3 概念 + 本周优化清单",
"message": msg}
ip = "/home/hatch/data/collab/inbox.json"
import inbox as inbox_gw
inbox_gw.append_notice(notice)
print("inbox appended")
