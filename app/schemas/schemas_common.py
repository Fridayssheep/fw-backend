from datetime import datetime

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int


class MetricCard(BaseModel):
    key: str
    label: str
    value: float
    unit: str | None = None
    change_rate: float | None = None
