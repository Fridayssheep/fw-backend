from datetime import datetime, timedelta

from app.core.database import fetch_all
from app.schemas.schemas_common import Pagination
from app.schemas.schemas_energy import (
    DetectedAnomalyPoint,
    EnergyAnomalyAnalysisRequest,
    EnergyAnomalyAnalysisResponse,
    EnergySeries,
)
from app.schemas.schemas_meters import (
    MeterAlarm,
    MeterAlarmLevel,
    MeterAlarmListResponse,
    MeterAlarmStatus,
)
from .service_common import (
    build_api_time_range,
    get_latest_timestamp,
    get_meter_unit,
    normalize_meter,
    normalize_pagination,
    require_api_datetime,
)

def get_energy_anomaly_analysis(
    payload: EnergyAnomalyAnalysisRequest,
) -> EnergyAnomalyAnalysisResponse:
    # 局部引入，避免循环依赖
    from .services_energy import query_trend_rows, map_energy_rows_to_points, get_weather_context

    resolved_start, resolved_end, normalized_meter = (
        require_api_datetime(payload.time_range.start),
        require_api_datetime(payload.time_range.end),
        normalize_meter(payload.meter),
    )

    # 查原始能耗数据用于前台绘图展示，同时防止空查报错
    _, _, _, rows = query_trend_rows(
        building_ids=[payload.building_id],
        site_id=None,
        meter=payload.meter,
        start_time=payload.time_range.start,
        end_time=payload.time_range.end,
        granularity=payload.granularity,
    )
    points = map_energy_rows_to_points(rows)
    
    # 查 offline_anomaly_detector 的检测结果
    anomaly_rows = fetch_all(
        """
        SELECT start_time, end_time, peak_deviation, severity, detected_by, description
        FROM anomaly_events
        WHERE building_id = :building_id
          AND meter = :meter
          AND start_time >= :start_time
          AND start_time <= :end_time
        ORDER BY start_time ASC
        """,
        {
            "building_id": payload.building_id,
            "meter": payload.meter,
            "start_time": resolved_start,
            "end_time": resolved_end,
        },
    )

    detected_points: list[DetectedAnomalyPoint] = []
    severity_map = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    
    for ar in anomaly_rows:
        detected_points.append(
            DetectedAnomalyPoint(
                timestamp=ar["start_time"],
                actual_value=float(ar["peak_deviation"] or 0),
                baseline_value=0.0,
                deviation_rate=float(ar["peak_deviation"] or 0),
                severity=severity_map.get((ar["severity"] or "").upper(), "low"),
            )
        )
        
    is_anomalous = len(detected_points) > 0
    if is_anomalous:
        summary = f"检测到 {len(detected_points)} 个离线批处理异常事件模块报警。"
    else:
        summary = "当前时间范围内未检测到明显异常。"

    weather_context = None
    if payload.include_weather_context:
        weather_context = get_weather_context(payload.building_id, resolved_start, resolved_end)

    return EnergyAnomalyAnalysisResponse(
        building_id=payload.building_id,
        meter=normalized_meter,
        time_range=build_api_time_range(resolved_start, resolved_end),
        is_anomalous=is_anomalous,
        summary=summary,
        baseline_mode="offline_batch",
        detected_points=detected_points,
        series=EnergySeries(
            building_id=payload.building_id,
            meter=normalized_meter,
            unit=get_meter_unit(normalized_meter),
            points=points,
        ),
        weather_context=weather_context,
    )  # 完成异常分析响应构造。

def build_meter_alarm_items(building_id: str, meter: str) -> list[MeterAlarm]:
    from .services_meters import get_meter_base_row_or_raise, build_meter_id, METER_ALARM_LOOKBACK_DAYS
    
    meter_row = get_meter_base_row_or_raise(building_id, meter)
    window_end = meter_row.get("last_seen_at") or get_latest_timestamp([building_id], None, meter)
    if not window_end:
        window_end = datetime.now()
    window_start = window_end - timedelta(days=METER_ALARM_LOOKBACK_DAYS)
    
    rows = fetch_all(
        """
        SELECT
            id,
            start_time,
            peak_deviation,
            severity,
            description,
            detected_by
        FROM anomaly_events
        WHERE building_id = :building_id
          AND meter = :meter
          AND start_time >= :start_time
          AND start_time <= :end_time
        ORDER BY start_time DESC
        """,
        {"building_id": building_id, "meter": meter, "start_time": window_start, "end_time": window_end},
    )
    if not rows:
        return []

    meter_id = build_meter_id(building_id, meter)
    alarms: list[MeterAlarm] = []

    for row in rows:
        level_map = {"HIGH": MeterAlarmLevel.critical, "MEDIUM": MeterAlarmLevel.warning, "LOW": MeterAlarmLevel.info}
        severity_str = (row["severity"] or "LOW").upper()
        level = level_map.get(severity_str, MeterAlarmLevel.info)

        alarms.append(
            MeterAlarm(
                alarm_id=f"evt_{row['id']}",
                meter_id=meter_id,
                level=level,
                code=row["detected_by"] or "anomaly",
                message=row["description"] or f"{meter} 异常",
                status=MeterAlarmStatus.open,
                occurred_at=row["start_time"],
            )
        )
    return alarms

def get_meter_alarms(meter_id: str, page: int, page_size: int) -> MeterAlarmListResponse:
    from .services_meters import parse_meter_id
    
    building_id, meter = parse_meter_id(meter_id)
    items = build_meter_alarm_items(building_id, meter)
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)
    paged_items = items[offset : offset + safe_page_size]
    return MeterAlarmListResponse(
        items=paged_items,
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),
    )

