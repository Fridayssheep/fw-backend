from __future__ import annotations
from typing import Any
from mcp.server.fastmcp import FastMCP

from ai.mcp.config import (
    ALLOWED_GRANULARITIES,
    ALLOWED_QUERY_AGGREGATIONS,
    ALLOWED_COMPARE_METRICS,
    ALLOWED_RANKING_METRICS,
    ALLOWED_RANKING_ORDERS,
    ALLOWED_ANOMALY_GRANULARITIES,
    ALLOWED_BASELINE_MODES
)
from ai.mcp.utils import (
    _validate_building_ids,
    _validate_meter,
    _validate_time_range,
    _validate_choice,
    _validate_positive_int
)
from ai.mcp.client import _request_backend
from ai.mcp.formatters import (
    _build_tool_result,
    _summarize_energy_query,
    _summarize_energy_trend,
    _summarize_energy_compare,
    _summarize_energy_rankings,
    _summarize_energy_cop_demo,
    _summarize_weather_correlation,
    _summarize_energy_anomaly_analysis
)

mcp = FastMCP("building-energy-mcp")

@mcp.tool()
def backend_health() -> dict[str, Any]:
    """检查后端健康状态。

    建议在调用其他能耗工具前先执行一次，快速确认服务与数据库是否可用。
    """
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
    """查询能耗明细/聚合数据（支持分页）。"""
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
    """获取建筑时序趋势数据。"""
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
    """对比多栋建筑在同一指标下的能耗表现。"""
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
    """按时间窗口返回建筑能耗排行。"""
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
    """获取 COP 演示版估算结果。"""
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
    """分析能耗与天气因素的相关性。"""
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
    """对单栋建筑、单类表计执行异常检测分析。"""
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


@mcp.tool()
def search_domain_knowledge(query: str, top_k: int = 3) -> str:
    """检索建筑/设备运维知识库内容（RAGFlow）。"""
    import sys
    import os
    # 确保可导入 ai.backend 模块。
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(os.path.dirname(current_dir))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
        
    from ai.backend.ragflow_client import ragflow_client
    chunks = ragflow_client.retrieve_chunks(question=query, top_k=top_k)
    
    if not chunks:
        return "No relevant knowledge found in the knowledge base."
        
    results = []
    for i, c in enumerate(chunks, 1):
        doc_name = c.get('document_keyword') or c.get('document_name') or 'Unknown Document'
        content = c.get('content', '')
        results.append(f"--- Document {i}: {doc_name} ---\n{content}\n")
    
    return "\n".join(results)


if __name__ == "__main__":
    mcp.run()