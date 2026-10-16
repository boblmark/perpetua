#!/usr/bin/env python3
"""把 360° 全息作战指挥中心(command.html)并入 Battle 标签页(tab-battle)，退役 /command。

关键约束：index.html 主体是 JS 模板字符串经 innerHTML 注入 ——
  → <style> 可随模板注入（样式生效）；
  → <script> 随 innerHTML 注入不会执行，因此 holo JS 作为独立 <script> 块追加到主 script 之后；
  → 模板字面量里不能出现反引号/`${`，holo 的 HTML/CSS 经校验不含这两者。
CSS 全部作用域化到 .holo 下；keyframes 重命名防冲突(pulse/spin 已存在)。
幂等：检测到 <!-- HOLO360-INTEGRATED --> 则退出。"""
import re, shutil, datetime

BASE = "/home/hatch/data/perpetua/vps_console"
IDX = BASE + "/index.html"
CMD = BASE + "/command.html"
SRV = BASE + "/console_server.py"
MARK = "<!-- HOLO360-INTEGRATED -->"
TS = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

def split_rules(css):
    rules, i, n = [], 0, len(css)
    while i < n:
        while i < n and css[i] in " \t\n\r":
            i += 1
        if i >= n: break
        if css.startswith("/*", i):
            i = css.find("*/", i) + 2
            continue
        j = css.find("{", i)
        if j < 0: break
        sel = css[i:j].strip()
        depth, k = 0, j
        while k < n:
            if css[k] == "{": depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0: break
            k += 1
        rules.append((sel, css[j+1:k]))
        i = k + 1
    return rules

KF_RENAME = {"spin": "holo-spin", "pulse": "holo-pulse", "dash": "holo-dash",
             "slidein": "holo-slidein", "flash": "holo-flash"}

def scope_css(css):
    out = []
    for sel, body in split_rules(css):
        if sel.startswith("@keyframes"):
            name = sel.split()[-1]
            out.append("@keyframes %s {%s}" % (KF_RENAME.get(name, name), body))
            continue
        if sel.startswith("@media"):
            out.append("%s {%s}" % (sel, scope_css(body)))
            continue
        sels = [s.strip() for s in sel.split(",")]
        new_sels, skip = [], False
        for s in sels:
            if s == ":root":
                new_sels.append(".holo")
            elif s == "body" or s.startswith("body::"):
                skip = True
                break
            elif s == "*":
                new_sels.append(".holo *")
            else:
                new_sels.append(".holo " + s)
        if skip:
            continue
        for old, new in KF_RENAME.items():
            body = re.sub(r"(animation(?:-name)?\s*:[^;}]*\b)%s\b" % old, r"\1" + new, body)
        out.append("%s {%s}" % (", ".join(new_sels), body))
    return "\n".join(out)

def main():
    idx = open(IDX, encoding="utf-8").read()
    if MARK in idx:
        print("already integrated, exit")
        return
    cmd = open(CMD, encoding="utf-8").read()

    shutil.copy2(IDX, IDX + ".bak-" + TS)
    shutil.copy2(SRV, SRV + ".bak-" + TS)
    print("backup done", TS)

    style = re.search(r"<style>(.*?)</style>", cmd, re.S).group(1)
    body_html = re.search(r"<body>(.*?)<script>", cmd, re.S).group(1).strip()
    script = re.search(r"<script>(.*?)</script>", cmd, re.S).group(1)

    # 模板字面量安全检查
    assert "`" not in style and "${" not in style, "css has template chars"
    assert "`" not in body_html and "${" not in body_html, "html has template chars"

    scoped_css = scope_css(style)

    # ---- JS 改造：独立 script 块，命名隔离 ----
    js = script
    js = js.replace("const $=id=>document.getElementById(id);",
                    "const h$=id=>document.getElementById(id);")
    js = re.sub(r'\$\("', 'h$("', js)
    js = js.replace("function drawFlow(", "function holoDrawFlow(")
    js = js.replace("drawFlow(d.stages);", "holoDrawFlow(d.stages);")
    js = js.replace("function openDrawer(", "function holoOpenDrawer(")
    js = js.replace("openDrawer(g.dataset.id)", "holoOpenDrawer(g.dataset.id)")
    js = js.replace("function openModule(", "function holoOpenModule(")
    js = js.replace("openModule(c.dataset.mid)", "holoOpenModule(c.dataset.mid)")
    js = js.replace("function esc(", "function holoEsc(")
    js = re.sub(r"(?<![a-zA-Z])esc\(", "holoEsc(", js)
    js = js.replace("async function tick(){", "async function holoTick(){")
    # 去掉原 5s 自驱与时钟自驱，改由 holoStart/holoStop 接管
    js = js.replace("setInterval(()=>{const d=new Date();h$(\"clock\").textContent=d.toLocaleTimeString(\"zh-CN\",{hour12:false});},1000);", "")
    js = js.replace("setInterval(tick,5000); tick();", "")
    js = js.replace("document.addEventListener(\"visibilitychange\",()=>{if(!document.hidden) tick();});", "")
    assert "tick()" not in js and "tick," not in js, "stray tick ref: " + [l for l in js.split("\n") if "tick" in l][:3]

    holo_script = ("<script>\n/* HOLO360: 360° 全息作战指挥中心，数据源 /api/command/live */\n"
        "(function(){\n" + js +
        "\nlet HOLO_TIMER=null,HOLO_CLOCK=null;\n"
        "function holoTickSafe(){try{holoTick();}catch(e){}}\n"
        "window.holoStart=function(){holoStop();holoTickSafe();"
        "HOLO_TIMER=setInterval(holoTickSafe,5000);"
        "HOLO_CLOCK=setInterval(()=>{try{const c=h$('clock');"
        "if(c)c.textContent=new Date().toLocaleTimeString('zh-CN',{hour12:false});}catch(e){}},1000);};\n"
        "window.holoStop=function(){if(HOLO_TIMER){clearInterval(HOLO_TIMER);HOLO_TIMER=null;}"
        "if(HOLO_CLOCK){clearInterval(HOLO_CLOCK);HOLO_CLOCK=null;}};\n"
        "// 初始加载 battle tab 时自启（switchTab 只处理切换）\n"
        "const holoBootCheck=setInterval(()=>{const p=document.getElementById('tab-battle');"
        "if(p&&p.classList.contains('active')){clearInterval(holoBootCheck);holoStart();}},800);\n"
        "setTimeout(()=>clearInterval(holoBootCheck),30000);\n"
        "document.addEventListener('visibilitychange',()=>{if(!document.hidden&&HOLO_TIMER)holoTickSafe();});\n"
        "})();\n</script>")

    # ---- 替换 tab-battle section（模板字面量内：只放 HTML+CSS） ----
    battle_sec_pat = re.compile(
        r'<section class="tab-panel \$\{ACTIVE_TAB===\'battle\'\?\'active\':\'\'\}" id="tab-battle">.*?</section>',
        re.S)
    new_section = (
        '<section class="tab-panel ${ACTIVE_TAB===\'battle\'?\'active\':\'\'}" id="tab-battle">\n'
        + MARK + "\n"
        + '<style>\n' + scoped_css + '\n</style>\n'
        + '<div class="holo">\n' + body_html + '\n</div>\n'
        + '</section>')
    idx2, n = battle_sec_pat.subn(new_section, idx)
    assert n == 1, "battle section not found"
    idx = idx2

    # ---- 删除旧 battle JS ----
    old_js_pat = re.compile(
        r"let BATTLE_TIMER=null;.*?function showBattleDetail\(stageId\)\{.*?\n\}\n",
        re.S)
    idx2, n = old_js_pat.subn(
        "/* HOLO360: 旧 battleMap 已由 360° 全息视图替换，刷新由 holoStart/holoStop 接管 */\n",
        idx)
    assert n == 1, "old battle js not found"
    idx = idx2

    # ---- switchTab 钩子 ----
    old_hook = "if(id==='battle'){renderBattle();startBattleTimer()}\n  else{stopBattleTimer()}"
    assert old_hook in idx, "switch hook not found"
    idx = idx.replace(old_hook,
        "if(id==='battle'){holoStart()}\n  else{holoStop()}")

    # ---- 追加 holo 独立 script ----
    tail = "boot();\n</script>\n</body>"
    assert tail in idx, "tail not found"
    idx = idx.replace(tail, "boot();\n</script>\n" + holo_script + "\n</body>")

    open(IDX, "w", encoding="utf-8").write(idx)
    print("index.html integrated")

    # ---- 退役 /command：301 到 / ----
    srv = open(SRV, encoding="utf-8").read()
    old_route = 'if path == "/command":\n            self.serve_file("command.html", "text/html; charset=utf-8")'
    assert old_route in srv, "command route not found"
    new_route = ('if path == "/command":\n'
                 '            # 2026-10-16 退役：360° 已并入 Battle 标签页，/command 永久跳转到 /\n'
                 '            self.send_response(301)\n'
                 '            self.send_header("Location", "/")\n'
                 '            self.end_headers()\n'
                 '            return')
    srv = srv.replace(old_route, new_route)
    open(SRV, "w", encoding="utf-8").write(srv)
    print("console_server.py /command retired -> 301 /")

if __name__ == "__main__":
    main()
