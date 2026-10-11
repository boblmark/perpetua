# Brain ③ AI Studio 回答原文（2026-10-08 11:45 CST）
# Model: Gemini 3.8 Flash (免费档)

KEEP: V51_CLOSEUP_OPENING
MODIFY V51_MOTION_QUANT:
MUST maintain continuous baseline motion of ≥20% frame-displacement per second from 0.0s to 6.0s. MUST accelerate to a peak motion velocity of ≥40% frame-displacement per second during the 6.5s-7.5s climax window. NEVER allow peak motion velocity between 0.0s and 1.5s to exceed 62.5% of the 6.5s-7.5s climax velocity. NEVER decelerate below 20% frame-displacement per second prior to 6.5s.
ADD:
- The Climax Energy Ratio (Motion Peak [6.5s-7.5s] divided by Motion Peak [0.0s-1.5s]) MUST equal or exceed 1.60.
- Climax window [6.5s-7.5s] MUST deliver ≥40% frame-displacement per second.
- NEVER execute recoil movements, velocity deceleration, or return-to-pose loops between 3.0s and 6.0s.
