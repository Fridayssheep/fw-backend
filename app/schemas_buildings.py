from pydantic import BaseModel
from pydantic import Field

from .schemas_common import MetricCard
from .schemas_common import Pagination


class MeterAvailability(BaseModel):
    meter: str
    available: bool


class Building(BaseModel):
    building_id: str
    site_id: str
    primaryspaceusage: str
    sub_primaryspaceusage: str | None = None
    sqm: float | None = None
    lat: float | None = None
    lng: float | None = None
    timezone: str | None = None
    yearbuilt: int | None = None
    leed_level: str | None = None


class BuildingListResponse(BaseModel):
    items: list[Building]
    pagination: Pagination


class BuildingDetailResponse(BaseModel):
    building: Building
    meters: list[MeterAvailability]
    summary_metrics: list[MetricCard] = Field(default_factory=list)
