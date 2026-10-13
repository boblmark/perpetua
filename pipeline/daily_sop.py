#!/usr/bin/env python3
"""每日 SOP（数字孪生 DNA v3.1 · 接口模块）。

- 09:00 morning_brief()    实验设计会：今日实验简报
- 21:00 evening_analysis()  实验分析会：今日分析报告
- 23:00 night_evolution()   调用 evolution_engine.daily_evolution()

CLI: python3 daily_sop.py --morning | --evening | --night
全部 stdlib。状态文件落盘在模块同目录 sop_state/ 下，原子写。
"""
import argparse
import datetime
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "sop_state")
sys.path.insert(0, BASE_DIR)

try:
    from atomic_json import atomic_write
except ImportError:
    def atomic_write(path, data, backup=True):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def today_str(tz_offset_hours=8):
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=tz_offset_hours)
    return now.strftime("%Y-%m-%d")


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _read_pipeline_yesterday():
    snap = load_json(os.path.join(BASE_DIR, "dashboard_snapshot.json"), {})
    runs = load_json(os.path.join(BASE_DIR, "pipeline_runs.json"), {})
    if not isinstance(snap, dict):
        snap = {}
    return {
        "published": snap.get("published_24h"),
        "viral": snap.get("viral_24h"),
        "viral_rate": snap.get("viral_rate_24h"),
        "source_files": {
            "dashboard_snapshot.json": bool(snap),
            "pipeline_runs.json": bool(runs),
        },
    }


def _read_ongoing_experiments():
    ab_dir = os.path.join(BASE_DIR, "ab_tests")
    exps = []
    if os.path.isdir(ab_dir):
        for name in sorted(os.listdir(ab_dir)):
            p = os.path.join(ab_dir, name)
            if os.path.isfile(p) and name.endswith(".json"):
                meta = load_json(p, {})
                if isinstance(meta, dict):
                    exps.append({
                        "id": meta.get("id", name.replace(".json", "")),
                        "name": meta.get("name", ""),
                        "status": meta.get("status", "unknown"),
                    })
    return exps


def _read_decay_warnings():
    weights = load_json(os.path.join(BASE_DIR, "topic_weights.json"), {})
    warnings = []
    if isinstance(weights, dict):
        for topic, info in weights.items():
            if isinstance(info, dict) and info.get("decaying"):
                warnings.append({
                    "topic": topic,
                    "drop_pct": info.get("drop_pct"),
                    "action": info.get("action", "降权"),
                })
    return warnings


def _creativity_quota():
    st = load_json(os.path.join(BASE_DIR, "human_creativity_state.json"), {})
    d = today_str()
    used = 0
    if isinstance(st, dict):
        used = st.get("dates", {}).get(d, {}).get("slots_used", 0)
    return {"date": d, "slots_used": used, "slots_total": 2,
            "slots_left": max(0, 2 - used)}


def morning_brief():
    """09:00 实验设计会。返回简报 dict，并打印人类可读版。"""
    date = today_str()
    brief = {
        "date": date,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "type": "morning_brief",
        "yesterday_review": _read_pipeline_yesterday(),
        "ongoing_experiments": _read_ongoing_experiments(),
        "new_experiments_today": [],
        "decay_warnings": _read_decay_warnings(),
        "human_creativity": {
            "solicitation": "大脑今日必须向人类征集 1 个「反直觉」选题想法",
            "rule": "不经过数据验证，直接分配 1-2 个探索位",
            "quota": _creativity_quota(),
            "tag": "source=human_bypass",
        },
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    out = os.path.join(STATE_DIR, "sop_morning_%s.json" % date)
    atomic_write(out, brief)

    lines = []
    lines.append("【今日实验简报】%s" % date)
    lines.append("")
    lines.append("1. 昨日复盘")
    yr = brief["yesterday_review"]
    if yr["published"] is not None:
        lines.append("   - 发布：%s 条 | 爆款：%s 条 | 爆款率：%s"
                     % (yr["published"], yr["viral"], yr["viral_rate"]))
    else:
        lines.append("   - 暂无昨日生产数据（dashboard_snapshot.json 未更新）")
    lines.append("")
    lines.append("2. 进行中实验")
    if brief["ongoing_experiments"]:
        for e in brief["ongoing_experiments"]:
            lines.append("   - %s：%s（%s）" % (e["id"], e["name"], e["status"]))
    else:
        lines.append("   - 当前无进行中实验")
    lines.append("")
    lines.append("3. 今日新实验")
    lines.append("   - 待 09:00 设计会确定（写入 new_experiments_today）")
    lines.append("")
    lines.append("4. 模式衰减预警")
    if brief["decay_warnings"]:
        for w in brief["decay_warnings"]:
            lines.append("   - 警告 %s：下降 %s，建议%s"
                         % (w["topic"], w.get("drop_pct", "?"), w["action"]))
    else:
        lines.append("   - 无衰减预警")
    lines.append("")
    lines.append("5. 人工创意征集（每日固定）")
    q = brief["human_creativity"]["quota"]
    lines.append("   - 大脑向你征集 1 个「反直觉」选题想法")
    lines.append("   - 不经过数据验证，直接分配 1-2 个探索位（今日剩余 %d/2）"
                 % q["slots_left"])
    lines.append("   - 标签：source=human_bypass，进同一因果库回读")
    print("\n".join(lines))
    print("\n[已保存] %s" % out)
    return brief


def evening_analysis():
    """21:00 实验分析会。汇总今日生产 + 实验数据点，输出分析报告。"""
    date = today_str()
    morning = load_json(os.path.join(STATE_DIR, "sop_morning_%s.json" % date), {})
    report = {
        "date": date,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "type": "evening_analysis",
        "today_production": _read_pipeline_yesterday(),
        "experiments_observed": _read_ongoing_experiments(),
        "morning_plan_followed": bool(morning),
        "notes": [],
    }
    if morning and not report["today_production"]["published"]:
        report["notes"].append("早上有简报但当日生产数据为空，请检查 pipeline 是否运行")
    os.makedirs(STATE_DIR, exist_ok=True)
    out = os.path.join(STATE_DIR, "sop_evening_%s.json" % date)
    atomic_write(out, report)

    lines = []
    lines.append("【今日实验分析】%s" % date)
    lines.append("")
    lines.append("早上计划已生成：%s" % ("是" if report["morning_plan_followed"] else "否"))
    lines.append("进行中实验数：%d" % len(report["experiments_observed"]))
    for n in report["notes"]:
        lines.append("注意 %s" % n)
    lines.append("")
    lines.append("结论：数据已汇总，显著性判断由统计引擎在明日 09:00 设计会前完成。")
    print("\n".join(lines))
    print("\n[已保存] %s" % out)
    return report


def night_evolution():
    """23:00 调用进化引擎。evolution_engine 由另一模块实现；不存在则如实记录失败。"""
    date = today_str()
    result = {
        "date": date,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "type": "night_evolution",
        "status": "unknown",
        "detail": "",
    }
    try:
        import evolution_engine
        fn = getattr(evolution_engine, "daily_evolution", None)
        if not callable(fn):
            raise AttributeError("evolution_engine.daily_evolution 不可调用")
        evo_result = fn()
        result["status"] = "ok"
        result["detail"] = str(evo_result)[:2000]
        print("[night_evolution] 进化引擎执行成功")
    except Exception as e:
        result["status"] = "failed"
        result["detail"] = "%s: %s" % (type(e).__name__, e)
        print("[night_evolution] 失败：%s" % result["detail"])
    os.makedirs(STATE_DIR, exist_ok=True)
    out = os.path.join(STATE_DIR, "sop_night_%s.json" % date)
    atomic_write(out, result)
    print("[已保存] %s" % out)
    return result


def selftest():
    print("=== daily_sop 自测 ===")
    b = morning_brief()
    assert b["type"] == "morning_brief" and b["date"] == today_str()
    assert b["human_creativity"]["quota"]["slots_total"] == 2
    print("morning_brief OK（含人工创意征集第5项）")
    r = evening_analysis()
    assert r["type"] == "evening_analysis"
    print("evening_analysis OK")
    n = night_evolution()
    assert n["type"] == "night_evolution" and n["status"] in ("ok", "failed")
    print("night_evolution OK 状态=%s（%s）" % (n["status"], n["detail"][:80]))
    print("自测通过 OK")


def main():
    ap = argparse.ArgumentParser(description="每日 SOP")
    ap.add_argument("--morning", action="store_true", help="09:00 实验设计会")
    ap.add_argument("--evening", action="store_true", help="21:00 实验分析会")
    ap.add_argument("--night", action="store_true", help="23:00 进化引擎")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    ran = False
    if args.morning:
        morning_brief()
        ran = True
    if args.evening:
        evening_analysis()
        ran = True
    if args.night:
        night_evolution()
        ran = True
    if args.selftest or not ran:
        if not ran:
            print("未指定时段，运行自测：")
        selftest()


if __name__ == "__main__":
    main()
