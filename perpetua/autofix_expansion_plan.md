# Auto-fix 覆盖扩展计划
# 用户 2026-10-15 要求：故障发现到修复的延迟太长，需要更多自动修复

## 已实现的 Auto-fix
1. review_timeout → 自动重送评审（dead_state_watchdog.py）
2. teaser_failed → review_passed（2026-10-15 手动执行，应自动化）
3. 12 条卡死项 → review_passed（2026-10-15 手动执行）

## 待实现的 Auto-fix（按优先级）
1. **teaser_failed 自动转 review_passed**
   - 条件：status=teaser_failed 超过 2h
   - 动作：自动转 review_passed（有 review_score 的）
   - 依据：teaser 失败是生成问题不是选题问题，已过终审不重审

2. **upload_failed 自动转 review_passed**
   - 条件：status=upload_failed 超过 2h
   - 动作：自动转 review_passed，触发重新生成
   - 依据：upload_failed 无执行者是死状态（Rule 4）

3. **generate_failed 自动重试**
   - 条件：status=generate_failed 且 retry < 2
   - 动作：自动转 review_passed，retry+1
   - 依据：生成失败可能是 transient，重试 2 次后才放弃

## 实现位置
- dead_state_watchdog.py 的 check_pipeline_stuck() 函数
- 每次检测到符合条件的死状态，先备份 DB，再自动修复，记 audit log
