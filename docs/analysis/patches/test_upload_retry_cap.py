# -*- coding: utf-8 -*-
"""F3 / F4 / F5 收敛性测试（2026-10-31，基线 af3ae58）

被测对象是两个真实模块文件（不是仿真模型）：
  - 原始：<仓库根>/perpetua/auto_pipeline.py（自动向上查找，兼容两种目录布局）
  - 补丁：把 f3_f4_f5_upload_retry_cap.patch 应用到临时副本后得到
           —— 测的是**要发布的补丁本身**，不是某份手工改的 preview

设计要点（都是踩过的坑）：
  1. 时钟必须可控。F3 的判定是"等了多久"而不是"试了几次"，用真实时钟
     跑不出 6 小时；用固定假时钟又测不出"等太久"。故每 tick 前进 20 分钟。
  2. 必须测"不该放弃时不放弃"。只测"故障持续会放弃"，会把任何过早放弃的
     实现都判成通过——这正是 cap=6（2h）那版补丁的漏洞：spacing 是 4 小时
     发布间隔门，2 小时放弃会把正常等待误杀。
  3. 每个用例独立 try/except。一条用例抛异常不该让后面的用例不跑、summary 不打印。
  4. 不写源码字符串匹配。`"xxx") < ` 这类断言对写法一变就假阴性，改用行为断言
     + 两处真正必要的 AST 结构断言。

运行：python analysis/patches/test_upload_retry_cap.py
"""
import ast
import atexit
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH_FILE = os.path.join(HERE, "f3_f4_f5_upload_retry_cap.patch")

TICK_MIN = 20          # collect 周期
TICKS = 40             # 40 × 20min = 13.3h，足够越过 6h 窗口
EXPECTED_ORIG_SHA = None   # 首次运行留空；不匹配只 WARN 不 FAIL
FAIL = []
WARN = []
ORIGINAL = None
PATCHED = None


def _find_original():
    """两条布局都支持：
      仓库内   <repo>/docs/analysis/patches/ → <repo>/perpetua/auto_pipeline.py
      本地开发 <root>/analysis/patches/      → <root>/repo/perpetua/auto_pipeline.py
    """
    cands = []
    d = HERE
    for _ in range(6):
        cands.append(os.path.join(d, "perpetua", "auto_pipeline.py"))
        d = os.path.dirname(d)
    cands.append(os.path.join(HERE, "..", "..", "repo", "perpetua", "auto_pipeline.py"))
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    raise FileNotFoundError(
        "找不到 perpetua/auto_pipeline.py，试过：\n  " + "\n  ".join(cands))


def _build_patched(original):
    """把补丁应用到临时副本，测的是**要发布的那个补丁**，不是某份 preview。

    顺带校验：本地 preview（若存在）必须与补丁应用结果逐字节一致，
    否则说明 patch 与 preview 已经漂移。
    """
    tmp = tempfile.mkdtemp(prefix="perpetua_patch_")
    atexit.register(shutil.rmtree, tmp, True)
    os.makedirs(os.path.join(tmp, "perpetua"))
    dst = os.path.join(tmp, "perpetua", "auto_pipeline.py")
    shutil.copy2(original, dst)
    r = subprocess.run(["git", "apply", "-p1", PATCH_FILE],
                       cwd=tmp, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"补丁应用失败：{r.stderr.strip()[:300]}")
    preview = os.path.join(HERE, "preview", "auto_pipeline.py")
    if os.path.isfile(preview):
        a = hashlib.sha256(open(dst, "rb").read()).hexdigest()
        b = hashlib.sha256(open(preview, "rb").read()).hexdigest()
        if a != b:
            WARN.append("preview/ 与补丁应用结果不一致，以补丁为准")
    return dst


def _install_stubs():
    if "fcntl" not in sys.modules:
        f = types.ModuleType("fcntl")
        f.LOCK_EX = f.LOCK_SH = f.LOCK_UN = f.LOCK_NB = 0
        f.flock = lambda *a, **k: None
        f.fcntl = lambda *a, **k: None
        sys.modules["fcntl"] = f
    if "queue_db" not in sys.modules:
        q = types.ModuleType("queue_db")
        q.pipeline_load = lambda: []
        q.pipeline_save = lambda *a, **k: None
        q.privateq_load = lambda: []
        q.privateq_save = lambda *a, **k: None
        sys.modules["queue_db"] = q


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mod.pipeline_log = lambda *a, **k: None
    mod.notify_inbox = lambda *a, **k: None
    return mod


class Clock:
    """可控时钟：每个 tick 前进 TICK_MIN，tick 内所有 now_iso() 返回同一值。"""

    def __init__(self, start=None):
        self.t = start or datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)

    def now_iso(self):
        return self.t.isoformat()

    def tick(self):
        self.t = self.t + timedelta(minutes=TICK_MIN)


def check(cond, label, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAIL.append(label)


def case(fn):
    """用例隔离：任何异常记 FAIL，不中断后续用例。"""
    def wrapper(*a, **k):
        try:
            fn(*a, **k)
        except Exception as ex:
            FAIL.append(f"{fn.__name__} 抛异常: {type(ex).__name__}: {ex}")
            print(f"  FAIL  {fn.__name__} 抛异常: {type(ex).__name__}: {ex}")
    return wrapper


# ---------- F3 原始：必须证明"没有上限" ----------
@case
def t1_f3_original_unbounded(orig):
    print("\n[T1] 原始 F3：spacing 持续命中，应永不放弃")
    clk = Clock()
    orig.now_iso = clk.now_iso
    calls = {"n": 0}

    def up(video, title, description, template=None, privacy="private"):
        calls["n"] += 1
        return "[gate1:错峰] 不在可上传窗口"

    orig._do_upload = up
    item = {"topic": "t", "title": "T", "status": "ready_to_upload",
            "video_file": "/tmp/x.mp4"}
    for _ in range(TICKS):
        orig._auto_upload_private(item)
        clk.tick()
    check(calls["n"] == TICKS, f"{TICKS} 轮全部重传（无任何停止条件）", f"{calls['n']} 次")
    check(item.get("status") == "ready_to_upload", "状态始终停在 ready_to_upload",
          item.get("status"))
    check(not item.get("upload_spacing_exhausted"), "无停止标记")


# ---------- F3 补丁：故障持续 → 到窗口才放弃 ----------
@case
def t2_f3_patched_gives_up_after_window(mod):
    print("\n[T2] 补丁 F3：spacing 持续命中，应在 6h 窗口后放弃")
    clk = Clock()
    mod.now_iso = clk.now_iso
    calls = {"n": 0}

    def up(video, title, description, template=None, privacy="private"):
        calls["n"] += 1
        return "[gate1:错峰]"

    mod._do_upload = up
    item = {"topic": "t", "title": "T", "status": "ready_to_upload",
            "video_file": "/tmp/x.mp4"}
    exhaust_tick = None
    for i in range(TICKS):
        mod._auto_upload_private(item)
        if item.get("upload_spacing_exhausted") and exhaust_tick is None:
            exhaust_tick = i + 1
        clk.tick()
    # 6h / 20min = 18 个间隔 → 第 19 轮首次超窗
    check(exhaust_tick is not None, "有限轮内触发停止", f"第 {exhaust_tick} 轮")
    check(exhaust_tick is not None and exhaust_tick >= 18,
          "不早于 6h 窗口放弃（>=18 轮）", str(exhaust_tick))
    check(exhaust_tick is not None and exhaust_tick <= 20,
          "也不拖过窗口太久（<=20 轮）", str(exhaust_tick))
    check(calls["n"] <= 21, "上传调用次数有界", f"{calls['n']} 次")
    check(item.get("upload_gate_held") is True, "转 upload_gate_held（Q9 24h 链路）")
    check(mod._upload_gate_ok(item) is False, "_upload_gate_ok 拦住后续重试")


# ---------- F3 补丁：关键反向用例 ----------
@case
def t3_f3_patched_must_not_give_up_early(mod):
    print("\n[T3] 补丁 F3：spacing 持续 3.3h 后自然解除，不得转人工")
    clk = Clock()
    mod.now_iso = clk.now_iso
    seq = {"n": 0}

    def up(video, title, description, template=None, privacy="private"):
        seq["n"] += 1
        return "[gate1:错峰]" if seq["n"] <= 10 else "abcdefghijk"

    def enq(video_id, title, slot=None, review_score=None, video_file=None):
        return {"status": "ok", "slot": "23:30"}

    mod._do_upload = up
    mod._enqueue_private_flip = enq
    item = {"topic": "t", "title": "T", "status": "ready_to_upload",
            "video_file": "/tmp/x.mp4"}
    for _ in range(11):
        mod._auto_upload_private(item)
        clk.tick()
    check(not item.get("upload_spacing_exhausted"),
          "3.3h 的合法等待未被判为卡死（cap=6/2h 的旧设计会在这里失败）")
    check(item.get("status") == "uploaded_private", "第 11 轮正常上传成功",
          item.get("status"))
    check(not item.get("upload_spacing_retries"), "成功后计数清零",
          str(item.get("upload_spacing_retries")))


# ---------- F4 / F5 ----------
@case
def t4_f4_throttle_bounded(mod):
    print("\n[T4] 补丁 F4：privateq 节流持续拒绝")
    calls = {"n": 0}

    def enq(video_id, title, slot=None, review_score=None, video_file=None):
        calls["n"] += 1
        return {"status": "throttle_deferred", "throttle_reason": "slot_full"}

    mod._enqueue_private_flip = enq
    item = {"topic": "t", "title": "T", "status": "uploaded_no_queue",
            "video_id": "abcdefghijk"}
    term = None
    for i in range(TICKS):
        mod._retry_enqueue_privateq(item)
        if item.get("status") == "upload_permanently_failed" and term is None:
            term = i + 1
    cap = mod.MAX_THROTTLE_DEFERS
    check(term is not None, "有限轮内进终态", f"第 {term} 轮")
    check(term is not None and term == cap, f"恰在 {cap} 次触发（不多不少）", str(term))
    check(calls["n"] == cap, "入队调用次数等于上限", f"{calls['n']} 次")
    check(item.get("video_id") == "abcdefghijk", "终态保留 video_id（可人工排期）")


@case
def t5_f5_exception_bounded(mod):
    print("\n[T5] 补丁 F5：_enqueue_private_flip 持续抛异常")

    def boom(*a, **k):
        raise RuntimeError("privateq 文件被占用")

    mod._enqueue_private_flip = boom
    item = {"topic": "t", "title": "T", "status": "uploaded_no_queue",
            "video_id": "abcdefghijk"}
    term = None
    for i in range(TICKS):
        mod._retry_enqueue_privateq(item)
        if item.get("status") == "upload_permanently_failed" and term is None:
            term = i + 1
    cap = mod.MAX_ENQUEUE_FAILS
    check(term is not None, "有限轮内进终态", f"第 {term} 轮")
    check(term is not None and term == cap, f"恰在 {cap} 次触发", str(term))


@case
def t6_enqueue_success_clears(mod):
    print("\n[T6] 补丁：节流 3 次后恢复，计数必须清零")
    seq = {"n": 0}

    def enq(video_id, title, slot=None, review_score=None, video_file=None):
        seq["n"] += 1
        if seq["n"] <= 3:
            return {"status": "throttle_deferred", "throttle_reason": "slot_full"}
        return {"status": "ok", "slot": "23:30"}

    mod._enqueue_private_flip = enq
    item = {"topic": "t", "title": "T", "status": "uploaded_no_queue",
            "video_id": "abcdefghijk"}
    for _ in range(4):
        mod._retry_enqueue_privateq(item)
    check(item.get("status") == "uploaded_private", "转 uploaded_private",
          item.get("status"))
    check(not item.get("throttle_defer_count"), "throttle_defer_count 已清",
          str(item.get("throttle_defer_count")))


# ---------- 结构断言（AST，只保留两条真正必要的） ----------
@case
def t7_terminal_membership(_=None):
    print("\n[T7] 结构：upload_permanently_failed 必须在 _TERMINAL 里（否则占坑不释放）")
    tree = ast.parse(open(PATCHED, encoding="utf-8").read())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_TERMINAL" for t in node.targets):
            vals = {e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            found = "upload_permanently_failed" in vals
    check(found, "_TERMINAL 含 upload_permanently_failed")


@case
def t8_call_site_wired(_=None):
    print("\n[T8] 结构：collect_results 必须真的调用 _retry_enqueue_privateq")
    tree = ast.parse(open(PATCHED, encoding="utf-8").read())
    ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "collect_results":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                        and sub.func.id == "_retry_enqueue_privateq":
                    ok = True
    check(ok, "collect_results 内有 _retry_enqueue_privateq(...) 调用")


def baseline_note():
    h = hashlib.sha256(open(ORIGINAL, "rb").read()).hexdigest()
    print(f"\n[基线] 原始文件 sha256 = {h[:16]}…")
    print(f"        路径 = {os.path.relpath(ORIGINAL, HERE)}")
    if EXPECTED_ORIG_SHA and h != EXPECTED_ORIG_SHA:
        WARN.append("原始文件已变更（repo/ 同步了新版本）")
        print("  WARN  原始文件与记录不一致：F3 若已被上游修复，T1 会 FAIL，"
              "那是基线变了，不是补丁错了")
    print("  提示   repo/ 每 30–60 分钟被 auto-sync 覆盖；结论只在 af3ae58 上成立")


def main():
    global ORIGINAL, PATCHED
    _install_stubs()
    ORIGINAL = _find_original()
    PATCHED = _build_patched(ORIGINAL)
    orig = load(ORIGINAL, "ap_original")
    patched = load(PATCHED, "ap_patched")
    baseline_note()
    t1_f3_original_unbounded(orig)
    t2_f3_patched_gives_up_after_window(patched)
    t3_f3_patched_must_not_give_up_early(patched)
    t4_f4_throttle_bounded(patched)
    t5_f5_exception_bounded(patched)
    t6_enqueue_success_clears(patched)
    t7_terminal_membership()
    t8_call_site_wired()
    print()
    if FAIL:
        print(f"FAIL — {len(FAIL)} 项未通过：")
        for f in FAIL:
            print("  -", f)
    else:
        print("PASS — 三条路径补丁后均有界收敛；原始 F3 无界；"
              "6h 窗口内不误杀合法等待")
    for w in WARN:
        print("WARN —", w)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
