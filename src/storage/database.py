"""
数据库存储模块
==============
使用 SQLite 持久化情报数据：
- raw_intelligence: 原始采集数据（保留3个月）
- reports: 生成的报告记录（保留12期/6个月）
- jobs: 任务执行记录
"""

import json
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger


class IntelligenceDB:
    """情报数据库管理类"""

    def __init__(self, db_path: str):
        """
        初始化数据库连接。

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（懒加载）"""
        if self._conn is None:
            # 确保父目录存在
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            logger.info(f"数据库已连接: {self.db_path}")
        return self._conn

    def _init_tables(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        conn.executescript("""
            -- 原始采集数据表
            CREATE TABLE IF NOT EXISTS raw_intelligence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                source_channel TEXT NOT NULL,       -- wechat/website/news
                source_name TEXT NOT NULL,          -- 来源名称
                title TEXT NOT NULL,
                url TEXT DEFAULT '',
                content TEXT DEFAULT '',
                publish_date TEXT,                   -- ISO 格式
                raw_metadata TEXT DEFAULT '{}',     -- JSON
                content_hash TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- 报告记录表
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,           -- 报告日期
                report_period TEXT NOT NULL,         -- 报告区间
                total_items INTEGER DEFAULT 0,
                important_items INTEGER DEFAULT 0,
                summary TEXT DEFAULT '',
                report_json TEXT DEFAULT '{}',       -- 完整 JSON 报告
                report_html_path TEXT DEFAULT '',    -- HTML 文件路径
                notification_sent_to TEXT DEFAULT '[]', -- JSON array
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- 任务执行记录表
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                execution_time TEXT NOT NULL,
                status TEXT DEFAULT 'running',       -- running/success/failed/partial
                channels_succeeded TEXT DEFAULT '[]',-- JSON array
                channels_failed TEXT DEFAULT '[]',   -- JSON array
                total_items_collected INTEGER DEFAULT 0,
                important_items_found INTEGER DEFAULT 0,
                report_generated INTEGER DEFAULT 0,  -- boolean
                error_message TEXT DEFAULT '',
                duration_seconds REAL DEFAULT 0.0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- 索引
            CREATE INDEX IF NOT EXISTS idx_raw_job ON raw_intelligence(job_id);
            CREATE INDEX IF NOT EXISTS idx_raw_channel ON raw_intelligence(source_channel);
            CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_intelligence(publish_date);
            CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date);
            CREATE INDEX IF NOT EXISTS idx_jobs_time ON jobs(execution_time);
        """)
        logger.debug("数据库表初始化完成")

    # ==================== 原始数据操作 ====================

    def save_raw_items(self, job_id: str, items: list) -> int:
        """
        批量保存原始采集数据。

        Args:
            job_id: 任务ID
            items: RawItem 列表

        Returns:
            保存的记录数
        """
        conn = self._get_conn()
        rows = []
        for item in items:
            rows.append((
                job_id,
                item.source_channel,
                item.source_name,
                item.title,
                getattr(item, 'url', ''),
                getattr(item, 'content', ''),
                item.publish_date.isoformat() if item.publish_date else None,
                json.dumps(getattr(item, 'raw_metadata', {}), ensure_ascii=False),
                getattr(item, 'content_hash', ''),
            ))

        conn.executemany(
            """INSERT INTO raw_intelligence
               (job_id, source_channel, source_name, title, url, content,
                publish_date, raw_metadata, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        logger.info(f"已保存 {len(rows)} 条原始数据到数据库")
        return len(rows)

    def get_raw_items_by_job(self, job_id: str) -> list[dict]:
        """获取某次任务的原始数据"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM raw_intelligence WHERE job_id = ? ORDER BY publish_date DESC",
            (job_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent_raw_items(self, days: int = 14) -> list[dict]:
        """获取最近N天的原始数据（用于查看近期采集）"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = conn.execute(
            "SELECT * FROM raw_intelligence WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 报告操作 ====================

    def save_report(self, report_data: dict) -> int:
        """
        保存情报报告。

        Args:
            report_data: 报告字典（IntelligenceReport.model_dump()）

        Returns:
            插入的记录ID
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO reports
               (report_date, report_period, total_items, important_items,
                summary, report_json, report_html_path, notification_sent_to)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(report_data.get("report_date", "")),
                report_data.get("report_period", ""),
                report_data.get("total_items", 0),
                report_data.get("important_items", 0),
                report_data.get("summary", ""),
                json.dumps(report_data, ensure_ascii=False, default=str),
                report_data.get("report_html_path", ""),
                json.dumps(report_data.get("notification_sent_to", []), ensure_ascii=False),
            ),
        )
        conn.commit()
        report_id = cursor.lastrowid
        logger.info(f"报告已保存，ID={report_id}")
        return report_id

    def get_recent_reports(self, limit: int = 12) -> list[dict]:
        """获取最近N期报告"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM reports ORDER BY report_date DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_latest_report(self) -> Optional[dict]:
        """获取最新一期报告"""
        reports = self.get_recent_reports(limit=1)
        return reports[0] if reports else None

    # ==================== 任务记录操作 ====================

    def create_job(self, job_id: str) -> int:
        """创建任务记录"""
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO jobs (job_id, execution_time, status) VALUES (?, ?, ?)",
            (job_id, datetime.now().isoformat(), "running"),
        )
        conn.commit()
        return cursor.lastrowid

    def update_job(self, job_id: str, **kwargs):
        """更新任务记录"""
        if not kwargs:
            return
        # 处理 JSON 字段
        for field in ["channels_succeeded", "channels_failed"]:
            if field in kwargs and isinstance(kwargs[field], list):
                kwargs[field] = json.dumps(kwargs[field], ensure_ascii=False)

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [job_id]
        conn = self._get_conn()
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE job_id = ?", values)
        conn.commit()

    def get_job(self, job_id: str) -> Optional[dict]:
        """获取任务记录"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_recent_jobs(self, limit: int = 24) -> list[dict]:
        """获取最近的任务记录"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM jobs ORDER BY execution_time DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 维护操作 ====================

    def cleanup_old_data(self, max_age_days: int = 90):
        """清理过期的原始数据（默认保留3个月）"""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
        cursor = conn.execute(
            "DELETE FROM raw_intelligence WHERE created_at < ?",
            (cutoff,),
        )
        conn.commit()
        deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"已清理 {deleted} 条过期原始数据（{max_age_days}天前）")
        return deleted

    def get_stats(self) -> dict:
        """获取数据库统计信息"""
        conn = self._get_conn()
        stats = {}
        for table in ["raw_intelligence", "reports", "jobs"]:
            cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            row = cursor.fetchone()
            stats[f"{table}_count"] = row["cnt"] if row else 0
        return stats

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("数据库连接已关闭")
