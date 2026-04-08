from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError

from .database import engine

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_SQL_FILES: list[Path] = [
    _PROJECT_ROOT / "app" / "core" / "sql" / "base_tables.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "anomaly_events.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "ai_anomaly_feedback.sql",
    _PROJECT_ROOT / "app" / "core" / "sql" / "ai_qa_sessions.sql",
]

_INDEX_FILE: Path = _PROJECT_ROOT / "app" / "core" / "sql" / "create_indexes.sql"

_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("ai_anomaly_feedback", "model_name", "VARCHAR(128)"),
    ("ai_anomaly_feedback", "analysis_mode", "VARCHAR(64)"),
]


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
