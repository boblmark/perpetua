# Veo 视频生成规范（2026-10-08）

## 时长：固定 8 秒
- Google Vids → Create AI videos → Generation settings
- **Video duration 滑块必须拖到 8s**（Vids 默认 10s，不改就是 10s）
- 原因：v5.2 算法按 8 秒设计（0-6s 爬坡 → 6.5-7.5s 高潮 → 收尾），10 秒多 2 秒尾巴

## 其他固定设置
- Model: Omni（唯一选项，Veo 驱动）
- 分辨率：720p（免费档最高）
- 方向：Portrait 9:16（Shorts）
- 导出后中央裁剪（如 Vids 导出 16:9）

## 生成后
- 文件命名：`veo_<版本>_<topic>.mp4`，直接存 `/home/hatch/data/veo_inbox/`
- 不要经过 /tmp
- 进 QC 前确认时长为 8.x 秒
