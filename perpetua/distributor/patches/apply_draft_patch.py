#!/usr/bin/env python3
"""给 vendor 抖音上传器打 Perpetua P1 补丁：新增 draft 策略（只存草稿，永不点发布）。

幂等：已打过补丁则直接退出。每个锚点必须精确命中一次，否则 fail-closed 报错。
上游更新后重新执行本脚本即可（锚点变了会报错，人工跟进）。
"""
import sys, pathlib

TARGET = pathlib.Path(__file__).resolve().parent.parent / "vendor" / "uploader" / "douyin_uploader" / "main.py"
MARKER = "Perpetua-P1-draft-patch"

def need(src: str, anchor: str) -> str:
    n = src.count(anchor)
    if n != 1:
        sys.exit(f"PATCH ABORT: 锚点命中 {n} 次（期望1次），拒绝修改:\n{anchor[:120]}")
    return anchor

def main():
    src = TARGET.read_text(encoding="utf-8")
    if MARKER in src:
        print("补丁已存在，跳过")
        return

    # 1. 新增 draft 常量
    a1 = need(src, 'DOUYIN_PUBLISH_STRATEGY_SCHEDULED = "scheduled"')
    src = src.replace(a1, a1 + '\nDOUYIN_PUBLISH_STRATEGY_DRAFT = "draft"  # ' + MARKER + '：只存草稿', 1)

    # 2. 策略白名单加入 draft
    a2 = need(src, "if self.publish_strategy not in {DOUYIN_PUBLISH_STRATEGY_IMMEDIATE, DOUYIN_PUBLISH_STRATEGY_SCHEDULED}:")
    src = src.replace(a2,
        "if self.publish_strategy not in {DOUYIN_PUBLISH_STRATEGY_IMMEDIATE, DOUYIN_PUBLISH_STRATEGY_SCHEDULED, DOUYIN_PUBLISH_STRATEGY_DRAFT}:  # " + MARKER, 1)

    # 3. 发布块：draft 策略改点"存草稿"，找不到按钮直接抛异常（fail-closed，绝不回退到发布）
    a3 = need(src, '''                # ── 正常发布流程 ──
                publish_button = page.get_by_role("button", name="发布", exact=True)
                if await publish_button.count():
                    await publish_button.click(force=True)
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/manage**",
                    timeout=3000,
                )
                douyin_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                break''')
    draft_block = '''                # ── 正常发布流程 ──
                if self.publish_strategy == DOUYIN_PUBLISH_STRATEGY_DRAFT:  # ''' + MARKER + '''
                    draft_button = page.get_by_role("button", name="存草稿", exact=True)
                    if not await draft_button.count():
                        raise RuntimeError("存草稿按钮未找到，fail-closed：拒绝任何发布动作")
                    await draft_button.click(force=True)
                    try:
                        await page.wait_for_url(
                            "https://creator.douyin.com/creator-micro/content/manage**",
                            timeout=10000,
                        )
                    except Exception:
                        raise RuntimeError("点击存草稿后未跳转到内容管理页，视为未保存成功")
                    douyin_logger.success(_msg("📝", "已存入抖音草稿箱，等待人工发布"))
                    break
                publish_button = page.get_by_role("button", name="发布", exact=True)
                if await publish_button.count():
                    await publish_button.click(force=True)
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/manage**",
                    timeout=3000,
                )
                douyin_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                break'''
    src = src.replace(a3, draft_block, 1)

    TARGET.write_text(src, encoding="utf-8")
    print("draft 补丁已应用:", TARGET)

if __name__ == "__main__":
    main()
