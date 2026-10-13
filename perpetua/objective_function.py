#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目标函数模块 · 数字孪生 DNA v3.1

================================================================
统计口径（LOCKED v3.1 · 修改需走 L3 策略变更流程）
================================================================
1. 爆款定义：视频发布后 72 小时内累计播放量 > 100,000（严格大于）
2. 爆款率   ：爆款视频数 / 参与统计的视频总数
3. 纳入统计条件：views_72h 已知（发布满 72 小时，数据定稿）。
   未满 72 小时的视频不计入分母（views_72h=None 的样本自动剔除）。
4. 置信区间：Wilson score interval（默认 95%），适用于小样本二项比例。
5. 时间窗口：固定 72h，不随平台/类型调整。如需调整阈值/窗口，
   必须走 L3 人工批准并全量重算历史（禁止静默改口径）。

数学定义：
    爆款率 = P(播放 > 100000 | 发布后 72h)
================================================================
"""

from statistics import NormalDist
from typing import Iterable, Mapping, Union

# ---- 锁定常量 ----
VIRAL_VIEWS_THRESHOLD = 100_000   # 爆款播放量阈值（72h 累计）
VIRAL_WINDOW_HOURS = 72           # 统计窗口（小时）
DEFAULT_CONFIDENCE = 0.95         # 默认置信水平

VideoLike = Union[int, Mapping]


def _extract_views(video: VideoLike) -> "int | None":
    """从 int 或 {'views_72h': ...} 中提取播放量；未知返回 None。"""
    if isinstance(video, Mapping):
        v = video.get("views_72h")
    else:
        v = video
    if v is None:
        return None
    return int(v)


def is_viral(views_72h: "int | None") -> bool:
    """判断单条视频是否为爆款。

    Args:
        views_72h: 发布后 72h 累计播放量；None 表示数据未定稿。

    Returns:
        True 仅当 views_72h > 100000（严格大于）。None/未达标返回 False。
    """
    if views_72h is None:
        return False
    return int(views_72h) > VIRAL_VIEWS_THRESHOLD


def viral_rate(videos: Iterable[VideoLike]) -> float:
    """计算爆款率 = 爆款数 / 有效样本数。

    有效样本 = views_72h 已知的视频（未满 72h 的自动剔除，不计入分母）。

    Args:
        videos: 元素为 int（播放量）或含 'views_72h' 键的 Mapping。

    Returns:
        爆款率 [0.0, 1.0]；无有效样本时返回 0.0。
    """
    n = 0
    viral = 0
    for v in videos:
        views = _extract_views(v)
        if views is None:
            continue
        n += 1
        if is_viral(views):
            viral += 1
    return (viral / n) if n else 0.0


def wilson_interval(successes: int, n: int,
                    confidence: float = DEFAULT_CONFIDENCE) -> "tuple[float, float]":
    """Wilson score 置信区间（二项比例）。

    Args:
        successes: 成功数（爆款数），必须 >= 0。
        n: 样本总数，必须 >= 0。
        confidence: 置信水平 (0, 1)，默认 0.95。

    Returns:
        (lower, upper)，钳制在 [0.0, 1.0] 内。
        n == 0 时返回 (0.0, 1.0)，表示完全不确定（无数据）。

    Raises:
        ValueError: 参数非法时。
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence 必须在 (0,1) 内，got {confidence}")
    if n < 0 or successes < 0 or successes > n:
        raise ValueError(f"非法参数：successes={successes}, n={n}")
    if n == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    delta = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    lo = max(0.0, center - delta)
    hi = min(1.0, center + delta)
    return (lo, hi)


def confidence_interval(videos: Iterable[VideoLike],
                        confidence: float = DEFAULT_CONFIDENCE) -> "tuple[float, float]":
    """对一组视频的爆款率计算 Wilson 置信区间（分母口径同 viral_rate）。"""
    items = list(videos)
    n = sum(1 for v in items if _extract_views(v) is not None)
    viral = sum(1 for v in items if is_viral(_extract_views(v)))
    return wilson_interval(viral, n, confidence)


def summary(videos: Iterable[VideoLike],
            confidence: float = DEFAULT_CONFIDENCE) -> dict:
    """一站式摘要：样本数/爆款数/爆款率/置信区间/口径元信息。"""
    items = list(videos)
    n = sum(1 for v in items if _extract_views(v) is not None)
    viral = sum(1 for v in items if is_viral(_extract_views(v)))
    lo, hi = wilson_interval(viral, n, confidence)
    return {
        "n": n,
        "viral": viral,
        "rate": (viral / n) if n else 0.0,
        "ci_lower": lo,
        "ci_upper": hi,
        "confidence": confidence,
        "threshold": VIRAL_VIEWS_THRESHOLD,
        "window_hours": VIRAL_WINDOW_HOURS,
    }


if __name__ == "__main__":
    # ---- 自测 ----
    # 1. 爆款判定：严格大于
    assert is_viral(100_001) is True
    assert is_viral(100_000) is False   # 等于阈值不算
    assert is_viral(99_999) is False
    assert is_viral(None) is False      # 未定稿不算
    assert is_viral(0) is False

    # 2. 爆款率：分母剔除未定稿
    vids = [200_000, 50_000, None, {"views_72h": 150_000}, {"views_72h": None}]
    assert viral_rate(vids) == 2 / 3, viral_rate(vids)

    # 3. 空样本
    assert viral_rate([]) == 0.0
    assert viral_rate([None, None]) == 0.0

    # 4. Wilson 区间基本性质
    lo, hi = wilson_interval(0, 0)
    assert (lo, hi) == (0.0, 1.0)
    lo, hi = wilson_interval(5, 100)
    assert 0.0 <= lo <= 0.05 <= hi <= 1.0, (lo, hi)
    lo, hi = wilson_interval(100, 100)
    assert lo <= 1.0 <= hi and lo > 0.9, (lo, hi)
    # 90% 区间比 95% 窄
    lo90, hi90 = wilson_interval(5, 100, 0.90)
    lo95, hi95 = wilson_interval(5, 100, 0.95)
    assert (hi90 - lo90) < (hi95 - lo95)

    # 5. 非法参数抛错
    for bad in [lambda: wilson_interval(-1, 10),
                lambda: wilson_interval(11, 10),
                lambda: wilson_interval(1, 10, 1.5)]:
        try:
            bad()
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass

    # 6. summary
    s = summary([200_000, 50_000, 300_000, 10_000])
    assert s["n"] == 4 and s["viral"] == 2 and s["rate"] == 0.5
    assert s["threshold"] == 100_000 and s["window_hours"] == 72

    print("objective_function.py 自测全部通过 ✓")
    print(f"  示例: {summary([200_000, 50_000, 300_000, 10_000, 500_000])}")
