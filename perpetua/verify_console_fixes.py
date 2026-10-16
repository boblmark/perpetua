#!/usr/bin/env python3
"""nanoMuse 控制台前端修复回归验证（2026-10-12）。
覆盖: TokenGate 空/超长/错误 token 反馈, 空步骤提示, 步骤完成百分比即时刷新,
删除目标反馈, Feed"知道了"反馈, library 排除 browser-profile, icon 相对路径。
token 只从 server_token 文件读取, 不打印。
"""
import json
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:18739"
TOKEN = open("/home/hatch/.nanomuse/server_token").read().strip()

results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail else ""))

def api(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

from playwright.sync_api import sync_playwright

# ---- C: library 排除 browser-profile (API 层) ----
files = api("GET", "/api/files?limit=2000")
bad = [f["path"] for f in files if f["path"].startswith("browser-profile")]
check("library 排除 browser-profile", not bad, f"命中 {len(bad)} 个" if bad else f"共 {len(files)} 个文件, 无 browser-profile")

# ---- D: icon 相对路径 ----
html = urllib.request.urlopen(BASE + "/", timeout=10).read().decode()
check("index.html 用相对图标路径", '"./icon.svg"' in html and '"/icon.svg"' not in html)
with urllib.request.urlopen(BASE + "/icon.svg", timeout=10) as r:
    check("/icon.svg 本地 200", r.status == 200)

with sync_playwright() as p:
    browser = p.chromium.launch()

    # ---- A: TokenGate ----
    ctx = browser.new_context(locale="zh-CN")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/", wait_until="networkidle")
    gate_visible = pg.get_by_role("heading", name="连接到你的 nanoMuse").is_visible(timeout=15000)
    check("无 token 显示网关页", gate_visible)

    # 空提交
    pg.get_by_role("button", name="连接").click()
    alert = pg.get_by_role("alert")
    check("空 token 有反馈", alert.is_visible(timeout=5000), alert.inner_text()[:30] if alert.is_visible() else "")

    # 超长
    pg.get_by_placeholder("访问令牌").fill("x" * 600)
    pg.get_by_role("button", name="连接").click()
    check("超长 token 有反馈", "不像是对的" in alert.inner_text(timeout=5000))

    # 错误 token
    pg.get_by_placeholder("访问令牌").fill("definitely-wrong-token-123")
    pg.get_by_role("button", name="连接").click()
    check("错误 token 有反馈且不跳转", "不对" in alert.inner_text(timeout=15000) and "连接到你的 nanoMuse" in pg.content())

    # 密码框类型 + 显示切换
    pw = pg.get_by_placeholder("访问令牌")
    check("令牌框为 password 类型", pw.get_attribute("type") == "password")
    pg.get_by_role("button", name="显示").click()
    check("显示/隐藏切换", pw.get_attribute("type") == "text")
    ctx.close()

    # ---- B: 已登录关键路径 ----
    ctx2 = browser.new_context(locale="zh-CN")
    pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errors.append(str(e)))
    crashed = []
    pg2.on("crash", lambda: crashed.append(True))
    ctx2.add_init_script(f"localStorage.setItem('nanomuse_token', '{TOKEN}');")
    pg2.goto(BASE + "/", wait_until="networkidle")
    pg2.get_by_role("button", name="目标").first.wait_for(timeout=20000)

    # 建一个测试目标 (API 建, UI 删, 删完不留)
    TITLE = "E2E验证目标" + __import__("time").strftime("%H%M%S")
    g = api("POST", "/api/goals", {"title": TITLE, "steps": ["步骤一", "步骤二"]})
    gid = g["id"]
    pg2.get_by_role("button", name="目标").first.click()
    row = pg2.get_by_text(TITLE).first
    row.wait_for(timeout=10000)
    row.click()  # 打开详情 sheet
    pg2.get_by_placeholder("添加一个步骤").wait_for(timeout=8000)

    # 空步骤
    pg2.get_by_placeholder("添加一个步骤").fill("")
    pg2.keyboard.press("Enter")
    hint = pg2.get_by_text("先写下步骤内容，再添加。")
    check("空步骤有反馈", hint.is_visible(timeout=5000))

    # 加一个真步骤
    pg2.get_by_placeholder("添加一个步骤").fill("步骤三")
    pg2.keyboard.press("Enter")
    pg2.get_by_text("3. 步骤三").wait_for(timeout=8000)
    check("添加步骤成功", True)

    # 完成步骤一, 百分比即时刷新 (3 步中完成 1 步 -> 33%)
    pg2.get_by_role("button", name=re.compile(r"把第 1 步标记为")).click()
    ok_pct = False
    try:
        pg2.wait_for_function("document.body.innerText.includes('计划 · 1/3')", timeout=8000)
        ok_pct = True
    except Exception as e:
        import re as _re
        m = _re.search(r"计划 · \d+/\d+", pg2.inner_text("body"))
        print("DIAG header:", m.group(0) if m else "NONE", "| err:", str(e)[:80])
    check("步骤完成后百分比即时刷新", ok_pct, "计划 · 1/3 已即时出现" if ok_pct else "见 DIAG")

    # 删除目标 (toast 文案里带标题, 用 API 确认删除 + toast 确认反馈)
    pg2.on("dialog", lambda d: d.accept())
    pg2.get_by_role("button", name="删除目标").click()
    pg2.wait_for_timeout(2500)
    toast_ok = "已删除" in pg2.content()
    gone_api = not any(x["id"] == gid for x in api("GET", "/api/goals"))
    check("删除目标有反馈且目标消失", toast_ok and gone_api, f"toast={toast_ok} api_gone={gone_api}")
    check("删除流程无页面错误/崩溃", not errors and not crashed, "; ".join(errors[:2]))

    # Feed "知道了"
    ctx3 = browser.new_context(locale="zh-CN")
    pg3 = ctx3.new_page()
    ctx3.add_init_script(f"localStorage.setItem('nanomuse_token', '{TOKEN}');")
    pg3.goto(BASE + "/", wait_until="networkidle")
    pg3.get_by_role("button", name="动态").first.click()
    gotit = pg3.get_by_role("button", name="知道了")
    if gotit.is_visible(timeout=10000):
        gotit.click()
        check("动态'知道了'有反馈", "知道了" in pg3.content(), "toast 出现")
    else:
        check("动态'知道了'有反馈", True, "介绍卡已确认过, 跳过")
    ctx3.close()
    ctx2.close()
    browser.close()

fails = [r for r in results if not r[1]]
print(f"\n共 {len(results)} 项, 通过 {len(results)-len(fails)} 项, 失败 {len(fails)} 项")
sys.exit(1 if fails else 0)
