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
    _summarize_domain_knowledge,
    _summarize_domain_knowledge_answer,
    _summarize_energy_query,
    _summarize_energy_trend,
    _summarize_energy_compare,
    _summarize_energy_rankings,
    _summarize_energy_cop_demo,
    _summarize_weather_correlation,
    _summarize_energy_anomaly_analysis
)
from ai.backend.knowledge import (
    answer_with_domain_knowledge as answer_with_domain_knowledge_result,
    search_domain_knowledge_references,
)

# ============================================================================
# MCP 服务器初始化
# 为 LLM/AI 应用提供建筑能源数据查询和分析工具
# ============================================================================

mcp = FastMCP("building-energy-mcp")

@mcp.tool()
def backend_health() -> dict[str, Any]:
    """后端健康检查工具。

    检查后端 API 服务和数据库连接状态。建议在调用其他能耗工具前先执行一次，
    快速确认服务与数据库是否可用。该工具返回服务状态、数据库状态和时间戳。
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
    """查询能耗数据详情或聚合数据。

    按指定时间范围、粒度（小时/天/周/月）和聚合方式（sum/avg/max/min）
    查询一个或多个建筑的能耗数据，支持分页查询。常用于趋势分析、对标比较、异常诊断等场景。
    """
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
    """获取建筑能耗时序趋势数据。

    返回指定时间范围内的能耗趋势，用于观察能耗变化规律、季节性特征或长期发展趋势。
    通常用于仪表板可视化、基线对标、运营决策支持等。
    """
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
    """多栋建筑能耗对标比较。

    对比两个或多个建筑在同一表计类型、同一时间范围下的能耗表现（如总耗量、平均值、峰值等），
    通常用于建筑间的性能基准对标、识别低效能建筑、或制定节能改进计划。
    """
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
    """建筑能耗排行榜。

    按照指定的时间窗口和指标（总耗量、平均值、峰值等），返回所有建筑的能耗排行。
    支持降序（从高到低）或升序（从低到高）排序，用于快速识别高耗能或低耗能的建筑。
    """
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
    """COP（性能系数）演示版估算。

    基于历史能耗数据和模型，对指定建筑在特定时间范围内的制冷/制热效率（COP）进行估算。
    COP 越高表示能效越好，该工具用于评估建筑空调系统的运行效率。
    """
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
    """分析能耗与天气因素的相关性。

    计算建筑能耗与气温、湿度、日照等气象要素的相关系数，
    识别哪些天气因素对能耗影响最大。用于理解气候驱动的能耗变化，
    以及优化空调控制策略。
    """
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
    """异常检测和根因诊断分析。

    对指定建筑和表计在给定时间窗口内执行异常检测分析，
    返回检测到的异常点、统计摘要、候选根因和天气相关性等诊断信息。
    支持多种基线计算模式（如全局平均、同类日期参考等），
    可选择是否引入天气相关性分析以增强诊断准确性。
    """
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
def search_domain_knowledge(query: str, top_k: int = 3) -> dict[str, Any]:
    """检索建筑运维知识库。

    通过 RAGFlow 知识库搜索与查询相关的建筑运维手册、设备说明、技术规范等内容，
    返回结构化的知识片段和文档聚合信息。该工具只负责检索证据，不负责生成最终回答，
    适合让上层模型按需调用，再自行决定是否基于这些证据继续作答。
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query 不能为空字符串。")
    safe_top_k = _validate_positive_int("top_k", top_k, minimum=1, maximum=10)
    references = search_domain_knowledge_references(
        normalized_query,
        top_k=safe_top_k,
    )
    return _summarize_domain_knowledge(
        references,
        query=normalized_query,
        top_k=safe_top_k,
    )


@mcp.tool()
def answer_with_domain_knowledge(question: str, top_k: int = 3) -> dict[str, Any]:
    """基于 RAGFlow 知识库直接生成答案。

    该工具会调用 RAGFlow `chats_openai`，返回更接近最终用户可直接阅读的成品答案。
    由于 chats_openai 的结构化引用不够稳定，这个工具适合“快速拿答案”，
    但如果上层模型还需要稳定证据链，仍建议同时调用 `search_domain_knowledge`。
    """

    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("question 不能为空字符串。")

    safe_top_k = _validate_positive_int("top_k", top_k, minimum=1, maximum=10)
    result = answer_with_domain_knowledge_result(
        normalized_question,
    )
    return _summarize_domain_knowledge_answer(
        result,
        question=normalized_question,
        top_k=safe_top_k,
    )


if __name__ == "__main__":
    mcp.run()
