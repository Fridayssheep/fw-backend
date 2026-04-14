import math  # 导入数学库，后面计算相关系数时会用到平方根。
from collections import defaultdict  # 导入默认字典，方便按建筑或时间桶聚合数据。
from datetime import datetime  # 导入日期时间类型，方便做时间计算。
from datetime import timedelta  # 导入时间差类型，方便构造默认 7 天 COP 窗口。
from typing import Any  # 导入任意类型注解，方便描述松散结构。

from app.core.database import build_in_clause  # 导入 IN 条件构造工具函数。
from app.core.database import fetch_all  # 导入多行查询函数。
from app.core.database import fetch_one  # 导入单行查询函数。
from app.core.database import fetch_scalar  # 导入单值查询函数。
from app.schemas.schemas_common import Pagination  # 导入分页模型，方便显式构造分页对象。
from app.schemas.schemas_energy import CopAnalysisResponse  # 导入 COP 响应模型。
from app.schemas.schemas_energy import CopPoint  # 导入 COP 点模型。
from app.schemas.schemas_energy import CopSummary  # 导入 COP 摘要模型。
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
from .service_common import ResourceNotFoundError  # 导入资源不存在异常，方便在建筑不存在时返回统一 404。
from .service_common import build_expected_time_buckets  # 导入完整时间桶构造函数，方便补齐缺失时间点。
from .service_common import build_api_time_range  # 导入构造接口时间范围对象的函数。
from .service_common import get_meter_unit  # 导入获取表计单位的函数。
from .service_common import get_meter_time_bounds  # 导入表计时间边界查询函数，方便收敛 COP 共同时间窗。
from .service_common import normalize_granularity  # 导入标准化粒度的函数。
from .service_common import normalize_meter  # 导入标准化表计类型的函数。
from .service_common import normalize_pagination  # 导入标准化分页参数的函数。
from .service_common import require_api_datetime  # 导入强制转换接口时间的函数。
from .service_common import resolve_numeric_data_status  # 导入统一数据状态判定函数，方便区分缺失值和有效值。
from .service_common import resolve_time_range  # 导入补齐时间范围的函数。
from .service_common import round_optional_float  # 导入可空数值四舍五入函数，避免把缺失值误写成 0。
from .service_common import to_api_datetime  # 导入转换接口输出时间的函数。


AGGREGATION_MAP = {  # 定义允许使用的聚合函数映射表。
    "sum": "SUM",  # sum 对应求和。
    "avg": "AVG",  # avg 对应平均。
    "max": "MAX",  # max 对应最大值。
    "min": "MIN",  # min 对应最小值。
}  # 结束聚合函数映射定义。


MAX_DEFAULT_TREND_BUILDINGS = 10  # 定义趋势接口在缺少建筑过滤时默认最多返回的建筑数量。
COP_PROXY_MAX_VALID = 10.0  # 定义建筑级代理 COP 的保守上限，用于剔除明显失真的超高值。
COP_PROXY_GOOD_THRESHOLD = 4.5  # 定义代理 COP 的良好参考阈值，参考高效冷机常见水平。
COP_PROXY_WARNING_THRESHOLD = 2.5  # 定义代理 COP 的预警参考阈值，参考常见风冷机组下沿。


COMPARE_METRIC_SQL_MAP = {  # 定义能耗对比接口允许的指标 SQL 表达式。
    "sum": "SUM(mr.meter_reading)",  # sum 表示总能耗。
    "total": "SUM(mr.meter_reading)",  # total 作为 sum 的兼容别名。
    "avg": "AVG(mr.meter_reading)",  # avg 表示平均能耗。
    "average": "AVG(mr.meter_reading)",  # average 作为 avg 的兼容别名。
    "peak": "MAX(mr.meter_reading)",  # peak 表示峰值能耗。
    "base_load": "MIN(mr.meter_reading)",  # base_load 这里用最小负荷做一个演示版近似。
    "eui": "SUM(mr.meter_reading) / NULLIF(MAX(bm.sqm), 0)",  # eui 为算总能耗除以建筑面积。
}  # 结束对比指标映射定义。


RANKING_METRIC_SQL_MAP = {  # 定义能耗排行接口允许的指标 SQL 表达式。
    "sum": "SUM(mr.meter_reading)",  # sum 表示总能耗。
    "total": "SUM(mr.meter_reading)",  # total 作为 sum 的兼容别名。
    "avg": "AVG(mr.meter_reading)",  # avg 表示平均能耗。
    "average": "AVG(mr.meter_reading)",  # average 作为 avg 的兼容别名。
    "peak": "MAX(mr.meter_reading)",  # peak 表示峰值能耗。
    "eui": "SUM(mr.meter_reading) / NULLIF(MAX(bm.sqm), 0)",  # eui 为算总能耗除以建筑面积。
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
        normalized_value = round_optional_float(row.get("value"))  # 先把当前行数值安全标准化，避免把缺失值静默写成 0。
        points.append(  # 把当前行转成 EnergyPoint 模型并追加进列表。
            EnergyPoint(  # 创建一个能耗点对象。
                timestamp=require_api_datetime(row["timestamp"]),  # 把数据库时间转成UTC+8标准时间后写入时间字段。
                building_id=row.get("building_id"),  # 写入建筑编号字段。
                meter=row.get("meter"),  # 写入表计类型字段。
                value=normalized_value,  # 写入标准化后的能耗值字段。
                data_status=resolve_numeric_data_status(has_data=row.get("value") is not None),  # 写入当前点位的数据状态。
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
            COUNT(mr.meter_reading) AS reading_count,
            SUM(mr.meter_reading) AS total,
            AVG(mr.meter_reading) AS average,
            MAX(mr.meter_reading) AS peak
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {where_sql}
        """,
        params,
    ) or {"reading_count": 0, "total": None, "average": None, "peak": None}  # 如果查不到数据，就返回显式缺失的兜底结构。
    reading_count = int(summary_row.get("reading_count") or 0)  # 读取当前筛选范围内真实命中的读数条数。
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
    ) if reading_count > 0 else None  # 只有真的存在读数时才去查询峰值时间。
    meter_name = meter or "all"  # 如果没传表计类型，就把摘要里的 meter 字段写成 all。
    has_summary_data = reading_count > 0  # 判断当前摘要是否真正命中了源数据。
    return EnergySummary(  # 构造并返回摘要对象。
        meter=meter_name,  # 写入摘要表计类型。
        total=round_optional_float(summary_row.get("total")),  # 写入总量；如果缺失则明确返回空值。
        average=round_optional_float(summary_row.get("average")),  # 写入均值；如果缺失则明确返回空值。
        peak=round_optional_float(summary_row.get("peak")),  # 写入峰值；如果缺失则明确返回空值。
        peak_time=to_api_datetime(peak_row["timestamp"]) if peak_row else None,  # 如果有峰值时间就转成UTC+8标准时间后写入，否则返回空。
        unit=get_meter_unit(meter),  # 根据表计类型补单位。
        data_status=resolve_numeric_data_status(has_data=has_summary_data),  # 写入摘要数据状态，避免把缺失值误认为 0。
        reading_count=reading_count,  # 写入命中的真实读数条数，方便前端判断数据覆盖程度。
        data_note=None if has_summary_data else "当前筛选条件下没有命中的表计读数。",  # 在缺失时补充明确说明。
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
        normalized_value = round_optional_float(row.get("value"))  # 先把聚合值安全标准化，避免把缺失值误写成 0。
        grouped_points[key].append(  # 把当前点位追加到对应序列里。
            EnergyPoint(  # 创建能耗点对象。
                timestamp=require_api_datetime(row["timestamp"]),  # 把数据库时间转成UTC+8标准时间后写入时间字段。
                building_id=row.get("building_id"),  # 写入建筑字段。
                meter=row.get("meter") or normalized_meter,  # 写入表计类型字段。
                value=normalized_value,  # 写入聚合后的数值字段。
                data_status=resolve_numeric_data_status(has_data=row.get("value") is not None),  # 写入当前点位的数据状态。
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
        time_range=build_api_time_range(resolved_start, resolved_end),  # 写入带UTC+8时区的最终时间范围。
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
            {metric_sql} AS value,
            COUNT(mr.meter_reading) AS reading_count
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {where_sql}
        GROUP BY mr.building_id
        ORDER BY value DESC
        """,
        params,
    )  # 执行对比查询。
    row_payload_map = {  # 把数据库结果整理成建筑到数值和覆盖情况的映射，方便补齐无数据建筑。
        str(row["building_id"]): {  # 以建筑编号作为映射键。
            "value": round_optional_float(row.get("value")),  # 保存当前建筑的计算值；如果缺失则保留空值。
            "reading_count": int(row.get("reading_count") or 0),  # 保存当前建筑命中的真实读数条数。
        }  # 完成当前建筑结果结构构造。
        for row in rows  # 遍历数据库返回的所有对比结果。
    }  # 完成映射构造。
    ordered_items = [  # 按前端传入顺序或默认建筑顺序逐条组装返回项。
        EnergyCompareItem(  # 创建对比项对象。
            building_id=str(current_building_id),  # 写入当前建筑编号字段。
            metric=normalized_metric,  # 写入对比指标字段。
            value=row_payload_map.get(str(current_building_id), {}).get("value"),  # 写入当前建筑的指标值；没有命中时明确返回空值。
            unit=f"{get_meter_unit(normalized_meter)}/m²" if normalized_metric == "eui" else get_meter_unit(normalized_meter),  # 动态生成EUI单位。
            data_status=resolve_numeric_data_status(has_data=row_payload_map.get(str(current_building_id), {}).get("reading_count", 0) > 0),  # 写入当前建筑的数据状态。
            data_note=(  # 根据当前指标的缺失原因补充说明文本。
                None  # 如果当前建筑有真实读数，就不额外补说明。
                if row_payload_map.get(str(current_building_id), {}).get("reading_count", 0) > 0 and row_payload_map.get(str(current_building_id), {}).get("value") is not None  # 只在真实有值时返回空说明。
                else "当前时间范围内没有可用于该指标计算的读数。" if row_payload_map.get(str(current_building_id), {}).get("reading_count", 0) <= 0  # 如果当前建筑完全没有读数，就提示读数缺失。
                else "当前建筑缺少面积等辅助字段，无法计算该指标。"  # 如果有读数但结果仍为空，就提示辅助字段缺失。
            ),
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
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE mr.meter = :meter
          AND mr.timestamp >= :start_time
          AND mr.timestamp <= :end_time
        GROUP BY mr.building_id
        ORDER BY value {normalized_order} NULLS LAST
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
                value=round_optional_float(row.get("value")),  # 写入排行值字段；如果结果缺失则显式返回空值。
                unit=f"{get_meter_unit(normalized_meter)}/m²" if normalized_metric == "eui" else get_meter_unit(normalized_meter),  # 动态生成EUI单位。
                data_status=resolve_numeric_data_status(has_data=row.get("value") is not None),  # 写入排行值的数据状态。
            )  # 完成排行项对象创建。
        )  # 完成当前排行项追加。
    return EnergyRankingResponse(items=ranking_items)  # 返回完整排行响应。


def resolve_cop_building_id(building_id: str | None) -> str:  # 定义解析 COP 目标建筑编号的函数。
    if building_id:  # 如果前端明确传了建筑编号，
        building_row = fetch_one(  # 就先校验该建筑是否真实存在。
            """
            SELECT building_id
            FROM building_metadata
            WHERE building_id = :building_id
            """,
            {"building_id": building_id},
        )  # 执行建筑存在性查询。
        if building_row is None:  # 如果数据库里根本没有这栋楼，
            raise ResourceNotFoundError(f"未找到建筑: {building_id}")  # 就抛出统一 404 异常。
        return str(building_row["building_id"])  # 返回已经确认存在的建筑编号。
    default_row = fetch_one(  # 如果前端没有传建筑，就优先找一栋同时拥有 electricity 和 chilledwater 的建筑。
        """
        SELECT
            mr.building_id AS building_id
        FROM meter_readings mr
        WHERE mr.meter IN ('electricity', 'chilledwater')
        GROUP BY mr.building_id
        HAVING COUNT(DISTINCT mr.meter) = 2
        ORDER BY COUNT(*) DESC, mr.building_id ASC
        LIMIT 1
        """,
    )  # 执行默认建筑选择查询。
    if default_row is None:  # 如果连一栋同时有两个表计的建筑都找不到，
        raise ResourceNotFoundError("当前数据库中没有可用于 COP 分析的建筑。")  # 就直接返回明确错误。
    return str(default_row["building_id"])  # 返回默认建筑编号。


def resolve_cop_time_range(  # 定义解析 COP 时间范围的函数。
    building_id: str,  # 接收已经确认存在的建筑编号。
    start_time: datetime | str | None,  # 接收开始时间参数。
    end_time: datetime | str | None,  # 接收结束时间参数。
) -> tuple[datetime, datetime, datetime | None, datetime | None, str | None]:  # 返回最终时间范围、共同可用区间和说明文本。
    electricity_bounds = get_meter_time_bounds(building_id, "electricity")  # 查询当前建筑电表的时间边界。
    chilledwater_bounds = get_meter_time_bounds(building_id, "chilledwater")  # 查询当前建筑冷冻水表的时间边界。
    electricity_count = int(electricity_bounds.get("reading_count") or 0)  # 读取当前建筑电表读数条数。
    chilledwater_count = int(chilledwater_bounds.get("reading_count") or 0)  # 读取当前建筑冷冻水表读数条数。
    if electricity_count <= 0 or chilledwater_count <= 0:  # 如果当前建筑缺少任意一个表计，
        resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id], None, None)  # 就退回普通时间解析，方便后续统一返回缺失状态。
        return resolved_start, resolved_end, None, None, "当前建筑缺少 electricity 或 chilledwater 表计，无法形成共同可用区间。"  # 返回缺失说明。
    overlap_start = max(electricity_bounds["min_timestamp"], chilledwater_bounds["min_timestamp"])  # 计算两个表计共同可用区间的开始时间。
    overlap_end = min(electricity_bounds["max_timestamp"], chilledwater_bounds["max_timestamp"])  # 计算两个表计共同可用区间的结束时间。
    if overlap_start is None or overlap_end is None or overlap_start > overlap_end:  # 如果理论共同区间不存在，
        resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id], None, None)  # 就退回普通时间解析，方便后续统一返回缺失状态。
        return resolved_start, resolved_end, None, None, "当前建筑的 electricity 与 chilledwater 时间范围没有交集。"  # 返回明确的无交集说明。
    requested_start, requested_end = resolve_time_range(start_time, end_time, [building_id], None, None)  # 先用统一逻辑把前端时间解析成数据库时间。
    used_overlap_note = None  # 初始化时间窗口说明文本。
    resolved_end = requested_end if end_time is not None else overlap_end  # 如果前端显式传了结束时间，就尊重请求；否则自动收敛到共同区间结束时间。
    if start_time is not None:  # 如果前端显式传了开始时间，
        resolved_start = requested_start  # 就直接使用请求开始时间。
    else:  # 如果前端没有显式传开始时间，
        default_start = resolved_end - timedelta(days=7)  # 就先按照最终结束时间向前推 7 天。
        if resolved_end >= overlap_start and default_start < overlap_start:  # 如果默认窗口压到了共同区间之外但仍有交集，
            resolved_start = overlap_start  # 就把开始时间收敛到共同区间开始时间。
            used_overlap_note = "默认时间窗口已自动收敛到 electricity + chilledwater 的共同可用区间。"  # 并记录自动收敛说明。
        else:  # 如果默认窗口本身没有落到共同区间左侧，
            resolved_start = default_start  # 就保留默认开始时间。
    if end_time is None and used_overlap_note is None:  # 如果结束时间是后端自动补出来的，且前面还没写过说明，
        used_overlap_note = "默认时间窗口已自动收敛到 electricity + chilledwater 的共同可用区间。"  # 就明确记录自动收敛说明。
    return resolved_start, resolved_end, overlap_start, overlap_end, used_overlap_note  # 返回最终时间范围和共同区间信息。


def calculate_proxy_cop(  # 定义计算建筑级代理 COP 的函数。
    electricity_value: float | None,  # 接收当前时间桶聚合后的电表值。
    chilledwater_value: float | None,  # 接收当前时间桶聚合后的冷冻水表值。
) -> tuple[float | None, str | None]:  # 返回代理 COP 值和可选说明文本。
    if electricity_value is None or chilledwater_value is None:  # 如果任意一个表计值缺失，
        return None, "当前时间桶缺少 electricity 或 chilledwater 数据。"  # 就返回空值和缺失说明。
    if electricity_value <= 0:  # 如果当前时间桶的电表聚合值小于等于 0，
        return None, "当前时间桶 electricity 聚合值小于等于 0，无法作为 COP 分母。"  # 就返回空值和分母无效说明。
    raw_cop = chilledwater_value / electricity_value  # 先按当前建筑级数据计算代理 COP 原始值。
    if raw_cop > COP_PROXY_MAX_VALID:  # 如果代理 COP 高到明显失真，
        return None, f"当前时间桶代理 COP 高于 {COP_PROXY_MAX_VALID}，已按异常高值过滤。"  # 就返回空值并说明已被过滤。
    return round(raw_cop, 4), "当前值基于建筑级 electricity 与 chilledwater 的代理换算，仅用于趋势参考。"  # 返回保留四位小数的代理 COP 和统一说明。


def get_energy_cop(  # 定义 COP 查询接口业务函数。
    building_id: str | None,  # 接收建筑编号。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    granularity: str | None,  # 接收时间粒度。
) -> CopAnalysisResponse:  # 返回 COP 响应模型。
    resolved_building_id = resolve_cop_building_id(building_id)  # 先解析并校验真正要分析的建筑编号。
    normalized_granularity = normalize_granularity(granularity)  # 标准化时间粒度。
    resolved_start, resolved_end, overlap_start, overlap_end, overlap_note = resolve_cop_time_range(resolved_building_id, start_time, end_time)  # 按两个表计的共同可用区间解析最终时间窗。
    rows = fetch_all(  # 查询 electricity 和 chilledwater 两类表计在同一时间桶下的聚合值。
        f"""
        SELECT
            date_trunc('{normalized_granularity}', timestamp) AS timestamp,
            meter,
            SUM(meter_reading) AS value,
            COUNT(meter_reading) AS reading_count
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
    bucket_map: dict[datetime, dict[str, dict[str, Any]]] = defaultdict(dict)  # 初始化时间桶到表计聚合值和覆盖情况的映射。
    for row in rows:  # 遍历所有查询结果。
        bucket_map[row["timestamp"]][row["meter"]] = {  # 把每个时间桶下的表计值和读数条数塞进字典。
            "value": round_optional_float(row.get("value")),  # 写入当前表计聚合值；缺失时保留空值。
            "reading_count": int(row.get("reading_count") or 0),  # 写入当前表计命中的读数条数。
        }  # 完成当前表计聚合结果写入。
    bucket_times = build_expected_time_buckets(resolved_start, resolved_end, normalized_granularity)  # 按最终时间范围构造完整时间桶列表，补齐缺失点位。
    cop_points: list[CopPoint] = []  # 初始化 COP 点位列表。
    filtered_point_count = 0  # 初始化被异常高值或无效分母过滤的点位数量。
    missing_point_count = 0  # 初始化缺少共同表计数据的点位数量。
    for bucket_time in bucket_times:  # 遍历完整时间桶列表，确保缺失数据也会显式返回。
        bucket_payload = bucket_map.get(bucket_time, {})  # 读取当前时间桶已经聚合到的表计数据。
        electricity_payload = bucket_payload.get("electricity")  # 读取当前时间桶的电表聚合结果。
        chilledwater_payload = bucket_payload.get("chilledwater")  # 读取当前时间桶的冷冻水聚合结果。
        electricity_value = electricity_payload.get("value") if electricity_payload else None  # 读取当前时间桶的电表聚合值。
        chilledwater_value = chilledwater_payload.get("value") if chilledwater_payload else None  # 读取当前时间桶的冷冻水聚合值。
        if electricity_payload is None or chilledwater_payload is None:  # 如果当前时间桶缺少任意一个表计，
            missing_point_count += 1  # 就累计缺失点位数量。
            cop_points.append(  # 仍然要把缺失点位显式写回响应，便于前端区分缺失和真实零值。
                CopPoint(  # 创建缺失点位对象。
                    timestamp=require_api_datetime(bucket_time),  # 写入当前时间桶时间。
                    cop=None,  # 缺失点位不返回数值。
                    data_status=resolve_numeric_data_status(has_data=False),  # 把当前点位标记为 missing。
                    electricity_value=electricity_value,  # 透传当前时间桶电表值，方便排查。
                    chilledwater_value=chilledwater_value,  # 透传当前时间桶冷冻水值，方便排查。
                    data_note="当前时间桶未同时命中 electricity 和 chilledwater 数据。",  # 写入缺失说明。
                )  # 完成缺失点位对象创建。
            )  # 完成缺失点位追加。
            continue  # 继续处理下一个时间桶。
        cop_value, cop_note = calculate_proxy_cop(electricity_value, chilledwater_value)  # 计算当前时间桶的代理 COP。
        point_status = resolve_numeric_data_status(has_data=cop_value is not None, estimated=cop_value is not None, filtered=cop_value is None)  # 根据结果判定当前点位状态。
        if point_status == resolve_numeric_data_status(has_data=False, filtered=True):  # 如果当前点位被规则过滤，
            filtered_point_count += 1  # 就累计过滤点位数量。
        cop_points.append(  # 把当前时间桶的结果追加到响应点位列表。
            CopPoint(  # 创建 COP 点位对象。
                timestamp=require_api_datetime(bucket_time),  # 写入当前时间桶时间。
                cop=cop_value,  # 写入当前时间桶的代理 COP 值；如果被过滤则为空。
                data_status=point_status,  # 写入当前点位的数据状态。
                electricity_value=electricity_value,  # 透传当前时间桶电表聚合值。
                chilledwater_value=chilledwater_value,  # 透传当前时间桶冷冻水聚合值。
                data_note=cop_note,  # 写入当前点位的说明文本。
            )  # 完成当前 COP 点位对象创建。
        )  # 完成当前点位追加。
    cop_values = [point.cop for point in cop_points if point.cop is not None]  # 取出所有真正有效的代理 COP 数值，方便后面算摘要。
    if cop_values:  # 如果有有效 COP 点，
        summary = CopSummary(  # 就生成真实摘要。
            avg_cop=round(sum(cop_values) / len(cop_values), 4),  # 计算平均 COP。
            min_cop=round(min(cop_values), 4),  # 计算最小 COP。
            max_cop=round(max(cop_values), 4),  # 计算最大 COP。
            calculation_mode="building_level_proxy_with_overlap_window",  # 标记当前计算方式为建筑级代理值并且使用共同时间窗。
            formula="proxy_COP ≈ chilledwater_kWh_sum / electricity_kWh_sum",  # 写入当前代理公式说明。
            data_status=resolve_numeric_data_status(has_data=True, estimated=True),  # 摘要有有效点位时标记为 estimated。
            valid_point_count=len(cop_values),  # 写入有效点位数量。
            missing_point_count=missing_point_count,  # 写入缺失点位数量。
            filtered_point_count=filtered_point_count,  # 写入过滤点位数量。
            data_note="；".join(item for item in [overlap_note, "当前数据集没有冷机专用电表，因此这里只返回建筑级代理 COP，仅适合做趋势排查参考。"] if item),  # 组合摘要说明文本。
        )  # 完成摘要创建。
    else:  # 如果没有有效 COP 点，
        summary = CopSummary(  # 就返回显式空值摘要，避免把缺失状态误伪装成 0。
            avg_cop=None,  # 平均值在完全没有有效点位时返回空值。
            min_cop=None,  # 最小值在完全没有有效点位时返回空值。
            max_cop=None,  # 最大值在完全没有有效点位时返回空值。
            calculation_mode="building_level_proxy_with_overlap_window",  # 依然标记为建筑级代理计算模式。
            formula="proxy_COP ≈ chilledwater_kWh_sum / electricity_kWh_sum",  # 依然返回代理公式说明。
            data_status=resolve_numeric_data_status(has_data=False, filtered=filtered_point_count > 0 and missing_point_count == 0),  # 根据缺失和过滤情况给出摘要状态。
            valid_point_count=0,  # 没有有效点位时显式返回 0。
            missing_point_count=missing_point_count,  # 写入缺失点位数量。
            filtered_point_count=filtered_point_count,  # 写入过滤点位数量。
            data_note="；".join(  # 组合无有效点位时的摘要说明文本。
                item  # 逐条输出非空说明。
                for item in [  # 依次准备多个候选说明文本。
                    overlap_note,  # 如果默认时间窗被共同区间约束，就补充该说明。
                    "当前时间范围内没有形成可解释的代理 COP 点位。" if overlap_start or overlap_end else None,  # 如果共同区间存在但没有有效值，就提示没有形成有效点位。
                    "当前数据集没有冷机专用电表，因此这里只返回建筑级代理 COP，仅适合做趋势排查参考。",  # 补充当前公式的限制说明。
                ]  # 完成候选说明列表构造。
                if item  # 只保留非空说明。
            ),
        )  # 完成兜底摘要创建。
    return CopAnalysisResponse(  # 构造并返回 COP 响应。
        building_id=str(resolved_building_id),  # 写入建筑编号字段。
        time_range=build_api_time_range(resolved_start, resolved_end),  # 写入带UTC+8时区的时间范围字段。
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
            timestamp=require_api_datetime(row["timestamp"]),  # 把数据库时间转成UTC+8标准时间后写入时间字段。
            air_temperature=row.get("air_temperature"),  # 写入气温字段。
            dew_temperature=row.get("dew_temperature"),  # 写入露点温度字段。
            wind_speed=row.get("wind_speed"),  # 写入风速字段。
        )  # 完成天气点对象创建。
        for row in rows  # 遍历所有天气结果行。
    ]  # 完成天气点列表构造。
