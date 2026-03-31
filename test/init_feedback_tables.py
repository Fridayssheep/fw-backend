from pathlib import Path
from sqlalchemy import create_engine
import os

sql_path = Path('D:/code/服外/fw-backend/ai/ai_anomaly_feedback.sql')
sql = sql_path.read_text(encoding='utf-8')
engine = create_engine(f"postgresql://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}")
with engine.begin() as conn:
    raw = conn.connection
    with raw.cursor() as cur:
        cur.execute(sql)
print('initialized')
