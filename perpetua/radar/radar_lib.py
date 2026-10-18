#!/usr/bin/env python3
"""爆款雷达共享库（D20261017-002）：SQLite 仓库 + 工具函数。

只读雷达：本目录下所有脚本只做数据采集与指标计算，永不触发选题快车道、
自动发布或任何 Tier 3 动作（D20261016-007 冻结期至 2026-12-10）。
"""
import hashlib
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "radar.db")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
LOG_DIR = os.path.expanduser("~/workspace/goals/karenvsai/hidden_files/radar")

# ---- 竞品池规格 v1（D20261017-003，四脑议会 2026-10-17） ----
# 池子 ≤25；三档为筛选起点不是硬配额，宁可空位不降标准。
POOL_MAX = 25
TIERS = {
    "tier1": {"count": (8, 10), "subs": (500, 5000)},      # 直接对标：AI 喜剧
    "tier2": {"count": (5, 8), "subs": (10000, 100000)},   # 增长标杆
    "tier3": {"count": (3, 5), "subs": (100000, None)},    # 趋势风向标
}
BASELINE_WINDOW_DAYS = 90        # 基线回看窗口（同格式上传）
BASELINE_TARGET = (15, 30)       # 基线目标样本数
BASELINE_MIN = 6                 # 基线最低样本数（低频博主按实际发片量标注）
PROVISIONAL_BELOW = 10           # 基线 <10 一律标 PROVISIONAL 并显示样本数
EXCLUDE_AGE_HOURS = 48           # <48h 新视频不进基线/不出 outlier
OUTLIER_MIN_AGE_DAYS = 3         # outlier 必须按"同龄"第 N 天算，N≥3
PRUNE_DORMANCY_DAYS = 60         # 60 天断更 → 清退候选
QUOTA_HARD_STOP = 9500           # YouTube 配额硬停（雷达自有项目用量口径）
CHALLENGER_MAX = 2               # 挑战者名额 0–2 可选（非常备）
CHALLENGER_DAYS = 30             # 挑战者 30 天轮换
HISTORY_CUTOFF_DAYS = 365        # 365 天只约束增速/outlier 计算，老视频保留作历史上下文
THUMB_HASH_DISTANCE_THRESHOLD = 8  # dHash 64bit 汉明距离>8 才算缩略图变更（URL/CDN 变体不算）


def now_shanghai():
    """返回 Asia/Shanghai 当前时间（禁止裸 date.today()，见 AGENTS.md 2026-10-17 条）。"""
    return datetime.now(SHANGHAI)


def today_str():
    return now_shanghai().strftime("%Y-%m-%d")


def ts_str():
    return now_shanghai().strftime("%Y-%m-%d %H:%M:%S")


SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_videos(
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    channel_id TEXT,
    label TEXT NOT NULL DEFAULT 'own',
    tier TEXT,
    archived INTEGER DEFAULT 0,
    archived_reason TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY(platform, video_id)
);
CREATE TABLE IF NOT EXISTS video_snapshots(
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    title TEXT,
    thumbnail_url TEXT,
    thumbnail_hash TEXT,
    published_at TEXT,
    duration_sec REAL,
    thumb_phash TEXT,
    format TEXT,
    PRIMARY KEY(platform, video_id, snapshot_at)
);
CREATE INDEX IF NOT EXISTS idx_snap_lookup ON video_snapshots(platform, video_id, snapshot_at);
CREATE TABLE IF NOT EXISTS metrics(
    platform TEXT NOT NULL,
    video_id TEXT NOT NULL,
    metric_date TEXT NOT NULL,
    view_velocity REAL,
    outlier_score REAL,
    outlier_status TEXT,
    outlier_sample_n INTEGER,
    outlier_age_days INTEGER,
    title_changed INTEGER DEFAULT 0,
    thumbnail_changed INTEGER DEFAULT 0,
    computed_at TEXT NOT NULL,
    PRIMARY KEY(platform, video_id, metric_date)
);
CREATE TABLE IF NOT EXISTS prune_candidates(
    platform TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT,
    flagged_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_at TEXT,
    PRIMARY KEY(platform, channel_id, reason)
);
"""

# 老库迁移：connect() 时补齐新列（幂等，列已存在则跳过）。
MIGRATIONS = [
    "ALTER TABLE tracked_videos ADD COLUMN tier TEXT",
    "ALTER TABLE tracked_videos ADD COLUMN archived INTEGER DEFAULT 0",
    "ALTER TABLE tracked_videos ADD COLUMN archived_reason TEXT",
    "ALTER TABLE video_snapshots ADD COLUMN published_at TEXT",
    "ALTER TABLE video_snapshots ADD COLUMN duration_sec REAL",
    "ALTER TABLE video_snapshots ADD COLUMN thumb_phash TEXT",
    "ALTER TABLE video_snapshots ADD COLUMN format TEXT",
    "ALTER TABLE metrics ADD COLUMN outlier_status TEXT",
    "ALTER TABLE metrics ADD COLUMN outlier_sample_n INTEGER",
    "ALTER TABLE metrics ADD COLUMN outlier_age_days INTEGER",
]


def connect():
    os.makedirs(LOG_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for sql in MIGRATIONS:
        try:
            con.execute(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    con.commit()
    return con


def track_video(con, platform, video_id, channel_id=None, label="own"):
    con.execute(
        "INSERT INTO tracked_videos(platform, video_id, channel_id, label, added_at)"
        " VALUES(?,?,?,?,?)"
        " ON CONFLICT(platform, video_id) DO UPDATE SET"
        " channel_id=COALESCE(excluded.channel_id, tracked_videos.channel_id),"
        " label=excluded.label",
        (platform, video_id, channel_id, label, ts_str()),
    )


def insert_snapshot(con, platform, video_id, views, likes, comments, title, thumb_url,
                    thumb_hash, published_at=None, duration_sec=None, fmt=None,
                    thumb_phash=None):
    con.execute(
        "INSERT INTO video_snapshots(platform, video_id, snapshot_at, view_count,"
        " like_count, comment_count, title, thumbnail_url, thumbnail_hash,"
        " published_at, duration_sec, thumb_phash, format)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(platform, video_id, snapshot_at) DO UPDATE SET"
        " view_count=excluded.view_count, like_count=excluded.like_count,"
        " comment_count=excluded.comment_count, title=excluded.title,"
        " thumbnail_url=excluded.thumbnail_url,"
        " thumbnail_hash=COALESCE(excluded.thumbnail_hash, video_snapshots.thumbnail_hash),"
        " published_at=COALESCE(excluded.published_at, video_snapshots.published_at),"
        " duration_sec=COALESCE(excluded.duration_sec, video_snapshots.duration_sec),"
        " thumb_phash=COALESCE(excluded.thumb_phash, video_snapshots.thumb_phash),"
        " format=COALESCE(excluded.format, video_snapshots.format)",
        (platform, video_id, ts_str(), views, likes, comments, title, thumb_url, thumb_hash,
         published_at, duration_sec, thumb_phash, fmt),
    )


def _download_bytes(url, timeout=15):
    """下载 URL 字节；SSL 握手卡死时线程 join 硬兜底，超时/失败返回 None。

    2026-10-19 修：egress 代理后 urllib urlopen(timeout) 拦不住 SSL do_handshake
    无限等待（youtube_snapshot 连续 3 轮被 timeout kill）。网络 I/O 放 daemon
    线程，join(timeout+5) 硬上限；线程内异常静默，调用方按 None 处理。
    """
    box = {}

    def _fetch():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                box["data"] = r.read(2 * 1024 * 1024)
        except Exception:
            pass

    import threading
    t = threading.Thread(target=_fetch, daemon=True)
    t.start()
    t.join(timeout + 5)
    return box.get("data")


def thumbnail_hash(url, timeout=15):
    """下载缩略图并返回 sha256；失败返回 None（不阻断快照）。"""
    if not url:
        return None
    data = _download_bytes(url, timeout)
    if not data:
        return None
    return hashlib.sha256(data).hexdigest()[:32]


def append_run_log(name, line):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, name + ".log"), "a", encoding="utf-8") as f:
        f.write(f"{ts_str()} {line}\n")


def thumb_phash(url, timeout=15):
    """64 位 dHash 感知哈希（16 位十六进制）；下载失败返回 None（不阻断快照）。

    与 thumbnail_hash（sha256 精确字节哈希）不同：CDN 变体/重压缩导致的字节差异
    在 dHash 下距离≈0，不会误判为换图。
    """
    if not url:
        return None
    try:
        import io
        from PIL import Image
        data = _download_bytes(url, timeout)
        if not data:
            return None
        img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8), Image.LANCZOS)
        px = list(img.getdata())
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | (1 if px[y * 9 + x] > px[y * 9 + x + 1] else 0)
        return f"{bits:016x}"
    except Exception:
        return None


def hash_distance(h1, h2):
    """两组十六进制感知哈希的汉明距离；任一缺失返回 64（最大距离）。"""
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except Exception:
        return 64


def video_format(duration_sec):
    """同格式判定：Shorts/长视频绝不混算（Ask Studio 规格）。"""
    if duration_sec is None:
        return "unknown"
    return "short" if duration_sec <= 60 else "long"


def normalize_competitors(data):
    """兼容两种种子格式：字符串列表 或 {channel_id, tier, added_at} 对象。

    返回 [{'channel_id':..., 'tier': 'tier1'|'tier2'|'tier3'|'challenger'|None,
           'added_at': ...}]。tier 为 None 表示未定档。
    """
    out = []
    for ch in data or []:
        if isinstance(ch, str):
            out.append({"channel_id": ch, "tier": None, "added_at": None})
        elif isinstance(ch, dict):
            out.append({"channel_id": ch.get("channel_id") or ch.get("id"),
                        "tier": ch.get("tier"), "added_at": ch.get("added_at")})
    return [c for c in out if c["channel_id"]]


def quota_guard(estimated_units, what="radar"):
    """YouTube 配额硬停：雷达自有项目用量口径，超过 QUOTA_HARD_STOP 直接中止。"""
    if estimated_units > QUOTA_HARD_STOP:
        raise RuntimeError(
            f"{what}: estimated {estimated_units} units > QUOTA_HARD_STOP={QUOTA_HARD_STOP}, aborted")


def set_channel_archived(con, platform, channel_id, reason):
    """频道被删/停用/转私密时的唯一自动移除路径（红队 KILL 规则 9 修订）。

    只打标 tracked_videos.archived=1，历史快照保留可查；恢复=重新加回种子文件。
    """
    con.execute("UPDATE tracked_videos SET archived=1, archived_reason=?"
                " WHERE platform=? AND channel_id=?",
                (reason, platform, channel_id))
