#!/usr/bin/env python3
"""Unit tests for nano-call watermark fix (no network, no server).

Simulates the busy-thread scenario from the 2026-10-13 bug report:
a thread that already has a stale assistant message must NOT yield that
stale text as the response to a new send.

Run: python3 test_nano_call_watermark.py
"""
import importlib.util
import sys
import time

SPEC = importlib.util.spec_from_loader(
    "nano_call",
    loader=None,
    origin="/home/hatch/workspace/custom-skills/local-nanomuse-caller/bin/nano-call",
)
# Load from source file directly (it has no .py extension)
import types
src = open("/home/hatch/workspace/custom-skills/local-nanomuse-caller/bin/nano-call").read()
mod = types.ModuleType("nano_call")
mod.__file__ = "/home/hatch/workspace/custom-skills/local-nanomuse-caller/bin/nano-call"
exec(compile(src, mod.__file__, "exec"), mod.__dict__)

# --- fake clock & fake event stream ---------------------------------------
_now = [1000.0]
_real_sleep = time.sleep
_real_time = time.time


def fake_sleep(s):
    _now[0] += s


def fake_time():
    return _now[0]


time.sleep = fake_sleep
time.time = fake_time

_events = []


def fake_get_events(thread_id, limit=50):
    return list(_events)


mod.get_events = fake_get_events

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def ev(eid, etype, text="", ts="2026-10-14T00:00:00+00:00", final=None):
    e = {"id": eid, "type": etype, "text": text, "ts": ts, "thread": "t_x"}
    if final is not None:
        e["final"] = final
    return e


print("Test 1: busy thread with stale assistant message -> must TIMEOUT, not return stale text")
_now[0] = 1000.0
_events[:] = [
    ev("e1", "user", "old task"),
    ev("a1", "assistant", "STALE OLD REPLY", final=True),
]
wm = mod.get_watermark("t_x")
check("watermark captures last event id", wm == ("a1", "2026-10-14T00:00:00+00:00"))
# Thread stays busy: no new events ever arrive
try:
    mod.wait_for_response("t_x", timeout=30, watermark=wm)
    check("raises NanoCallTimeout on busy thread", False)
except mod.NanoCallTimeout as ex:
    check("raises NanoCallTimeout on busy thread", True)
    check("timeout message mentions thread", "t_x" in str(ex))
except Exception as ex:
    check(f"raises NanoCallTimeout (got {type(ex).__name__})", False)

print("Test 2: new assistant message with final=True -> returns NEW text")
_now[0] = 2000.0
_events[:] = [
    ev("e1", "user", "old task"),
    ev("a1", "assistant", "STALE OLD REPLY", final=True),
]
wm = mod.get_watermark("t_x")
# Simulate: first poll sees nothing new, second poll sees the fresh reply
calls = [0]


def staged_get_events(tid, limit=50):
    calls[0] += 1
    if calls[0] >= 2:
        return list(_events) + [ev("a2", "assistant", "FRESH REPLY", final=True)]
    return list(_events)


mod.get_events = staged_get_events
try:
    out = mod.wait_for_response("t_x", timeout=60, watermark=wm)
    check("returns fresh text, not stale", out == "FRESH REPLY")
except Exception as ex:
    check(f"returns fresh text (got {type(ex).__name__}: {ex})", False)
mod.get_events = fake_get_events

print("Test 3: streaming without final flag -> stability heuristic on NEW stream only")
_now[0] = 3000.0
_events[:] = [ev("e1", "user", "old"), ev("a1", "assistant", "STALE", final=True)]
wm = mod.get_watermark("t_x")
stream = [
    ev("a2", "assistant", "partial..."),   # no final flag: streaming
]
polls = [0]


def stream_get_events(tid, limit=50):
    polls[0] += 1
    return list(_events) + list(stream)


mod.get_events = stream_get_events
try:
    out = mod.wait_for_response("t_x", timeout=60, watermark=wm)
    check("stability heuristic returns streamed text", out == "partial...")
    # must have waited ~10s of stability: polls at 5s each => >=3 polls
    check("waited for stability (>=3 polls)", polls[0] >= 3)
except Exception as ex:
    check(f"stability path (got {type(ex).__name__}: {ex})", False)
mod.get_events = fake_get_events

print("Test 4: watermark id scrolled out -> timestamp fallback still finds new message")
_now[0] = 4000.0
# Server window only holds recent events; watermark id 'a_old' is gone,
# but its ts is known.
wm = ("a_old", "2026-10-14T00:00:00+00:00")
_events[:] = [
    ev("a9", "assistant", "NEWER VIA TS", ts="2026-10-14T00:00:05+00:00", final=True),
]
got = mod._events_after(list(_events), *wm)
check("ts fallback returns the newer event",
      len(got) == 1 and got[0]["id"] == "a9")

print("Test 5: watermark unresolvable -> fail safe, returns nothing new")
wm = ("missing_id", None)
_events[:] = [ev("a1", "assistant", "STALE", final=True)]
got = mod._events_after(list(_events), *wm)
check("fail-safe empty list", got == [])

print("Test 6: fresh thread (no watermark) -> everything is new")
_events[:] = [ev("a1", "assistant", "HELLO", final=True)]
_now[0] = 5000.0
try:
    out = mod.wait_for_response("t_x", timeout=30, watermark=(None, None))
    check("no-watermark path returns message", out == "HELLO")
except Exception as ex:
    check(f"no-watermark path (got {type(ex).__name__}: {ex})", False)

time.sleep = _real_sleep
time.time = _real_time

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
