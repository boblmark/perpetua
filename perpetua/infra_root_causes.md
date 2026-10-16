# 基础设施根因分析
# 用户 2026-10-15 要求：修根因，不只修表象

## 已修复根因
1. **Dispatcher 探针误报 DOWN**
   - 根因：单次 curl 遇到出站代理抖动就判 DOWN
   - 修复：3 次重试防抖（2026-10-15）
   - 文件：dispatch_health.py

## 已知根因（无法彻底修复，只能缓解）
1. **浏览器任务槽位问题**
   - 根因：worker 和主 agent 的 browser task 路由到不同 Chromium profile 槽位
   - 缓解：worker 只报"疑似"，主 agent 复核定论（2026-10-12 已落地）
   - 状态：基础设施层问题，需平台方修复

2. **SSH 隧道间歇性断开**
   - 根因：出站经 198.19.0.1:3128 代理，链路抖动
   - 缓解：5 分钟 keepalive + 三层判活（进程/VPS端口/服务响应）
   - 状态：已是最优，只能快速恢复不能预防

3. **Cron 平台冻结**
   - 根因：2026-10-13 平台级 safety review 冻结 23h
   - 缓解：Rule 11 恢复清单，冻结解除后手动全量拉起
   - 状态：平台方行为，无法预防

## 待调查根因
1. **nanoMuse 18739 高频重启**
   - 现象：2026-10-15 当天重启 3 次
   - 待查：重启前日志已备份，需分析 traceback
   - 位置：~/workspace/goals/nanomuse-runtime-migration/

2. **Smart Gym 生成 integrity_check_failed**
   - 现象：连续 2 次生成失败
   - 待查：生成后端返回的具体错误
   - 影响：阻塞 23:30 档
