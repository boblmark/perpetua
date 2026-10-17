# -*- coding: utf-8 -*-
"""小红书可行性验证（Agent Reach / xiaohongshu-mcp 路线）

结论摘要（2026-10-14 实测）：
  ✅ 笔记级指标可得：点击列表卡片进入详情后，可读到点赞/收藏/评论/分享
     —— 关键机制：列表链接自带 xsec_token，直接输 URL 会被重定向到 /404/sec_*，
        必须「从列表页点进去」或带上 xsec_token 访问。
  ⚠️ 列表页的 feed API 返回完整结构化数据（interact_info / tag_list / time / user），
     但只在点击进详情时触发。
  ❌ 搜索页、话题页、频道页在登出态均返回 0 条结果（需登录）。
  ❌ 主页粉丝数为占位值「10+ 粉丝」，非真实值 —— 按铁律不得采用。

依赖：xiaohongshu-mcp 自带 Chromium（含指纹伪装）
  ~/.cache/xiaohongshu-mcp/browser/<ver>/browser/browser/chrome
运行：DISPLAY=:99 python3 step10_xhs_probe.py     （需 Xvfb 或 headless）
"""
import json, os, re, sys, time

CHROME = os.path.expanduser("~/.cache/xiaohongshu-mcp/browser/148.0.7778.215/browser/browser/chrome")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "xhs_probe.json")


def extract_card():
    return """() => {
      const o=[];
      document.querySelectorAll('section.note-item').forEach(el=>{
        const a=el.querySelector('a.cover')||el.querySelector('a');
        const card={
          href: a ? a.getAttribute('href') : null,
          title: (el.querySelector('.title')?.innerText||'').trim(),
          author: (el.querySelector('.name')?.innerText||'').trim(),
          like: (el.querySelector('.count')?.innerText||'').trim(),
        };
        if(card.href) o.push(card);
      });
      return o;
    }"""


DETAIL = """() => {
  const q=s=>{const e=document.querySelector(s); return e? e.innerText.trim():null};
  return {
    title: q('#detail-title') || q('.note-content .title'),
    desc: q('#detail-desc') || q('.note-content .desc'),
    date: q('.bottom-container .date') || q('.date'),
    like: q('.like-wrapper .count') || q('.like-wrapper'),
    collect: q('.collect-wrapper .count') || q('.collect-wrapper'),
    comment: q('.chat-wrapper .count') || q('.comment-wrapper .count') || q('.chat-wrapper'),
    author: q('.author-wrapper .username') || q('.username'),
  };
}"""


def main(target_notes=6):
    from playwright.sync_api import sync_playwright
    if not os.path.exists(CHROME):
        print("!! 未找到 xiaohongshu-mcp 的 Chromium，请先安装 Agent Reach / xiaohongshu-mcp")
        return 1
    found, details, api_hits = [], [], []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True,
                              args=["--no-sandbox", "--disable-dev-shm-usage",
                                    "--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(user_agent=UA, viewport={"width": 1400, "height": 900}, locale="zh-CN")
        pg = ctx.new_page()

        def on_resp(r):
            if "/api/sns/web/v1/feed" in r.url:
                try:
                    d = r.json()
                    for it in d.get("data", {}).get("items", []):
                        nc = it.get("note_card") or {}
                        ii = nc.get("interact_info") or {}
                        if ii.get("liked_count") is not None:
                            api_hits.append({
                                "note_id": nc.get("note_id"),
                                "title": nc.get("title"), "desc": nc.get("desc"),
                                "user": (nc.get("user") or {}).get("nickname"),
                                "user_id": (nc.get("user") or {}).get("user_id"),
                                "liked_count": ii.get("liked_count"),
                                "collected_count": ii.get("collected_count"),
                                "comment_count": ii.get("comment_count"),
                                "share_count": ii.get("share_count"),
                                "time": nc.get("time"),
                                "tags": [t.get("name") for t in (nc.get("tag_list") or [])],
                            })
                except Exception:
                    pass
        pg.on("response", on_resp)

        print("→ 打开 explore 列表页")
        pg.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(4000)
        for _ in range(2):
            pg.mouse.wheel(0, 3200)
            pg.wait_for_timeout(2200)
        cards = pg.evaluate(extract_card())
        print(f"  列表卡片 {len(cards)} 张")
        found = cards[:target_notes]

        for i, c in enumerate(found, 1):
            href = c["href"]
            if not href:
                continue
            url = href if href.startswith("http") else "https://www.xiaohongshu.com" + href
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=40000)
                pg.wait_for_timeout(4500)
                if "/404" in pg.url:
                    print(f"  [{i}] ✗ 被拦到 404（token 失效）")
                    continue
                d = pg.evaluate(DETAIL)
                d.update({"list_href": url, "final_url": pg.url, "list_card": c})
                details.append(d)
                print(f"  [{i}] ✓ {d.get('title') or c.get('title')} | 赞{d.get('like')} 藏{d.get('collect')} 评{d.get('comment')}")
            except Exception as e:
                print(f"  [{i}] ✗ {type(e).__name__}")
            time.sleep(1.2)
        b.close()

    res = {"probed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "chrome": CHROME,
           "cards_found": len(found), "detail_ok": len(details),
           "details": details, "feed_api_notes": api_hits}
    json.dump(res, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\n保存 {OUT}: 卡片 {len(found)} / 详情成功 {len(details)} / feed API 笔记 {len(api_hits)}")
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    sys.exit(main(n))
