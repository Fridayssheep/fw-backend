from typing import Any
from ai.mcp.utils import _build_tool_result, _format_number

def _summarize_energy_query(
    response: dict[str, Any],
    *,
    building_ids: list[str],
    meter: str,
    aggregation: str | None,
) -> dict[str, Any]:
    """格式化 energy_query 的结果摘要。"""
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
    """格式化 energy_trend 的结果摘要。"""
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
    """格式化 energy_compare 的结果摘要。"""
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
    """格式化 energy_rankings 的结果摘要。"""
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
    """格式化 energy_cop_demo 的结果摘要。"""
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
    """格式化 weather-correlation 的结果摘要。"""
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
    """格式化 anomaly-analysis 的结果摘要。"""
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