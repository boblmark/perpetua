#!/usr/bin/env python3
"""
分发器生命线巡检（2026-10-15 用户立：生命线，断了整个系统停摆）
2026-10-15 四脑议会 D20261015-006/007/008 修订：分级断言（OK/SUSPECT/CONFIRMED）

检查视频生成分发链路的每一环：
  1. dispatcher (192.166.82.123:8740/mcp) 存活
  2. mcp-b 队列：pending 深度 + 消费者新鲜度
  3. geminigen：Chrome 会话（401=掉线）+ 额度信号
  4. H3：tunnel 可达（无配置则记 unconfigured）
  5. vids/builtin：已知状态（配额/地区墙）

分级断言铁律：
- SUSPECT（检查器自身可能坏了）永不触发状态跃迁，只写 ledger + 升级
- 只有 CONFIRMED 能判 DOWN/DEGRADED
- M4/N1：pending==0 时消费者检查直接 OK，不看"上次消费时间"（杀 2026-10-15 口径 bug）
- M9：SSH/探针自身失败 → SUSPECT，不判 ok/fail

用法：python3 dispatch_health.py [--json]
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import graded_assertions as ga

STATE_FILE = os.path.join(BASE, "dispatch_health_state.json")
VM_HOST = "192.166.82.123"
VM_USER = "root"
SSH_KEY = "/home/hatch/.ssh/id_ed25519"  # Rule 11: fixed absolute path, HOME may be /root in some runners
PROXY = "nc -X connect -x 198.19.0.1:3128 %h %p"
DISPATCHER_URL = f"http://{VM_HOST}:8740/mcp"
VIDS_QUOTA_UNTIL = "2026-11-01"

SSH_BASE = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
            "-o", f"ProxyCommand={PROXY}", "-o", "ConnectTimeout=10",
            f"{VM_USER}@{VM_HOST}"]

CHECKER = "dispatch_health"


def ssh(cmd, timeout=25):
    try:
        r = subprocess.run(SSH_BASE + [cmd], capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return f"SSH_ERR:{e}", 99


def _suspect(checker_fn, subject, condition, detail, evidence_ts=None, ttl_key=None):
    """SUSPECT：写 ledger + 升级，不跃迁。返回 verdict 记录。"""
    rec = ga.make_verdict(ga.SUSPECT, detail, evidence_ts, ttl_key,
                          checker=CHECKER, subject=subject,
                          checker_health={"probe_ok": False, "last_error": condition})
    ga.ledger_append(rec)
    ga.escalate(CHECKER, subject, condition, severity="P2", detail=detail,
                evidence_ts=evidence_ts, ttl_key=ttl_key,
                checker_health={"probe_ok": False})
    return rec


def check_dispatcher():
    """dispatcher 8740 存活。探针自身失败 → SUSPECT（M9）；3 次重试都失败 → CONFIRMED down。"""
    last_err = ""
    probe_ok = True
    for attempt in range(3):
        try:
            r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                                "-m", "10", DISPATCHER_URL],
                               capture_output=True, text=True, timeout=15)
            code = r.stdout.strip()
            if code and code != "000":
                d = f"dispatcher 8740 HTTP {code}"
                return ga.make_verdict(ga.OK, d, ga.utcnow(), "queue_snapshot",
                                       checker=CHECKER, subject="dispatcher",
                                       checker_health={"probe_ok": True})
            last_err = "dispatcher 8740 不可达 (curl 000)"
        except Exception as e:
            last_err = f"dispatcher 探针异常: {e}"
            probe_ok = False
        if attempt < 2:
            time.sleep(5)
    if not probe_ok:
        return _suspect("check_dispatcher", "dispatcher", last_err,
                        f"dispatcher 探针自身异常，无法定论：{last_err}")
    d = f"{last_err}（3次重试均失败）"
    return ga.make_verdict(ga.CONFIRMED, d, ga.utcnow(), "queue_snapshot",
                           checker=CHECKER, subject="dispatcher",
                           checker_health={"probe_ok": True})


CLAIMED_STALE_MIN = 360


def check_queue():
    """pending 深度 + 消费者新鲜度。
    M4/N1：pending==0 → 直接 OK，不看"上次消费时间"（杀口径 bug）。
    M9：SSH 失败 → SUSPECT。
    2026-10-28 P0-2：认领态文件（*.claimed-*.json）仍在 pending 目录内，
    旧口径只看 pending 总数会把认领卡死误判为“有活干但心跳新鲜”。
    本函数新增认领态探针：drained = pending==0 且 claimed==0；
    stuck = 任一认领文件最老年龄 >360 分钟（6 小时，与闲时看门狗口径一致，
    不用 90 分钟，避免误杀慢认领）→ CONFIRMED 升级，不自动删/改 VPS 文件
    （认领文件归消费者所有，本地无已验证的释放协议，擅自改动属破坏性操作）。
    2026-10-28 C9：pending 计数排除认领文件（grep -v 'claimed-'），
    只计未认领任务；未认领 pending==0 时直接返回“全部外部认领中”，
    不再进入消费者新鲜度分支（旧口径把认领文件计入 pending，认领新鲜
    但 done 心跳超 30 分钟时会误判 CONFIRMED“消费者停滞”）。
    认领老化只由上方的 P0-2 探针定论。"""
    snap_ts = ga.utcnow()
    # C9：只计未认领 pending（排除 *.claimed-*.json），认领文件另由
    # 下方 P0-2 探针单独计数；旧口径含认领文件会误判“消费者停滞”。
    out, rc = ssh("ls /opt/mcp-b/data/mcp_jobs/pending/*.json 2>/dev/null | grep -v result | grep -v 'claimed-' | wc -l")
    if rc != 0 or out.startswith("SSH_ERR"):
        return _suspect("check_queue", "mcp-b-queue", f"SSH/目录异常: {out[:80]}",
                        "队列快照不可读，无法定论", snap_ts, "queue_snapshot")
    try:
        pending = int(out.strip() or "0")
    except ValueError:
        return _suspect("check_queue", "mcp-b-queue", f"pending 解析失败: {out[:80]}",
                        "队列快照不可解析，无法定论", snap_ts, "queue_snapshot")
    # P0-2 认领态探针：stat 无匹配时 rc 非 0 属正常（claimed=0），只有 SSH_ERR 才 SUSPECT
    claimed_out, _claimed_rc = ssh(
        "stat -c %Y /opt/mcp-b/data/mcp_jobs/pending/*.claimed-*.json 2>/dev/null | sort -n")
    if claimed_out.startswith("SSH_ERR"):
        return _suspect("check_queue", "mcp-b-claimed", "认领态探针 SSH 失败",
                        "认领文件状态读不到，无法定论是否卡死", snap_ts,
                        "claimed_snapshot")
    claimed_epochs = [int(x) for x in claimed_out.split() if x.isdigit()] \
        if claimed_out else []
    claimed_n = len(claimed_epochs)
    claimed_oldest_min = ((time.time() - min(claimed_epochs)) / 60
                          if claimed_epochs else None)
    if claimed_oldest_min is not None and claimed_oldest_min > CLAIMED_STALE_MIN:
        return ga.make_verdict(
            ga.CONFIRMED,
            f"认领卡死：claimed={claimed_n}，最老认领 "
            f"{claimed_oldest_min:.0f} 分钟前（>{CLAIMED_STALE_MIN} 分钟），"
            f"消费者未写回（本地不自动删/改 VPS 认领文件，只升级）",
            snap_ts, "queue_snapshot",
            checker=CHECKER, subject="mcp-b-claimed",
            checker_health={"probe_ok": True})
    claimed_detail = (f"，认领中 {claimed_n}（最老 "
                      f"{claimed_oldest_min:.0f} 分钟前）"
                      if claimed_n else "，无认领中文件")
    # M4：空队列先行返回 OK。C9：pending 已是未认领计数，故 pending==0
    # 时 claimed 可能 >0（全部任务在外部认领中、新鲜未 stale）——此时
    # 本地消费者无事可做，直接返回“全部外部认领中”，绝不进入下方
    # 消费者新鲜度分支（旧口径在此误判“消费者停滞”）。
    if pending == 0:
        if claimed_n:
            return ga.make_verdict(ga.OK,
                f"全部外部认领中（claimed={claimed_n}，最老 "
                f"{claimed_oldest_min:.0f} 分钟前），本地消费者无事可做",
                snap_ts, "queue_snapshot",
                checker=CHECKER, subject="mcp-b-queue",
                checker_health={"probe_ok": True})
        return ga.make_verdict(ga.OK, "pending=0 且 claimed=0（空队列，消费者无需工作）",
                               snap_ts, "queue_snapshot",
                               checker=CHECKER, subject="mcp-b-queue",
                               checker_health={"probe_ok": True})
    # pending>0（未认领任务在队）：看消费者新鲜度
    out2, rc2 = ssh("ls -t /opt/mcp-b/data/mcp_jobs/done/*.result.json 2>/dev/null | head -1 | xargs stat -c %Y 2>/dev/null")
    if rc2 != 0 or not out2.strip().isdigit():
        return _suspect("check_queue", "mcp-b-consumer", "消费者心跳不可读",
                        f"未认领 pending={pending} 但消费者心跳读不到，无法定论是否停滞",
                        snap_ts, "consumer_heartbeat")
    age_min = (time.time() - int(out2.strip())) / 60
    detail = f"未认领 pending={pending}，最近消费 {age_min:.0f} 分钟前{claimed_detail}"
    if age_min > 30:
        # C12（2026-10-28）：30 分钟阈值对小时级任务是误判——消费者可能
        # 正在处理一个长任务（done 心跳自然陈旧）。定论停滞须同时满足
        # “无新 result”且“无在途证据”。在途证据 = 未 stale 的认领文件
        # （stale 认领已在上方 P0-2 分支先行 CONFIRMED，故到此处认领
        # 均未 stale，即为在途证据）；独立的消费者心跳文件不存在，
        # done result mtime 本身就是唯一心跳，故认领存在即降为 SUSPECT。
        if claimed_n:
            return _suspect("check_queue", "mcp-b-consumer",
                            "consumer_heartbeat_stale_with_claims",
                            detail + "（在途认领存在，可能是长任务处理中，"
                            "降为 SUSPECT 不定论停滞）",
                            snap_ts, "consumer_heartbeat")
        return ga.make_verdict(ga.CONFIRMED, detail + "（消费者停滞）",
                               snap_ts, "queue_snapshot",
                               checker=CHECKER, subject="mcp-b-consumer",
                               checker_health={"probe_ok": True})
    return ga.make_verdict(ga.OK, detail, snap_ts, "queue_snapshot",
                           checker=CHECKER, subject="mcp-b-queue",
                           checker_health={"probe_ok": True})


def check_geminigen():
    """geminigen 会话 + 额度。探针失败 → SUSPECT；401/额度0 → CONFIRMED。"""
    import base64
    import time as _time
    base = "/usr/bin/agent-browser --cdp http://127.0.0.1:9344 --session lifeline9344"
    snap_ts = ga.utcnow()
    out0, rc0 = ssh(f"{base} open https://geminigen.link", timeout=30)
    if rc0 != 0 or out0.startswith("SSH_ERR"):
        return _suspect("check_geminigen", "geminigen", f"探针 open 失败: {out0[:80]}",
                        "geminigen 探针打不开页面，无法定论会话状态", snap_ts, "session_state")
    rb64 = base64.b64encode(b"document.readyState+'|'+location.href").decode()
    loaded = False
    for _ in range(10):
        _time.sleep(2)
        rout, rrc = ssh(f"{base} eval -b {rb64}", timeout=20)
        if rrc == 0 and "complete|https://geminigen.link" in rout:
            loaded = True
            break
    if not loaded:
        return _suspect("check_geminigen", "geminigen", "探针 tab 20s 未就绪",
                        "geminigen 页面未就绪，无法定论会话状态", snap_ts, "session_state")
    js = ("fetch('https://geminigen.link/api/ai/aimodel-api',{method:'POST',"
          "headers:{'Content-Type':'application/json'},body:'{}'})"
          ".then(async r=>{var t=await r.text();return r.status+'::'+t.slice(0,120)})"
          ".catch(e=>'ERR:'+e.message)")
    b64 = base64.b64encode(js.encode()).decode()
    out, rc = ssh(f"{base} eval -b {b64}", timeout=40)
    if rc != 0 or out.startswith("SSH_ERR"):
        # 探针偶发 eval 失败（2026-10-16 实测：连续两次失败后第三次 OK，服务本身健康），
        # 重试一次再判，避免把检查器抖动误报成 SUSPECT。
        _time.sleep(5)
        out, rc = ssh(f"{base} eval -b {b64}", timeout=40)
    out = out.strip().strip('"')
    if rc != 0 or out.startswith("SSH_ERR"):
        return _suspect("check_geminigen", "geminigen", f"探针 eval 失败: {out[:80]}",
                        "geminigen 会话探针失败，无法定论", snap_ts, "session_state")
    health = {"probe_ok": True}
    if out.startswith("401") or "Please login" in out:
        return ga.make_verdict(ga.CONFIRMED, "geminigen 会话掉线（401，需重登）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="geminigen", checker_health=health)
    if "Not enough credits" in out:
        return ga.make_verdict(ga.CONFIRMED, "geminigen 会话活但额度为 0（需充值）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="geminigen", checker_health=health)
    if out.startswith("402") or out.startswith("403"):
        return ga.make_verdict(ga.OK, "geminigen 会话活（402/403 已认证）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="geminigen", checker_health=health)
    _sig = out.replace("\\", "").replace('"', "")
    if out.startswith("200") and "success:true" in _sig:
        return ga.make_verdict(ga.OK, "geminigen 会话活（200 已认证，免费档）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="geminigen", checker_health=health)
    return _suspect("check_geminigen", "geminigen", f"探针未识别: {out[:80]}",
                    "geminigen 探针返回无法识别，无法定论", snap_ts, "session_state")


def check_arena():
    """arena.ai/video：页面可达 + prompt 输入框存在。
    2026-10-17 接入：Battle 模式一次产出 2 条视频（匿名模型），无付费墙。
    探针失败 → SUSPECT；登录墙/付费墙 → CONFIRMED（不可用）。
    """
    snap_ts = ga.utcnow()
    js = ("""(async () => {"""
          """  try {"""
          """    const r = await fetch('https://arena.ai/video', {method: 'GET', credentials: 'include', mode: 'no-cors'});"""
          """    return 'fetch_ok';"""
          """  } catch(e) { return 'fetch_err:' + e.message.slice(0,80); }"""
          """})()""")
    # 经 VPS 浏览器探针（带登录态）
    out0, rc0 = ssh(f"/usr/bin/agent-browser --cdp http://127.0.0.1:9222 open https://arena.ai/video", timeout=75)
    if rc0 != 0:
        return _suspect("check_arena", "arena", f"探针 open 失败: {out0[:80]}",
                        "arena.ai/video 探针打不开页面，无法定论可用性", snap_ts, "session_state")
    time.sleep(3)
    probe_js = ("(function(){"
                "var t=(document.body.innerText||'').slice(0,800).toLowerCase();"
                "var hasBox=!!document.querySelector('textarea');"
                "var blocked=/sign in|log in|subscribe|upgrade|payment|paywall/.test(t);"
                "return JSON.stringify({hasBox:hasBox,blocked:blocked,snip:t.slice(0,120)});"
                "})()")
    out, rrc = ssh(f"/usr/bin/agent-browser --cdp http://127.0.0.1:9222 eval \"{probe_js}\"", timeout=75)
    if rrc != 0:
        return _suspect("check_arena", "arena", f"探针 eval 失败: {out[:80]}",
                        "arena.ai/video 探针执行失败，无法定论", snap_ts, "session_state")
    try:
        info = json.loads(out.strip().strip('"').replace('\\"', '"'))
    except Exception:
        return _suspect("check_arena", "arena", f"探针返回解析失败: {out[:80]}",
                        "arena.ai/video 探针返回无法解析", snap_ts, "session_state")
    if info.get("blocked"):
        return ga.make_verdict(ga.CONFIRMED, "arena.ai/video 被登录/付费墙拦截（不可用）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="arena", checker_health={"probe_ok": True})
    if info.get("hasBox"):
        return ga.make_verdict(ga.OK, "arena.ai/video 可用（prompt 输入框就绪，Battle 模式）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="arena", checker_health={"probe_ok": True})
    return _suspect("check_arena", "arena", f"页面结构异常: {info.get('snip','')[:80]}",
                    "arena.ai/video 页面无 prompt 输入框，疑似改版或异常", snap_ts, "session_state")


def check_h3():
    """H3 tunnel：动态检查，不硬编码。
    无配置 → UNKNOWN（用户 2026-10-15 明确要求：h3 有配置地址则实测连通性、
    无配置 unknown；不写 ledger、不升级、不污染 SUSPECT 口径）。
    2026-10-17 anomaly-watchdog 修复：此前误判 SUSPECT，导致 grader SUSPECT 率
    100% 被判不健康、每日重复 P1 升级。
    """
    snap_ts = ga.utcnow()
    h3_addr = os.environ.get("H3_ADDR", "")
    if not h3_addr:
        for cfg in ["/home/hatch/data/perpetua/h3_config.json",
                    "/home/hatch/data/h3_addr.txt"]:
            try:
                with open(cfg, encoding="utf-8") as f:
                    h3_addr = f.read().strip().split()[0]
                    if h3_addr:
                        break
            except Exception:
                pass
    if not h3_addr:
        return ga.make_verdict("UNKNOWN",
                               "H3 未配置地址（tunnel 自 10-13 断开，待配置新地址）",
                               snap_ts, "session_state",
                               checker=CHECKER, subject="h3",
                               checker_health={"probe_ok": True, "unconfigured": True})
    try:
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                            "-m", "10", h3_addr],
                           capture_output=True, text=True, timeout=15)
        code = r.stdout.strip()
        if code in ("200", "401", "403"):
            return ga.make_verdict(ga.OK, f"H3 可达（{h3_addr} HTTP {code}）",
                                   snap_ts, "session_state", checker=CHECKER,
                                   subject="h3", checker_health={"probe_ok": True})
        return ga.make_verdict(ga.CONFIRMED, f"H3 地址 {h3_addr} 返回 HTTP {code}（待验证）",
                               snap_ts, "session_state", checker=CHECKER,
                               subject="h3", checker_health={"probe_ok": True})
    except Exception as e:
        return _suspect("check_h3", "h3", f"curl 异常: {e}",
                        f"H3 地址 {h3_addr} 探针异常，无法定论", snap_ts, "session_state")


def check_vids():
    """vids 配额：基于日期动态判断。"""
    from datetime import date
    snap_ts = ga.utcnow()
    try:
        until = date.fromisoformat(VIDS_QUOTA_UNTIL)
        if date.today() >= until:
            return _suspect("check_vids", "vids", "配额恢复日期已到需重测",
                            f"vids 配额恢复日期 {VIDS_QUOTA_UNTIL} 已到，需重新实测",
                            snap_ts, "session_state")
    except Exception:
        pass
    return ga.make_verdict(ga.CONFIRMED, f"vids 配额耗尽至 {VIDS_QUOTA_UNTIL}（实测，待到期重验）",
                           snap_ts, "session_state", checker=CHECKER,
                           subject="vids", checker_health={"probe_ok": True})


def check_builtin():
    """builtin 状态：基于实际证据。"""
    import glob
    videos_dir = "/home/hatch/data/perpetua/videos"
    now = time.time()
    snap_ts = ga.utcnow()
    recent_ok = []
    try:
        for f in glob.glob(os.path.join(videos_dir, "job-*.mp4")):
            try:
                mtime = os.path.getmtime(f)
                if now - mtime < 24 * 3600:
                    recent_ok.append((mtime, os.path.basename(f)))
            except Exception:
                pass
    except Exception:
        return _suspect("check_builtin", "builtin", "视频目录不可读",
                        "builtin 出片目录不可读，无法定论", snap_ts, "consumer_heartbeat")
    if recent_ok:
        recent_ok.sort(reverse=True)
        return ga.make_verdict(ga.OK, f"builtin 可用（24h 内成功出片：{recent_ok[0][1]}）",
                               snap_ts, "consumer_heartbeat", checker=CHECKER,
                               subject="builtin", checker_health={"probe_ok": True})
    return _suspect("check_builtin", "builtin", "无 24h 内成功记录",
                    "builtin 无 24h 内成功出片记录，状态未知（非已知不可用）",
                    snap_ts, "consumer_heartbeat")


def summarize(verdicts):
    """只有 CONFIRMED 能定级。SUSPECT 只升级、不跃迁（M2/N4）。"""
    vs = [v["verdict"] for v in verdicts.values()]
    details = [v["detail"] for v in verdicts.values()]
    # CONFIRMED 的 fail 语义：detail 含"掉线/不可达/停滞/耗尽"等
    confirmed_bad = [v for v in verdicts.values()
                     if v["verdict"] == ga.CONFIRMED
                     and any(k in v["detail"] for k in ("掉线", "不可达", "停滞", "耗尽", "失败"))]
    if confirmed_bad:
        # dispatcher 不可达 → DOWN；其余 → DEGRADED
        if any(v["subject"] == "dispatcher" for v in confirmed_bad):
            return "DOWN"
        return "DEGRADED"
    if any(v["verdict"] == ga.CONFIRMED for v in verdicts.values()):
        # CONFIRMED 但非 fail 语义（如 vids 配额耗尽已知）→ DEGRADED
        return "DEGRADED"
    # C8（2026-10-28，审计 C 路第 8 条）：纯 SUSPECT/UNKNOWN 不再翻成
    # DEGRADED——此前代码违背本函数 docstring（M2/N4：SUSPECT 只升级、
    # 不跃迁），检查器自坏直接污染生命线总状态、制造假 DEGRADED 噪声。
    # SUSPECT 仍走 suspect_forever 熔断升级通道（main 内），只不碰总状态。
    return "HEALTHY"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def main():
    verdicts = {
        "dispatcher": check_dispatcher(),
        "queue": check_queue(),
        "geminigen": check_geminigen(),
        "arena": check_arena(),
        "h3": check_h3(),
        "vids": check_vids(),
        "builtin": check_builtin(),
    }
    overall = summarize(verdicts)
    # 台账自愈（2026-10-21）：OK/CONFIRMED 结论落盘即 resolve 同 (checker,subject)
    # 的未解决 SUSPECT——否则熔断按最早条目算龄，条件消失后仍持续 P1
    # （builtin 实证：远端同步成片使探针转 OK，台账条目却从 10-17 悬到现在）。
    # fail-open：自愈失败绝不影响主流程。
    for _v in verdicts.values():
        try:
            if (_v.get("verdict") in (ga.OK, ga.CONFIRMED)
                    and _v.get("checker") and _v.get("subject")):
                ga.ledger_resolve(
                    _v["checker"], _v["subject"],
                    "台账自愈：%s 当前轮结论 %s，未知状态已消除"
                    % (_v["subject"], _v["verdict"]))
        except Exception:
            pass
    # SUSPECT-forever 熔断检查（R2）
    forever = ga.suspect_forever_check()
    for subject in forever:
        ga.escalate("suspect_forever", subject, "forever",
                    severity="P1",
                    detail=f"{subject} 持续 SUSPECT 超过 6h，自动升 P1（终端动作：人工介入/降级通道）")

    # C1（2026-10-28）：CONFIRMED 结论不再只进 print，必须升级。
    # condition 用检查项名 + verdict 做稳定签名（不用 detail 全文，
    # 否则“37 分钟前”这类易变文本每轮生成新升级、刷屏；detail 全文
    # 仍进 detail 字段）。escalate 自带 24h 去重 + 风暴限流。
    for _k, _v in verdicts.items():
        try:
            if (_v.get("verdict") == ga.CONFIRMED
                    and _v.get("checker") and _v.get("subject")):
                ga.escalate(_v["checker"], _v["subject"],
                            f"{_k}:{_v['verdict']}", severity="P2",
                            detail=_v.get("detail", ""))
        except Exception:
            pass

    prev = load_state()
    prev_overall = prev.get("overall")
    now = datetime.now(timezone.utc).isoformat()
    alert = None
    # C1（2026-10-28）：删“仅变迁才报”逻辑——持续非健康也重报。
    if overall != "HEALTHY":
        last_alert = prev.get("last_alert_at", "")
        try:
            dt = (datetime.now(timezone.utc) -
                  datetime.fromisoformat(last_alert)).total_seconds() / 3600
        except Exception:
            dt = 99
        if dt >= 0.5:
            _trans = (f"{prev_overall} → {overall}"
                      if prev_overall and prev_overall != overall
                      else f"持续 {overall}")
            alert = (f"分发器生命线状态：{_trans}\n" +
                     "\n".join(f"- {k}: {v['verdict']} {v['detail']}"
                               for k, v in verdicts.items()))
    # C2（2026-10-28）：run.log 收进 main() 自身，不再依赖 worker 代写。
    try:
        with open("/home/hatch/data/perpetua/dispatch_health_run.log",
                  "a", encoding="utf-8") as _f:
            _f.write(f"{now} overall={overall} alert={bool(alert)}\n")
    except Exception:
        pass
    save_state({"overall": overall, "at": now,
                "last_alert_at": now if alert else prev.get("last_alert_at", ""),
                "details": {k: {"verdict": v["verdict"], "state": v["verdict"].lower(),
                                "detail": v["detail"]} for k, v in verdicts.items()}})

    out = {"overall": overall, "at": now,
           "checks": {k: {"verdict": v["verdict"], "state": v["verdict"].lower(),
                          "detail": v["detail"]} for k, v in verdicts.items()},
           "suspect_forever_p1": forever,
           "alert": alert}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return {"HEALTHY": 0, "DEGRADED": 1, "DOWN": 2}[overall]


if __name__ == "__main__":
    sys.exit(main())
