#!/usr/bin/env python3
"""dispatcher_nano_bridge 的 mock 测试。

不实际调用 dispatcher（VPS）或 nanoMuse，用 mock 验证桥接逻辑：
1. 超时任务能被正确识别
2. job → instruction 翻译正确
3. nano 结果 → dispatcher 结果翻译正确
4. 非目标 consumer 的任务不被处理
5. 已有 done 结果的任务不被重复处理
6. 手动模式能处理指定 job
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatcher_nano_bridge as B


def _make_job(job_id="job-001", consumer="muse-main", minutes_ago=45,
              job_type="generate_video"):
    queued = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return B.DispatcherJob(
        job_id=job_id,
        job_type=job_type,
        consumer=consumer,
        payload={"instruction": "a cute cat video", "video_count": 1},
        idempotency_key=f"key-{job_id}",
        queued_at=queued,
    )


def test_find_timed_out():
    """超时识别：只有 muse-main + 超时 + 无 done 的才入选。"""
    mock_disp = MagicMock(spec=B.DispatcherClient)
    mock_disp.list_pending_jobs.return_value = [
        _make_job("old-1", minutes_ago=45),           # 超时 → 入选
        _make_job("fresh-1", minutes_ago=5),          # 太新 → 不入选
        _make_job("other-1", consumer="other", minutes_ago=60),  # 非目标 → 不入选
        _make_job("done-1", minutes_ago=90),          # 已有 done → 不入选
    ]
    # done-1 已有结果
    mock_disp.job_already_done.side_effect = lambda jid: jid == "done-1"

    bridge = B.Bridge(dispatcher=mock_disp, nano=MagicMock(), timeout_min=30)
    found = bridge.find_timed_out()
    ids = [j.job_id for j in found]
    assert ids == ["old-1"], f"期望 ['old-1']，实际 {ids}"
    print("PASS: test_find_timed_out")


def test_job_to_instruction_video():
    """视频任务翻译包含关键字段。"""
    job = _make_job(job_type="generate_video")
    instr = B.job_to_instruction(job)
    assert "[BRIDGE JOB]" in instr
    assert job.job_id in instr
    assert "generate_video" in instr
    assert "9:16" in instr
    assert "a cute cat video" in instr
    assert "DONE:" in instr and "FAILED:" in instr
    print("PASS: test_job_to_instruction_video")


def test_job_to_instruction_custom():
    """custom 任务翻译。"""
    job = _make_job(job_type="custom")
    job.payload = {"instruction": "do something custom"}
    instr = B.job_to_instruction(job)
    assert "do something custom" in instr
    print("PASS: test_job_to_instruction_custom")


def test_parse_nano_result():
    """nano 结果解析。"""
    # DONE 带文件路径
    ok, content, _ = B.parse_nano_result(
        {"type": "assistant", "text": "处理完成\nDONE: /tmp/video.mp4\n备注"})
    assert ok and content == "/tmp/video.mp4", f"DONE 解析失败: {content}"

    # FAILED
    ok, content, _ = B.parse_nano_result(
        {"type": "assistant", "text": "FAILED: 额度不足"})
    assert not ok and "额度不足" in content

    # tool 事件带路径
    ok, content, _ = B.parse_nano_result(
        {"type": "tool", "output": "Video generated: /home/x/out.mp4 (123 bytes)"})
    assert ok and content == "/home/x/out.mp4", f"tool 解析失败: {content}"

    print("PASS: test_parse_nano_result")


def test_process_job_video_success():
    """完整流程：video 任务成功 → 交付 → 归档。"""
    job = _make_job("vid-001", minutes_ago=45)

    # mock nanoMuse：返回带文件路径的 DONE
    mock_nano = MagicMock(spec=B.NanoMuseClient)
    mock_nano.create_thread.return_value = "t_mock123"
    mock_nano.send.return_value = {}
    mock_nano.wait_for_completion.return_value = {
        "type": "assistant",
        "text": "DONE: /tmp/fake_video.mp4",
    }

    # mock dispatcher
    mock_disp = MagicMock(spec=B.DispatcherClient)

    # 创建假视频文件
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake video data")
        fake_path = f.name
    # 让 parse 找到这个真实文件：patch parse 行为
    # 更简单：直接让 wait_for_completion 返回指向 fake_path 的 DONE
    mock_nano.wait_for_completion.return_value = {
        "type": "assistant",
        "text": f"DONE: {fake_path}",
    }
    mock_disp.deliver_result.return_value = "vid-001.mp4"

    bridge = B.Bridge(dispatcher=mock_disp, nano=mock_nano)
    result = bridge.process_job(job)

    assert result.success, f"期望成功，error={result.error}"
    assert result.output_file == "vid-001.mp4"
    assert result.nano_thread_id == "t_mock123"
    # 验证调用链
    mock_nano.create_thread.assert_called_once()
    mock_nano.send.assert_called_once()
    mock_disp.deliver_result.assert_called_once()
    args, kwargs = mock_disp.deliver_result.call_args
    assert args[0] == "vid-001" and kwargs.get("status") == "done"
    mock_disp.mark_pending_done.assert_called_once_with("vid-001")

    os.unlink(fake_path)
    print("PASS: test_process_job_video_success")


def test_process_job_nano_failed():
    """nano 失败 → 写 failed 结果 → 归档。"""
    job = _make_job("fail-001", minutes_ago=45)

    mock_nano = MagicMock(spec=B.NanoMuseClient)
    mock_nano.create_thread.return_value = "t_fail"
    mock_nano.wait_for_completion.return_value = {
        "type": "assistant", "text": "FAILED: 模型额度用完了"}

    mock_disp = MagicMock(spec=B.DispatcherClient)

    bridge = B.Bridge(dispatcher=mock_disp, nano=mock_nano)
    result = bridge.process_job(job)

    assert not result.success
    assert "额度" in result.error
    # 失败也要写结果 + 归档（避免永远 pending）
    mock_disp.deliver_result.assert_called_once()
    args, kwargs = mock_disp.deliver_result.call_args
    assert kwargs.get("status") == "failed"
    mock_disp.mark_pending_done.assert_called_once_with("fail-001")
    print("PASS: test_process_job_nano_failed")


def test_process_job_dry_run():
    """dry-run 不实际调用。"""
    job = _make_job("dry-001", minutes_ago=45)
    mock_nano = MagicMock(spec=B.NanoMuseClient)
    mock_disp = MagicMock(spec=B.DispatcherClient)

    bridge = B.Bridge(dispatcher=mock_disp, nano=mock_nano, dry_run=True)
    result = bridge.process_job(job)

    assert result.success
    mock_nano.create_thread.assert_not_called()
    mock_disp.deliver_result.assert_not_called()
    print("PASS: test_process_job_dry_run")


def test_run_single():
    """手动模式：读取指定 job 并处理。"""
    mock_disp = MagicMock(spec=B.DispatcherClient)
    mock_disp.read_job_file.return_value = {
        "job_id": "manual-001",
        "job_type": "custom",
        "consumer": "muse-main",
        "payload": json.dumps({"instruction": "manual task"}),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }

    mock_nano = MagicMock(spec=B.NanoMuseClient)
    mock_nano.create_thread.return_value = "t_manual"
    mock_nano.wait_for_completion.return_value = {
        "type": "assistant", "text": "DONE: 任务完成"}

    bridge = B.Bridge(dispatcher=mock_disp, nano=mock_nano)
    result = bridge.run_single("manual-001")

    assert result.success
    mock_disp.read_job_file.assert_called_once_with("manual-001")
    print("PASS: test_run_single")


def test_run_single_not_found():
    """手动模式：job 不存在抛异常。"""
    mock_disp = MagicMock(spec=B.DispatcherClient)
    mock_disp.read_job_file.return_value = {}

    bridge = B.Bridge(dispatcher=mock_disp, nano=MagicMock())
    try:
        bridge.run_single("nope-999")
        assert False, "应该抛异常"
    except RuntimeError as e:
        assert "找不到" in str(e)
    print("PASS: test_run_single_not_found")


def test_valid_job_id():
    """job_id 校验防注入。"""
    assert B._valid_job_id("abc-123_XYZ")
    assert not B._valid_job_id("../etc/passwd")
    assert not B._valid_job_id("a/b")
    assert not B._valid_job_id("")
    print("PASS: test_valid_job_id")


def test_no_claim_no_consumer_change():
    """核心安全约束：bridge 绝不调用 claim_job，也没有改 consumer 的代码路径。"""
    import inspect
    src = inspect.getsource(B.Bridge)
    assert "claim_job" not in src, "Bridge 不应包含 claim_job 调用"
    # deliver_result / mark_pending_done 不应碰 consumer 字段
    disp_src = inspect.getsource(B.DispatcherClient)
    assert "claim_job" not in disp_src
    print("PASS: test_no_claim_no_consumer_change")


def main():
    tests = [
        test_find_timed_out,
        test_job_to_instruction_video,
        test_job_to_instruction_custom,
        test_parse_nano_result,
        test_process_job_video_success,
        test_process_job_nano_failed,
        test_process_job_dry_run,
        test_run_single,
        test_run_single_not_found,
        test_valid_job_id,
        test_no_claim_no_consumer_change,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print()
    print(f"=== {len(tests) - failed}/{len(tests)} 通过 ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
