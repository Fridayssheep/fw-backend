from datetime import datetime

from pydantic import BaseModel


class SystemHealth(BaseModel):
    status: str
    database: str
    timestamp: datetime
