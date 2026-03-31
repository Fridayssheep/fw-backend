from datetime import datetime  # 导入日期时间类型，方便定义时间字段。
from typing import Any  # 导入任意类型注解，方便给松散结构做标注。

from pydantic import BaseModel  # 导入 Pydantic 基类，用来定义接口模型。
from pydantic import Field  # 导入字段定义函数，方便给字段设置默认值。


class ErrorResponse(BaseModel):  # 定义统一错误响应模型。
    code: str  # 定义错误码字段。
    message: str  # 定义错误信息字段。


class SystemHealth(BaseModel):  # 定义健康检查响应模型。
    status: str  # 定义服务状态字段。
    database: str  # 定义数据库状态字段。
    timestamp: datetime  # 定义响应时间字段。


class TimeRange(BaseModel):  # 定义时间范围模型。
    start: datetime  # 定义开始时间字段。
    end: datetime  # 定义结束时间字段。


class Pagination(BaseModel):  # 定义分页模型。
    page: int  # 定义页码字段。
    page_size: int  # 定义每页条数字段。
    total: int  # 定义总条数字段。


class EnergyPoint(BaseModel):  # 定义单个能耗点模型。
    timestamp: datetime  # 定义时间点字段。
    building_id: str | None = None  # 定义建筑编号字段。
    meter: str | None = None  # 定义表计类型字段。
    value: float  # 定义能耗值字段。


class EnergySummary(BaseModel):  # 定义能耗汇总模型。
    meter: str  # 定义表计类型字段。
    total: float  # 定义总能耗字段。
    average: float  # 定义平均能耗字段。
    peak: float  # 定义峰值能耗字段。
    peak_time: datetime | None = None  # 定义峰值时间字段。
    unit: str | None = None  # 定义单位字段。


class EnergyQueryResponse(BaseModel):  # 定义能耗明细查询响应模型。
    items: list[EnergyPoint]  # 定义明细数据列表字段。
    summary: EnergySummary  # 定义摘要字段。
    pagination: Pagination | None = None  # 定义分页字段。


class EnergySeries(BaseModel):  # 定义趋势序列模型。
    building_id: str | None = None  # 定义建筑编号字段。
    meter: str  # 定义表计类型字段。
    unit: str | None = None  # 定义单位字段。
    points: list[EnergyPoint]  # 定义点位列表字段。


class EnergyTrendResponse(BaseModel):  # 定义趋势响应模型。
    time_range: TimeRange  # 定义时间范围字段。
    series: list[EnergySeries]  # 定义趋势序列字段。


class EnergyCompareItem(BaseModel):  # 定义对比项模型。
    building_id: str  # 定义建筑编号字段。
    metric: str  # 定义对比指标字段。
    value: float  # 定义对比值字段。
    unit: str | None = None  # 定义单位字段。


class EnergyCompareResponse(BaseModel):  # 定义对比响应模型。
    items: list[EnergyCompareItem]  # 定义对比结果列表字段。


class EnergyRankingItem(BaseModel):  # 定义排行项模型。
    rank: int  # 定义排名字段。
    building_id: str  # 定义建筑编号字段。
    value: float  # 定义排行值字段。
    unit: str | None = None  # 定义单位字段。


class EnergyRankingResponse(BaseModel):  # 定义排行响应模型。
    items: list[EnergyRankingItem]  # 定义排行结果列表字段。


class CopPoint(BaseModel):  # 定义 COP 单点模型。
    timestamp: datetime  # 定义时间点字段。
    cop: float  # 定义 COP 数值字段。


class CopSummary(BaseModel):  # 定义 COP 摘要模型。
    avg_cop: float  # 定义平均 COP 字段。
    min_cop: float  # 定义最小 COP 字段。
    max_cop: float  # 定义最大 COP 字段。
    calculation_mode: str  # 定义计算模式字段。
    formula: str  # 定义公式说明字段。


class CopAnalysisResponse(BaseModel):  # 定义 COP 响应模型。
    building_id: str  # 定义建筑编号字段。
    time_range: TimeRange  # 定义时间范围字段。
    points: list[CopPoint]  # 定义 COP 点位列表字段。
    summary: CopSummary | dict[str, Any] | None = None  # 定义摘要字段，同时兼容文档里的 object。


class WeatherPoint(BaseModel):  # 定义天气点模型。
    timestamp: datetime  # 定义时间点字段。
    air_temperature: float | None = None  # 定义气温字段。
    dew_temperature: float | None = None  # 定义露点温度字段。
    wind_speed: float | None = None  # 定义风速字段。


class WeatherFactor(BaseModel):  # 定义天气相关因子模型。
    name: str  # 定义因子名称字段。
    coefficient: float  # 定义相关系数字段。
    direction: str  # 定义正负方向字段。


class WeatherCorrelationResponse(BaseModel):  # 定义天气相关性响应模型。
    building_id: str  # 定义建筑编号字段。
    meter: str  # 定义表计类型字段。
    correlation_coefficient: float  # 定义主相关系数字段。
    factors: list[WeatherFactor] = Field(default_factory=list)  # 定义因子列表字段。


class DetectedAnomalyPoint(BaseModel):  # 定义检测到的异常点模型。
    timestamp: datetime  # 定义异常时间字段。
    actual_value: float  # 定义实际值字段。
    baseline_value: float  # 定义基线值字段。
    deviation_rate: float  # 定义偏离率字段。
    severity: str  # 定义严重级别字段。


class EnergyAnomalyAnalysisRequest(BaseModel):  # 定义异常分析请求模型。
    building_id: str  # 定义建筑编号字段。
    meter: str  # 定义表计类型字段。
    time_range: TimeRange  # 定义时间范围字段。
    granularity: str | None = "hour"  # 定义粒度字段，默认按小时分析。
    baseline_mode: str | None = "overall_mean"  # 定义基线模式字段，默认整体均值。
    include_weather_context: bool | None = False  # 定义是否返回天气上下文字段。


class EnergyAnomalyAnalysisResponse(BaseModel):  # 定义异常分析响应模型。
    building_id: str  # 定义建筑编号字段。
    meter: str  # 定义表计类型字段。
    time_range: TimeRange  # 定义时间范围字段。
    is_anomalous: bool  # 定义是否存在异常字段。
    summary: str  # 定义摘要说明字段。
    baseline_mode: str  # 定义基线模式字段。
    detected_points: list[DetectedAnomalyPoint]  # 定义异常点列表字段。
    series: EnergySeries  # 定义用于分析的原始序列字段。
    weather_context: list[WeatherPoint] | None = None  # 定义天气上下文字段。
