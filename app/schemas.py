from datetime import date  # 导入日期类型，方便定义设备安装日期字段。
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


class MeterAvailability(BaseModel):  # 定义建筑表计可用性模型。
    meter: str  # 定义表计类型字段。
    available: bool  # 定义是否可用字段。


class MetricCard(BaseModel):  # 定义通用指标卡片模型。
    key: str  # 定义指标键字段。
    label: str  # 定义指标名称字段。
    value: float  # 定义指标值字段。
    unit: str | None = None  # 定义指标单位字段。
    change_rate: float | None = None  # 定义变化率字段。


class Building(BaseModel):  # 定义建筑基础信息模型。
    building_id: str  # 定义建筑编号字段。
    site_id: str  # 定义园区编号字段。
    primaryspaceusage: str  # 定义主要用途字段。
    sub_primaryspaceusage: str | None = None  # 定义次级用途字段。
    sqm: float | None = None  # 定义建筑面积字段。
    lat: float | None = None  # 定义纬度字段。
    lng: float | None = None  # 定义经度字段。
    timezone: str | None = None  # 定义时区字段。
    yearbuilt: int | None = None  # 定义建成年份字段。
    leed_level: str | None = None  # 定义 LEED 等级字段。


class BuildingListResponse(BaseModel):  # 定义建筑列表响应模型。
    items: list[Building]  # 定义建筑列表字段。
    pagination: Pagination  # 定义分页字段。


class BuildingDetailResponse(BaseModel):  # 定义建筑详情响应模型。
    building: Building  # 定义建筑信息字段。
    meters: list[MeterAvailability]  # 定义表计可用性列表字段。
    summary_metrics: list[MetricCard] = Field(default_factory=list)  # 定义摘要指标卡片字段。


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


class EnergySummaryResponse(BaseModel):  # 定义建筑级能耗摘要响应模型。
    building_id: str  # 定义建筑编号字段。
    time_range: TimeRange  # 定义时间范围字段。
    summary: EnergySummary  # 定义能耗摘要字段。


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


class DeviceSummary(BaseModel):  # 定义设备摘要模型。
    device_id: str  # 定义设备编号字段。
    device_name: str  # 定义设备名称字段。
    device_type: str  # 定义设备类型字段。
    building_id: str | None = None  # 定义建筑编号字段。
    status: str  # 定义设备状态字段。


class Device(DeviceSummary):  # 定义设备详情模型。
    manufacturer: str | None = None  # 定义制造商字段。
    model: str | None = None  # 定义型号字段。
    install_date: date | None = None  # 定义安装日期字段。
    last_seen_at: datetime | None = None  # 定义最后活跃时间字段。


class DeviceListResponse(BaseModel):  # 定义设备列表响应模型。
    items: list[Device]  # 定义设备列表字段。
    pagination: Pagination  # 定义分页字段。


class DeviceAlarm(BaseModel):  # 定义设备告警模型。
    alarm_id: str  # 定义告警编号字段。
    device_id: str  # 定义设备编号字段。
    level: str  # 定义告警等级字段。
    code: str | None = None  # 定义告警代码字段。
    message: str  # 定义告警消息字段。
    status: str  # 定义告警状态字段。
    occurred_at: datetime  # 定义告警发生时间字段。


class DeviceAlarmListResponse(BaseModel):  # 定义设备告警列表响应模型。
    items: list[DeviceAlarm]  # 定义告警列表字段。
    pagination: Pagination  # 定义分页字段。


class DeviceDetailResponse(BaseModel):  # 定义设备详情响应模型。
    device: Device  # 定义设备详情字段。
    recent_alarms: list[DeviceAlarm] = Field(default_factory=list)  # 定义最近告警字段。
    recent_metrics: list[MetricCard] = Field(default_factory=list)  # 定义最近指标字段。


class MaintenanceRecord(BaseModel):  # 定义维护记录模型。
    record_id: str  # 定义记录编号字段。
    device_id: str  # 定义设备编号字段。
    title: str  # 定义维护标题字段。
    description: str | None = None  # 定义维护描述字段。
    performed_at: datetime  # 定义维护执行时间字段。


class MaintenanceRecordListResponse(BaseModel):  # 定义维护记录列表响应模型。
    items: list[MaintenanceRecord]  # 定义维护记录列表字段。
    pagination: Pagination  # 定义分页字段。


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
