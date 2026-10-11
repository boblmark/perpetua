#!/usr/bin/env python3
"""
kb_context.py — 知识库统一拉取入口（2026-10-09 三脑评审 C 方案 Commit 1）

管线各阶段动手前调用 get_context() 拉取相关知识。
确定性相关性打分，无 ML，零 LLM 调用。

用法：
    from kb.kb_context import get_context
    ctx = get_context("prompt_gen", decision_hint="injected_top3_directive")
    for e in ctx:
        print(e["entry_id"], e["relevance_score"], e["snippet"][:80])
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

try:
    import yaml
except ImportError:
    yaml = None

KB_DIR = Path("/home/hatch/data/perpetua/kb")
SOURCES_YAML = KB_DIR / "kb_sources.yaml"
USAGE_LEDGER = KB_DIR / "kb_usage_ledger.jsonl"

TaskType = Literal["topic_gen", "prompt_gen", "qc", "review", "publish", "post_publish"]

# 源优先级（tie-break 用，数字越小越优先）
_SOURCE_PRIORITY = {
    "dynamic_constraints": 1,
    "criteria": 2,
    "publish_cadence": 3,
    "deep_dive_findings": 4,
    "brain_review_index": 5,
    "notebooklm_export": 6,
    "dud_feedback": 7,
}

# 内存缓存：key -> (expire_ts, entries, mtime_snapshot)
_cache: dict = {}
CACHE_TTL = 3600


class KBEntry(TypedDict):
    entry_id: str
    source: str
    snippet: str
    relevance_score: float
    version: str | None
    fetched_at: str


def _load_sources() -> list:
    if not SOURCES_YAML.exists():
        return []
    if yaml is None:
        # 无 yaml 时用最小内置注册（只读 json 源）
        return _builtin_sources()
    with open(SOURCES_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _builtin_sources() -> list:
    """yaml 缺失时的最小 fallback"""
    return [
        {"key": "dynamic_constraints",
         "path": "/home/hatch/data/perpetua/dynamic_constraints.json",
         "adapter": "json_file", "task_types": ["prompt_gen", "qc", "topic_gen"],
         "extract": {"entries_from": "directives",
                      "entry_id_template": "dynamic_constraints:{index}"}},
    ]


def _read_json_tolerant(path: str):
    try:
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl_tail(path: str, n: int = 14) -> list:
    try:
        p = Path(path)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        out = []
        for ln in lines[-n:]:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
        return out
    except Exception:
        return []


def _extract_entries(src: dict) -> list[dict]:
    """按 adapter 从源文件抽取条目，返回 [{entry_id, source, text, version, task_types}]"""
    key = src["key"]
    path = src["path"]
    adapter = src.get("adapter", "json_file")
    task_types = src.get("task_types", [])
    extract = src.get("extract", {})
    entries_from = extract.get("entries_from", "")
    tmpl = extract.get("entry_id_template", f"{key}:{{index}}")

    entries = []
    version = None

    if adapter == "json_file":
        data = _read_json_tolerant(path)
        if data is None:
            return []
        version = str(data.get("version", data.get("generated_at", "")))[:20] or None
        items = []
        if entries_from == "directives":
            items = data.get("directives", [])
        elif entries_from == "rules":
            # criteria.json：把规则拍平成条目
            rules = data.get("rules", data)
            if isinstance(rules, dict):
                items = [f"{k}: {v}" for k, v in rules.items()]
            elif isinstance(rules, list):
                items = rules
        elif entries_from == "cadence":
            c = data
            items = [f"posts_per_day {c.get('posts_per_day')}, "
                     f"interval_hours {c.get('interval_hours')}, "
                     f"enforced={c.get('enforced')}"]
        elif entries_from == "findings":
            raw = data.get("findings", [])
            items = []
            for i in raw:
                if isinstance(i, dict):
                    items.append({
                        "_text": f"[{i.get('device', '?')}] {i.get('issue', '')} → "
                                 f"{i.get('recommendation', '')}",
                        "_device": i.get("device", "general"),
                    })
                else:
                    items.append({"_text": str(i), "_device": "general"})
        elif entries_from == "verdicts":
            items = data.get("verdicts", [])
            if items and isinstance(items[0], dict):
                items = [f"{i.get('title', '')}: {i.get('verdict', '')}" for i in items]
        elif entries_from == "notes":
            items = data.get("notes", [])
            if items and isinstance(items[0], dict):
                items = [i.get("content", i.get("title", "")) for i in items]
        else:
            # 通用：尝试 directives / items / 直接列表
            if isinstance(data, dict):
                for k in ("directives", "items", "entries", "findings"):
                    if isinstance(data.get(k), list):
                        items = data[k]
                        break
            elif isinstance(data, list):
                items = data
        for i, it in enumerate(items):
            if isinstance(it, dict) and "_text" in it:
                text = it["_text"]
                fmt_kwargs = {"index": i, "device": it.get("_device", "general")}
            else:
                text = it if isinstance(it, str) else json.dumps(it, ensure_ascii=False)
                fmt_kwargs = {"index": i}
                if isinstance(it, dict):
                    fmt_kwargs["device"] = it.get("device", "general")
            try:
                eid = tmpl.format(**fmt_kwargs)
            except KeyError:
                eid = f"{key}:{i}"
            entries.append({
                "entry_id": eid,
                "source": key,
                "text": text,
                "version": version,
                "task_types": task_types,
            })
    elif adapter == "jsonl_tail":
        n = 14
        if entries_from.startswith("tail_"):
            try:
                n = int(entries_from.split("_")[1])
            except Exception:
                pass
        items = _read_jsonl_tail(path, n)
        for i, it in enumerate(items):
            text = json.dumps(it, ensure_ascii=False)
            entries.append({
                "entry_id": tmpl.format(index=i),
                "source": key,
                "text": text,
                "version": None,
                "task_types": task_types,
            })
    return entries


def _score(entry: dict, task_type: str, device: str | None,
           video_key: str | None, source_mtime_age_days: float) -> float:
    """确定性相关性打分（规格公式，无 ML）"""
    score = 0.0
    if task_type in entry.get("task_types", []):
        score = 1.0
    # device_scope / video_specific 暂未在源中定义，保留扩展点
    if entry["source"] in ("deep_dive_findings", "brain_review_index"):
        score += 0.10 * max(0.0, 1.0 - source_mtime_age_days / 180.0)
    return min(1.0, round(score, 2))


def _source_mtime_age_days(path: str) -> float:
    try:
        mtime = Path(path).stat().st_mtime
        return (time.time() - mtime) / 86400.0
    except Exception:
        return 9999.0


def get_context(
    task_type: TaskType,
    device: str | None = None,
    video_key: str | None = None,
    limit: int = 5,
    snippet_chars: int = 400,
    min_relevance: float = 0.20,
    use_cache: bool = True,
    decision_hint: str = "read_only",
) -> list[KBEntry]:
    """
    拉取与任务相关的知识条目。

    decision_hint 会写入使用账本（Commit 2 的 @ledger_logged 装饰器消费）。
    """
    # 参数钳制
    limit = max(1, min(int(limit), 20))
    snippet_chars = max(50, min(int(snippet_chars), 2000))
    if limit * snippet_chars > 2000:
        # 预算硬上限：优先保证条数，压缩单条长度
        snippet_chars = max(50, 2000 // limit)

    cache_key = (task_type, device, video_key, limit, snippet_chars, min_relevance)

    # 缓存检查（含源文件 mtime 失效）
    if use_cache and cache_key in _cache:
        expire_ts, entries, mtime_snap = _cache[cache_key]
        if time.time() < expire_ts:
            still_valid = True
            for src_key, old_mtime in mtime_snap.items():
                for src in _load_sources():
                    if src["key"] == src_key:
                        try:
                            cur = Path(src["path"]).stat().st_mtime
                        except Exception:
                            cur = -1
                        if cur != old_mtime:
                            still_valid = False
                            break
                if not still_valid:
                    break
            if still_valid:
                return entries

    sources = _load_sources()
    scored = []
    mtime_snap = {}
    for src in sources:
        try:
            mtime_snap[src["key"]] = Path(src["path"]).stat().st_mtime
        except Exception:
            mtime_snap[src["key"]] = -1
        entries = _extract_entries(src)
        age = _source_mtime_age_days(src["path"])
        for e in entries:
            s = _score(e, task_type, device, video_key, age)
            if s >= min_relevance:
                scored.append((e, s))

    # 排序：分数 desc，tie-break 按源优先级，再按 entry_id
    scored.sort(key=lambda x: (
        -x[1],
        _SOURCE_PRIORITY.get(x[0]["source"], 99),
        x[0]["entry_id"],
    ))

    now = datetime.now(timezone.utc).isoformat()
    result: list[KBEntry] = []
    for e, s in scored[:limit]:
        text = e["text"]
        snippet = text[:snippet_chars]
        result.append({
            "entry_id": e["entry_id"],
            "source": e["source"],
            "snippet": snippet,
            "relevance_score": s,
            "version": e["version"],
            "fetched_at": now,
        })

    if use_cache:
        _cache[cache_key] = (time.time() + CACHE_TTL, result, mtime_snap)

    # Commit 2：使用账本 — 每次调用记一行（装饰器逻辑内联，避免循环导入）
    _log_usage(result, task_type, decision_hint)

    return result


def _log_usage(entries: list[KBEntry], task_type: str, decision_hint: str):
    """写 kb_usage_ledger.jsonl：ts/entry_id/reader/task_type/decision_influenced/relevance_score/snippet_chars"""
    import inspect
    # reader 取调用方的 file:line
    reader = "unknown"
    try:
        frame = inspect.currentframe()
        # _log_usage <- get_context <- caller
        caller = frame.f_back.f_back if frame and frame.f_back else None
        if caller is not None:
            fn = caller.f_code.co_filename
            ln = caller.f_lineno
            # 缩短为相对路径
            try:
                fn = str(Path(fn).relative_to("/home/hatch/data"))
            except Exception:
                fn = Path(fn).name
            reader = f"{fn}:{ln}"
    except Exception:
        pass
    finally:
        try:
            del frame
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()
    try:
        with open(USAGE_LEDGER, "a", encoding="utf-8") as f:
            for e in entries:
                rec = {
                    "ts": now,
                    "entry_id": e["entry_id"],
                    "reader": reader,
                    "task_type": task_type,
                    "decision_influenced": decision_hint,
                    "relevance_score": e["relevance_score"],
                    "snippet_chars": len(e["snippet"]),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 账本写失败不阻塞主流程


if __name__ == "__main__":
    import sys
    tt = sys.argv[1] if len(sys.argv) > 1 else "prompt_gen"
    ctx = get_context(tt, use_cache=False)
    print(f"task_type={tt}, got {len(ctx)} entries")
    for e in ctx[:5]:
        print(f"  [{e['relevance_score']:.2f}] {e['entry_id']} ({e['source']})")
        print(f"    {e['snippet'][:100]}")
