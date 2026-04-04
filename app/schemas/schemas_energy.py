from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from .schemas_common import Pagination
from .schemas_common import TimeRange


class EnergyPoint(BaseModel):
    timestamp: datetime
    building_id: str | None = None
    meter: str | None = None
    value: float


class EnergySummary(BaseModel):
    meter: str
    total: float
    average: float
    peak: float
    peak_time: datetime | None = None
    unit: str | None = None


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


class EnergyCompareItem(BaseModel):
    building_id: str
    metric: str
    value: float
    unit: str | None = None


class EnergyCompareResponse(BaseModel):
    items: list[EnergyCompareItem]


class EnergyRankingItem(BaseModel):
    rank: int
    building_id: str
    value: float
    unit: str | None = None


class EnergyRankingResponse(BaseModel):
    items: list[EnergyRankingItem]


class CopPoint(BaseModel):
    timestamp: datetime
    cop: float


class CopSummary(BaseModel):
    avg_cop: float
    min_cop: float
    max_cop: float
    calculation_mode: str
    formula: str


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


class WeatherFactor(BaseModel):
    name: str
    coefficient: float
    direction: str


class WeatherCorrelationResponse(BaseModel):
    building_id: str
    meter: str
    correlation_coefficient: float
    factors: list[WeatherFactor] = Field(default_factory=list)


class DetectedAnomalyPoint(BaseModel):
    timestamp: datetime
    actual_value: float
    baseline_value: float
    deviation_rate: float
    severity: str


class EnergyAnomalyAnalysisRequest(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    granularity: str | None = "hour"
    baseline_mode: str | None = "overall_mean"
    include_weather_context: bool | None = False


class EnergyAnomalyAnalysisResponse(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    is_anomalous: bool
    summary: str
    baseline_mode: str
    detected_points: list[DetectedAnomalyPoint]
    series: EnergySeries
    weather_context: list[WeatherPoint] | None = None
