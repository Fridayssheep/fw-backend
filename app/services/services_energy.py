import math  # 导入数学库，后面计算相关系数时会用到平方根。
from collections import defaultdict  # 导入默认字典，方便按建筑或时间桶聚合数据。
from datetime import datetime  # 导入日期时间类型，方便做时间计算。
from typing import Any  # 导入任意类型注解，方便描述松散结构。

from app.core.database import build_in_clause  # 导入 IN 条件构造工具函数。
from app.core.database import fetch_all  # 导入多行查询函数。
from app.core.database import fetch_one  # 导入单行查询函数。
from app.core.database import fetch_scalar  # 导入单值查询函数。
from app.schemas.schemas_common import Pagination  # 导入分页模型，方便显式构造分页对象。
from app.schemas.schemas_energy import CopAnalysisResponse  # 导入 COP 响应模型。
from app.schemas.schemas_energy import CopPoint  # 导入 COP 点模型。
from app.schemas.schemas_energy import CopSummary  # 导入 COP 摘要模型。
from app.schemas.schemas_energy import DetectedAnomalyPoint  # 导入异常点模型。
from app.schemas.schemas_energy import EnergyAnomalyAnalysisRequest  # 导入异常分析请求模型。
from app.schemas.schemas_energy import EnergyAnomalyAnalysisResponse  # 导入异常分析响应模型。
from app.schemas.schemas_energy import EnergyCompareItem  # 导入能耗对比项模型。
from app.schemas.schemas_energy import EnergyCompareResponse  # 导入能耗对比响应模型。
from app.schemas.schemas_energy import EnergyPoint  # 导入能耗点模型。
from app.schemas.schemas_energy import EnergyQueryResponse  # 导入能耗明细响应模型。
from app.schemas.schemas_energy import EnergyRankingItem  # 导入能耗排行项模型。
from app.schemas.schemas_energy import EnergyRankingResponse  # 导入能耗排行响应模型。
from app.schemas.schemas_energy import EnergySeries  # 导入能耗序列模型。
from app.schemas.schemas_energy import EnergySummary  # 导入能耗摘要模型。
from app.schemas.schemas_energy import EnergyTrendResponse  # 导入能耗趋势响应模型。
from app.schemas.schemas_energy import WeatherCorrelationResponse  # 导入天气相关性响应模型。
from app.schemas.schemas_energy import WeatherFactor  # 导入天气因子模型。
from app.schemas.schemas_energy import WeatherPoint  # 导入天气点模型。
from .service_common import build_api_time_range  # 导入构造接口时间范围对象的函数。
from .service_common import get_meter_unit  # 导入获取表计单位的函数。
from .service_common import normalize_granularity  # 导入标准化粒度的函数。
from .service_common import normalize_meter  # 导入标准化表计类型的函数。
from .service_common import normalize_pagination  # 导入标准化分页参数的函数。
from .service_common import require_api_datetime  # 导入强制转换接口时间的函数。
from .service_common import resolve_time_range  # 导入补齐时间范围的函数。
from .service_common import to_api_datetime  # 导入转换接口输出时间的函数。


AGGREGATION_MAP = {  # 定义允许使用的聚合函数映射表。
    "sum": "SUM",  # sum 对应求和。
    "avg": "AVG",  # avg 对应平均。
    "max": "MAX",  # max 对应最大值。
    "min": "MIN",  # min 对应最小值。
}  # 结束聚合函数映射定义。


MAX_DEFAULT_TREND_BUILDINGS = 10  # 定义趋势接口在缺少建筑过滤时默认最多返回的建筑数量。


COMPARE_METRIC_SQL_MAP = {  # 定义能耗对比接口允许的指标 SQL 表达式。
    "sum": "SUM(mr.meter_reading)",  # sum 表示总能耗。
    "total": "SUM(mr.meter_reading)",  # total 作为 sum 的兼容别名。
    "avg": "AVG(mr.meter_reading)",  # avg 表示平均能耗。
    "average": "AVG(mr.meter_reading)",  # average 作为 avg 的兼容别名。
    "peak": "MAX(mr.meter_reading)",  # peak 表示峰值能耗。
    "base_load": "MIN(mr.meter_reading)",  # base_load 这里用最小负荷做一个演示版近似。
}  # 结束对比指标映射定义。


RANKING_METRIC_SQL_MAP = {  # 定义能耗排行接口允许的指标 SQL 表达式。
    "sum": "SUM(mr.meter_reading)",  # sum 表示总能耗。
    "total": "SUM(mr.meter_reading)",  # total 作为 sum 的兼容别名。
    "avg": "AVG(mr.meter_reading)",  # avg 表示平均能耗。
    "average": "AVG(mr.meter_reading)",  # average 作为 avg 的兼容别名。
    "peak": "MAX(mr.meter_reading)",  # peak 表示峰值能耗。
}  # 结束排行指标映射定义。


def normalize_aggregation(aggregation: str | None) -> str | None:  # 定义标准化聚合函数的函数。
    if aggregation is None:  # 如果前端没有传聚合方式，
        return None  # 就直接返回空，表示走原始明细查询。
    return AGGREGATION_MAP.get(aggregation.lower())  # 如果传了就从白名单里取合法 SQL 关键字。


def normalize_compare_metric(metric: str | None) -> str:  # 定义标准化对比指标类型的函数。
    return metric.lower() if metric and metric.lower() in COMPARE_METRIC_SQL_MAP else "sum"  # 如果非法就回退到 sum。


def normalize_ranking_metric(metric: str | None) -> str:  # 定义标准化排行指标类型的函数。
    return metric.lower() if metric and metric.lower() in RANKING_METRIC_SQL_MAP else "sum"  # 如果非法就回退到 sum。


def normalize_order(order: str | None) -> str:  # 定义标准化排序方向的函数。
    return "ASC" if order and order.lower() == "asc" else "DESC"  # 只有显式传 asc 才升序，否则默认降序。


def build_energy_filters(  # 定义构造能耗查询通用过滤条件的函数。
    building_ids: list[str] | None,  # 接收建筑编号列表。
    site_id: str | None,  # 接收园区编号。
    meter: str | None,  # 接收表计类型。
    start_time: datetime,  # 接收开始时间。
    end_time: datetime,  # 接收结束时间。
) -> tuple[str, dict[str, Any]]:  # 返回 where 条件片段和参数字典。
    clauses: list[str] = ["mr.timestamp >= :start_time", "mr.timestamp <= :end_time"]  # 先放入时间范围条件。
    params: dict[str, Any] = {"start_time": start_time, "end_time": end_time}  # 初始化 SQL 参数字典。
    if building_ids:  # 如果传了建筑编号列表，
        clause, clause_params = build_in_clause("mr.building_id", building_ids, "building_id")  # 就构造建筑 IN 条件。
        clauses.append(clause)  # 把建筑条件拼进 where 子句。
        params.update(clause_params)  # 把建筑参数放进参数字典。
    if site_id:  # 如果传了园区编号，
        clauses.append("bm.site_id = :site_id")  # 就增加园区过滤条件。
        params["site_id"] = site_id  # 把园区值放进参数字典。
    if meter:  # 如果传了表计类型，
        clauses.append("mr.meter = :meter")  # 就增加表计过滤条件。
        params["meter"] = meter  # 把表计值放进参数字典。
    return " AND ".join(clauses), params  # 返回完整 where 条件和参数。


def map_energy_rows_to_points(rows: list[dict[str, Any]]) -> list[EnergyPoint]:  # 定义把数据库结果转成能耗点模型的函数。
    points: list[EnergyPoint] = []  # 初始化能耗点列表。
    for row in rows:  # 遍历数据库返回的每一行。
        points.append(  # 把当前行转成 EnergyPoint 模型并追加进列表。
            EnergyPoint(  # 创建一个能耗点对象。
                timestamp=require_api_datetime(row["timestamp"]),  # 把数据库时间转成台湾标准时间后写入时间字段。
                building_id=row.get("building_id"),  # 写入建筑编号字段。
                meter=row.get("meter"),  # 写入表计类型字段。
                value=float(row["value"] or 0),  # 写入能耗值字段，并把空值转成 0。
            )  # 完成当前点对象创建。
        )  # 完成当前点追加。
    return points  # 返回最终点位列表。


def build_summary(  # 定义构造摘要对象的函数。
    meter: str | None,  # 接收表计类型。
    start_time: datetime,  # 接收开始时间。
    end_time: datetime,  # 接收结束时间。
    building_ids: list[str] | None = None,  # 接收建筑编号列表。
    site_id: str | None = None,  # 接收园区编号。
) -> EnergySummary:  # 返回能耗摘要模型。
    normalized_meter = meter if meter else None  # 如果前端传了 meter 就保留，否则允许汇总所有表计。
    where_sql, params = build_energy_filters(building_ids, site_id, normalized_meter, start_time, end_time)  # 先复用通用过滤条件。
    summary_row = fetch_one(  # 查询总量、均值和峰值。
        f"""
        SELECT
            COALESCE(SUM(mr.meter_reading), 0) AS total,
            COALESCE(AVG(mr.meter_reading), 0) AS average,
            COALESCE(MAX(mr.meter_reading), 0) AS peak
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {where_sql}
        """,
        params,
    ) or {"total": 0, "average": 0, "peak": 0}  # 如果查不到数据，就返回全 0 的兜底值。
    peak_row = fetch_one(  # 单独查询峰值出现的时间。
        f"""
        SELECT mr.timestamp
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {where_sql}
        ORDER BY mr.meter_reading DESC NULLS LAST, mr.timestamp ASC
        LIMIT 1
        """,
        params,
    )  # 查询峰值时间。
    meter_name = meter or "all"  # 如果没传表计类型，就把摘要里的 meter 字段写成 all。
    return EnergySummary(  # 构造并返回摘要对象。
        meter=meter_name,  # 写入摘要表计类型。
        total=round(float(summary_row["total"] or 0), 4),  # 写入总量并做简单保留小数。
        average=round(float(summary_row["average"] or 0), 4),  # 写入均值并做简单保留小数。
        peak=round(float(summary_row["peak"] or 0), 4),  # 写入峰值并做简单保留小数。
        peak_time=to_api_datetime(peak_row["timestamp"]) if peak_row else None,  # 如果有峰值时间就转成台湾标准时间后写入，否则返回空。
        unit=get_meter_unit(meter),  # 根据表计类型补单位。
    )  # 完成摘要对象构造。


def get_energy_query(  # 定义能耗明细查询函数。
    building_ids: list[str] | None,  # 接收建筑编号列表。
    site_id: str | None,  # 接收园区编号。
    meter: str | None,  # 接收表计类型。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    granularity: str | None,  # 接收粒度。
    aggregation: str | None,  # 接收聚合方式。
    page: int,  # 接收页码。
    page_size: int,  # 接收每页条数。
) -> EnergyQueryResponse:  # 返回能耗查询响应模型。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, building_ids, site_id, meter)  # 先按当前过滤条件补齐默认时间范围。
    normalized_meter = meter  # 明细查询允许不传 meter，所以这里不强制默认 electricity。
    where_sql, params = build_energy_filters(building_ids, site_id, normalized_meter, resolved_start, resolved_end)  # 构造通用过滤条件。
    normalized_granularity = normalize_granularity(granularity)  # 标准化粒度。
    normalized_aggregation = normalize_aggregation(aggregation)  # 标准化聚合函数。
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size, 500)  # 标准化分页参数，并把 page_size 上限限制为 500。
    if normalized_aggregation:  # 如果前端传了合法聚合函数，
        rows = fetch_all(  # 就按时间桶聚合后再返回。
            f"""
            SELECT
                date_trunc('{normalized_granularity}', mr.timestamp) AS timestamp,
                mr.building_id AS building_id,
                COALESCE(mr.meter, 'all') AS meter,
                {normalized_aggregation}(mr.meter_reading) AS value
            FROM meter_readings mr
            LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
            WHERE {where_sql}
            GROUP BY 1, 2, 3
            ORDER BY 1 ASC, 2 ASC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": safe_page_size, "offset": offset},
        )  # 执行聚合分页查询。
        total_row = fetch_one(  # 再查询聚合后总共有多少个时间桶结果。
            f"""
            SELECT COUNT(*) AS total
            FROM (
                SELECT date_trunc('{normalized_granularity}', mr.timestamp), mr.building_id, COALESCE(mr.meter, 'all')
                FROM meter_readings mr
                LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
                WHERE {where_sql}
                GROUP BY 1, 2, 3
            ) AS grouped_rows
            """,
            params,
        ) or {"total": 0}  # 如果查不到结果就回退到 0。
    else:  # 如果前端没传聚合方式，
        rows = fetch_all(  # 就直接返回明细记录。
            f"""
            SELECT
                mr.timestamp AS timestamp,
                mr.building_id AS building_id,
                mr.meter AS meter,
                mr.meter_reading AS value
            FROM meter_readings mr
            LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
            WHERE {where_sql}
            ORDER BY mr.timestamp ASC, mr.building_id ASC
            LIMIT :limit OFFSET :offset
            """,
            {**params, "limit": safe_page_size, "offset": offset},
        )  # 执行明细分页查询。
        total_row = fetch_one(  # 再查询总条数。
            f"""
            SELECT COUNT(*) AS total
            FROM meter_readings mr
            LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
            WHERE {where_sql}
            """,
            params,
        ) or {"total": 0}  # 如果查不到结果就回退到 0。
    return EnergyQueryResponse(  # 构造最终响应对象。
        items=map_energy_rows_to_points(rows),  # 把数据库行结果转成点列表。
        summary=build_summary(normalized_meter, resolved_start, resolved_end, building_ids, site_id),  # 构造摘要。
        pagination=Pagination(  # 显式构造分页模型，避免编辑器把字典当成类型不匹配。
            page=safe_page,  # 写入当前页码。
            page_size=safe_page_size,  # 写入当前每页条数。
            total=int(total_row["total"] or 0),  # 写入总条数。
        ),
    )  # 返回完整明细响应。


def get_default_building_ids(  # 定义获取默认建筑列表的函数。
    meter: str,  # 接收表计类型。
    start_time: datetime,  # 接收开始时间。
    end_time: datetime,  # 接收结束时间。
    limit: int = 5,  # 接收默认返回建筑数量。
    site_id: str | None = None,  # 接收可选站点编号，方便只在某个园区内挑选建筑。
) -> list[str]:  # 返回建筑编号列表。
    where_clauses = [  # 初始化默认建筑查询的 where 条件列表。
        "mr.meter = :meter",  # 先限定表计类型。
        "mr.timestamp >= :start_time",  # 限定开始时间。
        "mr.timestamp <= :end_time",  # 限定结束时间。
    ]  # 完成默认条件列表初始化。
    params: dict[str, Any] = {"meter": meter, "start_time": start_time, "end_time": end_time, "limit": limit}  # 初始化查询参数字典。
    join_sql = ""  # 先默认不需要关联元数据表。
    if site_id:  # 如果调用方传了园区编号，
        join_sql = "LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id"  # 就增加建筑元数据关联。
        where_clauses.append("bm.site_id = :site_id")  # 并只取该园区下的建筑。
        params["site_id"] = site_id  # 写入站点参数。
    rows = fetch_all(  # 查询时间段内指定表计能耗最高的若干建筑。
        f"""
        SELECT mr.building_id, SUM(mr.meter_reading) AS total_value
        FROM meter_readings mr
        {join_sql}
        WHERE {' AND '.join(where_clauses)}
        GROUP BY mr.building_id
        ORDER BY total_value DESC
        LIMIT :limit
        """,
        params,
    )  # 执行默认建筑查询。
    return [str(row["building_id"]) for row in rows]  # 把查询结果转成建筑编号列表返回。


def query_trend_rows(  # 定义趋势接口底层查询函数。
    building_ids: list[str] | None,  # 接收建筑编号列表。
    site_id: str | None,  # 接收园区编号。
    meter: str | None,  # 接收表计类型。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    granularity: str | None,  # 接收粒度。
) -> tuple[datetime, datetime, str, list[dict[str, Any]]]:  # 返回补齐后的时间范围、标准化表计和查询结果。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, building_ids, site_id, normalize_meter(meter))  # 按当前趋势过滤条件补齐默认时间范围。
    normalized_granularity = normalize_granularity(granularity)  # 标准化粒度。
    normalized_meter = normalize_meter(meter)  # 趋势图默认按 electricity 处理。
    effective_building_ids = building_ids or get_default_building_ids(normalized_meter, resolved_start, resolved_end, MAX_DEFAULT_TREND_BUILDINGS, site_id)  # 如果没传建筑过滤，就自动收缩成当前周期内最活跃的少量建筑。
    where_sql, params = build_energy_filters(effective_building_ids, site_id, normalized_meter, resolved_start, resolved_end)  # 构造过滤条件。
    rows = fetch_all(  # 查询分桶后的趋势数据。
        f"""
        SELECT
            date_trunc('{normalized_granularity}', mr.timestamp) AS timestamp,
            mr.building_id AS building_id,
            mr.meter AS meter,
            SUM(mr.meter_reading) AS value
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {where_sql}
        GROUP BY 1, 2, 3
        ORDER BY 1 ASC, 2 ASC
        """,
        params,
    )  # 执行趋势数据查询。
    return resolved_start, resolved_end, normalized_meter, rows  # 返回趋势查询所需信息。


def get_energy_trend(  # 定义趋势接口业务函数。
    building_ids: list[str] | None,  # 接收建筑编号列表。
    site_id: str | None,  # 接收园区编号。
    meter: str | None,  # 接收表计类型。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    granularity: str | None,  # 接收粒度。
) -> EnergyTrendResponse:  # 返回趋势响应模型。
    resolved_start, resolved_end, normalized_meter, rows = query_trend_rows(building_ids, site_id, meter, start_time, end_time, granularity)  # 先查出趋势原始行。
    grouped_points: dict[tuple[str | None, str], list[EnergyPoint]] = defaultdict(list)  # 按建筑和表计分组存点位。
    for row in rows:  # 遍历每一行趋势数据。
        key = (row.get("building_id"), row.get("meter") or normalized_meter)  # 生成当前序列的分组键。
        grouped_points[key].append(  # 把当前点位追加到对应序列里。
            EnergyPoint(  # 创建能耗点对象。
                timestamp=require_api_datetime(row["timestamp"]),  # 把数据库时间转成台湾标准时间后写入时间字段。
                building_id=row.get("building_id"),  # 写入建筑字段。
                meter=row.get("meter") or normalized_meter,  # 写入表计类型字段。
                value=float(row["value"] or 0),  # 写入聚合后的数值字段。
            )  # 完成点对象创建。
        )  # 完成点位追加。
    series_list: list[EnergySeries] = []  # 初始化趋势序列列表。
    for (building_id, series_meter), points in grouped_points.items():  # 遍历每一组序列。
        series_list.append(  # 把当前组装好的序列追加进列表。
            EnergySeries(  # 创建趋势序列对象。
                building_id=building_id,  # 写入建筑编号字段。
                meter=series_meter,  # 写入表计类型字段。
                unit=get_meter_unit(series_meter),  # 写入单位字段。
                points=points,  # 写入点位列表字段。
            )  # 完成当前序列对象创建。
        )  # 完成当前序列追加。
    return EnergyTrendResponse(  # 构造并返回趋势响应对象。
        time_range=build_api_time_range(resolved_start, resolved_end),  # 写入带台湾时区的最终时间范围。
        series=series_list,  # 写入所有趋势序列。
    )  # 完成趋势响应构造。


def get_energy_compare(  # 定义能耗对比接口业务函数。
    building_ids: list[str] | None,  # 接收建筑编号列表。
    meter: str | None,  # 接收表计类型。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    metric: str | None,  # 接收对比指标。
) -> EnergyCompareResponse:  # 返回能耗对比响应模型。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, building_ids, None, normalize_meter(meter))  # 按当前对比过滤条件补齐默认时间范围。
    normalized_meter = normalize_meter(meter)  # 标准化表计类型。
    normalized_metric = normalize_compare_metric(metric)  # 标准化对比指标。
    effective_building_ids = building_ids or get_default_building_ids(normalized_meter, resolved_start, resolved_end)  # 如果前端没传建筑列表，就取默认前五。
    where_sql, params = build_energy_filters(effective_building_ids, None, normalized_meter, resolved_start, resolved_end)  # 构造过滤条件。
    metric_sql = COMPARE_METRIC_SQL_MAP[normalized_metric]  # 取出当前指标对应的 SQL 表达式。
    rows = fetch_all(  # 查询多建筑对比结果。
        f"""
        SELECT
            mr.building_id AS building_id,
            {metric_sql} AS value
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {where_sql}
        GROUP BY mr.building_id
        ORDER BY value DESC
        """,
        params,
    )  # 执行对比查询。
    row_value_map = {str(row["building_id"]): round(float(row["value"] or 0), 4) for row in rows}  # 把数据库结果整理成建筑到数值的映射，方便补齐无数据建筑。
    ordered_items = [  # 按前端传入顺序或默认建筑顺序逐条组装返回项。
        EnergyCompareItem(  # 创建对比项对象。
            building_id=str(current_building_id),  # 写入当前建筑编号字段。
            metric=normalized_metric,  # 写入对比指标字段。
            value=row_value_map.get(str(current_building_id), 0.0),  # 如果当前建筑没有命中数据，就用 0 兜底。
            unit=get_meter_unit(normalized_meter),  # 写入单位字段。
        )  # 完成当前对比项对象创建。
        for current_building_id in effective_building_ids  # 遍历最终生效的建筑列表。
    ]  # 完成对比结果列表创建。
    return EnergyCompareResponse(items=ordered_items)  # 返回完整响应。


def get_energy_rankings(  # 定义能耗排行接口业务函数。
    meter: str | None,  # 接收表计类型。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    metric: str | None,  # 接收排行指标。
    order: str | None,  # 接收排序方向。
    limit: int,  # 接收返回条数上限。
) -> EnergyRankingResponse:  # 返回排行响应模型。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, None, None, normalize_meter(meter))  # 按当前排行过滤条件补齐默认时间范围。
    normalized_meter = normalize_meter(meter)  # 标准化表计类型。
    normalized_metric = normalize_ranking_metric(metric)  # 标准化排行指标。
    normalized_order = normalize_order(order)  # 标准化排序方向。
    safe_limit = max(1, min(limit, 100))  # 给 limit 做简单范围限制。
    metric_sql = RANKING_METRIC_SQL_MAP[normalized_metric]  # 取出指标 SQL 表达式。
    rows = fetch_all(  # 查询排行结果。
        f"""
        SELECT
            mr.building_id AS building_id,
            {metric_sql} AS value
        FROM meter_readings mr
        WHERE mr.meter = :meter
          AND mr.timestamp >= :start_time
          AND mr.timestamp <= :end_time
        GROUP BY mr.building_id
        ORDER BY value {normalized_order}
        LIMIT :limit
        """,
        {"meter": normalized_meter, "start_time": resolved_start, "end_time": resolved_end, "limit": safe_limit},
    )  # 执行排行查询。
    ranking_items: list[EnergyRankingItem] = []  # 初始化排行项列表。
    for index, row in enumerate(rows, start=1):  # 遍历排行结果并从 1 开始编号。
        ranking_items.append(  # 把当前排行项追加到列表。
            EnergyRankingItem(  # 创建排行项对象。
                rank=index,  # 写入排名字段。
                building_id=str(row["building_id"]),  # 写入建筑编号字段。
                value=round(float(row["value"] or 0), 4),  # 写入排行值字段。
                unit=get_meter_unit(normalized_meter),  # 写入单位字段。
            )  # 完成排行项对象创建。
        )  # 完成当前排行项追加。
    return EnergyRankingResponse(items=ranking_items)  # 返回完整排行响应。


def get_energy_cop(  # 定义 COP 查询接口业务函数。
    building_id: str | None,  # 接收建筑编号。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    granularity: str | None,  # 接收时间粒度。
) -> CopAnalysisResponse:  # 返回 COP 响应模型。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id] if building_id else None, None, None)  # 按当前建筑过滤条件补齐默认时间范围。
    resolved_building_id = building_id or fetch_scalar("SELECT building_id FROM building_metadata LIMIT 1")  # 如果没传建筑，就默认拿第一栋楼。
    normalized_granularity = normalize_granularity(granularity)  # 标准化时间粒度。
    rows = fetch_all(  # 查询 electricity 和 chilledwater 两类表计在同一时间桶下的聚合值。
        f"""
        SELECT
            date_trunc('{normalized_granularity}', timestamp) AS timestamp,
            meter,
            SUM(meter_reading) AS value
        FROM meter_readings
        WHERE building_id = :building_id
          AND meter IN ('electricity', 'chilledwater')
          AND timestamp >= :start_time
          AND timestamp <= :end_time
        GROUP BY 1, 2
        ORDER BY 1 ASC
        """,
        {"building_id": resolved_building_id, "start_time": resolved_start, "end_time": resolved_end},
    )  # 执行 COP 所需的聚合查询。
    bucket_map: dict[datetime, dict[str, float]] = defaultdict(dict)  # 初始化时间桶到表计值的映射。
    for row in rows:  # 遍历所有查询结果。
        bucket_map[row["timestamp"]][row["meter"]] = float(row["value"] or 0)  # 把每个时间桶下的表计值塞进字典。
    cop_points: list[CopPoint] = []  # 初始化 COP 点位列表。
    for bucket_time in sorted(bucket_map.keys()):  # 按时间排序遍历所有时间桶。
        electricity_value = bucket_map[bucket_time].get("electricity", 0.0)  # 读取当前时间桶的电表值。
        chilledwater_value = bucket_map[bucket_time].get("chilledwater", 0.0)  # 读取当前时间桶的冷冻水值。
        if electricity_value <= 0 or chilledwater_value <= 0:  # 如果任意一方没有值，就跳过当前时间桶。
            continue  # 直接处理下一条。
        cop_value = chilledwater_value / electricity_value  # 用冷冻水表值除以电表值，做一个演示版估算 COP。
        cop_points.append(CopPoint(timestamp=require_api_datetime(bucket_time), cop=round(cop_value, 4)))  # 把当前 COP 点转成台湾标准时间后写进列表。
    cop_values = [point.cop for point in cop_points]  # 取出所有 COP 数值，方便后面算摘要。
    if cop_values:  # 如果有有效 COP 点，
        summary = CopSummary(  # 就生成真实摘要。
            avg_cop=round(sum(cop_values) / len(cop_values), 4),  # 计算平均 COP。
            min_cop=round(min(cop_values), 4),  # 计算最小 COP。
            max_cop=round(max(cop_values), 4),  # 计算最大 COP。
            calculation_mode="demo_estimated",  # 标记当前计算方式是演示版估算。
            formula="COP ≈ chilledwater_sum / electricity_sum",  # 写入当前演示版公式说明。
        )  # 完成摘要创建。
    else:  # 如果没有有效 COP 点，
        summary = CopSummary(  # 就返回全 0 摘要，避免前端报错。
            avg_cop=0.0,  # 平均值返回 0。
            min_cop=0.0,  # 最小值返回 0。
            max_cop=0.0,  # 最大值返回 0。
            calculation_mode="demo_estimated",  # 依然标记为演示版估算。
            formula="COP ≈ chilledwater_sum / electricity_sum",  # 依然返回公式说明。
        )  # 完成兜底摘要创建。
    return CopAnalysisResponse(  # 构造并返回 COP 响应。
        building_id=str(resolved_building_id),  # 写入建筑编号字段。
        time_range=build_api_time_range(resolved_start, resolved_end),  # 写入带台湾时区的时间范围字段。
        points=cop_points,  # 写入 COP 点位字段。
        summary=summary,  # 写入 COP 摘要字段。
    )  # 完成 COP 响应构造。


def calculate_pearson_correlation(  # 定义计算皮尔逊相关系数的函数。
    x_values: list[float],  # 接收第一个序列。
    y_values: list[float],  # 接收第二个序列。
) -> float:  # 返回相关系数。
    if len(x_values) != len(y_values) or len(x_values) < 2:  # 如果两个序列长度不同或数据点不足，
        return 0.0  # 就直接返回 0。
    x_mean = sum(x_values) / len(x_values)  # 计算 x 序列均值。
    y_mean = sum(y_values) / len(y_values)  # 计算 y 序列均值。
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))  # 计算协方差分子部分。
    x_denominator = math.sqrt(sum((x - x_mean) ** 2 for x in x_values))  # 计算 x 标准差的分母部分。
    y_denominator = math.sqrt(sum((y - y_mean) ** 2 for y in y_values))  # 计算 y 标准差的分母部分。
    if x_denominator == 0 or y_denominator == 0:  # 如果任意一侧没有波动，
        return 0.0  # 就直接返回 0，避免除零错误。
    return numerator / (x_denominator * y_denominator)  # 返回最终相关系数。


def get_energy_weather_correlation(  # 定义天气相关性接口业务函数。
    building_id: str | None,  # 接收建筑编号。
    meter: str | None,  # 接收表计类型。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
) -> WeatherCorrelationResponse:  # 返回天气相关性响应模型。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id] if building_id else None, None, normalize_meter(meter))  # 按当前建筑和表计过滤条件补齐默认时间范围。
    resolved_building_id = building_id or fetch_scalar("SELECT building_id FROM building_metadata LIMIT 1")  # 如果没传建筑，就默认取第一栋楼。
    normalized_meter = normalize_meter(meter)  # 标准化表计类型。
    rows = fetch_all(  # 把建筑的能耗数据和站点天气数据按时间点对齐查询出来。
        """
        SELECT
            mr.timestamp AS timestamp,
            mr.meter_reading AS energy_value,
            wd."airTemperature" AS air_temperature,
            wd."dewTemperature" AS dew_temperature,
            wd."windSpeed" AS wind_speed
        FROM meter_readings mr
        JOIN building_metadata bm ON mr.building_id = bm.building_id
        JOIN weather_data wd ON bm.site_id = wd.site_id AND mr.timestamp = wd.timestamp
        WHERE mr.building_id = :building_id
          AND mr.meter = :meter
          AND mr.timestamp >= :start_time
          AND mr.timestamp <= :end_time
        ORDER BY mr.timestamp ASC
        """,
        {"building_id": resolved_building_id, "meter": normalized_meter, "start_time": resolved_start, "end_time": resolved_end},
    )  # 执行天气相关性原始数据查询。
    factor_defs = [  # 定义要参与相关性分析的天气因子。
        ("air_temperature", "air_temperature"),  # 气温字段映射。
        ("dew_temperature", "dew_temperature"),  # 露点温度字段映射。
        ("wind_speed", "wind_speed"),  # 风速字段映射。
    ]  # 结束因子定义。
    factors: list[WeatherFactor] = []  # 初始化天气因子结果列表。
    main_correlation = 0.0  # 初始化主相关系数。
    for index, (response_name, row_key) in enumerate(factor_defs):  # 逐个处理每个天气因子。
        paired_values = [(float(row["energy_value"]), float(row[row_key])) for row in rows if row["energy_value"] is not None and row[row_key] is not None]  # 只保留能耗和天气都不为空的数据点。
        if len(paired_values) < 2:  # 如果有效配对数据不足两个，
            coefficient = 0.0  # 就直接把相关系数记为 0。
        else:  # 如果有效配对数据足够，
            x_values = [pair[0] for pair in paired_values]  # 取出能耗序列。
            y_values = [pair[1] for pair in paired_values]  # 取出天气序列。
            coefficient = calculate_pearson_correlation(x_values, y_values)  # 计算当前因子的相关系数。
        if index == 0:  # 如果当前因子是第一个，
            main_correlation = coefficient  # 就把它作为主相关系数返回。
        factors.append(  # 把当前因子追加到结果列表。
            WeatherFactor(  # 创建天气因子对象。
                name=response_name,  # 写入因子名称字段。
                coefficient=round(coefficient, 4),  # 写入相关系数字段。
                direction="positive" if coefficient >= 0 else "negative",  # 根据符号生成方向字段。
            )  # 完成因子对象创建。
        )  # 完成因子追加。
    return WeatherCorrelationResponse(  # 构造并返回天气相关性响应。
        building_id=str(resolved_building_id),  # 写入建筑编号字段。
        meter=normalized_meter,  # 写入表计类型字段。
        correlation_coefficient=round(main_correlation, 4),  # 写入主相关系数字段。
        factors=factors,  # 写入因子列表字段。
    )  # 完成天气相关性响应构造。


def get_weather_context(  # 定义查询天气上下文的函数。
    building_id: str,  # 接收建筑编号。
    start_time: datetime,  # 接收开始时间。
    end_time: datetime,  # 接收结束时间。
) -> list[WeatherPoint]:  # 返回天气点列表。
    rows = fetch_all(  # 根据建筑对应的 site_id 查询时间范围内天气数据。
        """
        SELECT
            wd.timestamp AS timestamp,
            wd."airTemperature" AS air_temperature,
            wd."dewTemperature" AS dew_temperature,
            wd."windSpeed" AS wind_speed
        FROM building_metadata bm
        JOIN weather_data wd ON bm.site_id = wd.site_id
        WHERE bm.building_id = :building_id
          AND wd.timestamp >= :start_time
          AND wd.timestamp <= :end_time
        ORDER BY wd.timestamp ASC
        LIMIT 200
        """,
        {"building_id": building_id, "start_time": start_time, "end_time": end_time},
    )  # 执行天气上下文查询。
    return [  # 把数据库结果转成天气点模型列表。
        WeatherPoint(  # 创建天气点对象。
            timestamp=require_api_datetime(row["timestamp"]),  # 把数据库时间转成台湾标准时间后写入时间字段。
            air_temperature=row.get("air_temperature"),  # 写入气温字段。
            dew_temperature=row.get("dew_temperature"),  # 写入露点温度字段。
            wind_speed=row.get("wind_speed"),  # 写入风速字段。
        )  # 完成天气点对象创建。
        for row in rows  # 遍历所有天气结果行。
    ]  # 完成天气点列表构造。


