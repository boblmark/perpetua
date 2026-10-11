#!/usr/bin/env python3
"""platform_registry.py — 平台插件注册表（D20261011-006 规格落地，v1.0.0）。

规则（Google AI Studio 规格）：
- 一个平台 = REGISTRY 里 1 个条目（key → spec）；加平台只需加 1 行，
  或调用 register_platform(key, spec)。
- driver 字段指向该平台的 driver（文件/模块名）；None = stub（未接 driver）。
- sync / cron / 前端 / 后端全部从这里动态读，禁止在别处硬编码平台列表。
- distribute.py 的旧 PLATFORMS 字典已迁移到此（唯一真相源）。

REGISTRY_VERSION 用于版本门：调用方可用 assert 做兼容性检查。
"""
import sys

REGISTRY_VERSION = "1.0.0"

PLATFORMS = {
    "douyin": {
        "cluster": "domestic",
        "driver": "douyin_driver.py",
        "default": "draft",
        "p1_force": "draft",
        "note": "抖音官方创作者中心通道",
    },
    "shipinhao": {
        "cluster": "domestic",
        "driver": None,
        "default": "hold",
        "p1_force": None,
        "note": "视频号：国内第一优先级，P1人工发，管线只备料（2026-10-11 dry-run 补入：strategy_c/variant_rules 早已引用，注册表漏登）",
    },
    "xiaohongshu": {
        "cluster": "domestic",
        "driver": None,
        "default": "hold",
        "p1_force": None,
        "note": "P1人工发，管线只备料",
    },
    "kuaishou": {
        "cluster": "domestic",
        "driver": "vendor/uploader/ks_uploader",
        "default": "hold",
        "p1_force": None,
        "note": "风控拦截中，P1人工发",
    },
    "bilibili": {
        "cluster": "domestic",
        "driver": None,
        "default": "hold",
        "p1_force": None,
        "note": "phase2(biliup)",
    },
    "youtube": {
        "cluster": "overseas",
        "driver": "youtube_api",
        "default": "private",
        "p1_force": None,
        "note": "沿用现有官方API通道",
    },
    "tiktok": {
        "cluster": "overseas",
        "driver": None,
        "default": "hold",
        "p1_force": None,
        "note": "phase2",
    },
    "facebook": {
        "cluster": "overseas",
        "driver": None,
        "default": "hold",
        "p1_force": None,
        "note": "stub，待官方API模块",
    },
    "x": {
        "cluster": "overseas",
        "driver": None,
        "default": "hold",
        "p1_force": None,
        "note": "stub，待官方API模块",
    },
}


def get_platform(key):
    """取单个平台 spec；未知 key 返回 None（调用方自行 fail-closed）。"""
    return PLATFORMS.get(key)


def list_platforms(cluster=None):
    """平台 key 列表；cluster='domestic'/'overseas' 可过滤。"""
    if cluster is None:
        return list(PLATFORMS.keys())
    return [k for k, v in PLATFORMS.items() if v.get("cluster") == cluster]


def register_platform(key, spec):
    """加平台：1 行注册。spec 至少含 cluster；缺省字段自动补 None。

    用法：register_platform("shipinhao", {"cluster": "domestic", "driver": None,
                                         "default": "hold"})
    已存在的 key 会抛 KeyError（防静默覆盖；改 spec 请直接改本文件）。
    """
    if key in PLATFORMS:
        raise KeyError(f"platform {key!r} 已存在，改 spec 请直接编辑 platform_registry.py")
    full = {"cluster": None, "driver": None, "default": "hold",
            "p1_force": None, "note": ""}
    full.update(spec or {})
    if not full.get("cluster"):
        raise ValueError(f"register_platform({key!r}): cluster 必填")
    PLATFORMS[key] = full
    return key


def check_version(required):
    """版本门：required 如 "1.0.0"；不满足抛 RuntimeError。"""
    if REGISTRY_VERSION != required:
        raise RuntimeError(
            f"platform_registry 版本不匹配：需要 {required}，实际 {REGISTRY_VERSION}")
