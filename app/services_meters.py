import math
from datetime import datetime
from datetime import timedelta
from typing import Any

from .database import fetch_all
from .database import fetch_one
from .schemas import MaintenanceRecord
from .schemas import MaintenanceRecordListResponse
from .schemas import Meter
from .schemas import MeterAlarm
from .schemas import MeterAlarmListResponse
from .schemas import MeterDetailResponse
from .schemas import MeterListResponse
from .schemas import MeterStatus
from .schemas import MetricCard
from .schemas import Pagination
from .service_common import ResourceNotFoundError
from .service_common import get_latest_timestamp
from .service_common import get_meter_unit
from .service_common import normalize_pagination
from .service_common import normalize_text
from .service_common import require_api_datetime
from .service_common import to_api_datetime
from .services_buildings import DEFAULT_WINDOW_DAYS
from .services_buildings import get_meter_window_statistics


METER_STATUS_ONLINE_WINDOW = timedelta(days=2)
METER_STATUS_WARNING_WINDOW = timedelta(days=7)
METER_STATUS_FAULT_WINDOW = timedelta(days=14)
METER_ALARM_LOOKBACK_DAYS = 30
METER_RECENT_ALARM_LIMIT = 5
METER_ID_SEPARATOR = "::"
METER_TYPE_LABEL_MAP = {
    "electricity": "Electricity Meter",
    "water": "Water Meter",
    "gas": "Gas Meter",
    "hotwater": "Hot Water Meter",
    "chilledwater": "Chilled Water Meter",
    "steam": "Steam Meter",
    "solar": "Solar Meter",
    "irrigation": "Irrigation Meter",
}


def build_meter_id(building_id: str, meter: str) -> str:
    return f"{building_id}{METER_ID_SEPARATOR}{meter}"


def parse_meter_id(meter_id: str) -> tuple[str, str]:
    if METER_ID_SEPARATOR not in meter_id:
        raise ValueError("非法 meterId，必须使用 meters 列表接口返回的 meter_id。")
    building_id, meter = meter_id.rsplit(METER_ID_SEPARATOR, 1)
    if not building_id or not meter:
        raise ValueError("非法 meterId，缺少 building_id 或 meter_type。")
    return building_id, meter


def build_meter_name(building_id: str, meter: str) -> str:
    meter_label = METER_TYPE_LABEL_MAP.get(meter, meter.replace("_", " ").title())
    return f"{building_id} {meter_label}"


def calculate_change_rate(current_value: float, previous_value: float) -> float | None:
    if previous_value == 0:
        return None
    return round((current_value - previous_value) / previous_value, 4)


def build_meter_status(last_seen_at: datetime | None, reference_latest: datetime) -> MeterStatus:
    if last_seen_at is None:
        return MeterStatus.offline
    lag = reference_latest - last_seen_at
    if lag <= METER_STATUS_ONLINE_WINDOW:
        return MeterStatus.online
    if lag <= METER_STATUS_WARNING_WINDOW:
        return MeterStatus.warning
    if lag <= METER_STATUS_FAULT_WINDOW:
        return MeterStatus.fault
    return MeterStatus.offline


def get_meter_base_row_or_raise(building_id: str, meter: str) -> dict[str, Any]:
    row = fetch_one(
        """
        SELECT
            mr.building_id AS building_id,
            mr.meter AS meter_type,
            MAX(mr.timestamp) AS last_seen_at
        FROM meter_readings mr
        WHERE mr.building_id = :building_id
          AND mr.meter = :meter
        GROUP BY mr.building_id, mr.meter
        """,
        {"building_id": building_id, "meter": meter},
    )
    if row is None:
        raise ResourceNotFoundError(f"未找到表计: {build_meter_id(building_id, meter)}")
    return row


def map_meter_row_to_model(row: dict[str, Any], reference_latest: datetime) -> Meter:
    building_id = str(row["building_id"])
    meter = str(row["meter_type"])
    return Meter(
        meter_id=build_meter_id(building_id, meter),
        meter_name=build_meter_name(building_id, meter),
        meter_type=meter,
        building_id=building_id,
        status=build_meter_status(row.get("last_seen_at"), reference_latest),
        manufacturer=None,
        model=None,
        install_date=None,
        last_seen_at=to_api_datetime(row.get("last_seen_at")),
    )


def build_meter_recent_metrics(building_id: str, meter: str) -> list[MetricCard]:
    meter_stats = get_meter_window_statistics(building_id, meter)
    unit = get_meter_unit(meter)
    return [
        MetricCard(
            key="latest_reading",
            label="最新读数",
            value=meter_stats["latest_value"],
            unit=unit,
        ),
        MetricCard(
            key="recent_average",
            label=f"近{DEFAULT_WINDOW_DAYS}天平均值",
            value=meter_stats["current_average"],
            unit=unit,
            change_rate=calculate_change_rate(meter_stats["current_average"], meter_stats["previous_average"]),
        ),
        MetricCard(
            key="recent_peak",
            label=f"近{DEFAULT_WINDOW_DAYS}天峰值",
            value=meter_stats["current_peak"],
            unit=unit,
        ),
    ]


def build_meter_alarm_items(building_id: str, meter: str) -> list[MeterAlarm]:
    meter_row = get_meter_base_row_or_raise(building_id, meter)
    window_end = meter_row.get("last_seen_at") or get_latest_timestamp([building_id], None, meter)
    window_start = window_end - timedelta(days=METER_ALARM_LOOKBACK_DAYS)
    rows = fetch_all(
        """
        SELECT
            timestamp,
            meter_reading
        FROM meter_readings
        WHERE building_id = :building_id
          AND meter = :meter
          AND timestamp >= :start_time
          AND timestamp <= :end_time
        ORDER BY timestamp DESC
        """,
        {"building_id": building_id, "meter": meter, "start_time": window_start, "end_time": window_end},
    )
    if not rows:
        return []

    values = [float(row["meter_reading"] or 0) for row in rows]
    mean_value = sum(values) / len(values) if values else 0.0
    variance = sum((value - mean_value) ** 2 for value in values) / len(values) if values else 0.0
    std_value = math.sqrt(variance)
    meter_id = build_meter_id(building_id, meter)
    alarms: list[MeterAlarm] = []

    for row in rows:
        current_value = float(row["meter_reading"] or 0)
        deviation_rate = abs(current_value - mean_value) / mean_value if mean_value else 0.0
        z_score = abs(current_value - mean_value) / std_value if std_value else 0.0
        if deviation_rate < 0.35 and z_score < 2.0:
            continue

        if deviation_rate >= 0.8 or z_score >= 3.0:
            level = "critical"
        elif deviation_rate >= 0.5 or z_score >= 2.5:
            level = "warning"
        else:
            level = "info"

        direction_label = "偏高" if current_value >= mean_value else "偏低"
        alarm_status = "open" if row["timestamp"] >= window_end - timedelta(hours=24) else "closed"
        alarms.append(
            MeterAlarm(
                alarm_id=f"{meter_id}{METER_ID_SEPARATOR}alarm{METER_ID_SEPARATOR}{row['timestamp'].strftime('%Y%m%d%H%M%S')}",
                meter_id=meter_id,
                level=level,
                code="ENERGY_SPIKE" if current_value >= mean_value else "ENERGY_DROP",
                message=f"{meter} 表计读数出现明显{direction_label}，当前值 {round(current_value, 4)}，相对均值偏离 {round(deviation_rate * 100, 2)}%。",
                status=alarm_status,
                occurred_at=require_api_datetime(row["timestamp"]),
            )
        )
    return alarms


def build_meter_maintenance_items(building_id: str, meter: str) -> list[MaintenanceRecord]:
    meter_row = get_meter_base_row_or_raise(building_id, meter)
    reference_time = meter_row.get("last_seen_at") or get_latest_timestamp([building_id], None, meter)
    meter_id = build_meter_id(building_id, meter)
    record_defs = [
        ("routine_check", "例行巡检", 30, "演示环境推导记录：基于表计最近活跃时间生成的例行巡检。"),
        ("calibration", "计量校准", 120, "演示环境推导记录：用于前端联调的周期性计量校准记录。"),
        ("communication_check", "通讯检查", 240, "演示环境推导记录：用于前端联调的通讯链路健康检查记录。"),
    ]
    items: list[MaintenanceRecord] = []
    for index, (record_key, title, days_offset, description) in enumerate(record_defs, start=1):
        performed_at = reference_time - timedelta(days=days_offset)
        items.append(
            MaintenanceRecord(
                record_id=f"{meter_id}{METER_ID_SEPARATOR}maintenance{METER_ID_SEPARATOR}{record_key}{METER_ID_SEPARATOR}{index}",
                meter_id=meter_id,
                title=title,
                description=description,
                performed_at=require_api_datetime(performed_at),
            )
        )
    return items


def get_meters(
    building_id: str | None,
    meter_type: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> MeterListResponse:
    clauses: list[str] = ["1=1"]
    params: dict[str, Any] = {}
    normalized_building_id = normalize_text(building_id)
    if normalized_building_id:
        clauses.append("mr.building_id = :building_id")
        params["building_id"] = normalized_building_id
    normalized_meter_type = normalize_text(meter_type)
    if normalized_meter_type:
        clauses.append("mr.meter = :meter_type")
        params["meter_type"] = normalized_meter_type

    rows = fetch_all(
        f"""
        SELECT
            mr.building_id AS building_id,
            mr.meter AS meter_type,
            MAX(mr.timestamp) AS last_seen_at
        FROM meter_readings mr
        WHERE {' AND '.join(clauses)}
        GROUP BY mr.building_id, mr.meter
        ORDER BY mr.building_id ASC, mr.meter ASC
        """,
        params,
    )
    reference_latest = get_latest_timestamp()
    items = [map_meter_row_to_model(row, reference_latest) for row in rows]

    normalized_status = normalize_text(status)
    if normalized_status:
        items = [item for item in items if item.status.value.lower() == normalized_status.lower()]

    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)
    paged_items = items[offset : offset + safe_page_size]
    return MeterListResponse(
        items=paged_items,
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),
    )


def get_meter_detail(meter_id: str) -> MeterDetailResponse:
    building_id, meter = parse_meter_id(meter_id)
    meter_row = get_meter_base_row_or_raise(building_id, meter)
    reference_latest = get_latest_timestamp()
    meter_model = map_meter_row_to_model(meter_row, reference_latest)
    recent_alarms = build_meter_alarm_items(building_id, meter)[:METER_RECENT_ALARM_LIMIT]
    recent_metrics = build_meter_recent_metrics(building_id, meter)
    return MeterDetailResponse(
        meter=meter_model,
        recent_alarms=recent_alarms,
        recent_metrics=recent_metrics,
    )


def get_meter_alarms(meter_id: str, page: int, page_size: int) -> MeterAlarmListResponse:
    building_id, meter = parse_meter_id(meter_id)
    items = build_meter_alarm_items(building_id, meter)
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)
    paged_items = items[offset : offset + safe_page_size]
    return MeterAlarmListResponse(
        items=paged_items,
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),
    )


def get_meter_maintenance_records(meter_id: str, page: int, page_size: int) -> MaintenanceRecordListResponse:
    building_id, meter = parse_meter_id(meter_id)
    items = build_meter_maintenance_items(building_id, meter)
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)
    paged_items = items[offset : offset + safe_page_size]
    return MaintenanceRecordListResponse(
        items=paged_items,
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),
    )


# 兼容旧的 device 命名，避免其他模块导入路径立刻失效。
build_device_id = build_meter_id
parse_device_id = parse_meter_id
build_device_name = build_meter_name
build_device_status = build_meter_status
get_device_base_row_or_raise = get_meter_base_row_or_raise
map_device_row_to_model = map_meter_row_to_model
build_device_recent_metrics = build_meter_recent_metrics
build_device_alarm_items = build_meter_alarm_items
build_device_maintenance_items = build_meter_maintenance_items
get_devices = get_meters
get_device_detail = get_meter_detail
get_device_alarms = get_meter_alarms
get_device_maintenance_records = get_meter_maintenance_records
