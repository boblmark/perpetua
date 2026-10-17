# 07 · 小红书 — 两条路线，各有边界

**可行性**：⚠️ 笔记级可得。点赞/收藏/评论/分享 + 标题/正文/标签/**发布时间** 可采。
**搜索与粉丝数需登录态**（服务端强制，非技术问题）。

> 这是全流程最难啃的平台。本文件记录了两条**实测可用**的路线及其精确边界，
> 可省去大量重复试错。

---

## 拦路虎的本质（先理解这个，再选路线）

小红书有**两道独立防线**：

1. **浏览器指纹**：普通自动化浏览器（如 Playwright 自带 Chromium）访问一律被重定向到
   `/404/sec_*`，页面提示「当前内容仅支持在小红书 APP 内查看」。
2. **`xsec_token`**：笔记链接需要携带签名 token。**直接输 URL 必被拦；从列表页点进去才行。**

**关键判别**：报错是 `-101 无登录信息` 还是签名校验失败？
- 签名校验失败 → 技术问题，可解
- **`-101` → 服务端要求登录，技术无法绕过**（已用正确签名验证过，见下方"已验证结论"）

---

## 路线 A：纯 HTTP 签名路线（**推荐**，无需浏览器）

**原理**：用 `xhshow` 库生成 `x-s` 签名 + `curl_cffi` 做 TLS 指纹伪装。

### 依赖

```bash
git clone --depth 1 https://github.com/JoeanAmier/XHS-Downloader.git /tmp/XHS-Downloader
pip install -r /tmp/XHS-Downloader/requirements.txt   # 含 xhshow + curl_cffi
```

### 用法

```python
import sys; sys.path.insert(0, "/tmp/XHS-Downloader")
from source import XHS

async with XHS(cookie="", impersonate="chrome146", ...) as xhs:
    rows = await xhs.extract(note_url, download=False)
```

参考实现：`scripts/collect/step10b_xhs_http.py`

### 实测结果（6/6 成功）

| 字段 | 可得 |
|---|---|
| 点赞数量 / 收藏数量 / 评论数量 / 分享数量 | ✅ |
| 作品标题 / 作品描述 / 作品标签 | ✅ |
| **发布时间** | ✅ （浏览器路线拿不到） |
| 作者昵称 / 作者ID / 封面地址 | ✅ |

### 优点
- 无需 713 MB 浏览器
- 可批量、速度快
- 多拿到**发布时间**字段

---

## 路线 B：指纹浏览器路线（备用）

**原理**：`xiaohongshu-mcp` 自带带指纹伪装的 Chromium **v148**（`platform=windows`）。

```bash
# 二进制
curl -sL -o xiaohongshu-mcp-linux-amd64 \
  https://github.com/xpzouying/xiaohongshu-mcp/releases/download/v2.5.5/xiaohongshu-mcp-linux-amd64
chmod +x xiaohongshu-mcp-linux-amd64
# 首次运行会下载 ~150MB 浏览器到 ~/.cache/xiaohongshu-mcp
```

然后用 Playwright 指定该 chrome 内核：

```python
b = p.chromium.launch(
    executable_path="~/.cache/xiaohongshu-mcp/browser/148.0.7778.215/browser/chrome",
    headless=True, args=["--no-sandbox", "--disable-dev-shm-usage",
                         "--disable-blink-features=AutomationControlled"])
ctx = b.new_context(user_agent="...Chrome/148.0.0.0...", locale="zh-CN")
```

参考实现：`scripts/collect/step10_xhs_probe.py`

### 关键操作：必须从列表页点进去

```python
pg.goto("https://www.xiaohongshu.com/explore")     # 列表页 → 200 ✅
cards = pg.evaluate("""() => [...document.querySelectorAll('section.note-item')]
    .map(el => el.querySelector('a')?.getAttribute('href'))""")
# 每个 href 自带 ?xsec_token=...&xsec_source=
pg.click("section.note-item a.cover")   # ← 必须用点击，不能直接 goto
```

直接 `goto` 笔记 URL（即使带 token）在部分情况下仍会被拦。
**最可靠的是点击**。

---

## 已验证结论：哪些缺口能补、哪些不能

用**正确的 xhshow 签名**直接调 API 得到的服务端响应：

| 接口 | 结果 | 结论 |
|---|---|---|
| `/api/sns/web/v1/search/notes`（搜索） | `{"code":-101,"msg":"无登录信息，或登录信息为空"}` | **签名完全正确，但仍需登录 → 技术上无解** |
| `/api/sns/web/v1/homefeed`（首页流） | 同上 `-101` | 同上 |
| 笔记详情（带 token） | ✅ 成功 | 路线 A/B 可用 |
| 笔记详情（**不带** token） | ✅ 200 但**字段全为 None** | token **必需** |
| 账号主页作品列表 | ❌ `提取小红书作品链接失败` | 需 Cookie |
| 账号粉丝数 | ❌ 页面显示 `10+ 粉丝` | **登录态占位值，不是真实数据** |

> ⚠️ **`10+ 粉丝` 是占位符，绝不可当作真实粉丝数录入。** 按铁律只能记 `N/A`。

---

## 补齐路径（需用户配合）

要解锁**搜索 / 粉丝数 / 账号作品列表**，只能上登录态：

1. 用 Chrome 插件 **Cookie-Editor** 从 `xiaohongshu.com` 登录后导出 Header String
2. 传给上述任一工具

⚠️ **安全提示**：Cookie 等于账号完整访问凭证。**强烈建议使用小号**，并在交付时提醒用户
该操作可能涉及平台条款约束。

---

## 容器缺系统库的解法（无 root 时）

指纹浏览器依赖若干系统库。若报错：

```
error while loading shared libraries: libnspr4.so: cannot open shared object file
```

无 root、`apt-get install` 不可用时，**手动提取 .deb**：

```bash
mkdir -p /tmp/libs && cd /tmp/libs
# apt-get download 不需要 root
for p in libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 \
         libcups2t64 libasound2t64 libxdamage1 libxkbcommon0 libavahi-common3; do
  apt-get download "$p"
done
for d in *.deb; do dpkg-deb -x "$d" /path/to/libdir; done   # dpkg-deb -x 不需要 root
# 运行
LD_LIBRARY_PATH=/path/to/libdir/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH <chrome> --version
```

> 实测：11 个缺失库可分两批补齐（第一批 9 个，补齐后暴露 `libavahi-common.so.3` 等剩余依赖，
> 继续同样方式补即可）。**把提取的库放在工作区内**，比放 `/tmp` 更持久。

---

## 踩坑记录

| 症状 | 原因 | 解法 |
|---|---|---|
| 全部 302 → `/404/sec_*` | 浏览器指纹不符 | 换指纹 Chromium v148，或用纯 HTTP 路线 |
| 详情页 404 但列表页正常 | 缺 `xsec_token` | 从列表页点进去 |
| 搜索返回 0 条 / `-101` | 需登录（**不是签名问题**） | 只能上登录态，别再调签名 |
| 粉丝显示 `10+ 粉丝` | 登录态占位值 | 记 `N/A`，绝不用 |
| Chrome 报 `Bus error` / `missing section headers` | **解压被超时中断**，二进制截断 | 重下并让解压**完整跑完**（约 90 秒），勿设短超时 |
| `Response.text()` 报解码错误 | gzip 响应 | 用 `response.body()` 自行解压 |
| 列表页卡片是隐藏元素，`click` 超时 | 选中了 `offsetParent === null` 的节点 | 先过滤可见性：`a.offsetParent !== null && a.getBoundingClientRect().width > 50` |
