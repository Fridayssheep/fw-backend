from datetime import datetime  # 导入日期时间类型，方便定义通用时间字段。
from enum import Enum  # 导入枚举类型，方便统一约束数据状态字段。

from pydantic import BaseModel  # 导入 Pydantic 基类，方便定义通用响应模型。
from pydantic import Field  # 导入字段定义函数，方便补充模型描述信息。


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


class DataStatus(str, Enum):  # 定义通用数据状态枚举。
    valid = "valid"  # 定义真实有效数据状态。
    missing = "missing"  # 定义源数据缺失状态。
    estimated = "estimated"  # 定义基于规则估算出的数据状态。
    filtered = "filtered"  # 定义因异常范围或非法分母被过滤的数据状态。


class MetricCard(BaseModel):  # 定义通用指标卡片模型。
    key: str  # 定义卡片键字段。
    label: str  # 定义卡片标题字段。
    value: float | None  # 定义卡片主值字段，缺失时允许返回空值。
    unit: str | None = None  # 定义卡片单位字段。
    change_rate: float | None = None  # 定义卡片变化率字段。
    data_status: DataStatus = DataStatus.valid  # 定义卡片数据状态字段。
    data_note: str | None = None  # 定义卡片数据说明字段。
