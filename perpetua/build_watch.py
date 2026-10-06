#!/usr/bin/env python3
"""检查 Perpetua Windows 构建状态，完成后通过 inbox 通知用户下载链接。"""
import json, subprocess, sys, os

GH = "/home/hatch/workspace/skills/github/bin/gh_api.py"
REPO = "boblmark/perpetua"
STATE_FILE = "/home/hatch/data/perpetua/build_watch_state.json"

def api(method, path, data=None):
    cmd = ["python3", GH, method, path]
    if data:
        cmd.append(json.dumps(data))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None

def main():
    state = {}
    if os.path.exists(STATE_FILE):
        state = json.load(open(STATE_FILE))
    notified = set(state.get("notified", []))

    d = api("GET", f"/repos/{REPO}/actions/runs?per_page=5")
    if not d:
        return
    for run in d["workflow_runs"]:
        rid = str(run["id"])
        if rid in notified:
            continue
        status, conclusion = run["status"], run.get("conclusion")
        if status == "completed":
            notified.add(rid)
            if conclusion == "success":
                # 找 release 下载链接
                rel = api("GET", f"/repos/{REPO}/releases/tags/{run['head_branch']}")
                # workflow 用 inputs.version 当 tag，尝试找最新 release
                rels = api("GET", f"/repos/{REPO}/releases?per_page=3")
                link = ""
                if rels:
                    link = rels[0].get("html_url", "")
                msg = f"Perpetua Windows 构建成功！下载：{link}" if link else "Perpetua Windows 构建成功，Release 已发布"
            else:
                msg = f"Perpetua Windows 构建失败（{conclusion}），run_id={rid}，请检查 Actions 日志"
            # 写 inbox 通知
            inbox = "/home/hatch/data/collab/inbox.json"
            try:
                data = json.load(open(inbox)) if os.path.exists(inbox) else {"messages": []}
            except:
                data = {"messages": []}
            data.setdefault("messages", []).append({
                "type": "build_notify",
                "run_id": rid,
                "conclusion": conclusion,
                "message": msg,
                "time": run.get("updated_at"),
            })
            json.dump(data, open(inbox, "w"), ensure_ascii=False, indent=2)
            print(f"通知已写入: {msg[:60]}")
    json.dump({"notified": list(notified)}, open(STATE_FILE, "w"))

if __name__ == "__main__":
    main()
