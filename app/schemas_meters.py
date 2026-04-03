from datetime import date
from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from pydantic import Field

from .schemas_common import MetricCard
from .schemas_common import Pagination


class MeterStatus(str, Enum):
    online = "online"
    warning = "warning"
    fault = "fault"
    offline = "offline"


class MeterSummary(BaseModel):
    meter_id: str
    meter_name: str
    meter_type: str
    building_id: str | None = None
    status: MeterStatus


class Meter(MeterSummary):
    manufacturer: str | None = None
    model: str | None = None
    install_date: date | None = None
    last_seen_at: datetime | None = None


class MeterListResponse(BaseModel):
    items: list[Meter]
    pagination: Pagination


class MeterAlarmLevel(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class MeterAlarmStatus(str, Enum):
    open = "open"
    closed = "closed"


class MeterAlarm(BaseModel):
    alarm_id: str
    meter_id: str
    level: MeterAlarmLevel
    code: str | None = None
    message: str
    status: MeterAlarmStatus
    occurred_at: datetime


class MeterAlarmListResponse(BaseModel):
    items: list[MeterAlarm]
    pagination: Pagination


class MeterDetailResponse(BaseModel):
    meter: Meter
    recent_alarms: list[MeterAlarm] = Field(default_factory=list)
    recent_metrics: list[MetricCard] = Field(default_factory=list)


class MaintenanceRecord(BaseModel):
    record_id: str
    meter_id: str
    title: str
    description: str | None = None
    performed_at: datetime


class MaintenanceRecordListResponse(BaseModel):
    items: list[MaintenanceRecord]
    pagination: Pagination


DeviceSummary = MeterSummary
Device = Meter
DeviceListResponse = MeterListResponse
DeviceAlarm = MeterAlarm
DeviceAlarmListResponse = MeterAlarmListResponse
DeviceDetailResponse = MeterDetailResponse
