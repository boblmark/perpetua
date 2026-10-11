#!/usr/bin/env python3
"""抖音分发驱动（subprocess隔离运行）。
stdin: JSON payload；stdout最后一行: JSON receipt。
策略只允许 draft（P1人工首月）；其他策略直接拒绝。

R3（AI Studio 规格）：发布请求 schema 必须携带 ai_generated=1
（DOUYIN_AI_DECLARATION_CODE）；缺失/不符 -> 任务 BLOCKED +
MissingPlatformDisclosureException，NEVER 只告警不阻断。
"""
import asyncio, json, os, sys

DOUYIN_AI_DECLARATION_CODE = 1


class MissingPlatformDisclosureException(Exception):
    """R3：抖音 AI 披露声明缺失，硬阻断。"""


def receipt(ok, detail, **kw):
    r = {"ok": ok, "detail": detail}
    r.update(kw)
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if ok else 1)

def main():
    try:
        p = json.load(sys.stdin)
    except Exception as e:
        receipt(False, f"payload解析失败: {e}")

    # R3 发网前检查：ai_generated 必须为 1，否则任务 BLOCKED + 抛异常
    try:
        if p.get("ai_generated") != DOUYIN_AI_DECLARATION_CODE:
            raise MissingPlatformDisclosureException(
                f"R3: 抖音 AI 披露声明缺失（ai_generated={p.get('ai_generated')}，"
                f"必须为 {DOUYIN_AI_DECLARATION_CODE}），任务 BLOCKED")
    except MissingPlatformDisclosureException as e:
        receipt(False, str(e), blocked=True)

    if p.get("strategy") != "draft":
        receipt(False, f"抖音P1只允许draft策略，拒绝 {p.get('strategy')}")

    vendor = p["vendor_dir"]
    sys.path.insert(0, vendor)
    sys.path.insert(0, os.path.join(vendor, "myUtils"))
    try:
        from uploader.douyin_uploader.main import DouYinVideo, DOUYIN_PUBLISH_STRATEGY_DRAFT, cookie_auth
    except Exception as e:
        receipt(False, f"vendor导入失败: {e}")

    ck = p["cookie_file"]
    if not os.path.exists(ck):
        receipt(False, f"cookie不存在，需用户扫码登录: {ck}")

    async def run():
        if not await cookie_auth(ck):
            return {"ok": False, "detail": "cookie已失效，需用户重新扫码登录"}
        up = DouYinVideo(
            title=p["title"],
            file_path=p["video_path"],
            tags=p.get("tags", []),
            publish_date=0,
            account_file=ck,
            desc=p.get("desc", ""),
            thumbnail_portrait_path=p.get("cover_path"),
            publish_strategy=DOUYIN_PUBLISH_STRATEGY_DRAFT,
            declaration="内容由AI生成",
            headless=True,
        )
        await up.validate_base_args()
        await up.upload()
        return {"ok": True, "detail": "已存入抖音草稿箱，待人工发布"}

    try:
        r = asyncio.run(run())
        receipt(r["ok"], r["detail"])
    except Exception as e:
        receipt(False, f"上传异常: {str(e)[:300]}")

if __name__ == "__main__":
    main()
