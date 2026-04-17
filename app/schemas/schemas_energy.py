from datetime import datetime  # 导入日期时间类型，方便定义能耗和 COP 时间字段。
from typing import Any  # 导入任意类型注解，方便兼容动态 summary 结构。

from pydantic import BaseModel  # 导入 Pydantic 基类，方便定义 energy 相关响应模型。
from pydantic import Field  # 导入字段定义函数，方便给列表字段设置默认值。

from .schemas_common import DataStatus  # 导入通用数据状态枚举，方便区分缺失值和有效值。
from .schemas_common import Pagination  # 导入分页模型，方便复用统一分页结构。
from .schemas_common import TimeRange  # 导入时间范围模型，方便复用统一时间结构。


class EnergyPoint(BaseModel):  # 定义能耗点位模型。
    timestamp: datetime  # 定义点位时间字段。
    building_id: str | None = None  # 定义建筑编号字段。
    meter: str | None = None  # 定义表计类型字段。
    value: float | None  # 定义点位数值字段，缺失时允许返回空值。
    data_status: DataStatus = DataStatus.valid  # 定义点位数据状态字段。
    data_note: str | None = None  # 定义点位数据说明字段。


class EnergySummary(BaseModel):  # 定义能耗摘要模型。
    meter: str  # 定义摘要对应的表计字段。
    total: float | None  # 定义摘要总量字段，缺失时允许返回空值。
    average: float | None  # 定义摘要均值字段，缺失时允许返回空值。
    peak: float | None  # 定义摘要峰值字段，缺失时允许返回空值。
    peak_time: datetime | None = None  # 定义摘要峰值时间字段。
    unit: str | None = None  # 定义摘要单位字段。
    data_status: DataStatus = DataStatus.valid  # 定义摘要数据状态字段。
    reading_count: int = 0  # 定义摘要命中的真实读数条数字段。
    data_note: str | None = None  # 定义摘要数据说明字段。


class EnergySummaryResponse(BaseModel):
    building_id: str
    time_range: TimeRange
    summary: EnergySummary


class EnergyQueryResponse(BaseModel):
    items: list[EnergyPoint]
    summary: EnergySummary
    pagination: Pagination | None = None


class EnergySeries(BaseModel):
    building_id: str | None = None
    meter: str
    unit: str | None = None
    points: list[EnergyPoint]


class EnergyTrendResponse(BaseModel):
    time_range: TimeRange
    series: list[EnergySeries]


class EnergyCompareItem(BaseModel):  # 定义能耗对比项模型。
    building_id: str  # 定义建筑编号字段。
    metric: str  # 定义对比指标字段。
    value: float | None  # 定义对比结果字段，缺失时允许返回空值。
    unit: str | None = None  # 定义对比单位字段。
    data_status: DataStatus = DataStatus.valid  # 定义对比项数据状态字段。
    data_note: str | None = None  # 定义对比项数据说明字段。


class EnergyCompareResponse(BaseModel):
    items: list[EnergyCompareItem]


class EnergyRankingItem(BaseModel):  # 定义能耗排行项模型。
    rank: int  # 定义排名字段。
    building_id: str  # 定义建筑编号字段。
    value: float | None  # 定义排行结果字段，缺失时允许返回空值。
    unit: str | None = None  # 定义排行单位字段。
    data_status: DataStatus = DataStatus.valid  # 定义排行项数据状态字段。


class EnergyRankingResponse(BaseModel):
    items: list[EnergyRankingItem]


class CopPoint(BaseModel):  # 定义 COP 点位模型。
    timestamp: datetime  # 定义点位时间字段。
    cop: float | None  # 定义代理 COP 数值字段，缺失或过滤时允许返回空值。
    data_status: DataStatus = DataStatus.valid  # 定义点位数据状态字段。
    electricity_value: float | None = None  # 定义当前时间桶电表聚合值字段。
    chilledwater_value: float | None = None  # 定义当前时间桶冷冻水聚合值字段。
    data_note: str | None = None  # 定义点位数据说明字段。


class CopSummary(BaseModel):  # 定义 COP 摘要模型。
    avg_cop: float | None  # 定义平均代理 COP 字段。
    min_cop: float | None  # 定义最小代理 COP 字段。
    max_cop: float | None  # 定义最大代理 COP 字段。
    calculation_mode: str  # 定义 COP 计算模式字段。
    formula: str  # 定义 COP 公式说明字段。
    data_status: DataStatus = DataStatus.valid  # 定义摘要数据状态字段。
    valid_point_count: int = 0  # 定义有效点位数量字段。
    missing_point_count: int = 0  # 定义缺失点位数量字段。
    filtered_point_count: int = 0  # 定义过滤点位数量字段。
    data_note: str | None = None  # 定义摘要数据说明字段。


class CopAnalysisResponse(BaseModel):
    building_id: str
    time_range: TimeRange
    points: list[CopPoint]
    summary: CopSummary | dict[str, Any] | None = None


class WeatherPoint(BaseModel):
    timestamp: datetime
    air_temperature: float | None = None
    dew_temperature: float | None = None
    wind_speed: float | None = None


class BuildingWeatherPoint(BaseModel):  # 定义建筑天气点位模型。
    timestamp: datetime  # 定义天气点位时间字段。
    air_temperature: float | None = None  # 定义气温字段。
    dew_temperature: float | None = None  # 定义露点温度字段。
    wind_speed: float | None = None  # 定义风速字段。
    data_status: DataStatus = DataStatus.valid  # 定义点位数据状态字段。
    data_note: str | None = None  # 定义点位数据说明字段。


class BuildingWeatherSeries(BaseModel):  # 定义建筑天气序列模型。
    building_id: str  # 定义建筑编号字段。
    site_id: str | None = None  # 定义站点编号字段。
    points: list[BuildingWeatherPoint] = Field(default_factory=list)  # 定义天气点位列表字段。
    data_status: DataStatus = DataStatus.valid  # 定义序列数据状态字段。
    data_note: str | None = None  # 定义序列数据说明字段。


class BuildingWeatherQueryResponse(BaseModel):  # 定义建筑天气查询响应模型。
    time_range: TimeRange  # 定义查询时间范围字段。
    granularity: str  # 定义查询粒度字段。
    series: list[BuildingWeatherSeries] = Field(default_factory=list)  # 定义建筑天气序列列表字段。
    missing_building_ids: list[str] = Field(default_factory=list)  # 定义未匹配到元数据的建筑列表字段。


class WeatherFactor(BaseModel):
    name: str
    coefficient: float
    direction: str


class WeatherCorrelationResponse(BaseModel):
    building_id: str
    meter: str
    correlation_coefficient: float
    factors: list[WeatherFactor] = Field(default_factory=list)


class DetectedAnomalyEvent(BaseModel):
    event_id: str
    start_time: datetime
    end_time: datetime
    severity: str
    detected_by: str
    event_type: str
    description: str
    peak_deviation: float | None = None


class AnomalyDetectorBreakdownItem(BaseModel):
    detected_by: str
    event_type: str
    count: int


class EnergyAnomalyAnalysisRequest(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    granularity: str | None = "hour"
    analysis_mode: str | None = "offline_event_review"
    include_weather_context: bool | None = False


class EnergyAnomalyAnalysisResponse(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    is_anomalous: bool
    summary: str
    analysis_mode: str = "offline_event_review"
    event_count: int = 0
    detector_breakdown: list[AnomalyDetectorBreakdownItem] = Field(default_factory=list)
    detected_events: list[DetectedAnomalyEvent] = Field(default_factory=list)
    series: EnergySeries
    weather_context: list[WeatherPoint] | None = None
