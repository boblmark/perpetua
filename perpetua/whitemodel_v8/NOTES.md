# 白模 v8 工程说明

- 原视频：机器人打架 v8（job-20261107135414-06bbd3.mp4，10.0s，720x1280，video_id bslAlkpwu0Y）
- scene.json：按原片 4 段切点（2s/4s/6s）手写的擂台白模；probe 0 红
- prompt.md：make_prompt.mjs 出的运镜事实表 + 草稿
- submit_prompt.txt：提交 Seedance 用的最终 prompt（通体纯白黏土、无文字）
- whitemodel.mp4：hyperframes 渲出的白模控制视频（10s，1080x1920）

## 两个环境坑（已踩过）

1. headless Chrome 连不上 jsdelivr CDN（ERR_TUNNEL_CONNECTION_FAILED），index.html 里
   three.js 的 CDN import 会静默失败、渲出全黑视频。已改为本地文件：
   three.module.js + three.core.js（three@0.181.2）放在本目录，index.html import
   改为 "./three.module.js"。**build.mjs 重跑会覆盖 index.html，之后须重新改这一行。**
2. /tmp 只有 512M tmpfs，hyperframes 会报 Low disk space。渲染须加
   TMPDIR=<本目录>/tmp（PRODUCER_TMP_PROJECT_DIR 同值），见 render2.log 的成功命令。

## 模板修复（2026-11-10，竖屏白模踩坑后修）

3. renderer.html 竖屏 CSS 写死 1920x1080：build.mjs 只把 __WIDTH__/__HEIGHT__ 替进
   data-width/data-height，CSS 与 viewport meta 仍写死横屏，导致 9:16 场景渲出来是
   横屏画布左上 1080x1080 裁切（上下黑带、主体被切）。已修模板：CSS 与 meta 改用
   __WIDTH__/__HEIGHT__ 占位；build.mjs 的 replace 改 replaceAll（String.replace 只替
   首处）。重跑 build 后 index.html 的 CSS 为 width:1080px;height:1920px。
4. headless Chrome 连不上 jsdelivr CDN（ERR_TUNNEL_CONNECTION_FAILED），three.js
   的 CDN import 静默失败、渲出全黑视频。已改为本地文件：
   three.module.js + three.core.js（three@0.181.2）放在本目录，index.html import
   改为 "./three.module.js"。**build.mjs 重跑会覆盖 index.html，之后须重新改这一行。**
5. /tmp 只有 512M tmpfs，hyperframes 会报 Low disk space。渲染须加
   TMPDIR=<本目录>/tmp（PRODUCER_TMP_PROJECT_DIR 同值），见 render2.log 的成功命令。

## 渲染历史

- render（首版）：全黑——three.js CDN 未加载；18,562 字节。
- render3（本地 three.js）：1080x1920 有画面，但竖屏 CSS 未修——实际是横屏画布裁切，
  1,350,160 字节；抽帧见两个问题：镜头1（50mm）横向视场太窄、两人半出画；
  镜头4 起始位在观众环外、前景观众圆柱挡住机器人。
- render4（模板竖屏修复后）：满幅 1080x1920，1,834,113 字节；镜头1 仍半出画、镜头4 仍遮挡。
- render5（最终版，2026-11-10 10:52）：镜头1 改 35mm、机位后拉至 6.8m；镜头4 起始位
  移进观众环内 [1.5,1.9,6.9]。probe 0 红，5 帧逐张验过：四镜头构图全部干净，
  1,656,272 字节，10.000s。submit_prompt.txt 已按新事实表更新
  （镜头1 35mm、镜头4 推进 6.8→6.2m）。

## Seedance 提交（2026-11-10 10:53）

- 模型 Seedance_2.5，task-type reference，参考视频 whitemodel.mp4（10s/1080x1920），
  输出 10s/9:16/720p；提交前余额 1302。
- thread_id skill_b44e9588-8937-4497-9d7b-6d6b0f78353a，
  run_id skill_8ebb7030-a0d9-4378-8baf-ca76762d15ad；
  网页查看：https://xyq.jianying.com/home?tab_name=integrated-agent&thread_id=skill_b44e9588-8937-4497-9d7b-6d6b0f78353a&agent_name=pippit_video_part_agent
- 提交日志 submit_20261110.log；轮询命令：
  pippit-tool-cli query-result --thread-id <tid> --run-id <rid> --download-dir output
  （--download-dir 必填，否则报错“缺少必填参数”）。

## Seedance 成片（2026-11-10 11:00 取回，已验）

- 文件：output/v02c76g10004dbp8gcnog65og25rrpu0.mp4，9,734,507 字节，
  720x1280、24fps、10.05s、h264+aac。
- 抽帧验过（output/frames/f_01..f_10）：全片通体白黏土、无颜色、无文字。
  0s 踢飞头颅特写（白黏土脚+碎屑飞溅）；2s 起机器人无头、颈部冒白烟、胸口裂开；
  4s 全景擂台+白黏土观众环；7-8s Karen 举臂庆祝、裁判在旁、无头机器人瘫左围绳、
  前景观众举拳欢呼。与白模空间/切点/节奏对齐；与原片偏差：0s 比白模更近
  （只见脚不见 Karen 全身）、4s 全景机位比白模高（俯视擂台），但分镜与动作都对。
- 费用：提交前余额 1302 → 取回后 782，**本次消耗 520**。
- 交付副本：~/workspace/your_files/whitemodel-v8-seedance.mp4（2026-11-10 11:01 发给用户）。
- 注意：中途换机一次清掉了 /usr/bin/pippit-tool-cli，2026-11-10 10:59 重装
  （npx @pippit-dev/cli@latest install，v1.0.55）后才取回成片；换机不影响
  Seedance 服务端的 run（thread/run id 在服务端，取回只认 id）。
