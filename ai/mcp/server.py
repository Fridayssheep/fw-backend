from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
BACKEND_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "30"))

ALLOWED_METERS = {
    "electricity",
    "water",
    "gas",
    "steam",
    "chilledwater",
    "hotwater",
    "irrigation",
    "solar",
}
ALLOWED_GRANULARITIES = {"hour", "day", "week", "month"}
ALLOWED_QUERY_AGGREGATIONS = {"sum", "avg", "max", "min"}
ALLOWED_COMPARE_METRICS = {"sum", "avg", "peak"}
ALLOWED_RANKING_METRICS = {"sum", "avg", "peak"}
ALLOWED_RANKING_ORDERS = {"asc", "desc"}
ALLOWED_BASELINE_MODES = {"overall_mean", "same_hour_mean"}
ALLOWED_ANOMALY_GRANULARITIES = {"hour", "day"}


mcp = FastMCP("building-energy-mcp")


# Keep tool outputs stable so downstream model logic does not need per-tool adapters.
def _build_tool_result(
    *,
    tool_name: str,
    summary: str,
    highlights: list[str] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    request_context: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "summary": summary,
        "highlights": highlights or [],
        "warnings": warnings or [],
        "next_actions": next_actions or [],
        "request_context": request_context or {},
        "data": data or {},
    }


def _clean_none_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _format_number(value: Any, digits: int = 4) -> str:
    try:
        return str(round(float(value), digits))
    except (TypeError, ValueError):
        return str(value)


# Normalize datetimes before sending them to the backend so validation is consistent.
def _normalize_datetime_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("时间参数不能为空字符串。")
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    if "T" in cleaned and " " in cleaned.rsplit("T", 1)[-1]:
        date_part, offset_part = cleaned.rsplit(" ", 1)
        cleaned = f"{date_part}+{offset_part}"
    try:
        datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"非法时间格式: {value}。请使用 ISO 8601，例如 2026-03-31T00:00:00+08:00。"
        ) from exc
    return cleaned


def _validate_time_range(start_time: str, end_time: str) -> tuple[str, str]:
    normalized_start = _normalize_datetime_text(start_time)
    normalized_end = _normalize_datetime_text(end_time)
    if datetime.fromisoformat(normalized_start) > datetime.fromisoformat(normalized_end):
        raise ValueError("开始时间不能晚于结束时间。")
    return normalized_start, normalized_end


def _validate_meter(meter: str) -> str:
    normalized_meter = meter.strip().lower()
    if normalized_meter not in ALLOWED_METERS:
        raise ValueError(
            f"非法 meter: {meter}。允许值为: {', '.join(sorted(ALLOWED_METERS))}。"
        )
    return normalized_meter


def _validate_choice(name: str, value: str | None, allowed: set[str]) -> str | None:
    if value is None:
        return None
    normalized_value = value.strip().lower()
    if normalized_value not in allowed:
        raise ValueError(
            f"非法 {name}: {value}。允许值为: {', '.join(sorted(allowed))}。"
        )
    return normalized_value


def _validate_positive_int(name: str, value: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    if value < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}。")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} 不能大于 {maximum}。")
    return value


def _validate_building_ids(
    building_ids: list[str] | None,
    *,
    min_count: int = 1,
    allow_empty: bool = False,
) -> list[str]:
    normalized_ids = []
    for building_id in building_ids or []:
        normalized = building_id.strip()
        if normalized:
            normalized_ids.append(normalized)
    if allow_empty and not normalized_ids:
        return []
    if len(normalized_ids) < min_count:
        if min_count == 1:
            raise ValueError("building_ids 不能为空，且至少需要一个有效建筑 ID。")
        raise ValueError(f"building_ids 至少需要 {min_count} 个有效建筑 ID。")
    return normalized_ids


def _extract_backend_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        if payload.get("message"):
            return str(payload["message"])
        if payload.get("detail"):
            return str(payload["detail"])
    return response.text.strip() or f"HTTP {response.status_code}"


# Centralize HTTP calls so all tools share the same error mapping.
def _request_backend(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{BACKEND_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=BACKEND_TIMEOUT) as client:
            response = client.request(
                method=method,
                url=url,
                params=_clean_none_values(params or {}),
                json=json_body,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        message = _extract_backend_error_message(exc.response)
        raise ValueError(
            f"后端接口调用失败: {method} {path} -> HTTP {exc.response.status_code}，{message}"
        ) from exc
    except httpx.RequestError as exc:
        raise ValueError(
            f"后端服务不可达: {method} {path}。请确认后端已启动，当前地址为 {BACKEND_BASE_URL}。"
        ) from exc


def _summarize_energy_query(
    response: dict[str, Any],
    *,
    building_ids: list[str],
    meter: str,
    aggregation: str | None,
) -> dict[str, Any]:
    items = response.get("items", [])
    summary_data = response.get("summary", {})
    pagination = response.get("pagination") or {}
    highlights = [
        f"建筑数量: {len(building_ids)}",
        f"记录条数: {len(items)}",
        f"总量: {_format_number(summary_data.get('total', 0))}",
        f"均值: {_format_number(summary_data.get('average', 0))}",
        f"峰值: {_format_number(summary_data.get('peak', 0))}",
    ]
    if pagination:
        highlights.append(
            f"分页: page={pagination.get('page')} page_size={pagination.get('page_size')} total={pagination.get('total')}"
        )
    query_mode = "聚合" if aggregation else "明细"
    return _build_tool_result(
        tool_name="energy_query",
        summary=f"已返回 {meter} 的{query_mode}查询结果，覆盖 {len(building_ids)} 个建筑。",
        highlights=highlights,
        next_actions=[
            "如需看时序波动，下一步调用 energy_trend。",
            "如需比较多栋建筑，下一步调用 energy_compare。",
            "如需判断异常，下一步调用 energy_anomaly_analysis。",
        ],
        request_context={
            "building_ids": building_ids,
            "meter": meter,
            "aggregation": aggregation,
        },
        data=response,
    )


def _summarize_energy_trend(
    response: dict[str, Any],
    *,
    building_ids: list[str],
    meter: str,
    granularity: str | None,
) -> dict[str, Any]:
    series = response.get("series", [])
    point_count = sum(len(item.get("points", [])) for item in series)
    return _build_tool_result(
        tool_name="energy_trend",
        summary=f"已返回 {meter} 趋势数据，共 {len(series)} 条序列。",
        highlights=[
            f"建筑数量: {len(building_ids)}",
            f"序列数量: {len(series)}",
            f"点位总数: {point_count}",
            f"粒度: {granularity or 'day'}",
        ],
        next_actions=[
            "如需检测异常点，下一步调用 energy_anomaly_analysis。",
            "如需比较多栋建筑，下一步调用 energy_compare。",
        ],
        request_context={
            "building_ids": building_ids,
            "meter": meter,
            "granularity": granularity,
        },
        data=response,
    )


def _summarize_energy_compare(
    response: dict[str, Any],
    *,
    building_ids: list[str],
    meter: str,
    metric: str,
) -> dict[str, Any]:
    items = response.get("items", [])
    highlights = [f"比较建筑数: {len(building_ids)}", f"指标: {metric}"]
    if items:
        top_item = max(items, key=lambda item: item.get("value", 0))
        highlights.extend(
            [
                f"最高建筑: {top_item.get('building_id')}",
                f"最高值: {_format_number(top_item.get('value'))}",
            ]
        )
        summary = f"已完成 {len(building_ids)} 个建筑的 {meter} 对比。"
    else:
        summary = "已执行能耗对比，但当前条件下没有返回有效对比数据。"
    return _build_tool_result(
        tool_name="energy_compare",
        summary=summary,
        highlights=highlights,
        next_actions=[
            "如需解释差异来源，下一步调用 energy_trend。",
            "如需判断单栋建筑是否异常，下一步调用 energy_anomaly_analysis。",
        ],
        request_context={
            "building_ids": building_ids,
            "meter": meter,
            "metric": metric,
        },
        data=response,
    )


def _summarize_energy_rankings(
    response: dict[str, Any],
    *,
    meter: str,
    metric: str,
    order: str,
    limit: int,
) -> dict[str, Any]:
    items = response.get("items", [])
    highlights = [
        f"表计: {meter}",
        f"指标: {metric}",
        f"排序: {order}",
        f"返回条数: {len(items)} / limit={limit}",
    ]
    if items:
        first_item = items[0]
        highlights.append(f"Top1 建筑: {first_item.get('building_id')}")
        highlights.append(f"Top1 数值: {_format_number(first_item.get('value'))}")
    return _build_tool_result(
        tool_name="energy_rankings",
        summary=f"已返回 {meter} 的能耗排行结果。",
        highlights=highlights,
        next_actions=[
            "如需查看某栋建筑的具体趋势，下一步调用 energy_trend。",
            "如需比较几个候选建筑，下一步调用 energy_compare。",
        ],
        request_context={
            "meter": meter,
            "metric": metric,
            "order": order,
            "limit": limit,
        },
        data=response,
    )


def _summarize_energy_cop_demo(
    response: dict[str, Any],
    *,
    building_id: str,
    granularity: str | None,
) -> dict[str, Any]:
    summary_data = response.get("summary") or {}
    points = response.get("points", [])
    warnings = [
        "COP 接口当前是演示口径估算值，不能直接作为工程级结论。",
    ]
    return _build_tool_result(
        tool_name="energy_cop_demo",
        summary="已返回 COP 演示版估算结果。",
        highlights=[
            f"建筑: {building_id}",
            f"粒度: {granularity or 'day'}",
            f"点位数量: {len(points)}",
            f"平均 COP: {_format_number(summary_data.get('avg_cop', 0))}",
            f"最小 COP: {_format_number(summary_data.get('min_cop', 0))}",
            f"最大 COP: {_format_number(summary_data.get('max_cop', 0))}",
        ],
        warnings=warnings,
        next_actions=[
            "如需看冷量和电量波动，下一步调用 energy_trend。",
            "如需解释异常波动，下一步调用 energy_anomaly_analysis。",
        ],
        request_context={
            "building_id": building_id,
            "granularity": granularity,
        },
        data=response,
    )


def _summarize_weather_correlation(
    response: dict[str, Any],
    *,
    building_id: str,
    meter: str,
) -> dict[str, Any]:
    coefficient = response.get("correlation_coefficient", 0)
    factors = response.get("factors", [])
    top_factor = max(factors, key=lambda item: abs(item.get("coefficient", 0)), default=None)
    highlights = [
        f"建筑: {building_id}",
        f"表计: {meter}",
        f"主相关系数: {_format_number(coefficient)}",
    ]
    if top_factor:
        highlights.append(
            f"最显著天气因子: {top_factor.get('name')} ({_format_number(top_factor.get('coefficient'))})"
        )
    return _build_tool_result(
        tool_name="energy_weather_correlation",
        summary="已完成天气相关性分析，可用于辅助解释波动。",
        highlights=highlights,
        warnings=["相关性结果只能作为辅助依据，不能直接视为因果结论。"],
        next_actions=[
            "如需查看原始波动，下一步调用 energy_trend。",
            "如需检测异常，下一步调用 energy_anomaly_analysis。",
        ],
        request_context={"building_id": building_id, "meter": meter},
        data=response,
    )


def _summarize_energy_anomaly_analysis(
    response: dict[str, Any],
    *,
    building_id: str,
    meter: str,
    baseline_mode: str,
) -> dict[str, Any]:
    detected_points = response.get("detected_points", [])
    is_anomalous = response.get("is_anomalous", False)
    highlights = [
        f"建筑: {building_id}",
        f"表计: {meter}",
        f"基线模式: {baseline_mode}",
        f"异常点数量: {len(detected_points)}",
    ]
    if detected_points:
        max_point = max(detected_points, key=lambda item: item.get("deviation_rate", 0))
        highlights.append(f"最大偏离率: {_format_number(max_point.get('deviation_rate', 0) * 100, 2)}%")
        highlights.append(f"最高严重级别: {max_point.get('severity')}")
    if response.get("weather_context"):
        highlights.append(f"天气上下文点数: {len(response.get('weather_context', []))}")
    summary = response.get("summary") or (
        "检测到异常点，建议继续结合趋势和天气信息解释原因。"
        if is_anomalous
        else "未检测到明显异常。"
    )
    return _build_tool_result(
        tool_name="energy_anomaly_analysis",
        summary=summary,
        highlights=highlights,
        warnings=["该结果属于检测结论，不应直接当成已确认故障。"],
        next_actions=[
            "如需查看完整波动，下一步调用 energy_trend。",
            "如需看天气影响，下一步调用 energy_weather_correlation。",
        ],
        request_context={
            "building_id": building_id,
            "meter": meter,
            "baseline_mode": baseline_mode,
        },
        data=response,
    )


@mcp.tool()
def backend_health() -> dict[str, Any]:
    """Check whether the backend service is reachable before running other tools."""
    response = _request_backend("GET", "/health")
    return _build_tool_result(
        tool_name="backend_health",
        summary="后端服务可达，且数据库探活成功。",
        highlights=[
            f"service_status: {response.get('status')}",
            f"database_status: {response.get('database')}",
            f"timestamp: {response.get('timestamp')}",
        ],
        next_actions=[
            "后续可以继续调用 energy_query、energy_trend、energy_compare、energy_rankings、energy_cop_demo、energy_weather_correlation、energy_anomaly_analysis。"
        ],
        data=response,
    )


@mcp.tool()
def energy_query(
    building_ids: list[str],
    meter: str,
    start_time: str,
    end_time: str,
    site_id: str | None = None,
    granularity: str | None = "day",
    aggregation: str | None = "sum",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Query detailed or aggregated energy data for specific buildings."""
    normalized_building_ids = _validate_building_ids(building_ids, min_count=1)
    normalized_meter = _validate_meter(meter)
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    normalized_granularity = _validate_choice("granularity", granularity, ALLOWED_GRANULARITIES)
    normalized_aggregation = _validate_choice("aggregation", aggregation, ALLOWED_QUERY_AGGREGATIONS)
    safe_page = _validate_positive_int("page", page, minimum=1)
    safe_page_size = _validate_positive_int("page_size", page_size, minimum=1, maximum=500)
    response = _request_backend(
        "GET",
        "/energy/query",
        params={
            "building_ids": normalized_building_ids,
            "site_id": site_id,
            "meter": normalized_meter,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "granularity": normalized_granularity,
            "aggregation": normalized_aggregation,
            "page": safe_page,
            "page_size": safe_page_size,
        },
    )
    return _summarize_energy_query(
        response,
        building_ids=normalized_building_ids,
        meter=normalized_meter,
        aggregation=normalized_aggregation,
    )


@mcp.tool()
def energy_trend(
    building_ids: list[str],
    meter: str,
    start_time: str,
    end_time: str,
    site_id: str | None = None,
    granularity: str | None = "day",
) -> dict[str, Any]:
    """Fetch time-series energy data for one or more buildings."""
    normalized_building_ids = _validate_building_ids(building_ids, min_count=1)
    normalized_meter = _validate_meter(meter)
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    normalized_granularity = _validate_choice("granularity", granularity, ALLOWED_GRANULARITIES)
    response = _request_backend(
        "GET",
        "/energy/trend",
        params={
            "building_ids": normalized_building_ids,
            "site_id": site_id,
            "meter": normalized_meter,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "granularity": normalized_granularity,
        },
    )
    return _summarize_energy_trend(
        response,
        building_ids=normalized_building_ids,
        meter=normalized_meter,
        granularity=normalized_granularity,
    )


@mcp.tool()
def energy_compare(
    building_ids: list[str],
    meter: str,
    start_time: str,
    end_time: str,
    metric: str = "sum",
) -> dict[str, Any]:
    """Compare the same energy metric across multiple buildings."""
    normalized_building_ids = _validate_building_ids(building_ids, min_count=2)
    normalized_meter = _validate_meter(meter)
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    normalized_metric = _validate_choice("metric", metric, ALLOWED_COMPARE_METRICS) or "sum"
    response = _request_backend(
        "GET",
        "/energy/compare",
        params={
            "building_ids": normalized_building_ids,
            "meter": normalized_meter,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "metric": normalized_metric,
        },
    )
    return _summarize_energy_compare(
        response,
        building_ids=normalized_building_ids,
        meter=normalized_meter,
        metric=normalized_metric,
    )


@mcp.tool()
def energy_rankings(
    meter: str,
    start_time: str,
    end_time: str,
    metric: str = "sum",
    order: str = "desc",
    limit: int = 10,
) -> dict[str, Any]:
    """Rank buildings by energy metric in a given time range."""
    normalized_meter = _validate_meter(meter)
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    normalized_metric = _validate_choice("metric", metric, ALLOWED_RANKING_METRICS) or "sum"
    normalized_order = _validate_choice("order", order, ALLOWED_RANKING_ORDERS) or "desc"
    safe_limit = _validate_positive_int("limit", limit, minimum=1, maximum=100)
    response = _request_backend(
        "GET",
        "/energy/rankings",
        params={
            "meter": normalized_meter,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "metric": normalized_metric,
            "order": normalized_order,
            "limit": safe_limit,
        },
    )
    return _summarize_energy_rankings(
        response,
        meter=normalized_meter,
        metric=normalized_metric,
        order=normalized_order,
        limit=safe_limit,
    )


@mcp.tool()
def energy_cop_demo(
    building_id: str,
    start_time: str,
    end_time: str,
    granularity: str | None = "day",
) -> dict[str, Any]:
    """Fetch the current demo COP estimation for a building."""
    normalized_building_id = _validate_building_ids([building_id], min_count=1)[0]
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    normalized_granularity = _validate_choice("granularity", granularity, ALLOWED_GRANULARITIES)
    response = _request_backend(
        "GET",
        "/energy/cop",
        params={
            "building_id": normalized_building_id,
            "start_time": normalized_start,
            "end_time": normalized_end,
            "granularity": normalized_granularity,
        },
    )
    return _summarize_energy_cop_demo(
        response,
        building_id=normalized_building_id,
        granularity=normalized_granularity,
    )


@mcp.tool()
def energy_weather_correlation(
    building_id: str,
    meter: str,
    start_time: str,
    end_time: str,
) -> dict[str, Any]:
    """Analyze correlation between energy usage and weather factors."""
    normalized_building_id = _validate_building_ids([building_id], min_count=1)[0]
    normalized_meter = _validate_meter(meter)
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    response = _request_backend(
        "GET",
        "/energy/weather-correlation",
        params={
            "building_id": normalized_building_id,
            "meter": normalized_meter,
            "start_time": normalized_start,
            "end_time": normalized_end,
        },
    )
    return _summarize_weather_correlation(
        response,
        building_id=normalized_building_id,
        meter=normalized_meter,
    )


@mcp.tool()
def energy_anomaly_analysis(
    building_id: str,
    meter: str,
    start_time: str,
    end_time: str,
    granularity: str = "hour",
    baseline_mode: str = "overall_mean",
    include_weather_context: bool = True,
) -> dict[str, Any]:
    """Run anomaly detection for a single building and meter."""
    normalized_building_id = _validate_building_ids([building_id], min_count=1)[0]
    normalized_meter = _validate_meter(meter)
    normalized_start, normalized_end = _validate_time_range(start_time, end_time)
    normalized_granularity = (
        _validate_choice("granularity", granularity, ALLOWED_ANOMALY_GRANULARITIES) or "hour"
    )
    normalized_baseline_mode = (
        _validate_choice("baseline_mode", baseline_mode, ALLOWED_BASELINE_MODES) or "overall_mean"
    )
    response = _request_backend(
        "POST",
        "/energy/anomaly-analysis",
        json_body={
            "building_id": normalized_building_id,
            "meter": normalized_meter,
            "time_range": {"start": normalized_start, "end": normalized_end},
            "granularity": normalized_granularity,
            "baseline_mode": normalized_baseline_mode,
            "include_weather_context": include_weather_context,
        },
    )
    return _summarize_energy_anomaly_analysis(
        response,
        building_id=normalized_building_id,
        meter=normalized_meter,
        baseline_mode=normalized_baseline_mode,
    )


if __name__ == "__main__":
    mcp.run()
