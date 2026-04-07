from pathlib import Path

from app.core.database import engine


def main() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "ai" / "ai_qa_sessions.sql"
    sql_text = sql_path.read_text(encoding="utf-8")
    raw_connection = engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(sql_text)
        raw_connection.commit()
    finally:
        raw_connection.close()
    print("ai_qa_sessions and ai_qa_messages initialized successfully.")


if __name__ == "__main__":
    main()
