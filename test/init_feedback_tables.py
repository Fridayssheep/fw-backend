import os
from pathlib import Path

from sqlalchemy import create_engine

BASE_DIR = Path(__file__).resolve().parents[1]
sql_path = BASE_DIR / 'ai' / 'ai_anomaly_feedback.sql'
sql = sql_path.read_text(encoding='utf-8')
database_url = os.getenv('DATABASE_URL', '').strip() or (
    f"postgresql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
    f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
)
engine = create_engine(database_url)
with engine.begin() as conn:
    raw = conn.connection
    with raw.cursor() as cur:
        cur.execute(sql)
print('initialized')
