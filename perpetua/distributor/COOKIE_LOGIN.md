# 各平台扫码登录指南（用户手动，一次即可）

分发器凭据 = 各平台 cookie 文件，一账号一文件，600 权限，只存本机，不跨机。

## 抖音（P1 必需）
```bash
cd /home/hatch/data/perpetua/distributor && python3 login_douyin.py
# 脚本会打开创作者中心登录页并生成二维码图片（终端也会打印ASCII码）；
# 用【档案管理员】账号的抖音APP扫码确认即可。
# 成功后 cookie 自动存到 cookies/douyin/account.json（600权限）。
```
注意：请用"档案管理员"账号登录；不要用已有大量作品的私人号混用。

## 小红书（P1 可选，备料模式不强制）
- P1 小红书走人工发，管线只备料到 pending_manual/，**可以不登录**。
- phase2 需要时再扫码：`ls vendor/uploader/xiaohongshu_uploader/` 找扫码脚本，
  cookie 放 `cookies/xiaohongshu/account.json`（600）。

## 有效性
- 每次分发前 driver 会校验 cookie 有效性，失效直接失败并告警（不重试、不裸奔）。
- 抖音 cookie 失效无预警：建议每周打开创作者中心看一眼；后续接每日探针 cron。

## 安全
- 绝不把 cookie 文件发给任何外部 agent（Marvis 等）；凭据隔离铁律。
- 换绑/掉登后删掉旧文件重新扫码即可。
