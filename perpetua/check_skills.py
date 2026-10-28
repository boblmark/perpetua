#!/usr/bin/env python3
"""自定义 skill 校验（2026-10-28，P2 补差距：Skill 版本化 + 模板 + 测试腿）。

检查 ~/workspace/custom-skills/*/：
- SKILL.md 存在
- skill.yaml 存在、可解析、含 name 与 version 字段
- templates/ 如存在则非空（内容型 skill 应有模板；缺失只警告，不判失败）
返回：通过数 / 总数 / 失败明细；有失败时 exit 1。
"""
import glob
import os
import sys

import yaml

BASE = os.path.expanduser("~/workspace/custom-skills")


def main():
    dirs = sorted(d for d in glob.glob(BASE + "/*") if os.path.isdir(d))
    ok, fails, warns = 0, [], []
    for d in dirs:
        name = os.path.basename(d)
        # 嵌套布局（如 viral-content-pipeline/viral-content-pipeline/）：以含 SKILL.md 的子目录为根
        if not os.path.exists(os.path.join(d, "SKILL.md")):
            subs = [s for s in glob.glob(d + "/*") if os.path.isdir(s)
                    and os.path.exists(os.path.join(s, "SKILL.md"))]
            if len(subs) == 1:
                d = subs[0]
        sm = os.path.join(d, "SKILL.md")
        sy = os.path.join(d, "skill.yaml")
        if not os.path.exists(sm):
            fails.append(f"{name}: 缺 SKILL.md")
            continue
        if not os.path.exists(sy):
            fails.append(f"{name}: 缺 skill.yaml")
            continue
        try:
            data = yaml.safe_load(open(sy)) or {}
        except Exception as e:
            fails.append(f"{name}: skill.yaml 解析失败 {e!r}")
            continue
        if not data.get("name"):
            fails.append(f"{name}: skill.yaml 缺 name")
            continue
        if not data.get("version"):
            fails.append(f"{name}: skill.yaml 缺 version")
            continue
        td = os.path.join(d, "templates")
        if os.path.isdir(td) and not glob.glob(td + "/*"):
            warns.append(f"{name}: templates/ 为空")
        ok += 1
    print(f"skills OK: {ok}/{len(dirs)}")
    for w in warns:
        print(f"WARN {w}")
    for f in fails:
        print(f"FAIL {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
