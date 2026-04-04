from datetime import datetime  # 导入日期时间类型，方便定义异常开始时间字段。
from enum import Enum  # 导入枚举类型，方便约束 dashboard 高亮类型。

from pydantic import BaseModel  # 导入 Pydantic 基类，方便定义响应模型。
from pydantic import Field  # 导入字段定义函数，方便给列表字段设置默认值。

from .schemas_common import MetricCard  # 导入通用指标卡片模型，方便复用现有返回结构。
from .schemas_common import TimeRange  # 导入时间范围模型，方便复用现有时间口径。


class DashboardHighlightType(str, Enum):  # 定义 dashboard 高亮类型枚举。
    anomaly = "anomaly"  # 定义异常型高亮。
    insight = "insight"  # 定义洞察型高亮。
    task = "task"  # 定义建议处理型高亮。


class AnomalySummary(BaseModel):  # 定义 dashboard 异常摘要模型。
    anomaly_id: str  # 定义异常编号字段。
    building_id: str  # 定义建筑编号字段。
    device_id: str | None = None  # 定义兼容旧文档的设备编号字段。
    meter: str  # 定义表计类型字段。
    severity: str  # 定义异常严重度字段。
    status: str  # 定义异常状态字段。
    title: str  # 定义异常标题字段。
    start_time: datetime  # 定义异常开始时间字段。


class DashboardOverviewResponse(BaseModel):  # 定义 dashboard 总览响应模型。
    time_range: TimeRange  # 定义时间范围字段。
    metrics: list[MetricCard] = Field(default_factory=list)  # 定义指标卡片列表字段。
    top_anomalies: list[AnomalySummary] = Field(default_factory=list)  # 定义顶部异常摘要字段。
    ai_summary_hint: str  # 定义给前端展示的规则摘要提示字段。


class DashboardHighlight(BaseModel):  # 定义 dashboard 高亮项模型。
    type: DashboardHighlightType  # 定义高亮类型字段。
    title: str  # 定义高亮标题字段。
    description: str  # 定义高亮描述字段。
    target: str  # 定义跳转目标字段。
    target_id: str | None = None  # 定义跳转目标编号字段。


class DashboardHighlightsResponse(BaseModel):  # 定义 dashboard 高亮列表响应模型。
    items: list[DashboardHighlight] = Field(default_factory=list)  # 定义高亮列表字段。
