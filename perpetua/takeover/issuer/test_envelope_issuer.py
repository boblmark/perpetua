#!/usr/bin/env python3
"""信封签发端校验器单元测试（3 条必过）：
1. 超限拒绝（max_daily_publishes=20 本意 2 的误写场景，红队 KILL 1 原案）
2. 白名单外拒绝（夹带 delete）
3. 正常签发 → validate_envelope 验签+天花板通过；且篡改后验签失败
"""
import copy
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/hatch/data/perpetua/takeover/issuer")
from envelope_issuer import (EnvelopeRejected, issue_envelope,
                             validate_envelope)

BASE = {
    "limits": {"max_daily_publishes": 2, "max_total_publishes": 6,
               "min_stock_level_alert": 4},
    "actions": ["flip_public", "private_upload", "comment_draft",
                "degrade_schedule"],
}


def test_over_limit_rejected():
    p = copy.deepcopy(BASE)
    p["limits"]["max_daily_publishes"] = 20  # 红队场景：误写 20
    try:
        issue_envelope(p)
    except EnvelopeRejected as e:
        assert "max_daily_publishes" in str(e), e
        print("PASS 1 超限拒绝:", str(e)[:80])
        return
    raise AssertionError("超限未被拒绝")


def test_forbidden_action_rejected():
    p = copy.deepcopy(BASE)
    p["actions"] = ["flip_public", "delete"]  # 白名单夹带 delete
    try:
        issue_envelope(p)
    except EnvelopeRejected as e:
        assert "delete" in str(e), e
        print("PASS 2 白名单外拒绝:", str(e)[:80])
        return
    raise AssertionError("白名单外动作未被拒绝")


def test_issue_and_validate():
    env = issue_envelope(copy.deepcopy(BASE))
    ok, reason = validate_envelope(env)
    assert ok, reason
    assert env["permissions"]["allow_delete_operation"] is False
    assert env["permissions"]["allow_auto_comment_post"] is False
    assert env["auth_channel_mode"] == "ISOLATED_BACKUP_OAUTH"
    # 篡改：把上限改大后验签必须失败（执行端视角）
    tampered = copy.deepcopy(env)
    tampered["limits"]["max_daily_publishes"] = 99
    ok2, reason2 = validate_envelope(tampered)
    assert not ok2, "篡改信封竟通过校验"
    # 过期窗口越界也必须被签发端拒绝
    p = copy.deepcopy(BASE)
    now = datetime.now(timezone.utc)
    p["issued_at"] = now.isoformat()
    p["expires_at"] = (now + timedelta(days=30)).isoformat()
    try:
        issue_envelope(p)
        raise AssertionError("30 天有效期未被拒绝")
    except EnvelopeRejected:
        pass
    print("PASS 3 正常签发验签通过 + 篡改拦截 + 超长有效期拒绝")


if __name__ == "__main__":
    test_over_limit_rejected()
    test_forbidden_action_rejected()
    test_issue_and_validate()
    print("ALL 3 TESTS PASS")
