#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
因果数据库 · 数字孪生 DNA v3.1

独立 SQLite 数据库，与业务库物理隔离。
记录每个视频的特征 → 72h 结果，是实验科学的唯一事实来源。

表结构：
  videos(id, title, features_json, views_72h, is_viral, source, created_at)
  features(video_id, feature_name, feature_value)
  experiments(exp_id, hypothesis, control, treatment, status, p_value,
              created_at, updated_at)

source 取值：normal | human_bypass | experiment
  - normal       : 自动流水线生产
  - human_bypass : 人工创意直投（Kimi 评审要求：必须打标签，进同一统计池）
  - experiment   : A/B 实验组样本

数据库文件：/home/hatch/data/perpetua/causal.db
（可通过环境变量 CAUSAL_DB_PATH 覆盖）
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

try:
    from objective_function import is_viral
except ImportError:  # 允许作为脚本直接运行
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from objective_function import is_viral

DEFAULT_DB_PATH = os.environ.get(
    "CAUSAL_DB_PATH", "/home/hatch/data/perpetua/causal.db")

VALID_SOURCES = ("normal", "human_bypass", "experiment")
VALID_EXP_STATUS = ("planned", "running", "done", "stopped")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    features_json TEXT NOT NULL DEFAULT '{}',
    views_72h    INTEGER,            -- NULL = 未满72h，结果未定稿
    is_viral     INTEGER,            -- 1/0；views_72h 为 NULL 时为 NULL
    source       TEXT NOT NULL DEFAULT 'normal'
                 CHECK (source IN ('normal','human_bypass','experiment')),
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS features (
    video_id      TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    feature_name  TEXT NOT NULL,
    feature_value TEXT NOT NULL,
    PRIMARY KEY (video_id, feature_name)
);
CREATE TABLE IF NOT EXISTS experiments (
    exp_id     TEXT PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    control    TEXT,
    treatment  TEXT,
    status     TEXT NOT NULL DEFAULT 'running'
               CHECK (status IN ('planned','running','done','stopped')),
    p_value    REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_source  ON videos(source);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
CREATE INDEX IF NOT EXISTS idx_features_name  ON features(feature_name);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CausalDB:
    """因果数据库访问层。"""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------- 写入 ----------------

    def ingest_video(self, video_id: str, title: str,
                     features: dict, views_72h: "int | None" = None,
                     source: str = "normal",
                     created_at: "str | None" = None) -> bool:
        """录入一条视频及其特征（幂等：同 id 覆盖写入）。

        Args:
            video_id: 业务侧视频唯一 ID。
            title: 标题。
            features: 特征字典 {feature_name: value}，value 会转 str 存储。
            views_72h: 72h 播放量；None 表示未定稿。
            source: normal | human_bypass | experiment。
            created_at: ISO 时间；None 则用当前 UTC。

        Returns:
            True 表示写入成功。

        Raises:
            ValueError: source 非法。
        """
        if source not in VALID_SOURCES:
            raise ValueError(f"source 非法: {source}，允许 {VALID_SOURCES}")
        viral = None if views_72h is None else (1 if is_viral(views_72h) else 0)
        ts = created_at or _utcnow()
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO videos(id,title,features_json,views_72h,is_viral,source,created_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, features_json=excluded.features_json,
                 views_72h=excluded.views_72h, is_viral=excluded.is_viral,
                 source=excluded.source""",
            (video_id, title, json.dumps(features, ensure_ascii=False),
             views_72h, viral, source, ts))
        cur.execute("DELETE FROM features WHERE video_id=?", (video_id,))
        cur.executemany(
            "INSERT INTO features(video_id,feature_name,feature_value) VALUES(?,?,?)",
            [(video_id, k, str(v)) for k, v in features.items()])
        self._conn.commit()
        return True

    def record_experiment(self, exp_id: str, hypothesis: str,
                          control: str = "", treatment: str = "",
                          status: str = "planned") -> bool:
        """登记一个实验。"""
        if status not in VALID_EXP_STATUS:
            raise ValueError(f"status 非法: {status}")
        ts = _utcnow()
        self._conn.execute(
            """INSERT INTO experiments(exp_id,hypothesis,control,treatment,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(exp_id) DO UPDATE SET
                 hypothesis=excluded.hypothesis, control=excluded.control,
                 treatment=excluded.treatment, updated_at=excluded.updated_at""",
            (exp_id, hypothesis, control, treatment, status, ts, ts))
        self._conn.commit()
        return True

    def update_experiment(self, exp_id: str, status: "str | None" = None,
                          p_value: "float | None" = None) -> bool:
        """更新实验状态 / p 值。"""
        sets, args = [], []
        if status is not None:
            if status not in VALID_EXP_STATUS:
                raise ValueError(f"status 非法: {status}")
            sets.append("status=?")
            args.append(status)
        if p_value is not None:
            sets.append("p_value=?")
            args.append(float(p_value))
        if not sets:
            return False
        sets.append("updated_at=?")
        args += [_utcnow(), exp_id]
        cur = self._conn.execute(
            f"UPDATE experiments SET {', '.join(sets)} WHERE exp_id=?", args)
        self._conn.commit()
        return cur.rowcount > 0

    # ---------------- 查询 ----------------

    def query_by_feature(self, feature_name: str,
                         feature_value: str) -> "list[str]":
        """查出具有某特征值的所有 video_id。"""
        rows = self._conn.execute(
            "SELECT video_id FROM features WHERE feature_name=? AND feature_value=?",
            (feature_name, str(feature_value))).fetchall()
        return [r["video_id"] for r in rows]

    def get_viral_rate_by_feature(self, feature_name: str,
                                  min_n: int = 1,
                                  source: "str | None" = None) -> dict:
        """按特征值分组统计爆款率（只计 views_72h 已定稿的视频）。

        Args:
            feature_name: 特征名。
            min_n: 该特征值最少样本数，低于则过滤。
            source: 限定来源；None 表示全来源（含 human_bypass 标签样本）。

        Returns:
            {feature_value: {"n": int, "viral": int, "rate": float}}
        """
        sql = """
            SELECT f.feature_value AS v,
                   COUNT(*) AS n,
                   SUM(vd.is_viral) AS viral
            FROM features f JOIN videos vd ON vd.id = f.video_id
            WHERE f.feature_name = ? AND vd.views_72h IS NOT NULL
        """
        args: list = [feature_name]
        if source is not None:
            if source not in VALID_SOURCES:
                raise ValueError(f"source 非法: {source}")
            sql += " AND vd.source = ?"
            args.append(source)
        sql += " GROUP BY f.feature_value HAVING n >= ?"
        args.append(min_n)
        out = {}
        for r in self._conn.execute(sql, args).fetchall():
            out[r["v"]] = {"n": r["n"], "viral": r["viral"] or 0,
                           "rate": (r["viral"] or 0) / r["n"]}
        return out

    def count_videos(self, source: "str | None" = None,
                     mature_only: bool = False) -> int:
        """视频总数；mature_only=True 只计 72h 已定稿的。"""
        sql = "SELECT COUNT(*) AS c FROM videos WHERE 1=1"
        args: list = []
        if source is not None:
            sql += " AND source=?"
            args.append(source)
        if mature_only:
            sql += " AND views_72h IS NOT NULL"
        return self._conn.execute(sql, args).fetchone()["c"]


if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mktemp(suffix=".db")
    with CausalDB(tmp) as db:
        # 1. 录入：question 风格 4 条（3 爆），statement 风格 4 条（1 爆）
        for i in range(4):
            db.ingest_video(f"q{i}", f"疑问标题{i}",
                            {"title_style": "question", "hour": "20"},
                            views_72h=200_000 if i < 3 else 50_000,
                            source="normal")
        for i in range(4):
            db.ingest_video(f"s{i}", f"陈述标题{i}",
                            {"title_style": "statement", "hour": "20"},
                            views_72h=200_000 if i == 0 else 50_000,
                            source="normal")
        # human_bypass 标签样本
        db.ingest_video("h0", "人工创意", {"title_style": "question"},
                        views_72h=300_000, source="human_bypass")
        # 未定稿样本（不计入统计）
        db.ingest_video("u0", "未定稿", {"title_style": "question"},
                        views_72h=None, source="normal")

        # 2. 按特征查询
        assert len(db.query_by_feature("title_style", "question")) == 6  # 4+1+1未定稿
        assert db.query_by_feature("title_style", "nope") == []

        # 3. 分组爆款率（只计定稿：question 5条4爆=0.8；statement 4条1爆=0.25）
        rates = db.get_viral_rate_by_feature("title_style")
        assert rates["question"] == {"n": 5, "viral": 4, "rate": 0.8}, rates
        assert rates["statement"] == {"n": 4, "viral": 1, "rate": 0.25}, rates

        # 4. source 过滤：只要 human_bypass
        hb = db.get_viral_rate_by_feature("title_style", source="human_bypass")
        assert hb == {"question": {"n": 1, "viral": 1, "rate": 1.0}}, hb

        # 5. min_n 过滤
        assert db.get_viral_rate_by_feature("title_style", min_n=10) == {}

        # 6. 计数
        assert db.count_videos() == 10
        assert db.count_videos(mature_only=True) == 9
        assert db.count_videos(source="human_bypass") == 1

        # 7. 幂等覆盖：更新 views_72h
        db.ingest_video("u0", "未定稿", {"title_style": "question"},
                        views_72h=500_000, source="normal")
        assert db.count_videos(mature_only=True) == 10

        # 8. 非法 source 抛错
        try:
            db.ingest_video("x", "t", {}, source="bad")
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass

        # 9. 实验表
        db.record_experiment("EXP-001", "疑问句>陈述句", "陈述句", "疑问句")
        assert db.update_experiment("EXP-001", status="done", p_value=0.03) is True
        assert db.update_experiment("EXP-999", status="done") is False

    os.unlink(tmp)
    print("causal_db.py 自测全部通过 ✓")
