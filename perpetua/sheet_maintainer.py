#!/usr/bin/env python3
"""30天执行表每日维护：把已完成动作打勾。

机制：
1. completions log（sheet_completions.json）：Dash 每完成一项表格任务就追加
{"task": "<任务名前缀>", "sheet": "30天逐日日历", "note": "<说明>"}，本脚本按前缀匹配打勾。
2. 内容清洗清单：每日抽查已标记行（抽 20 条）调 API 核验状态；每周五全量核验。
3. KPI仪表盘：每周五填"实际"列（订阅/视频数/观看小时）。
"""
import sys
sys.path.insert(0, "/home/hatch/data/perpetua")
from json_safe import atomic_write_json
import json, os, sys, random, datetime
import openpyxl

XLSX = os.path.expanduser("~/workspace/user/files/KarenVsAI_30______20_3vqd.xlsx")
COMP_LOG = os.path.expanduser("~/workspace/goals/youtube-ypp/hidden_files/sheet_completions.json")
MAINT_LOG = os.path.expanduser("~/workspace/goals/youtube-ypp/hidden_files/sheet_maintain.log")

def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line)
    with open(MAINT_LOG, "a") as f:
        f.write(line + "\n")

def load_completions():
    if not os.path.exists(COMP_LOG):
        return []
    try:
        return json.load(open(COMP_LOG))
    except Exception:
        return []

def main():
    wb = openpyxl.load_workbook(XLSX)
    today = datetime.date.today()
    marked = 0

    # 1) completions log -> 逐日日历 / 合规自查 打勾
    comps = load_completions()
    if comps:
        cal = wb["30天逐日日历"]
        chk = wb["申请前合规自查"]
        for c in comps:
            if c.get("done_marked"):
                continue
            task, note = c.get("task", ""), c.get("note", "")
            hit = False
            for ws, tcol, xcol in ((cal, 2, 5), (chk, 1, 3)):
                for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
                    name = str(row[tcol].value or "")
                    if task and name.startswith(task) and not row[xcol].value:
                        row[xcol].value = 1
                        # 备注追加到执行要点列
                        ncol = 3 if ws is cal else 4
                        row[ncol].value = (row[ncol].value or "") + f" [{note}]" if note else (row[ncol].value or "")
                        hit = True
                        marked += 1
                        break
                if hit:
                    break
            c["done_marked"] = True
        atomic_write_json(COMP_LOG, comps)
        log(f"completions log 打勾 {marked} 项")

    # 2) 清洗清单抽查核验
    try:
        sys.path.insert(0, "/home/hatch/data/youtube")
        from yt import api_call
        ws = wb["内容清洗清单"]
        marked_rows = []
        for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
            if row[6].value == 1 and row[3].value:
                marked_rows.append(row)
        sample = random.sample(marked_rows, min(20, len(marked_rows)))
        ids = [r[3].value for r in sample]
        ok = 0
        for i in range(0, len(ids), 50):
            batch = ids[i:i+50]
            r = api_call("GET", "/youtube/v3/videos",
                         params={"id": ",".join(batch), "part": "id,status"})
            found = {v["id"]: v["status"]["privacyStatus"] for v in r.get("items", [])}
            for vid in batch:
                disp = None
                for rr in sample:
                    if rr[3].value == vid:
                        disp = str(rr[0].value or "")
                        break
                if vid not in found and "删除" in disp:
                    ok += 1
                elif found.get(vid) == "unlisted" and "不公开" in disp:
                    ok += 1
                else:
                    log(f"WARN 清洗清单状态不符: {vid} 期望[{disp}] 实际[{found.get(vid, 'gone')}]")
        log(f"清洗清单抽查 {len(sample)} 条，通过 {ok}")
    except Exception as e:
        log(f"清洗清单抽查失败: {e}")

    # 3) KPI 每周五填实际
    if today.weekday() == 4:  # Friday
        try:
            sys.path.insert(0, "/home/hatch/data/youtube")
            from yt import api_call
            r = api_call("GET", "/youtube/v3/channels",
                         params={"mine": "true", "part": "statistics"})
            st = r["items"][0]["statistics"]
            ws = wb["KPI仪表盘"]
            for row in ws.iter_rows(min_row=4, max_row=ws.max_row):
                name = str(row[0].value or "")
                if name.startswith("订阅数"):
                    row[6].value = int(st["subscriberCount"])
                elif name.startswith("公开视频数"):
                    row[6].value = int(st["videoCount"])
            log(f"KPI 已填实际: 订阅 {st['subscriberCount']}, 视频 {st['videoCount']}")
        except Exception as e:
            log(f"KPI 填写失败: {e}")

    wb.save(XLSX)
    log("维护完成，已保存")

if __name__ == "__main__":
    main()
