# vids_auto.py 实测 bug 清单（2026-10-09 Veo 得来速手动跑通后记录）

## 本次实测结论
- Vids 生成链路可走通：prompt → Generate → 生成 → Insert → 下载 → 取回 → QC，全程约 15 分钟
- 本次生成 2 次（第1次脚本触发/Landscape，第2次手动触发/Portrait），Vids 当日免费额度消耗 2/10

## Bug 1（致命）: [8/9] 完成检测误报 → 直接导致 [9/9] 失败
- 现状：`re.search(r'Insert|Add to.*scene|Use.*video', s)` + `re.search(r'0:0[3-9]|0:1[0-9]|720p|preview|play', s)`
- 误报原因：快照里常驻文本命中——"Generation settings: Omni, 720p" 命中 `720p`，"Play (Ctrl+F5)" 按钮命中 `play`，menubar 的 menuitem "Insert" 命中 `Insert`
- 后果：生成仅 30 秒就判"生成完成"，实际服务端渲染需 2-4 分钟；[9/9] 去找 Insert 时视频根本还没生成
- 修复：检测 AI 面板内 `button "Generated video:`（注意冒号，文本含 prompt 前缀），这是生成完成的唯一可靠信号

## Bug 2（致命）: 项目画布是横屏，下载渲染的是项目不是原片
- 现状：[2/9] 点 "+" tile 后直接点 "Create AI videos"，项目默认为 Landscape 16:16
- 后果：即使 AI 生成设置为 Portrait，File > Download > MP4 渲染的是项目画布 → 输出 1920x1080 横屏，QC resolution 直接 fail
- 本次实测：第一次下载得到 1920x1080（2MB），ffprobe 确认横屏
- 修复三选一：
  a) 新建项目时先选 "Create a portrait video"（对话框里有该选项，脚本目前跳过）
  b) 下载前把项目尺寸改成 9:16（工具栏曾有 "Video size" 按钮，需验证）
  c) 不走时间线渲染，直接下载 AI 原片（本次验证可行，见 Bug 4）

## Bug 3: [5/9] 从未设置 Portrait（与 Bug 2 叠加）
- 现状：只处理 duration slider，aspect radio 从不点
- 本次手动验证：点选 radio "Portrait" 有效，设置按钮文本变为 "Omni, 720p, Portrait, 10 seconds"，生成原片确为 720x1280
- 修复：在 Generation settings 里点选 Portrait radio（ref 模式：找 `radio "Portrait"`）

## Bug 4: [10/10] 下载链路——已找到可靠方案
- File > Download > MP4 可用（Alt+F → hover "Download" → 点 "MP4 video (.mp4)"），但渲染的是时间线（慢，且受项目画布影响）
- 直接 curl 原片 URL 失败：Google 登录墙，返回 accounts.google.com/signin HTML（本次实测确认）
- 可靠方案（本次验证通过）：页面 JS 注入 `<a href=videoUrl download>` 并 click，浏览器用自带 auth cookie 下载到 /root/Downloads/，3.7MB/10s/720x1280 完整可用
  - JS: `(function(){var v=document.querySelector('video');var a=document.createElement('a');a.href=v.currentSrc||v.src;a.download='x.mp4';document.body.appendChild(a);a.click();a.remove();return 'TRIGGERED'})()`
  - 经 agent-browser eval 执行，文件名取 URL 的 filename 参数（video.mp4），download 属性可能被 Content-Disposition 覆盖

## Bug 5: [9/9] Insert 查找时机与面板状态
- Insert 按钮只在 AI 侧边栏打开且 "Generated video:" 存在时出现（ref 如 e15505）
- 脚本在 [9/9] 前按了 Escape 可能关掉面板；且 Bug 1 导致找太早
- 修复：先点 Insertion 工具栏 "Generate an AI video clip" 确保面板开，再找 `Generated video:` 后的第一个 `button "Insert"`

## 已确认的非 bug
- 时长滑块确实调不动（保持 10s 默认），接受 10s
- "Create AI videos" 直达 AI 面板比进编辑器再找工具栏可靠（昨晚修复有效）
- prompt 粘贴（fill_smart）和 Generate 点击稳定

## 本次产出
- /home/hatch/data/veo_inbox/veo_drivethru_20261009.mp4（3.7MB，720x1280，10s，Portrait）
- QC：passed=false，experience_score=0 —— Tier1 全过，Tier2 motion_1s=1.49<2.5（开场静态）/ loop=0.45<0.75 fail，needs_regen=true
- Vids 额度：今日已用约 2/10

## 2026-10-09 10:05 修复落地（vids_auto.py）
- Bug 1：完成检测改为 `button "Generated video:`（唯一可靠信号），轮询延长至 8 分钟
- Bug 3：Generation settings 里点选 `radio "Portrait"`（click_smart）
- Bug 4：跳过 Insert→时间线渲染，改 JS 注入直接下载 AI 原片（`js_eval` helper + `<a download>` click），轮询 /root/Downloads 等大小稳定
- 备份：vids_auto.py.bak-20261009-1005
