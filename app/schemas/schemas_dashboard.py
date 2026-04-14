from datetime import datetime  # 导入日期时间类型，方便定义异常开始时间与趋势标签。
from enum import Enum  # 导入枚举类型，方便约束 dashboard 的范围和状态字段。

from pydantic import BaseModel  # 导入 Pydantic 基类，方便定义响应模型。
from pydantic import Field  # 导入字段定义函数，方便给列表字段设置默认值。

from .schemas_common import DataStatus  # 导入通用数据状态枚举，方便区分缺失值和真实零值。
from .schemas_common import MetricCard  # 导入通用指标卡片模型，方便复用现有返回结构。
from .schemas_common import TimeRange  # 导入时间范围模型，方便复用现有时间口径。


class DashboardChartRange(str, Enum):  # 定义 dashboard 图表范围枚举。
    day = "day"  # 定义按日展示模式。
    week = "week"  # 定义按周展示模式。
    month = "month"  # 定义按月展示模式。


class DashboardCardStatus(str, Enum):  # 定义 dashboard 顶部卡片状态枚举。
    good = "good"  # 定义表现良好状态。
    neutral = "neutral"  # 定义中性状态。
    warning = "warning"  # 定义需要关注状态。
    danger = "danger"  # 定义高风险状态。


class DashboardHighlightType(str, Enum):  # 定义 dashboard 高亮类型枚举。
    anomaly = "anomaly"  # 定义异常型高亮。
    insight = "insight"  # 定义洞察型高亮。
    task = "task"  # 定义建议处理型高亮。


class DashboardQuickLinkLevel(str, Enum):  # 定义 dashboard 快捷跳转卡片等级枚举。
    critical = "critical"  # 定义紧急等级。
    warning = "warning"  # 定义警告等级。
    info = "info"  # 定义信息等级。


class DashboardMiniBar(BaseModel):  # 定义顶部卡片迷你柱状图模型。
    labels: list[str] = Field(default_factory=list)  # 定义迷你柱状图横轴标签列表字段。
    values: list[float | None] = Field(default_factory=list)  # 定义迷你柱状图纵轴数值列表字段，缺失时允许返回空值。
    data_statuses: list[DataStatus] = Field(default_factory=list)  # 定义每个柱子的取值状态列表，方便前端区分缺失和真实零值。


class DashboardKpiCard(BaseModel):  # 定义 dashboard 顶部 KPI 卡片模型。
    key: str  # 定义卡片键字段。
    title: str  # 定义卡片标题字段。
    value: float | None  # 定义卡片主值字段，缺失时允许返回空值。
    unit: str | None = None  # 定义卡片单位字段。
    change_rate: float | None = None  # 定义卡片变化率字段。
    subtitle: str = ""  # 定义卡片副标题字段。
    status: DashboardCardStatus = DashboardCardStatus.neutral  # 定义卡片状态字段。
    mini_bar: DashboardMiniBar = Field(default_factory=DashboardMiniBar)  # 定义卡片迷你柱状图字段。
    data_status: DataStatus = DataStatus.valid  # 定义卡片数据状态字段，方便区分缺失值和有效值。
    data_note: str | None = None  # 定义卡片数据说明字段，方便补充估算或过滤原因。


class DashboardTrendSeries(BaseModel):  # 定义 dashboard 折线图序列模型。
    key: str  # 定义序列键字段。
    name: str  # 定义序列名称字段。
    unit: str | None = None  # 定义序列单位字段。
    chart_type: str = "line"  # 定义序列图表类型字段。
    values: list[float | None] = Field(default_factory=list)  # 定义序列数值列表字段，缺失时允许返回空值。
    data_statuses: list[DataStatus] = Field(default_factory=list)  # 定义每个点位的数据状态列表。


class DashboardTrendChart(BaseModel):  # 定义 dashboard 折线图模型。
    range: DashboardChartRange = DashboardChartRange.day  # 定义图表范围字段。
    labels: list[str] = Field(default_factory=list)  # 定义折线图横轴标签列表字段。
    series: list[DashboardTrendSeries] = Field(default_factory=list)  # 定义折线图序列列表字段。


class DashboardBarChart(BaseModel):  # 定义 dashboard 柱状图模型。
    key: str  # 定义柱状图键字段。
    title: str  # 定义柱状图标题字段。
    unit: str | None = None  # 定义柱状图单位字段。
    labels: list[str] = Field(default_factory=list)  # 定义柱状图横轴标签列表字段。
    values: list[float | None] = Field(default_factory=list)  # 定义柱状图纵轴数值列表字段，缺失时允许返回空值。
    data_statuses: list[DataStatus] = Field(default_factory=list)  # 定义柱状图每个柱子的状态列表。


class AnomalySummary(BaseModel):  # 定义 dashboard 异常摘要模型。
    anomaly_id: str  # 定义异常编号字段。
    building_id: str  # 定义建筑编号字段。
    device_id: str | None = None  # 定义兼容旧文档的设备编号字段。
    meter: str  # 定义表计类型字段。
    severity: str  # 定义异常严重度字段。
    status: str  # 定义异常状态字段。
    title: str  # 定义异常标题字段。
    start_time: datetime  # 定义异常开始时间字段。


class DashboardHighlight(BaseModel):  # 定义 dashboard 高亮项模型。
    type: DashboardHighlightType  # 定义高亮类型字段。
    title: str  # 定义高亮标题字段。
    description: str  # 定义高亮描述字段。
    target: str  # 定义跳转目标字段。
    target_id: str | None = None  # 定义跳转目标编号字段。
    level: DashboardQuickLinkLevel = DashboardQuickLinkLevel.info  # 定义高亮等级字段。
    count: int | None = None  # 定义高亮关联数量字段。


class DashboardOverviewResponse(BaseModel):  # 定义 dashboard 总览响应模型。
    time_range: TimeRange  # 定义时间范围字段。
    metrics: list[MetricCard] = Field(default_factory=list)  # 定义指标卡片列表字段。
    kpi_cards: list[DashboardKpiCard] = Field(default_factory=list)  # 定义顶部 KPI 卡片列表字段。
    trend_chart: DashboardTrendChart = Field(default_factory=DashboardTrendChart)  # 定义折线图字段。
    bar_charts: list[DashboardBarChart] = Field(default_factory=list)  # 定义柱状图列表字段。
    quick_links: list[DashboardHighlight] = Field(default_factory=list)  # 定义右侧快捷跳转列表字段。
    top_anomalies: list[AnomalySummary] = Field(default_factory=list)  # 定义顶部异常摘要字段。
    ai_summary_hint: str  # 定义给前端展示的规则摘要提示字段。


class DashboardHighlightsResponse(BaseModel):  # 定义 dashboard 高亮列表响应模型。
    items: list[DashboardHighlight] = Field(default_factory=list)  # 定义高亮列表字段。
