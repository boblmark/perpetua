# 03 · TikTok — 话题标签 API 是主力

**可行性**：✅ 可得。播放/点赞/评论/分享/收藏 + 作者粉丝数全部可采。

---

## 核心接口：`challenge/item_list`

登出态访问 `/tag/<tag>` 页面时，页面自身会调用：

```
GET /api/challenge/item_list/?challengeID=<id>&count=30&cursor=<n>
```

每次返回 **30 条**（响应 0.8–0.87 MB），可直接解析。

### 响应字段（已实测）

```jsonc
{
  "itemList": [{
    "id": "7612254527726636318",
    "desc": "#cutecat #cartoons ...",
    "createTime": 1759...,
    "stats": {
      "playCount":   135900000,   // 播放
      "diggCount":    2400000,    // 点赞
      "commentCount":   16100,    // 评论
      "shareCount":    212900,    // 转发
      "collectCount":  171000     // 收藏
    },
    "authorStats": {
      "followerCount": 3500000,   // 粉丝数 ✅
      "videoCount": ..., "heartCount": ...
    },
    "author": { "uniqueId": "...", "nickname": "...", "secUid": "...", "id": "...", "verified": false },
    "textExtra": [ { "hashtagName": "cutecat" } ],
    "video": { "duration": 61 },
    "originCover": "https://...",
    "ShowAIGC": true             // 平台 AI 生成标注 ✅
  }]
}
```

视频链接构造：`https://www.tiktok.com/@<uniqueId>/video/<id>`

---

## 找账号的技巧：`/tag/<用户名>` 页面

**TikTok 上大量创作者会给自己打自己的用户名标签**，所以 `/tag/<username>` 往往能列出该账号的作品 —— 这是登出态做**账号级深度抽样**的唯一实用路径。

- 先试完整用户名；命中为空时，试**去掉数字的变体**（如 `aicat` vs `aicat973`）
- 判定标准：该话题页可回收作品数 **≥10 条**才纳入账号级抽样

若 `/tag/<username>` 拿到的数量不足，则退化为**话题池横截面**（按主题标签采，如 `#aivideo`）。
**两种口径必须在 `sampling_frame` 里如实标注**，因为跨口径的行不可直接比较。

---

## 抽样建议

| 口径 | 行数 | 说明 |
|---|---|---|
| 账号级抽样 | 每账号 10 条 | 仅对"话题页可回收 ≥10 条"的账号执行，5 爆款 + 5 对照 |
| 话题池横截面 | 其余 | 按主题标签采，用于补足行数 |

---

## 踩坑记录

| 问题 | 原因 | 解法 |
|---|---|---|
| 列表页只给 20 条 | 前端分页限制 | 直接调 `challenge/item_list` 带 `cursor` 翻页 |
| 首页无法枚举 | 个性化推荐，无游标 | 不要试图枚举首页 |
| 单条视频详情页无数据 | 需 JS 渲染 | 用 Playwright 打开后从 HTML 里正则取 `"playCount":<int>` |
| 账号级抽样账号太少 | 大多数创作者不打自己用户名标签 | 接受现实，改用话题池 + 标注口径 |
| 数字标签变体 | 用户改名/系统加后缀 | 同时试原名与去数字变体 |

---

## 封面

封面 URL 在 `originCover` 字段，可直接下载（竖屏 540×960 居多）。
下载后做 OCR + 像素分析，见 `references/09-analysis.md`。
