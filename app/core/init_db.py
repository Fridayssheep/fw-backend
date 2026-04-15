from __future__ import annotations

import logging
import os
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError

from .database import engine

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_SQL_FILES: list[Path] = [
    _PROJECT_ROOT / "app" / "core" / "sql" / "base_tables.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "meter_daily_agg.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "anomaly_events.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "ai_anomaly_feedback.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "ai_qa_sessions.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "reports.sql",
]

_INDEX_FILE: Path = _PROJECT_ROOT / "app" / "core" / "sql" / "create_indexes.sql"

_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("ai_anomaly_feedback", "model_name", "VARCHAR(128)"),
    ("ai_anomaly_feedback", "analysis_mode", "VARCHAR(64)"),
]
_DASHBOARD_AGG_PREWARM_DAYS = int(os.getenv("DASHBOARD_AGG_PREWARM_DAYS", "45"))
_DASHBOARD_AGG_PREWARM_METERS = ("electricity", "chilledwater", "lighting")


def init_database() -> None:
    """Run idempotent schema initialization during app startup."""
    with engine.begin() as conn:
        for sql_file in _SQL_FILES:
            if not sql_file.exists():
                logger.warning("Schema SQL file not found, skipping: %s", sql_file)
                continue
            sql_content = sql_file.read_text(encoding="utf-8")
            for statement in _split_sql_statements(sql_content):
                conn.execute(text(statement))
            logger.info("Executed schema file: %s", sql_file.name)

        for table, column, col_type in _COLUMN_MIGRATIONS:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"))

    ensure_indexes()
    prewarm_dashboard_daily_agg()
    logger.info("Database schema and indexes initialization complete.")


def ensure_indexes() -> None:
    """Ensure indexes exist; safe to call repeatedly after each upload."""
    if not _INDEX_FILE.exists():
        logger.warning("Index SQL file not found, skipping: %s", _INDEX_FILE)
        return

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        sql_content = _INDEX_FILE.read_text(encoding="utf-8")
        for statement in _split_sql_statements(sql_content):
            _execute_index_statement(conn, statement)
    logger.info("Index ensure completed via: %s", _INDEX_FILE.name)


def prewarm_dashboard_daily_agg() -> None:  # 定义启动阶段预热 dashboard 日聚合窗口的函数。
    if _DASHBOARD_AGG_PREWARM_DAYS <= 0:  # 如果配置了非正预热天数，
        logger.info("跳过 dashboard 日聚合预热：DASHBOARD_AGG_PREWARM_DAYS <= 0。")  # 记录跳过原因日志。
        return  # 直接返回，避免执行预热 SQL。

    with engine.begin() as conn:  # 在一个事务中完成预热窗口重建，保证过程一致性。
        latest_timestamp = conn.execute(  # 先查询 electricity 的最新明细时间作为预热锚点。
            text(
                """
                SELECT MAX(timestamp) AS latest_timestamp
                FROM meter_readings
                WHERE meter = 'electricity'
                """
            )
        ).scalar()  # 读取标量结果。
        if latest_timestamp is None:  # 如果明细表为空，
            logger.info("跳过 dashboard 日聚合预热：meter_readings 为空。")  # 记录跳过日志。
            return  # 直接返回。

        if isinstance(latest_timestamp, datetime):  # 如果查询结果已经是 datetime，
            latest_day = latest_timestamp.date()  # 就直接取日期部分。
        else:  # 如果适配器返回了字符串或其他类型，
            latest_day = datetime.fromisoformat(str(latest_timestamp)).date()  # 就兜底解析成日期。

        start_day = latest_day - timedelta(days=_DASHBOARD_AGG_PREWARM_DAYS)  # 计算预热窗口起始日期。
        meter_params = {f"agg_meter_{index}": meter for index, meter in enumerate(_DASHBOARD_AGG_PREWARM_METERS)}  # 生成 meter 参数字典。
        meter_placeholders = ", ".join(f":agg_meter_{index}" for index, _ in enumerate(_DASHBOARD_AGG_PREWARM_METERS))  # 生成 meter 占位符列表。

        conn.execute(  # 先删除预热窗口内旧聚合结果，确保重算后数据干净。
            text(
                f"""
                DELETE FROM meter_daily_agg
                WHERE bucket_day >= :agg_start_day
                  AND bucket_day <= :agg_end_day
                  AND meter IN ({meter_placeholders})
                """
            ),
            {
                "agg_start_day": start_day,
                "agg_end_day": latest_day,
                **meter_params,
            },
        )

        conn.execute(  # 再把预热窗口内的明细按天重算写入聚合表。
            text(
                f"""
                INSERT INTO meter_daily_agg (
                    bucket_day,
                    building_id,
                    meter,
                    reading_sum,
                    reading_count,
                    latest_timestamp,
                    refreshed_at
                )
                SELECT
                    date_trunc('day', mr.timestamp)::date AS bucket_day,
                    mr.building_id AS building_id,
                    mr.meter AS meter,
                    COALESCE(SUM(mr.meter_reading), 0) AS reading_sum,
                    COUNT(mr.meter_reading) AS reading_count,
                    MAX(mr.timestamp) AS latest_timestamp,
                    NOW() AS refreshed_at
                FROM meter_readings mr
                WHERE mr.timestamp >= :agg_start_ts
                  AND mr.timestamp < :agg_end_exclusive
                  AND mr.meter IN ({meter_placeholders})
                GROUP BY 1, 2, 3
                """
            ),
            {
                "agg_start_ts": datetime.combine(start_day, datetime.min.time()),
                "agg_end_exclusive": datetime.combine(latest_day + timedelta(days=1), datetime.min.time()),
                **meter_params,
            },
        )

    logger.info(  # 记录预热完成日志，便于排查冷启动性能。
        "Dashboard 日聚合预热完成。start_day=%s end_day=%s meters=%s",
        start_day,
        latest_day,
        ",".join(_DASHBOARD_AGG_PREWARM_METERS),
    )


def _split_sql_statements(sql_content: str) -> list[str]:
    statements: list[str] = []
    for stmt in sql_content.split(";"):
        cleaned = stmt.strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def _execute_index_statement(connection: Connection, statement: str) -> None:
    """Execute one index statement; skip when target relation does not exist yet."""
    try:
        connection.execute(text(statement))
    except ProgrammingError as exc:
        if _is_missing_relation_error(exc):
            logger.warning("Skip index creation because target relation is missing: %s", statement)
            return
        raise


def _is_missing_relation_error(exc: ProgrammingError) -> bool:
    original = getattr(exc, "orig", None)
    pgcode = getattr(original, "pgcode", None)
    if pgcode == "42P01":
        return True

    text_message = str(exc).lower()
    if "does not exist" in text_message:
        return True
    if "不存在" in str(exc):
        return True
    return False
