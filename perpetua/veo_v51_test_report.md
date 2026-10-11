# Veo v5.1 测试报告（2026-10-08）

> 更新：原始 prompt 已从 VM（desktop-llm-gw:/tmp/veo_prompt_v51.txt）找回，
> 存于 `/home/hatch/data/perpetua/veo_prompt_v51.txt`（6325 字节）。
> v5.1 新增能力已集成进 `viral_prompt.py`（V51_CLOSEUP_OPENING / V51_MOTION_QUANT / V51_LOOP_SEED）。

## v5.1 相对 v5 新增（实测提炼）
1. **EXTREME CLOSE-UP OPENING**：首帧 Karen 脸占 ≥50% 画面，mugshot 取景
2. **MOTION QUANTIFICATION**：每秒头部/上身移动 ≥20% 画面宽度；静止 ≤0.3s；手持微抖 ±10px；运动模糊是期望的
3. **LOOP PRE-BURIAL**：最后 0.5s 回到首帧姿势；8s 为完整振荡周期（前冲 0-3s → 回缩 3-6s → 再前冲 6-8s）

## 视频文件
- 原始竖屏版：`/home/hatch/data/veo_inbox/veo_v51_portrait.mp4`
- 最终版：`/home/hatch/data/veo_inbox/veo_v51_final.mp4`
- 规格：1080×1920、10.03 秒

## QC 结果（2026-10-08 08:50 CST）
- **PASSED: True，体验分 79/100**
- 人脸占比 27.1%（神经科学连续乘子 0.95，不再硬拒）
- motion_1s 通过，loop 满分 20
- 警告：
  - 首帧中央主体略弱
  - 高潮强度偏平
  - 峰值在 1.2s 而非 6.5–7.5s
  - 字幕检查跳过

## 后处理（一次性手工，未集成进 postprocess_video.py）
- 前 1.5 秒加入 ±8px 数字抖动
- OpenCV 处理丢音频，用 ffmpeg 从原片补回音轨

## 发布状态
- 2026-10-08 08:56 用户批准，scheduled_slot=2026-10-08 12:30
- awaiting_approval.json: status=approved, human_approved=true

## 教训
- prompt 必须直接写持久目录（AGENTS.md Rule 3）
- 后处理步骤应集成进 postprocess_video.py（待办）
