from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class ErrorResponse(BaseModel):
    code: str
    message: str


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class CurrentTimeContext(BaseModel):
    use_current_time: bool = Field(
        default=True,
        description="是否直接使用后端当前时间。为 false 时，将使用 current_time 作为时间锚点。",
    )
    current_time: datetime | None = Field(
        default=None,
        description="前端指定的当前时间。仅在 use_current_time=false 时生效。",
    )
    timezone: str | None = Field(
        default=None,
        description="当前时间所属时区，例如 Asia/Shanghai。未传时使用后端默认时区。",
    )


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
