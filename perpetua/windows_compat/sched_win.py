#!/usr/bin/env python3
"""把现有 cron 定义（~/workspace/cron.d + goals/*/crons 的 .md）翻译成
Windows Task Scheduler 可导入的 XML。

选型（见 README_WINDOWS.md §调度）：
  选 Task Scheduler XML，不选常驻 Python 调度服务。理由：
  1. 与 Linux 侧对齐：Linux 用系统 cron（非自研常驻服务），Windows 侧对等物就是 Task Scheduler；
  2. 可靠性由系统保证：休眠唤醒、失败重试、电源条件、错过补跑；
  3. 无常驻进程，故障面小；schtasks /CREATE 批量导入，install.bat 一行搞定；
  4. 常驻 Python 服务要自己实现调度/保活/日志轮转，是重复造轮子。

覆盖说明（诚实边界）：
  cron .md 分两类：(a) 正文是直接 shell/python 命令的（如各隧道 keepalive）——全自动翻译；
  (b) 正文是 agent 平台任务 prompt 的——其执行依赖 agent 调度运行时，XML 的动作为占位
      task_stub.bat（记录日志并提示需在 Windows 上部署 agent 运行时），清单见 COVERAGE.txt。
用法：
  sched_win.py --scan [--out DIR] [--dry-run]
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from config import IS_WINDOWS  # noqa: E402

HOME = os.path.expanduser("~")
CRON_DIRS = [
    os.path.join(HOME, "workspace", "cron.d"),
    # goals 下的 crons 目录在扫描时动态发现
]

FNAME_RE = re.compile(
    r"^(?P<name>.+?)__(?P<kind>interval|daily|weekly|monthly)@(?P<spec>[^.]+)\.md$")
INTERVAL_RE = re.compile(r"^(?P<n>\d+)(?P<u>[mhd])$")
DAILY_RE = re.compile(r"^(?P<h>\d{2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?")

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)


def _t(tag):
    return f"{{{NS}}}{tag}"


def _el(tag, text):
    e = ET.Element(_t(tag))
    e.text = text
    return e


def find_cron_files():
    roots = [os.path.join(HOME, "workspace", "cron.d")]
    gdir = os.path.join(HOME, "workspace", "goals")
    if os.path.isdir(gdir):
        for slug in os.listdir(gdir):
            c = os.path.join(gdir, slug, "crons")
            if os.path.isdir(c):
                roots.append(c)
    files = []
    for r in roots:
        for dp, _, fns in os.walk(r):
            if "_archive" in dp or "_invalid" in dp:
                continue
            for fn in fns:
                if fn.endswith(".md") and "__" in fn:
                    files.append(os.path.join(dp, fn))
    return sorted(files)


def parse_schedule(path):
    m = FNAME_RE.match(os.path.basename(path))
    if not m:
        return None
    kind, spec = m.group("kind"), m.group("spec")
    if kind == "interval":
        im = INTERVAL_RE.match(spec)
        if not im:
            return None
        n, u = int(im.group("n")), im.group("u")
        minutes = n * {"m": 1, "h": 60, "d": 1440}[u]
        return {"type": "interval", "minutes": minutes, "name": m.group("name")}
    if kind == "daily":
        dm = DAILY_RE.match(spec)
        if not dm:
            return None
        return {"type": "daily",
                "time": f"{dm.group('h')}:{dm.group('m')}:{dm.group('s') or '00'}",
                "name": m.group("name")}
    return {"type": kind, "name": m.group("name"), "note": "manual"}


def extract_command(path):
    """正文首个可执行命令；没有则判为 agent-platform prompt。"""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None, "unreadable"
    # ```bash ... ``` 代码块首行
    bm = re.search(r"```(?:bash|sh)\n(.+?)(?:\n```|\Z)", text, re.S)
    if bm:
        first = bm.group(1).strip().split("\n")[0].strip().strip("`")
        if first and not first.startswith("#"):
            return first, "direct"
    # 行首反引号命令
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("`") and s.endswith("`") and len(s) > 4:
            inner = s.strip("`").strip()
            if re.match(r"^(bash|python3?|ssh|curl|systemctl|schtasks) ", inner):
                return inner, "direct"
    return None, "agent-platform"


def trigger_xml(parent, sched):
    triggers = ET.SubElement(parent, _t("Triggers"))
    if sched["type"] == "interval":
        t = ET.SubElement(triggers, _t("TimeTrigger"))
        ET.SubElement(t, _t("StartBoundary")).text = "2026-01-01T00:00:00"
        ET.SubElement(t, _t("Enabled")).text = "true"
        rep = ET.SubElement(t, _t("Repetition"))
        ET.SubElement(rep, _t("Interval")).text = f"PT{sched['minutes']}M"
        ET.SubElement(rep, _t("StopAtDurationEnd")).text = "false"
    elif sched["type"] == "daily":
        t = ET.SubElement(triggers, _t("CalendarTrigger"))
        ET.SubElement(t, _t("StartBoundary")).text = f"2026-01-01T{sched['time']}"
        ET.SubElement(t, _t("Enabled")).text = "true"
        sched_el = ET.SubElement(t, _t("ScheduleByDay"))
        ET.SubElement(sched_el, _t("DaysInterval")).text = "1"
    else:
        t = ET.SubElement(triggers, _t("TimeTrigger"))
        ET.SubElement(t, _t("StartBoundary")).text = "2026-01-01T00:05:00"
        ET.SubElement(t, _t("Enabled")).text = "false"  # weekly/monthly 需人工确认
        c = ET.SubElement(parent, _t("Comment"))
        c.text = f"kind={sched['type']} 需人工确认后启用"


def build_xml(job_id, sched, action_cmd, is_stub):
    task = ET.Element(_t("Task"), version="1.4")
    ri = ET.SubElement(task, _t("RegistrationInfo"))
    ri.append(_el("Description", f"Perpetua {job_id}" + ("（agent运行时占位）" if is_stub else "")))
    trig_parent = task
    trigger_xml(trig_parent, sched)
    princ = ET.SubElement(task, _t("Principals"))
    p = ET.SubElement(princ, _t("Principal"), id="Author")
    ET.SubElement(p, _t("RunLevel")).text = "HighestAvailable"
    ET.SubElement(p, _t("LogonType")).text = "Password"
    settings = ET.SubElement(task, _t("Settings"))
    for k, v in [("MultipleInstancesPolicy", "IgnoreNew"),
                 ("DisallowStartIfOnBatteries", "false"),
                 ("StopIfGoingOnBatteries", "false"),
                 ("AllowHardTerminate", "true"),
                 ("StartWhenAvailable", "true"),
                 ("AllowStartOnDemand", "true"),
                 ("Enabled", "true"),
                 ("ExecutionTimeLimit", "PT2H")]:
        ET.SubElement(settings, _t(k)).text = v
    actions = ET.SubElement(task, _t("Actions"), Context="Author")
    exe = ET.SubElement(actions, _t("Exec"))
    # schtasks 对命令行长度敏感：用 bat 中转
    ET.SubElement(exe, _t("Command")).text = "cmd.exe"
    ET.SubElement(exe, _t("Arguments")).text = f"/c \"{action_cmd}\""
    return minidom.parseString(ET.tostring(task)).toprettyxml(indent="  ", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "tasks_xml"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    files = find_cron_files()
    print(f"[sched] 发现 {len(files)} 个 cron 定义")
    results = []
    for path in files:
        sched = parse_schedule(path)
        if not sched:
            results.append((path, None, "unparsed-filename"))
            continue
        cmd, kind = extract_command(path)
        results.append((path, sched, kind, cmd))

    direct = [r for r in results if len(r) == 4 and r[2] == "direct"]
    plat = [r for r in results if len(r) == 4 and r[2] == "agent-platform"]
    other = [r for r in results if len(r) == 3]
    print(f"[sched] 直接命令: {len(direct)} / agent平台: {len(plat)} / 未解析: {len(other)}")

    if a.dry_run:
        for path, sched, kind, cmd in direct[:5]:
            print(f"  DIRECT {sched['name']}: {cmd[:80]}")
        for path, sched, kind, cmd in plat[:5]:
            print(f"  PLATFORM {sched['name']}: 需agent运行时")
        return 0

    os.makedirs(a.out, exist_ok=True)
    bat_lines = ["@echo off", "REM 由 sched_win.py 生成：批量导入 Task Scheduler",
                 "REM 需管理员权限运行"]
    for path, sched, kind, cmd in [r for r in results if len(r) == 4]:
        job_id = "perpetua-" + re.sub(r"[^A-Za-z0-9_-]+", "-", sched["name"])[:60]
        is_stub = (kind != "direct")
        if is_stub:
            action = f"%PERPETUA_HOME%\\windows_compat\\task_stub.bat {sched['name']}"
        else:
            # bash 脚本调用转 python/windows 等价物；其余原样写入 bat 由人工复核
            action = f"%PERPETUA_HOME%\\windows_compat\\task_direct.bat \"{sched['name']}\""
        xml_bytes = build_xml(job_id, sched, action, is_stub)
        xp = os.path.join(a.out, job_id + ".xml")
        with open(xp, "wb") as f:
            f.write(xml_bytes)
        bat_lines.append(f'schtasks /CREATE /TN "{job_id}" /XML "{job_id}.xml" /F')
    with open(os.path.join(a.out, "import_tasks.bat"), "w", encoding="utf-8") as f:
        f.write("\r\n".join(bat_lines) + "\r\n")
    with open(os.path.join(a.out, "COVERAGE.txt"), "w", encoding="utf-8") as f:
        f.write(f"cron 定义总数: {len(files)}\n直接命令: {len(direct)}\n"
                f"agent平台(占位): {len(plat)}\n未解析: {len(other)}\n\n")
        f.write("== agent平台任务（需在 Windows 部署 agent 调度运行时）==\n")
        for path, sched, kind, cmd in plat:
            f.write(f"- {sched['name']} [{sched['type']}] {path}\n")
    print(f"[sched] XML 已生成: {a.out}（import_tasks.bat + COVERAGE.txt）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
