# -*- coding: utf-8 -*-
"""小红书笔记数据采集（纯 HTTP 路线 · 无需 Cookie/登录）

依据：JoeanAmier/XHS-Downloader（⭐13k+）内置 xhshow 的 x-s 签名实现，
      配合 curl_cffi 的 TLS 指纹伪装（impersonate=chrome146），
      可在登出态直接解析笔记详情，返回结构化字段：
        点赞数量 / 收藏数量 / 评论数量 / 分享数量 / 作品标题 / 作品描述
        / 作品标签 / 发布时间 / 作者昵称 / 作者ID / 封面地址

与浏览器路线的对比：
  · 浏览器（xiaohongshu-mcp Chromium v148）需下载 ~713MB 浏览器，仅能读到页面上的数字
  · 本路线纯 HTTP，轻量、可批量、且多出「发布时间」「作品标签」「作者ID」

已知边界（2026-10-14 实测）：
  · 账号主页作品列表 → 提示“提取小红书作品链接失败”，需 Cookie
  · 关键词搜索 → 本项目不含搜索 API；搜索页登出态返回 0 结果 → 需 Cookie

用法：
  python3 step10b_xhs_http.py collector/xhs_probe.json      # 从探针结果批量取数
  python3 step10b_xhs_http.py <note_url> [<note_url> ...]  # 直接给链接
"""
import asyncio, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("XHSDL_SRC", "/tmp/XHS-Downloader")
OUT = os.path.join(HERE, "xhs_rows.json")


def load_urls(argv):
    urls = []
    for a in argv:
        a = a.strip().strip('"').strip("'")   # 容忍调用方带入的引号
        if a.startswith("http"):
            urls.append(a)
        elif os.path.exists(a):
            d = json.load(open(a))
            urls += [x["final_url"] for x in d.get("details", []) if x.get("final_url")]
    return urls


async def main():
    if not os.path.isdir(SRC):
        print(f"!! 未找到 XHS-Downloader 源码：{SRC}\n"
              f"   请先执行：git clone --depth 1 https://github.com/JoeanAmier/XHS-Downloader.git {SRC}\n"
              f"   并安装依赖：pip install -r {SRC}/requirements.txt")
        return 1
    sys.path.insert(0, SRC)
    from source import XHS

    urls = load_urls(sys.argv[1:])
    if not urls:
        print("用法：python3 step10b_xhs_http.py collector/xhs_probe.json")
        return 1
    print(f"待取数笔记：{len(urls)} 条")

    keep = ["作品ID", "作品标题", "作品描述", "作品标签", "点赞数量", "收藏数量", "评论数量",
            "分享数量", "发布时间", "作者昵称", "作者ID", "作品链接", "封面地址"]
    rows = []
    async with XHS(work_path="/tmp/xhsdl_work", folder_name="D", cookie="", proxy=None,
                   timeout=15, max_retry=2, record_data=False, image_download=False,
                   video_download=False, video_cover_download=False, live_download=False,
                   download_record=False, author_archive=True, write_mtime=False,
                   language="zh_CN") as xhs:
        for i, u in enumerate(urls, 1):
            try:
                r = await xhs.extract(u, download=False)
                if r:
                    it = {k: r[0].get(k) for k in keep if k in r[0]}
                    it["采集时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    rows.append(it)
                    print(f"  [{i}/{len(urls)}] ✓ {str(it.get('作品标题'))[:32]} | 赞{it.get('点赞数量')} "
                          f"藏{it.get('收藏数量')} 评{it.get('评论数量')} 发{it.get('发布时间')}")
                else:
                    print(f"  [{i}/{len(urls)}] ✗ 无返回")
            except Exception as e:
                print(f"  [{i}/{len(urls)}] ✗ {type(e).__name__}: {str(e)[:80]}")
            await asyncio.sleep(1.0)

    json.dump({"collected_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(rows), "rows": rows},
              open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\n保存 {OUT}：{len(rows)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
