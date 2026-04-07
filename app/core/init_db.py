"""应用启动时的数据库 Schema 初始化。

所有建表语句都使用 IF NOT EXISTS，索引也使用 IF NOT EXISTS，
因此可以在每次应用启动时安全执行（幂等）。

对于已有表的新增列，使用 ALTER TABLE ... ADD COLUMN IF NOT EXISTS 补齐。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from .database import engine

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 需要按顺序执行的建表 SQL 文件
_SQL_FILES: list[Path] = [
    _PROJECT_ROOT / "dataprocess" / "anomaly_events.sql",
    _PROJECT_ROOT / "ai" / "ai_anomaly_feedback.sql",
    _PROJECT_ROOT / "ai" / "ai_qa_sessions.sql",
]

# 历史遗留列迁移：(表名, 列名, 列定义)
# 当 SQL 文件更新了而已有数据库 volume 未重建时，通过 ALTER TABLE 补齐
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("ai_anomaly_feedback", "model_name", "VARCHAR(128)"),
    ("ai_anomaly_feedback", "analysis_mode", "VARCHAR(64)"),
]


def init_database() -> None:
    """在应用启动时执行幂等的 schema 初始化。"""
    with engine.begin() as conn:
        # 1. 执行所有建表 SQL
        for sql_file in _SQL_FILES:
            if not sql_file.exists():
                logger.warning("Schema SQL file not found, skipping: %s", sql_file)
                continue
            sql_content = sql_file.read_text(encoding="utf-8")
            for statement in _split_sql_statements(sql_content):
                conn.execute(text(statement))
            logger.info("Executed schema file: %s", sql_file.name)

        # 2. 补齐可能缺失的列
        for table, column, col_type in _COLUMN_MIGRATIONS:
            conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
            ))
        logger.info("Database schema initialization complete.")


def _split_sql_statements(sql_content: str) -> list[str]:
    """将 SQL 文件内容按分号拆分为独立语句，忽略空语句。"""
    statements = []
    for stmt in sql_content.split(";"):
        cleaned = stmt.strip()
        if cleaned:
            statements.append(cleaned)
    return statements
