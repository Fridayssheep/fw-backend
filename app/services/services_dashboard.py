from datetime import date  # 导入日期类型，方便做日聚合窗口和缓存键计算。
from datetime import datetime  # 导入日期时间类型，方便做 dashboard 时间计算。
from datetime import timedelta  # 导入时间差类型，方便构造上一统计周期。
import os  # 导入环境变量读取函数，方便配置缓存 TTL。
from threading import Lock  # 导入线程锁，避免并发请求重复刷新聚合窗口。
from typing import Any  # 导入任意类型注解，方便描述松散的中间数据结构。

from sqlalchemy import text  # 导入 SQL 文本函数，方便执行多语句事务。
from app.core.database import build_in_clause  # 导入 IN 子句构造函数，方便动态拼接 meter/building 过滤。
from app.core.database import engine  # 导入数据库引擎，方便在同一事务内先删后写聚合窗口。
from app.core.database import fetch_all  # 导入多行查询函数，方便查询建筑范围和聚合结果。
from app.core.database import fetch_one  # 导入单行查询函数，方便做建筑存在性检查。
from app.schemas.schemas_common import MetricCard  # 导入通用指标卡片模型，方便复用现有前端结构。
from app.schemas.schemas_dashboard import AnomalySummary  # 导入 dashboard 异常摘要模型。
from app.schemas.schemas_dashboard import DashboardBarChart  # 导入 dashboard 柱状图模型。
from app.schemas.schemas_dashboard import DashboardCardStatus  # 导入 dashboard 卡片状态枚举。
from app.schemas.schemas_dashboard import DashboardChartRange  # 导入 dashboard 图表范围枚举。
from app.schemas.schemas_dashboard import DashboardHighlight  # 导入 dashboard 高亮模型。
from app.schemas.schemas_dashboard import DashboardHighlightsResponse  # 导入 dashboard 高亮列表响应模型。
from app.schemas.schemas_dashboard import DashboardHighlightType  # 导入 dashboard 高亮类型枚举。
from app.schemas.schemas_dashboard import DashboardKpiCard  # 导入 dashboard 顶部 KPI 卡片模型。
from app.schemas.schemas_dashboard import DashboardMiniBar  # 导入 dashboard 迷你柱状图模型。
from app.schemas.schemas_dashboard import DashboardOverviewResponse  # 导入 dashboard 总览响应模型。
from app.schemas.schemas_dashboard import DashboardQuickLinkLevel  # 导入 dashboard 快捷跳转等级枚举。
from app.schemas.schemas_dashboard import DashboardTrendChart  # 导入 dashboard 折线图模型。
from app.schemas.schemas_dashboard import DashboardTrendSeries  # 导入 dashboard 折线图序列模型。
from .service_common import ResourceNotFoundError  # 导入资源不存在异常，方便返回一致的 404 语义。
from .service_common import build_api_time_range  # 导入接口时间范围构造函数，方便统一输出UTC+8时区。
from .service_common import require_api_datetime  # 导入必填时间转换函数，方便输出 API 时间。
from .service_common import resolve_numeric_data_status  # 导入统一数据状态判定函数，方便区分缺失值和真实零值。
from .service_common import resolve_time_range  # 导入时间范围补齐函数，方便沿用现有默认时间逻辑。
from .services_energy import COP_PROXY_GOOD_THRESHOLD  # 导入代理 COP 良好阈值，保证 dashboard 与 energy 口径一致。
from .services_energy import COP_PROXY_WARNING_THRESHOLD  # 导入代理 COP 预警阈值，保证 dashboard 与 energy 口径一致。
from .services_energy import calculate_proxy_cop  # 导入代理 COP 计算函数，复用 energy 的过滤与说明规则。


DEFAULT_DASHBOARD_METER = "electricity"  # 定义 dashboard 默认以电耗作为主统计口径。
DASHBOARD_DEFAULT_LIMIT = 3  # 定义 dashboard highlights 默认返回条数。
DASHBOARD_ANOMALY_LIMIT = 5  # 定义 dashboard overview 默认最多返回的异常条数。
DASHBOARD_HIGH_ENERGY_MULTIPLIER = 1.25  # 定义高能耗建筑判定时相对基线的放大倍数。
CARBON_FACTOR_KG_PER_KWH = 0.554  # 定义比赛版估算碳排时使用的固定电力排放因子。
DASHBOARD_LIGHTING_ESTIMATE_RATIO = 0.22  # 定义照明能耗估算比例（无 lighting 表计时使用）。
DASHBOARD_RECENT_DAYS = 7  # 定义顶部卡片默认回看天数。
DASHBOARD_COP_GOOD_THRESHOLD = COP_PROXY_GOOD_THRESHOLD  # 定义 dashboard 复用 energy 的代理 COP 良好阈值。
DASHBOARD_COP_WARNING_THRESHOLD = COP_PROXY_WARNING_THRESHOLD  # 定义 dashboard 复用 energy 的代理 COP 预警阈值。
METER_DAILY_AGG_REFRESH_TTL_SECONDS = int(os.getenv("METER_DAILY_AGG_REFRESH_TTL_SECONDS", "86400"))  # 定义日聚合窗口刷新的 TTL（默认 24 小时）。
DASHBOARD_MONTH_CACHE_TTL_SECONDS = int(os.getenv("DASHBOARD_MONTH_CACHE_TTL_SECONDS", "180"))  # 定义 dashboard 月视图缓存 TTL（默认 3 分钟）。
_DAILY_AGG_WINDOW_CACHE: list[dict[str, Any]] = []  # 缓存已刷新聚合窗口，避免同时间窗重复回刷明细表。
_DAILY_AGG_WINDOW_LOCK = Lock()  # 保护聚合窗口缓存的并发访问。
_DASHBOARD_MONTH_CACHE: dict[tuple[str, str, str, str], dict[str, Any]] = {}  # 缓存月视图折线图结果，降低热点请求抖动。
_DASHBOARD_MONTH_CACHE_LOCK = Lock()  # 保护月视图缓存的并发访问。


def build_dashboard_scope_filters(  # 定义构造 dashboard 范围过滤条件的函数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    metadata_alias: str = "bm",  # 接收 building_metadata 的表别名。
) -> tuple[str, dict[str, Any]]:  # 返回 where 条件和参数字典。
    clauses: list[str] = ["1=1"]  # 先放一个恒成立条件，方便统一拼接其他过滤条件。
    params: dict[str, Any] = {}  # 初始化 SQL 参数字典。
    if site_id:  # 如果前端传了 site_id，
        clauses.append(f"{metadata_alias}.site_id = :dashboard_site_id")  # 就追加站点过滤条件。
        params["dashboard_site_id"] = site_id  # 把站点参数写入参数字典。
    if building_id:  # 如果前端传了 building_id，
        clauses.append(f"{metadata_alias}.building_id = :dashboard_building_id")  # 就追加建筑过滤条件。
        params["dashboard_building_id"] = building_id  # 把建筑参数写入参数字典。
    return " AND ".join(clauses), params  # 返回完整过滤条件和参数字典。


def normalize_meter_list(meters: list[str]) -> list[str]:  # 定义标准化 meter 列表的函数。
    normalized = sorted({str(item).strip().lower() for item in meters if str(item).strip()})  # 去重并统一小写，避免 SQL 参数重复。
    if not normalized:  # 如果标准化后没有可用 meter，
        raise ValueError("meter 列表不能为空")  # 就抛出明确异常，避免执行无意义 SQL。
    return normalized  # 返回稳定排序后的 meter 列表。


def build_dashboard_fact_scope(  # 定义构造事实表过滤条件的函数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    fact_alias: str,  # 接收事实表别名（如 mr/da）。
    metadata_alias: str = "bm",  # 接收元数据表别名。
) -> tuple[str, str, dict[str, Any]]:  # 返回 join 语句、where 条件和参数字典。
    clauses: list[str] = ["1=1"]  # 初始化 where 子句列表。
    params: dict[str, Any] = {}  # 初始化 SQL 参数字典。
    join_sql = ""  # 默认不做 metadata join，避免全局查询引入额外开销。
    if site_id:  # 只有筛 site 时才需要 join 元数据表。
        join_sql = f"JOIN building_metadata {metadata_alias} ON {fact_alias}.building_id = {metadata_alias}.building_id"  # 构造按站点筛选所需的 join。
        clauses.append(f"{metadata_alias}.site_id = :dashboard_site_id")  # 追加站点过滤条件。
        params["dashboard_site_id"] = site_id  # 写入站点参数。
    if building_id:  # 如果传了 building_id，
        clauses.append(f"{fact_alias}.building_id = :dashboard_building_id")  # 直接用事实表字段过滤，避免无谓 join。
        params["dashboard_building_id"] = building_id  # 写入建筑参数。
    return join_sql, " AND ".join(clauses), params  # 返回 join/where/params 三元组。


def _prune_daily_agg_window_cache(now: datetime) -> None:  # 定义清理过期聚合窗口缓存的函数。
    _DAILY_AGG_WINDOW_CACHE[:] = [item for item in _DAILY_AGG_WINDOW_CACHE if item["expires_at"] > now]  # 仅保留仍在 TTL 内的窗口记录。


def _is_daily_agg_window_fresh(  # 定义判断聚合窗口是否已被覆盖的函数。
    start_day: date,  # 接收窗口开始日期。
    end_day: date,  # 接收窗口结束日期。
    meter_set: set[str],  # 接收窗口涉及的 meter 集合。
    now: datetime,  # 接收当前时间。
) -> bool:  # 返回当前窗口是否已在缓存内。
    for item in _DAILY_AGG_WINDOW_CACHE:  # 遍历所有已缓存窗口。
        if item["expires_at"] <= now:  # 如果窗口已经过期，
            continue  # 就跳过当前记录。
        if item["start_day"] <= start_day and item["end_day"] >= end_day and set(item["meters"]).issuperset(meter_set):  # 如果缓存窗口完整覆盖了目标范围且 meter 是超集，
            return True  # 就表示无需重新刷新聚合窗口。
    return False  # 如果没有命中覆盖窗口，就返回 false。


def _register_daily_agg_window_cache(  # 定义登记已刷新聚合窗口缓存的函数。
    start_day: date,  # 接收窗口开始日期。
    end_day: date,  # 接收窗口结束日期。
    meters: list[str],  # 接收窗口涉及的 meter 列表。
) -> None:  # 无返回值。
    now = datetime.now()  # 记录当前时间，方便计算 TTL 过期时间。
    with _DAILY_AGG_WINDOW_LOCK:  # 加锁保护共享缓存。
        _prune_daily_agg_window_cache(now)  # 写入前先清理过期窗口，控制缓存体积。
        _DAILY_AGG_WINDOW_CACHE.append(  # 追加当前窗口记录。
            {
                "start_day": start_day,
                "end_day": end_day,
                "meters": tuple(meters),
                "expires_at": now + timedelta(seconds=METER_DAILY_AGG_REFRESH_TTL_SECONDS),
            }
        )


def ensure_meter_daily_agg_window(  # 定义按窗口刷新日聚合表的函数。
    start_time: datetime,  # 接收窗口开始时间（包含）。
    end_time: datetime,  # 接收窗口结束时间（包含）。
    meters: list[str],  # 接收需要刷新的 meter 列表。
) -> None:  # 无返回值。
    if end_time < start_time:  # 如果时间窗口非法，
        return  # 直接返回，避免执行多余 SQL。
    normalized_meters = normalize_meter_list(meters)  # 标准化 meter 列表。
    start_day = start_time.date()  # 取窗口开始日期。
    end_day = end_time.date()  # 取窗口结束日期。
    meter_set = set(normalized_meters)  # 构造 meter 集合，方便做覆盖判断。
    now = datetime.now()  # 记录当前时间，方便做 TTL 判断。
    with _DAILY_AGG_WINDOW_LOCK:  # 读取缓存时加锁，避免并发下重复刷新。
        _prune_daily_agg_window_cache(now)  # 读取前先清理过期窗口。
        if _is_daily_agg_window_fresh(start_day, end_day, meter_set, now):  # 如果当前窗口已在 TTL 内覆盖，
            return  # 就直接复用，跳过刷新 SQL。
    delete_meter_clause, delete_meter_params = build_in_clause("meter", normalized_meters, "agg_delete_meter")  # 构造 delete 阶段 meter 过滤子句。
    select_meter_clause, select_meter_params = build_in_clause("mr.meter", normalized_meters, "agg_select_meter")  # 构造 insert 阶段 meter 过滤子句。
    existing_state = fetch_one(  # 先检查数据库里该窗口的聚合结果是否已经是新鲜数据。
        f"""
        SELECT
            COUNT(*) AS row_count,
            MIN(refreshed_at) AS min_refreshed_at
        FROM meter_daily_agg
        WHERE bucket_day >= :agg_start_day
          AND bucket_day <= :agg_end_day
          AND {delete_meter_clause}
        """,
        {
            "agg_start_day": start_day,
            "agg_end_day": end_day,
            **delete_meter_params,
        },
    ) or {}  # 如果查不到结果就回退空字典。
    row_count = int(existing_state.get("row_count") or 0)  # 读取窗口聚合行数。
    min_refreshed_at = existing_state.get("min_refreshed_at")  # 读取窗口最早刷新时间，作为数据新鲜度判定依据。
    if isinstance(min_refreshed_at, str):  # 兼容少量驱动返回字符串时间的情况。
        try:  # 尝试把字符串转成 datetime。
            min_refreshed_at = datetime.fromisoformat(min_refreshed_at)  # 解析 ISO 时间。
        except ValueError:  # 如果解析失败，
            min_refreshed_at = None  # 就回退为空，进入重算分支。
    if row_count > 0 and isinstance(min_refreshed_at, datetime) and (now - min_refreshed_at).total_seconds() <= METER_DAILY_AGG_REFRESH_TTL_SECONDS:  # 如果数据库内窗口数据仍在 TTL 内，
        _register_daily_agg_window_cache(start_day, end_day, normalized_meters)  # 就登记进进程缓存，避免重复查库。
        return  # 并直接返回，跳过重算。
    with engine.begin() as connection:  # 同一事务中完成先删后写，避免读到中间态。
        connection.execute(  # 删除目标窗口内旧聚合结果，保证重算后数据绝对一致。
            text(
                f"""
                DELETE FROM meter_daily_agg
                WHERE bucket_day >= :agg_start_day
                  AND bucket_day <= :agg_end_day
                  AND {delete_meter_clause}
                """
            ),
            {
                "agg_start_day": start_day,
                "agg_end_day": end_day,
                **delete_meter_params,
            },
        )
        connection.execute(  # 按天重算并写入窗口聚合结果。
            text(
                f"""
                INSERT INTO meter_daily_agg (
                    bucket_day,
                    building_id,
                    meter,
                    reading_sum,
                    reading_count,
                    latest_timestamp,
                    refreshed_at
                )
                SELECT
                    date_trunc('day', mr.timestamp)::date AS bucket_day,
                    mr.building_id AS building_id,
                    mr.meter AS meter,
                    COALESCE(SUM(mr.meter_reading), 0) AS reading_sum,
                    COUNT(mr.meter_reading) AS reading_count,
                    MAX(mr.timestamp) AS latest_timestamp,
                    NOW() AS refreshed_at
                FROM meter_readings mr
                WHERE mr.timestamp >= :agg_start_ts
                  AND mr.timestamp < :agg_end_exclusive
                  AND {select_meter_clause}
                GROUP BY 1, 2, 3
                """
            ),
            {
                "agg_start_ts": datetime.combine(start_day, datetime.min.time()),
                "agg_end_exclusive": datetime.combine(end_day + timedelta(days=1), datetime.min.time()),
                **select_meter_params,
            },
        )
    _register_daily_agg_window_cache(start_day, end_day, normalized_meters)  # 刷新成功后登记缓存窗口。


def build_dashboard_month_cache_key(  # 定义构造 dashboard 月视图缓存键的函数。
    current_end: datetime,  # 接收当前窗口结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> tuple[str, str, str, str]:  # 返回月视图缓存键。
    end_time_bucket = current_end.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")  # 以小时桶作为 end_time_bucket，平衡命中率和一致性。
    return (
        DashboardChartRange.month.value,
        site_id or "__all_sites__",
        building_id or "__all_buildings__",
        end_time_bucket,
    )  # 返回 (chart_range, site_id, building_id, end_time_bucket) 结构的缓存键。


def get_cached_dashboard_month_trend_chart(  # 定义读取 dashboard 月视图缓存的函数。
    cache_key: tuple[str, str, str, str],  # 接收缓存键。
) -> DashboardTrendChart | None:  # 返回命中的折线图缓存；未命中返回空。
    now = datetime.now()  # 记录当前时间用于 TTL 判断。
    with _DASHBOARD_MONTH_CACHE_LOCK:  # 读取缓存时加锁，避免并发读写冲突。
        cached_item = _DASHBOARD_MONTH_CACHE.get(cache_key)  # 尝试读取缓存记录。
        if cached_item is None:  # 如果不存在缓存，
            return None  # 就返回空。
        if cached_item["expires_at"] <= now:  # 如果缓存已过期，
            _DASHBOARD_MONTH_CACHE.pop(cache_key, None)  # 删除过期缓存，避免字典膨胀。
            return None  # 并返回空。
        cached_chart = cached_item["chart"]  # 取出缓存中的图表对象。
        return cached_chart.model_copy(deep=True)  # 返回深拷贝，避免外部修改污染缓存。


def set_cached_dashboard_month_trend_chart(  # 定义写入 dashboard 月视图缓存的函数。
    cache_key: tuple[str, str, str, str],  # 接收缓存键。
    chart: DashboardTrendChart,  # 接收需要缓存的折线图对象。
) -> None:  # 无返回值。
    with _DASHBOARD_MONTH_CACHE_LOCK:  # 写缓存时加锁。
        _DASHBOARD_MONTH_CACHE[cache_key] = {  # 覆盖写入缓存项。
            "expires_at": datetime.now() + timedelta(seconds=DASHBOARD_MONTH_CACHE_TTL_SECONDS),
            "chart": chart.model_copy(deep=True),
        }


def normalize_dashboard_window(  # 定义标准化 dashboard 时间窗口的函数。
    resolved_start: datetime,  # 接收当前周期开始时间。
    resolved_end: datetime,  # 接收当前周期结束时间。
) -> tuple[datetime, datetime, datetime, datetime]:  # 返回当前周期和上一周期的时间范围。
    if resolved_end <= resolved_start:  # 如果前端传入了非正常的时间区间，
        resolved_start = resolved_end - timedelta(days=7)  # 就回退到一个稳定的近七天窗口。
    current_start = resolved_start  # 记录当前周期开始时间。
    current_end = resolved_end  # 记录当前周期结束时间。
    period_duration = current_end - current_start  # 计算当前周期持续时长。
    previous_end = current_start  # 把上一周期结束时间定义为当前周期开始时间。
    previous_start = previous_end - period_duration  # 让上一周期长度和当前周期保持一致。
    return current_start, current_end, previous_start, previous_end  # 返回完整的双周期时间范围。


def get_dashboard_scope_rows(  # 定义查询 dashboard 统计范围内建筑清单的函数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> list[dict[str, Any]]:  # 返回范围内建筑元数据列表。
    where_sql, params = build_dashboard_scope_filters(site_id, building_id)  # 先构造建筑范围过滤条件。
    rows = fetch_all(  # 查询符合 dashboard 条件的建筑元数据。
        f"""
        SELECT
            bm.building_id,
            bm.site_id,
            bm.primaryspaceusage,
            bm.sqm
        FROM building_metadata bm
        WHERE {where_sql}
        ORDER BY bm.building_id ASC
        """,
        params,
    )  # 执行建筑范围查询。
    if rows:  # 如果已经查询到建筑范围，
        return rows  # 就直接返回结果列表。
    if building_id:  # 如果前端明确传了 building_id 但上面的查询没有命中，
        building_exists = fetch_one(  # 再单独检查该建筑是否存在于元数据表中。
            """
            SELECT
                bm.building_id
            FROM building_metadata bm
            WHERE bm.building_id = :building_id
            """,
            {"building_id": building_id},
        )  # 执行建筑存在性检查。
        if building_exists is None:  # 如果建筑本身不存在，
            raise ResourceNotFoundError(f"未找到建筑: {building_id}")  # 就返回明确的 404 异常。
        raise ValueError(f"建筑 {building_id} 不在站点 {site_id} 的筛选范围内")  # 如果建筑存在但和站点筛选冲突，就抛出校验错误。
    raise ValueError("当前筛选条件下没有可用建筑")  # 如果只是范围筛空，就返回一个清晰的业务错误。


def get_dashboard_period_rows(  # 定义查询 dashboard 双周期聚合结果的函数。
    current_start: datetime,  # 接收当前周期开始时间。
    current_end: datetime,  # 接收当前周期结束时间。
    previous_start: datetime,  # 接收上一周期开始时间。
    previous_end: datetime,  # 接收上一周期结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> list[dict[str, Any]]:  # 返回按建筑聚合后的双周期结果列表。
    ensure_meter_daily_agg_window(previous_start, current_end, [DEFAULT_DASHBOARD_METER])  # 先确保双周期窗口内的 electricity 日聚合可用。
    previous_end_effective = previous_end - timedelta(microseconds=1)  # 把上一周期开区间尾部转成闭区间末端日期，方便落到 DATE 维度。
    where_sql, params = build_dashboard_scope_filters(site_id, building_id)  # 先构造 dashboard 范围过滤条件。
    rows = fetch_all(  # 查询每栋楼在当前周期和上一周期的聚合电耗。
        f"""
        SELECT
            bm.building_id AS building_id,
            bm.site_id AS site_id,
            bm.primaryspaceusage AS primaryspaceusage,
            bm.sqm AS sqm,
            COALESCE(SUM(CASE WHEN da.bucket_day >= :current_start_day AND da.bucket_day <= :current_end_day THEN da.reading_count ELSE 0 END), 0) AS current_count,
            COALESCE(SUM(CASE WHEN da.bucket_day >= :previous_start_day AND da.bucket_day <= :previous_end_day THEN da.reading_count ELSE 0 END), 0) AS previous_count,
            COALESCE(SUM(CASE WHEN da.bucket_day >= :current_start_day AND da.bucket_day <= :current_end_day THEN da.reading_sum ELSE 0 END), 0) AS current_total,
            COALESCE(SUM(CASE WHEN da.bucket_day >= :previous_start_day AND da.bucket_day <= :previous_end_day THEN da.reading_sum ELSE 0 END), 0) AS previous_total,
            NULL::timestamp AS latest_timestamp
        FROM building_metadata bm
        LEFT JOIN meter_daily_agg da
            ON bm.building_id = da.building_id
           AND da.meter = :dashboard_meter
           AND da.bucket_day >= :previous_start_day
           AND da.bucket_day <= :current_end_day
        WHERE {where_sql}
        GROUP BY bm.building_id, bm.site_id, bm.primaryspaceusage, bm.sqm
        ORDER BY bm.building_id ASC
        """,
        {
            **params,
            "dashboard_meter": DEFAULT_DASHBOARD_METER,
            "current_start_day": current_start.date(),
            "current_end_day": current_end.date(),
            "previous_start_day": previous_start.date(),
            "previous_end_day": previous_end_effective.date(),
        },
    )  # 执行双周期聚合查询。
    return rows  # 返回按建筑聚合后的结果列表。


def to_float(value: Any) -> float:  # 定义把任意输入安全转换成浮点数的函数。
    return round(float(value or 0), 4)  # 返回保留四位小数的浮点值，方便统一口径。


def safe_divide(numerator: float, denominator: float) -> float:  # 定义安全除法函数。
    if denominator <= 0:  # 如果分母小于等于零，
        return 0.0  # 就返回零，避免除零异常和误导性结果。
    return round(numerator / denominator, 4)  # 返回保留四位小数的除法结果。


def calculate_change_rate(current_value: float | None, previous_value: float | None) -> float | None:  # 定义变化率计算函数。
    if current_value is None or previous_value is None:  # 如果当前值或上一值本身缺失，
        return None  # 就直接返回空，避免把缺失值误算成变化率。
    if previous_value <= 0:  # 如果上一周期没有有效值，
        return None  # 就不返回变化率，避免错误放大。
    return round((current_value - previous_value) / previous_value, 4)  # 返回保留四位小数的变化率。


def classify_anomaly_severity(deviation_rate: float) -> str:  # 定义根据偏离率划分异常严重度的函数。
    if deviation_rate >= 1.0:  # 如果偏离率达到 100% 及以上，
        return "critical"  # 就标记为严重。
    if deviation_rate >= 0.6:  # 如果偏离率达到 60% 及以上，
        return "high"  # 就标记为高风险。
    if deviation_rate >= 0.4:  # 如果偏离率达到 40% 及以上，
        return "medium"  # 就标记为中风险。
    return "low"  # 其余超过阈值的情况统一标记为低风险。


def normalize_dashboard_chart_range(chart_range: DashboardChartRange | str | None) -> DashboardChartRange:  # 定义标准化 dashboard 图表范围的函数。
    if isinstance(chart_range, DashboardChartRange):  # 如果传入值本身已经是合法枚举，
        return chart_range  # 就直接返回原值。
    normalized_text = str(chart_range or DashboardChartRange.day.value).strip().lower()  # 把原始值转成稳定小写文本。
    if normalized_text in {item.value for item in DashboardChartRange}:  # 如果文本值属于允许范围，
        return DashboardChartRange(normalized_text)  # 就转成枚举并返回。
    return DashboardChartRange.day  # 其余非法值统一回退到 day。


def build_dashboard_trend_context(  # 定义构造 dashboard 趋势图上下文的函数。
    current_end: datetime,  # 接收 dashboard 当前周期结束时间。
    chart_range: DashboardChartRange,  # 接收图表范围枚举。
) -> tuple[list[datetime], list[str], datetime, datetime, str]:  # 返回趋势点位时间列表、标签列表、查询开始、查询结束和 SQL 粒度。
    anchor_day_start = current_end.replace(hour=0, minute=0, second=0, microsecond=0)  # 把当前周期结束时间对齐到当天 00:00。
    if chart_range == DashboardChartRange.day:  # 如果当前是日视图，
        point_times = [anchor_day_start + timedelta(hours=offset) for offset in (0, 4, 8, 12, 16, 20, 23)]  # 构造 7 个当天折线点位，最后一个点固定为 23:00，避免跨到次日 00:00。
        labels = [point_time.strftime("%H:%M") for point_time in point_times]  # 直接使用实际点位时间作为日视图标签，避免生成会跨天的 24:00 标签。
        query_start = point_times[0]  # 把查询开始时间设为当天 00:00。
        query_end = anchor_day_start + timedelta(days=1)  # 把查询结束时间严格限定为次日 00:00，避免把次日 00:00-01:00 数据计入当天最后一个点。
        return point_times, labels, query_start, query_end, "hour"  # 返回日视图需要的上下文信息。
    if chart_range == DashboardChartRange.week:  # 如果当前是周视图，
        chart_start = anchor_day_start - timedelta(days=6)  # 把趋势起点设为最近 7 天的第一天 00:00。
        point_times = [chart_start + timedelta(days=offset) for offset in range(7)]  # 构造最近 7 天的折线点位。
        labels = [point_time.strftime("%m-%d") for point_time in point_times]  # 构造周视图标签列表。
        query_start = point_times[0]  # 把查询开始时间设为第一天 00:00。
        query_end = anchor_day_start + timedelta(days=1)  # 把查询结束时间设为当天 24:00。
        return point_times, labels, query_start, query_end, "day"  # 返回周视图需要的上下文信息。
    chart_start = anchor_day_start - timedelta(days=29)  # 把月视图趋势起点设为最近 30 天的第一天 00:00。
    point_times = [chart_start + timedelta(days=offset) for offset in range(30)]  # 构造最近 30 天的折线点位。
    labels = [point_time.strftime("%m-%d") for point_time in point_times]  # 构造月视图标签列表。
    query_start = point_times[0]  # 把查询开始时间设为第一天 00:00。
    query_end = anchor_day_start + timedelta(days=1)  # 把查询结束时间设为当天 24:00。
    return point_times, labels, query_start, query_end, "day"  # 返回月视图需要的上下文信息。


def get_dashboard_trend_rows(  # 定义查询 dashboard 趋势图原始数据的函数。
    query_start: datetime,  # 接收趋势查询开始时间。
    query_end: datetime,  # 接收趋势查询结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    bucket_granularity: str,  # 接收 SQL 时间粒度。
) -> list[dict[str, Any]]:  # 返回趋势原始聚合行列表。
    trend_meters = ["electricity", "chilledwater", "lighting"]  # 定义趋势图固定使用的三类 meter。
    if bucket_granularity == "day":  # 周/月视图按天查询时，优先读取日聚合表。
        ensure_meter_daily_agg_window(query_start, query_end - timedelta(microseconds=1), trend_meters)  # 先保证趋势窗口对应的日聚合数据可用。
        join_sql, where_sql, params = build_dashboard_fact_scope(site_id, building_id, "da")  # 构造日聚合查询的动态范围过滤条件。
        meter_clause, meter_params = build_in_clause("da.meter", trend_meters, "trend_meter")  # 构造 meter IN 条件。
        return fetch_all(  # 执行日聚合趋势查询并返回结果。
            f"""
            SELECT
                da.bucket_day::timestamp AS bucket_time,
                da.meter AS meter,
                COALESCE(SUM(da.reading_sum), 0) AS value
            FROM meter_daily_agg da
            {join_sql}
            WHERE {where_sql}
              AND da.bucket_day >= :trend_start_day
              AND da.bucket_day < :trend_end_day
              AND {meter_clause}
            GROUP BY 1, 2
            ORDER BY 1 ASC, 2 ASC
            """,
            {
                **params,
                **meter_params,
                "trend_start_day": query_start.date(),
                "trend_end_day": query_end.date(),
            },
        )  # 返回按天聚合后的趋势行。
    join_sql, where_sql, params = build_dashboard_fact_scope(site_id, building_id, "mr")  # 日内视图继续走明细查询，并按条件动态控制 join。
    meter_clause, meter_params = build_in_clause("mr.meter", trend_meters, "trend_meter")  # 构造 meter IN 条件。
    return fetch_all(  # 执行小时粒度趋势聚合查询并返回结果。
        f"""
        SELECT
            date_trunc('{bucket_granularity}', mr.timestamp) AS bucket_time,
            mr.meter AS meter,
            COALESCE(SUM(mr.meter_reading), 0) AS value
        FROM meter_readings mr
        {join_sql}
        WHERE {where_sql}
          AND mr.timestamp >= :trend_start
          AND mr.timestamp < :trend_end
          AND {meter_clause}
        GROUP BY 1, 2
        ORDER BY 1 ASC, 2 ASC
        """,
        {
            **params,
            **meter_params,
            "trend_start": query_start,
            "trend_end": query_end,
        },
    )  # 返回原始趋势聚合行。


def build_dashboard_trend_chart(  # 定义构造 dashboard 折线图对象的函数。
    current_end: datetime,  # 接收 dashboard 当前周期结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    chart_range: DashboardChartRange,  # 接收图表范围枚举。
) -> DashboardTrendChart:  # 返回 dashboard 折线图模型。
    month_cache_key: tuple[str, str, str, str] | None = None  # 初始化月视图缓存键。
    if chart_range == DashboardChartRange.month:  # 月视图先尝试命中短 TTL 缓存，降低热点重复计算。
        month_cache_key = build_dashboard_month_cache_key(current_end, site_id, building_id)  # 构造缓存键。
        cached_chart = get_cached_dashboard_month_trend_chart(month_cache_key)  # 读取缓存结果。
        if cached_chart is not None:  # 如果命中缓存，
            return cached_chart  # 就直接返回缓存结果。
    point_times, labels, query_start, query_end, bucket_granularity = build_dashboard_trend_context(current_end, chart_range)  # 先构造折线图上下文。
    trend_rows = get_dashboard_trend_rows(query_start, query_end, site_id, building_id, bucket_granularity)  # 查询折线图原始聚合数据。
    index_map = {point_time: index for index, point_time in enumerate(point_times)}  # 构造时间到索引的映射，方便 O(1) 回填序列值。
    series_value_map = {  # 初始化三条折线序列的值缓存。
        "electricity": [None] * len(point_times),  # 初始化总能耗（电耗）序列，缺失时间桶先显式标成空值。
        "chilledwater": [None] * len(point_times),  # 初始化制冷能耗序列，缺失时间桶先显式标成空值。
        "lighting": [None] * len(point_times),  # 初始化照明能耗序列，缺失时间桶先显式标成空值。
    }  # 完成序列缓存初始化。
    series_status_map = {  # 初始化三条折线序列的状态缓存。
        "electricity": [resolve_numeric_data_status(has_data=False)] * len(point_times),  # 初始化总能耗序列状态为 missing。
        "chilledwater": [resolve_numeric_data_status(has_data=False)] * len(point_times),  # 初始化制冷能耗序列状态为 missing。
        "lighting": [resolve_numeric_data_status(has_data=False)] * len(point_times),  # 初始化照明能耗序列状态为 missing。
    }  # 完成状态缓存初始化。
    for row in trend_rows:  # 遍历每一条趋势聚合行。
        bucket_time = row.get("bucket_time")  # 读取当前行时间桶。
        meter_name = str(row.get("meter") or "")  # 读取当前行表计名称。
        if bucket_time not in index_map:  # 如果当前时间桶不在预期展示点位里，
            continue  # 就跳过当前行。
        if meter_name not in series_value_map:  # 如果当前表计不是三条目标序列之一，
            continue  # 就跳过当前行。
        series_index = index_map[bucket_time]  # 获取当前时间桶对应的序列索引。
        current_value = series_value_map[meter_name][series_index] or 0.0  # 读取当前时间桶已累计值；此前缺失时从 0 开始累计。
        series_value_map[meter_name][series_index] = round(current_value + to_float(row.get("value")), 4)  # 把当前聚合值累计到目标序列。
        series_status_map[meter_name][series_index] = resolve_numeric_data_status(has_data=True)  # 当前时间桶命中真实数据后，状态改成 valid。
    lighting_values = series_value_map["lighting"]  # 读取照明序列原始值。
    lighting_statuses = series_status_map["lighting"]  # 读取照明序列原始状态。
    if not any(status == resolve_numeric_data_status(has_data=True) for status in lighting_statuses):  # 如果当前数据源里没有真实 lighting 表计值，
        lighting_values = [round(value * DASHBOARD_LIGHTING_ESTIMATE_RATIO, 4) if value is not None else None for value in series_value_map["electricity"]]  # 就按电耗比例生成估算照明序列，并保留缺失时间桶。
        lighting_statuses = [resolve_numeric_data_status(has_data=value is not None, estimated=value is not None) for value in lighting_values]  # 把估算后的照明序列状态标记成 estimated 或 missing。
    trend_series = [  # 构造前端折线图需要的序列列表。
        DashboardTrendSeries(key="total_energy", name="总能耗", unit="kWh", chart_type="line", values=series_value_map["electricity"], data_statuses=series_status_map["electricity"]),  # 构造总能耗折线序列。
        DashboardTrendSeries(key="cooling_energy", name="制冷能耗", unit="kWh", chart_type="line", values=series_value_map["chilledwater"], data_statuses=series_status_map["chilledwater"]),  # 构造制冷能耗折线序列。
        DashboardTrendSeries(key="lighting_energy", name="照明能耗", unit="kWh", chart_type="line", values=lighting_values, data_statuses=lighting_statuses),  # 构造照明能耗折线序列。
    ]  # 完成折线图序列构造。
    chart = DashboardTrendChart(range=chart_range, labels=labels, series=trend_series)  # 构造最终折线图对象。
    if month_cache_key is not None:  # 如果当前是月视图，
        set_cached_dashboard_month_trend_chart(month_cache_key, chart)  # 就把结果写入短 TTL 缓存。
    return chart  # 返回完整折线图对象。


def build_dashboard_recent_daily_context(  # 定义构造 dashboard 顶部卡片近 N 天上下文的函数。
    current_end: datetime,  # 接收 dashboard 当前周期结束时间。
    recent_days: int = DASHBOARD_RECENT_DAYS,  # 接收近 N 天窗口长度。
) -> tuple[list[datetime], list[str], datetime, datetime]:  # 返回日期点位、日期标签、查询开始和查询结束。
    anchor_day_end = current_end.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)  # 把当前周期结束时间对齐到当天 24:00。
    query_start = anchor_day_end - timedelta(days=recent_days)  # 计算近 N 天窗口的查询开始时间。
    day_points = [query_start + timedelta(days=offset) for offset in range(recent_days)]  # 构造近 N 天每天 00:00 点位列表。
    day_labels = [day_point.strftime("%m-%d") for day_point in day_points]  # 构造近 N 天标签列表。
    return day_points, day_labels, query_start, anchor_day_end  # 返回顶部卡片所需上下文。


def get_dashboard_recent_energy_rows(  # 定义查询 dashboard 顶部卡片近 N 天能耗行数据的函数。
    query_start: datetime,  # 接收查询开始时间。
    query_end: datetime,  # 接收查询结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> list[dict[str, Any]]:  # 返回按天聚合的能耗行列表。
    ensure_meter_daily_agg_window(query_start, query_end - timedelta(microseconds=1), ["electricity", "chilledwater"])  # 先确保近 N 天窗口的日聚合结果可用。
    join_sql, where_sql, params = build_dashboard_fact_scope(site_id, building_id, "da")  # 构造按范围过滤的动态 join/where 片段。
    meter_clause, meter_params = build_in_clause("da.meter", ["electricity", "chilledwater"], "recent_meter")  # 构造 meter IN 条件。
    return fetch_all(  # 执行近 N 天电耗和制冷能耗聚合查询。
        f"""
        SELECT
            da.bucket_day::timestamp AS bucket_day,
            da.meter AS meter,
            COALESCE(SUM(da.reading_sum), 0) AS value
        FROM meter_daily_agg da
        {join_sql}
        WHERE {where_sql}
          AND da.bucket_day >= :recent_start_day
          AND da.bucket_day < :recent_end_day
          AND {meter_clause}
        GROUP BY 1, 2
        ORDER BY 1 ASC, 2 ASC
        """,
        {
            **params,
            **meter_params,
            "recent_start_day": query_start.date(),
            "recent_end_day": query_end.date(),
        },
    )  # 返回近 N 天能耗行列表。


def get_dashboard_recent_anomaly_rows(  # 定义查询 dashboard 顶部卡片近 N 天异常行数据的函数。
    query_start: datetime,  # 接收查询开始时间。
    query_end: datetime,  # 接收查询结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> list[dict[str, Any]]:  # 返回按天聚合的异常行列表。
    clauses: list[str] = ["ae.start_time >= :recent_start", "ae.start_time < :recent_end"]  # 初始化异常查询过滤条件。
    params: dict[str, Any] = {"recent_start": query_start, "recent_end": query_end}  # 初始化异常查询参数字典。
    if site_id:  # 如果传入了站点过滤，
        clauses.append("COALESCE(ae.site_id, bm.site_id) = :dashboard_site_id")  # 就追加站点过滤条件。
        params["dashboard_site_id"] = site_id  # 把站点参数写入参数字典。
    if building_id:  # 如果传入了建筑过滤，
        clauses.append("ae.building_id = :dashboard_building_id")  # 就追加建筑过滤条件。
        params["dashboard_building_id"] = building_id  # 把建筑参数写入参数字典。
    try:  # 尝试执行近 N 天异常聚合查询。
        return fetch_all(  # 执行近 N 天异常聚合查询并返回结果。
            f"""
            SELECT
                date_trunc('day', ae.start_time) AS bucket_day,
                COUNT(*) AS event_count,
                COUNT(DISTINCT ae.building_id) AS building_count,
                COALESCE(SUM(CASE WHEN UPPER(COALESCE(ae.severity, '')) IN ('CRITICAL', 'HIGH', 'MEDIUM') THEN 1 ELSE 0 END), 0) AS pending_count
            FROM anomaly_events ae
            LEFT JOIN building_metadata bm ON ae.building_id = bm.building_id
            WHERE {' AND '.join(clauses)}
            GROUP BY 1
            ORDER BY 1 ASC
            """,
            params,
        )  # 返回近 N 天异常行列表。
    except Exception:  # 如果当前环境尚未初始化 anomaly_events 表或查询失败，
        return []  # 就回退为空列表，避免 dashboard 主流程中断。


def get_dashboard_average_resolution_hours(  # 定义查询 dashboard 平均处理时长的函数。
    query_start: datetime,  # 接收查询开始时间。
    query_end: datetime,  # 接收查询结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> float:  # 返回平均处理时长（小时）。
    clauses: list[str] = [  # 初始化平均处理时长过滤条件列表。
        "ae.start_time >= :recent_start",  # 追加开始时间过滤条件。
        "ae.start_time < :recent_end",  # 追加结束时间过滤条件。
        "ae.end_time >= ae.start_time",  # 限制结束时间必须不早于开始时间。
    ]  # 完成过滤条件初始化。
    params: dict[str, Any] = {"recent_start": query_start, "recent_end": query_end}  # 初始化平均处理时长查询参数字典。
    if site_id:  # 如果传入了站点过滤，
        clauses.append("COALESCE(ae.site_id, bm.site_id) = :dashboard_site_id")  # 就追加站点过滤条件。
        params["dashboard_site_id"] = site_id  # 把站点参数写入参数字典。
    if building_id:  # 如果传入了建筑过滤，
        clauses.append("ae.building_id = :dashboard_building_id")  # 就追加建筑过滤条件。
        params["dashboard_building_id"] = building_id  # 把建筑参数写入参数字典。
    try:  # 尝试执行平均处理时长查询。
        row = fetch_one(  # 执行平均处理时长查询。
            f"""
            SELECT
                COALESCE(AVG(EXTRACT(EPOCH FROM (ae.end_time - ae.start_time)) / 3600.0), 0) AS avg_hours
            FROM anomaly_events ae
            LEFT JOIN building_metadata bm ON ae.building_id = bm.building_id
            WHERE {' AND '.join(clauses)}
            """,
            params,
        ) or {"avg_hours": 0}  # 如果查询为空则回退到零值。
        return round(float(row.get("avg_hours") or 0), 4)  # 返回保留四位小数的平均处理时长。
    except Exception:  # 如果当前环境尚未初始化 anomaly_events 表或查询失败，
        return 0.0  # 就回退到零小时，避免 dashboard 主流程中断。


def format_change_rate_text(change_rate: float | None) -> str:  # 定义把变化率格式化成展示文案的函数。
    if change_rate is None:  # 如果当前没有可比变化率，
        return "无可比数据"  # 就返回“无可比数据”文案。
    sign = "+" if change_rate >= 0 else "-"  # 根据变化率方向选择正负号。
    return f"{sign}{round(abs(change_rate) * 100, 2)}%"  # 返回百分比文本。


def resolve_cop_status(cop_value: float | None) -> tuple[DashboardCardStatus, str]:  # 定义根据 COP 值判定状态的函数。
    if cop_value is None:  # 如果当前没有有效代理 COP，
        return DashboardCardStatus.neutral, "共同区间数据不足"  # 就返回中性状态和缺失说明。
    if cop_value >= DASHBOARD_COP_GOOD_THRESHOLD:  # 如果 COP 达到良好阈值，
        return DashboardCardStatus.good, "运行状态良好"  # 就返回良好状态和文案。
    if cop_value >= DASHBOARD_COP_WARNING_THRESHOLD:  # 如果 COP 处于警告阈值和良好阈值之间，
        return DashboardCardStatus.warning, "运行状态一般"  # 就返回警告状态和文案。
    return DashboardCardStatus.danger, "运行状态偏低"  # 其余情况返回高风险状态和文案。


def build_dashboard_kpi_cards_and_bars(  # 定义构造 dashboard 顶部卡片和柱状图的函数。
    current_end: datetime,  # 接收 dashboard 当前周期结束时间。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> tuple[list[DashboardKpiCard], list[DashboardBarChart], dict[str, int | float]]:  # 返回顶部卡片列表、柱状图列表和快捷统计字典。
    day_points, day_labels, query_start, query_end = build_dashboard_recent_daily_context(current_end, DASHBOARD_RECENT_DAYS)  # 先构造近 N 天上下文。
    day_index_map = {day_point: index for index, day_point in enumerate(day_points)}  # 构造日期到索引映射，方便回填数组。
    energy_rows = get_dashboard_recent_energy_rows(query_start, query_end, site_id, building_id)  # 查询近 N 天能耗聚合行。
    anomaly_rows = get_dashboard_recent_anomaly_rows(query_start, query_end, site_id, building_id)  # 查询近 N 天异常聚合行。
    electricity_values = [None] * len(day_points)  # 初始化近 N 天日电耗序列，缺失日期先显式标成空值。
    cooling_values = [None] * len(day_points)  # 初始化近 N 天日制冷能耗序列，缺失日期先显式标成空值。
    electricity_statuses = [resolve_numeric_data_status(has_data=False)] * len(day_points)  # 初始化日电耗序列状态为 missing。
    cooling_statuses = [resolve_numeric_data_status(has_data=False)] * len(day_points)  # 初始化日制冷序列状态为 missing。
    for row in energy_rows:  # 遍历每一条近 N 天能耗聚合行。
        bucket_day = row.get("bucket_day")  # 读取当前行日期桶。
        meter_name = str(row.get("meter") or "")  # 读取当前行表计名称。
        if bucket_day not in day_index_map:  # 如果当前日期桶不在近 N 天窗口中，
            continue  # 就跳过当前行。
        value_index = day_index_map[bucket_day]  # 获取当前日期桶索引。
        if meter_name == "electricity":  # 如果当前行是电耗，
            electricity_values[value_index] = round((electricity_values[value_index] or 0.0) + to_float(row.get("value")), 4)  # 就累计到电耗序列；此前缺失时从 0 开始累计。
            electricity_statuses[value_index] = resolve_numeric_data_status(has_data=True)  # 当前日期命中真实电耗数据后，状态改成 valid。
        elif meter_name == "chilledwater":  # 如果当前行是制冷能耗，
            cooling_values[value_index] = round((cooling_values[value_index] or 0.0) + to_float(row.get("value")), 4)  # 就累计到制冷序列；此前缺失时从 0 开始累计。
            cooling_statuses[value_index] = resolve_numeric_data_status(has_data=True)  # 当前日期命中真实制冷数据后，状态改成 valid。
    cop_values: list[float | None] = []  # 初始化近 N 天代理 COP 序列。
    cop_statuses = []  # 初始化近 N 天代理 COP 状态序列。
    cop_notes: list[str | None] = []  # 初始化近 N 天代理 COP 说明序列。
    for electricity_value, cooling_value, electricity_state, cooling_state in zip(electricity_values, cooling_values, electricity_statuses, cooling_statuses):  # 并行遍历日电耗、制冷值和状态。
        if electricity_state != resolve_numeric_data_status(has_data=True) or cooling_state != resolve_numeric_data_status(has_data=True):  # 如果任意一方缺少真实源数据，
            cop_values.append(None)  # 就把当前日期代理 COP 显式写成空值。
            cop_statuses.append(resolve_numeric_data_status(has_data=False))  # 并把状态标记成 missing。
            cop_notes.append("当前日期未同时命中 electricity 和 chilledwater 数据。")  # 记录缺失说明。
            continue  # 继续处理下一天。
        cop_value, cop_note = calculate_proxy_cop(electricity_value, cooling_value)  # 使用 energy 的统一规则计算当天代理 COP。
        cop_values.append(cop_value)  # 写入当天代理 COP 值；如果被过滤则为空。
        cop_statuses.append(resolve_numeric_data_status(has_data=cop_value is not None, estimated=cop_value is not None, filtered=cop_value is None))  # 写入当天代理 COP 的状态。
        cop_notes.append(cop_note)  # 写入当天代理 COP 的说明文本。
    anomaly_building_values = [0] * len(day_points)  # 初始化近 N 天异常建筑数序列。
    pending_work_order_values = [0] * len(day_points)  # 初始化近 N 天待处理工单数序列。
    anomaly_event_values = [0] * len(day_points)  # 初始化近 N 天异常事件总数序列。
    for row in anomaly_rows:  # 遍历每一条近 N 天异常聚合行。
        bucket_day = row.get("bucket_day")  # 读取当前行日期桶。
        if bucket_day not in day_index_map:  # 如果当前日期桶不在近 N 天窗口中，
            continue  # 就跳过当前行。
        value_index = day_index_map[bucket_day]  # 获取当前日期桶索引。
        anomaly_building_values[value_index] = int(row.get("building_count") or 0)  # 写入当前日期的异常建筑数。
        pending_work_order_values[value_index] = int(row.get("pending_count") or 0)  # 写入当前日期的待处理工单数。
        anomaly_event_values[value_index] = int(row.get("event_count") or 0)  # 写入当前日期的异常事件总数。
    latest_index = len(day_points) - 1  # 计算最新一天索引。
    previous_index = max(latest_index - 1, 0)  # 计算前一天索引（防止越界）。
    latest_electricity = electricity_values[latest_index] if electricity_values else None  # 读取最新一天总电耗；如果缺失则返回空值。
    previous_electricity = electricity_values[previous_index] if electricity_values else None  # 读取前一天总电耗；如果缺失则返回空值。
    energy_change_rate = calculate_change_rate(latest_electricity, previous_electricity)  # 计算总电耗相对前一天变化率。
    latest_energy_data_status = electricity_statuses[latest_index] if electricity_statuses else resolve_numeric_data_status(has_data=False)  # 读取最新一天总电耗的数据状态。
    energy_status = DashboardCardStatus.warning if latest_electricity is not None and (energy_change_rate or 0.0) > 0.08 else DashboardCardStatus.good if latest_electricity is not None else DashboardCardStatus.neutral  # 根据变化幅度和缺失情况判定总电耗卡片状态。
    latest_cop = cop_values[latest_index] if cop_values else None  # 读取最新一天代理 COP。
    previous_cop = cop_values[previous_index] if cop_values else None  # 读取前一天代理 COP。
    cop_change_rate = calculate_change_rate(latest_cop, previous_cop)  # 计算 COP 相对前一天变化率。
    cop_status, cop_subtitle = resolve_cop_status(latest_cop)  # 根据最新 COP 判定状态和副标题。
    latest_cop_data_status = cop_statuses[latest_index] if cop_statuses else resolve_numeric_data_status(has_data=False)  # 读取最新一天代理 COP 的数据状态。
    latest_cop_note = cop_notes[latest_index] if cop_notes else None  # 读取最新一天代理 COP 的说明文本。
    latest_anomaly_buildings = anomaly_building_values[latest_index] if anomaly_building_values else 0  # 读取最新一天异常建筑数。
    previous_anomaly_buildings = anomaly_building_values[previous_index] if anomaly_building_values else 0  # 读取前一天异常建筑数。
    anomaly_change_rate = calculate_change_rate(float(latest_anomaly_buildings), float(previous_anomaly_buildings))  # 计算异常建筑数变化率。
    latest_pending_work_orders = pending_work_order_values[latest_index] if pending_work_order_values else 0  # 读取最新一天待处理工单数。
    previous_pending_work_orders = pending_work_order_values[previous_index] if pending_work_order_values else 0  # 读取前一天待处理工单数。
    pending_change_rate = calculate_change_rate(float(latest_pending_work_orders), float(previous_pending_work_orders))  # 计算待处理工单数变化率。
    latest_event_count = anomaly_event_values[latest_index] if anomaly_event_values else 0  # 读取最新一天异常事件总数。
    latest_processed_count = max(latest_event_count - latest_pending_work_orders, 0)  # 按“总事件 - 待处理”估算已处理数量。
    anomaly_status = DashboardCardStatus.danger if latest_anomaly_buildings >= 3 else DashboardCardStatus.warning if latest_anomaly_buildings > 0 else DashboardCardStatus.good  # 根据异常建筑数判定状态。
    work_order_status = DashboardCardStatus.danger if latest_pending_work_orders >= 5 else DashboardCardStatus.warning if latest_pending_work_orders > 0 else DashboardCardStatus.good  # 根据待处理工单数判定状态。
    average_resolution_hours = get_dashboard_average_resolution_hours(query_start, query_end, site_id, building_id)  # 查询近 N 天平均处理时长。
    if average_resolution_hours <= 0:  # 如果缺少可用处理时长数据，
        work_order_subtitle = "平均处理时长 暂无数据"  # 就返回暂无数据文案。
    elif average_resolution_hours < 2:  # 如果平均处理时长小于 2 小时，
        work_order_subtitle = "平均处理时长 <2h"  # 就返回小于 2 小时文案。
    else:  # 如果平均处理时长大于等于 2 小时，
        work_order_subtitle = f"平均处理时长 {round(average_resolution_hours, 1)}h"  # 就返回带数值的处理时长文案。
    cards = [  # 构造顶部四张 KPI 卡片。
        DashboardKpiCard(  # 构造“今日总能耗”卡片。
            key="daily_total_energy",  # 写入卡片键。
            title="今日总能耗",  # 写入卡片标题。
            value=latest_electricity,  # 写入卡片主值。
            unit="kWh",  # 写入卡片单位。
            change_rate=energy_change_rate,  # 写入卡片变化率。
            subtitle=f"同比昨日 {format_change_rate_text(energy_change_rate)}",  # 写入卡片副标题。
            status=energy_status,  # 写入卡片状态。
            mini_bar=DashboardMiniBar(labels=day_labels, values=electricity_values, data_statuses=electricity_statuses),  # 写入卡片迷你柱状图，并明确每一天的数据状态。
            data_status=latest_energy_data_status,  # 写入当前卡片的数据状态。
            data_note=None if latest_electricity is not None else "最新日期没有 electricity 数据。",  # 在缺失时补充明确说明。
        ),  # 完成“今日总能耗”卡片构造。
        DashboardKpiCard(  # 构造“实时 COP 代理值”卡片。
            key="realtime_cop",  # 写入卡片键。
            title="实时 COP 代理值",  # 写入卡片标题。
            value=latest_cop,  # 写入卡片主值。
            unit=None,  # COP 没有固定单位。
            change_rate=cop_change_rate,  # 写入卡片变化率。
            subtitle=cop_subtitle,  # 写入卡片副标题。
            status=cop_status,  # 写入卡片状态。
            mini_bar=DashboardMiniBar(labels=day_labels, values=cop_values, data_statuses=cop_statuses),  # 写入卡片迷你柱状图，并明确每一天的代理 COP 状态。
            data_status=latest_cop_data_status,  # 写入当前卡片的数据状态。
            data_note=latest_cop_note,  # 写入当前卡片的计算说明或过滤原因。
        ),  # 完成“实时 COP 代理值”卡片构造。
        DashboardKpiCard(  # 构造“异常建筑数”卡片。
            key="anomaly_buildings",  # 写入卡片键。
            title="异常建筑数",  # 写入卡片标题。
            value=float(latest_anomaly_buildings),  # 写入卡片主值。
            unit="栋",  # 写入卡片单位。
            change_rate=anomaly_change_rate,  # 写入卡片变化率。
            subtitle=f"已处理 {latest_processed_count}，待处理 {latest_pending_work_orders}",  # 写入卡片副标题。
            status=anomaly_status,  # 写入卡片状态。
            mini_bar=DashboardMiniBar(labels=day_labels, values=[float(item) for item in anomaly_building_values]),  # 写入卡片迷你柱状图。
        ),  # 完成“异常建筑数”卡片构造。
        DashboardKpiCard(  # 构造“待处理工单”卡片。
            key="pending_work_orders",  # 写入卡片键。
            title="待处理工单",  # 写入卡片标题。
            value=float(latest_pending_work_orders),  # 写入卡片主值。
            unit="单",  # 写入卡片单位。
            change_rate=pending_change_rate,  # 写入卡片变化率。
            subtitle=work_order_subtitle,  # 写入卡片副标题。
            status=work_order_status,  # 写入卡片状态。
            mini_bar=DashboardMiniBar(labels=day_labels, values=[float(item) for item in pending_work_order_values]),  # 写入卡片迷你柱状图。
        ),  # 完成“待处理工单”卡片构造。
    ]  # 完成顶部 KPI 卡片列表构造。
    bar_charts = [  # 构造 dashboard 需要的柱状图列表。
        DashboardBarChart(key="daily_total_energy", title="今日总能耗柱状图", unit="kWh", labels=day_labels, values=electricity_values, data_statuses=electricity_statuses),  # 构造总电耗柱状图，并明确每天的数据状态。
        DashboardBarChart(key="realtime_cop", title="实时 COP 代理值柱状图", unit=None, labels=day_labels, values=cop_values, data_statuses=cop_statuses),  # 构造代理 COP 柱状图，并明确每天的数据状态。
        DashboardBarChart(key="anomaly_buildings", title="异常建筑数柱状图", unit="栋", labels=day_labels, values=[float(item) for item in anomaly_building_values]),  # 构造异常建筑柱状图。
        DashboardBarChart(key="pending_work_orders", title="待处理工单柱状图", unit="单", labels=day_labels, values=[float(item) for item in pending_work_order_values]),  # 构造待处理工单柱状图。
    ]  # 完成柱状图列表构造。
    quick_link_stats = {  # 构造供快捷跳转和高亮模块复用的统计字典。
        "anomaly_building_count": int(latest_anomaly_buildings),  # 写入最新异常建筑数。
        "pending_work_order_count": int(latest_pending_work_orders),  # 写入最新待处理工单数。
        "processed_event_count": int(latest_processed_count),  # 写入最新已处理事件数。
        "average_resolution_hours": float(average_resolution_hours),  # 写入平均处理时长。
    }  # 完成快捷统计字典构造。
    return cards, bar_charts, quick_link_stats  # 返回顶部卡片、柱状图和快捷统计结果。


def build_building_diagnostics(  # 定义构造楼栋级诊断结果的函数。
    period_rows: list[dict[str, Any]],  # 接收按建筑聚合后的双周期结果列表。
) -> list[dict[str, Any]]:  # 返回包含异常判定信息的中间结果列表。
    diagnostics: list[dict[str, Any]] = []  # 初始化楼栋诊断结果列表。
    active_rows = [row for row in period_rows if int(row.get("current_count") or 0) > 0]  # 先筛出当前周期真实命中过电耗读数的建筑，避免把真实 0 误判成缺失。
    active_eui_values = [safe_divide(to_float(row.get("current_total")), to_float(row.get("sqm"))) for row in active_rows if to_float(row.get("sqm")) > 0]  # 计算所有活跃建筑的当前周期 EUI 列表。
    peer_average_eui = safe_divide(sum(active_eui_values), float(len(active_eui_values))) if active_eui_values else 0.0  # 计算当前范围的平均 EUI，作为多建筑场景的同群基线。
    usage_eui_map: dict[str, list[float]] = {}  # 初始化按建筑用途分组保存 EUI 的映射字典。
    for row in active_rows:  # 遍历所有活跃建筑，准备计算分用途的 EUI 基线。
        usage_key = str(row.get("primaryspaceusage") or "Unknown")  # 读取当前建筑的主要用途并转成稳定文本键。
        current_total = to_float(row.get("current_total"))  # 读取当前建筑的当前周期总电耗。
        sqm_value = to_float(row.get("sqm"))  # 读取当前建筑的面积。
        current_eui = safe_divide(current_total, sqm_value)  # 计算当前建筑的 EUI。
        if current_eui <= 0:  # 如果当前建筑没有有效 EUI，
            continue  # 就跳过当前建筑，避免把无效值混入用途基线。
        usage_eui_map.setdefault(usage_key, []).append(current_eui)  # 把当前建筑的 EUI 加入对应用途的列表。
    usage_average_map = {usage_key: safe_divide(sum(values), float(len(values))) for usage_key, values in usage_eui_map.items() if values}  # 计算每种建筑用途下的平均 EUI。
    single_scope_mode = len(active_rows) <= 1  # 判断当前范围是否更接近单建筑分析场景。
    for row in period_rows:  # 遍历每一栋建筑的聚合结果。
        current_count = int(row.get("current_count") or 0)  # 读取当前周期真实命中的电耗读数条数。
        previous_count = int(row.get("previous_count") or 0)  # 读取上一周期真实命中的电耗读数条数。
        current_total = to_float(row.get("current_total"))  # 读取当前周期总电耗。
        previous_total = to_float(row.get("previous_total"))  # 读取上一周期总电耗。
        sqm_value = to_float(row.get("sqm"))  # 读取建筑面积。
        current_eui = safe_divide(current_total, sqm_value)  # 计算当前周期 EUI。
        previous_eui = safe_divide(previous_total, sqm_value)  # 计算上一周期 EUI。
        usage_key = str(row.get("primaryspaceusage") or "Unknown")  # 读取当前建筑的主要用途，方便优先按同用途比较。
        usage_average_eui = usage_average_map.get(usage_key, 0.0)  # 读取当前用途的平均 EUI，查不到时回退到零。
        comparison_baseline_eui = usage_average_eui or peer_average_eui  # 优先使用同用途均值作为基线，查不到时再回退到全范围均值。
        is_high_energy = False  # 先默认当前建筑不属于高能耗建筑。
        deviation_rate = 0.0  # 先默认偏离率为零。
        anomaly_title = ""  # 先初始化异常标题为空字符串。
        if current_count > 0 and single_scope_mode and previous_count > 0:  # 如果当前是单建筑场景且前后两个周期都真实命中过数据，
            deviation_rate = max(calculate_change_rate(current_eui or current_total, previous_eui or previous_total) or 0.0, 0.0)  # 就按同建筑前后周期变化率做异常偏离率。
            is_high_energy = deviation_rate >= (DASHBOARD_HIGH_ENERGY_MULTIPLIER - 1)  # 如果增长超过约定阈值，就标记为高能耗。
            if is_high_energy:  # 如果该建筑确实触发了高能耗判定，
                anomaly_title = f"{row['building_id']} 电耗较上一周期上升 {round(deviation_rate * 100, 2)}%"  # 生成单建筑场景下的异常标题。
        elif current_count > 0 and current_eui > 0 and comparison_baseline_eui > 0:  # 如果是多建筑场景且当前周期真实有数据并能拿到有效 EUI 基线，
            deviation_rate = max((current_eui - comparison_baseline_eui) / comparison_baseline_eui, 0.0)  # 就按当前 EUI 相对基线的偏离率做判定。
            is_high_energy = current_eui >= round(comparison_baseline_eui * DASHBOARD_HIGH_ENERGY_MULTIPLIER, 4)  # 如果当前 EUI 超过基线阈值倍数，就标记为高能耗。
            if is_high_energy:  # 如果该建筑确实触发了高能耗判定，
                baseline_label = "同用途均值" if usage_average_eui > 0 else "同范围均值"  # 根据基线来源生成更清晰的标题文本。
                anomaly_title = f"{row['building_id']} 电耗EUI高于{baseline_label} {round(deviation_rate * 100, 2)}%"  # 生成多建筑场景下的异常标题。
        diagnostics.append(  # 把当前建筑的诊断结果写入列表。
            {
                "building_id": str(row["building_id"]),  # 写入建筑编号。
                "site_id": str(row["site_id"]),  # 写入站点编号。
                "primaryspaceusage": str(row.get("primaryspaceusage") or "Unknown"),  # 写入建筑主要用途。
                "sqm": sqm_value,  # 写入建筑面积。
                "current_count": current_count,  # 写入当前周期真实命中的读数条数。
                "previous_count": previous_count,  # 写入上一周期真实命中的读数条数。
                "current_total": current_total,  # 写入当前周期总电耗。
                "previous_total": previous_total,  # 写入上一周期总电耗。
                "current_eui": current_eui,  # 写入当前周期 EUI。
                "previous_eui": previous_eui,  # 写入上一周期 EUI。
                "latest_timestamp": row.get("latest_timestamp"),  # 写入当前周期最新采样时间。
                "peer_average_eui": peer_average_eui,  # 写入当前范围的平均 EUI。
                "usage_average_eui": usage_average_eui,  # 写入当前用途的平均 EUI。
                "deviation_rate": round(deviation_rate, 4),  # 写入异常偏离率。
                "is_high_energy": is_high_energy,  # 写入当前建筑是否属于高能耗建筑。
                "severity": classify_anomaly_severity(deviation_rate) if is_high_energy else "info",  # 写入严重级别。
                "anomaly_title": anomaly_title,  # 写入异常标题。
            }
        )  # 完成当前建筑诊断结果追加。
    diagnostics.sort(key=lambda item: (item["is_high_energy"], item["deviation_rate"], item["current_total"]), reverse=True)  # 按是否高能耗、偏离率和总电耗对诊断结果排序。
    return diagnostics  # 返回完整楼栋诊断结果列表。


def get_dashboard_latest_timestamps_for_buildings(  # 定义按建筑批量查询当前周期最新采样时间的函数。
    current_start: datetime,  # 接收当前周期开始时间。
    current_end: datetime,  # 接收当前周期结束时间。
    building_ids: list[str],  # 接收需要查询的建筑编号列表。
) -> dict[str, datetime]:  # 返回建筑编号到最新时间的映射。
    safe_building_ids = sorted({str(item).strip() for item in building_ids if str(item).strip()})  # 标准化建筑编号列表，避免重复查询。
    if not safe_building_ids:  # 如果没有可查询建筑编号，
        return {}  # 就返回空映射。
    building_clause, building_params = build_in_clause("mr.building_id", safe_building_ids, "latest_building")  # 构造建筑 IN 条件。
    rows = fetch_all(  # 查询建筑范围内当前周期最新时间。
        f"""
        SELECT
            mr.building_id AS building_id,
            MAX(mr.timestamp) AS latest_timestamp
        FROM meter_readings mr
        WHERE mr.meter = :dashboard_meter
          AND mr.timestamp >= :current_start
          AND mr.timestamp <= :current_end
          AND {building_clause}
        GROUP BY mr.building_id
        """,
        {
            "dashboard_meter": DEFAULT_DASHBOARD_METER,
            "current_start": current_start,
            "current_end": current_end,
            **building_params,
        },
    )  # 执行按建筑最新时间查询。
    return {str(row["building_id"]): row.get("latest_timestamp") for row in rows if row.get("building_id")}  # 返回建筑编号到最新时间的映射。


def attach_latest_timestamps_for_top_anomalies(  # 定义给高能耗候选建筑补最新时间的函数。
    diagnostics: list[dict[str, Any]],  # 接收楼栋诊断结果列表。
    current_start: datetime,  # 接收当前周期开始时间。
    current_end: datetime,  # 接收当前周期结束时间。
    limit: int = DASHBOARD_ANOMALY_LIMIT,  # 接收需要补时间的高能耗建筑数量上限。
) -> None:  # 原地修改 diagnostics，无返回值。
    target_buildings: list[str] = []  # 初始化待查询最新时间的建筑列表。
    for item in diagnostics:  # 遍历已排序诊断结果。
        if not item.get("is_high_energy"):  # 只给高能耗候选建筑补最新时间。
            continue  # 非高能耗对象直接跳过。
        target_buildings.append(str(item.get("building_id") or ""))  # 记录当前目标建筑编号。
        if len(target_buildings) >= limit:  # 到达上限后提前结束，避免无效查询。
            break
    if not target_buildings:  # 如果没有需要补充的建筑，
        return  # 直接返回。
    latest_map = get_dashboard_latest_timestamps_for_buildings(current_start, current_end, target_buildings)  # 查询目标建筑的最新时间映射。
    if not latest_map:  # 如果查询结果为空，
        return  # 就直接返回。
    for item in diagnostics:  # 遍历诊断结果并回填最新时间。
        building_key = str(item.get("building_id") or "")  # 读取建筑键。
        if building_key in latest_map:  # 如果该建筑命中了最新时间结果，
            item["latest_timestamp"] = latest_map[building_key]  # 就把最新时间回填到诊断结果中。


def build_dashboard_metrics(  # 定义构造 dashboard 指标卡片列表的函数。
    scope_rows: list[dict[str, Any]],  # 接收 dashboard 范围内建筑清单。
    diagnostics: list[dict[str, Any]],  # 接收楼栋诊断结果列表。
) -> list[MetricCard]:  # 返回 dashboard 指标卡片列表。
    scoped_building_count = len(scope_rows)  # 统计当前范围内的建筑总数。
    scoped_site_count = len({str(row["site_id"]) for row in scope_rows})  # 统计当前范围覆盖的站点数量。
    current_active_buildings = [item for item in diagnostics if item["current_count"] > 0]  # 取出当前周期真实命中过电耗读数的建筑列表。
    previous_active_buildings = [item for item in diagnostics if item["previous_count"] > 0]  # 取出上一周期真实命中过电耗读数的建筑列表。
    current_total = round(sum(item["current_total"] for item in current_active_buildings), 4)  # 只汇总当前周期真实有数据的建筑总电耗，避免把缺失值混进统计。
    previous_total = round(sum(item["previous_total"] for item in previous_active_buildings), 4)  # 只汇总上一周期真实有数据的建筑总电耗。
    current_active_area = round(sum(item["sqm"] for item in current_active_buildings if item["sqm"] > 0), 4)  # 计算当前周期活跃建筑总面积。
    previous_active_area = round(sum(item["sqm"] for item in previous_active_buildings if item["sqm"] > 0), 4)  # 计算上一周期活跃建筑总面积。
    current_eui = safe_divide(current_total, current_active_area)  # 计算当前周期电耗 EUI。
    previous_eui = safe_divide(previous_total, previous_active_area)  # 计算上一周期电耗 EUI。
    current_carbon = round(current_total * CARBON_FACTOR_KG_PER_KWH, 4)  # 计算当前周期估算碳排。
    previous_carbon = round(previous_total * CARBON_FACTOR_KG_PER_KWH, 4)  # 计算上一周期估算碳排。
    high_energy_count = len([item for item in diagnostics if item["is_high_energy"]])  # 统计当前范围内被判定为高能耗的建筑数量。
    return [  # 按固定顺序返回 dashboard 指标卡片列表。
        MetricCard(key="scoped_buildings", label="纳管建筑数", value=float(scoped_building_count), unit="count"),  # 返回纳管建筑数卡片。
        MetricCard(key="scoped_sites", label="覆盖站点数", value=float(scoped_site_count), unit="count"),  # 返回覆盖站点数卡片。
        MetricCard(key="active_buildings", label="本期活跃建筑", value=float(len(current_active_buildings)), unit="count", change_rate=calculate_change_rate(float(len(current_active_buildings)), float(len(previous_active_buildings)))),  # 返回活跃建筑数卡片。
        MetricCard(key="electricity_total", label="本期总电耗", value=current_total if current_active_buildings else None, unit="kWh", change_rate=calculate_change_rate(current_total if current_active_buildings else None, previous_total if previous_active_buildings else None), data_status=resolve_numeric_data_status(has_data=bool(current_active_buildings)), data_note=None if current_active_buildings else "当前筛选范围内没有命中的 electricity 数据。"),  # 返回总电耗卡片，并明确区分缺失与真实零值。
        MetricCard(key="electricity_eui", label="本期电耗EUI", value=current_eui if current_active_area > 0 else None, unit="kWh/sqm", change_rate=calculate_change_rate(current_eui if current_active_area > 0 else None, previous_eui if previous_active_area > 0 else None), data_status=resolve_numeric_data_status(has_data=current_active_area > 0), data_note=None if current_active_area > 0 else "当前筛选范围缺少有效面积或 electricity 数据，无法计算 EUI。"),  # 返回电耗 EUI 卡片，并明确区分缺失与真实零值。
        MetricCard(key="estimated_carbon", label="估算碳排", value=current_carbon if current_active_buildings else None, unit="kgCO2e", change_rate=calculate_change_rate(current_carbon if current_active_buildings else None, previous_carbon if previous_active_buildings else None), data_status=resolve_numeric_data_status(has_data=bool(current_active_buildings), estimated=bool(current_active_buildings)), data_note=None if current_active_buildings else "当前筛选范围内没有命中的 electricity 数据，无法估算碳排。"),  # 返回估算碳排卡片，并明确区分缺失与真实零值。
        MetricCard(key="high_energy_buildings", label="高能耗建筑数", value=float(high_energy_count), unit="count"),  # 返回高能耗建筑数卡片。
    ]  # 完成指标卡片列表构造。


def build_dashboard_anomalies(  # 定义构造 dashboard 异常摘要列表的函数。
    diagnostics: list[dict[str, Any]],  # 接收楼栋诊断结果列表。
    limit: int = DASHBOARD_ANOMALY_LIMIT,  # 接收异常摘要条数上限。
) -> list[AnomalySummary]:  # 返回 dashboard 异常摘要模型列表。
    anomaly_items: list[AnomalySummary] = []  # 初始化异常摘要结果列表。
    for item in diagnostics:  # 遍历已经排序好的楼栋诊断结果。
        if not item["is_high_energy"]:  # 如果当前建筑没有触发高能耗判定，
            continue  # 就跳过当前建筑。
        latest_timestamp = require_api_datetime(item["latest_timestamp"]) if item["latest_timestamp"] else None  # 把当前建筑的最新数据时间转成接口输出时间。
        anomaly_items.append(  # 把当前建筑转换成 dashboard 异常摘要对象。
            AnomalySummary(  # 创建异常摘要模型。
                anomaly_id=f"derived-{item['building_id']}-{DEFAULT_DASHBOARD_METER}",  # 生成演示版规则异常编号。
                building_id=item["building_id"],  # 写入建筑编号字段。
                device_id=None,  # 当前项目没有真实设备案件主键，这里返回空值。
                meter=DEFAULT_DASHBOARD_METER,  # 写入默认表计类型字段。
                severity=item["severity"],  # 写入严重等级字段。
                status="derived_open",  # 标记当前异常是规则派生、未落案件表的开放状态。
                title=item["anomaly_title"],  # 写入异常标题字段。
                start_time=latest_timestamp or require_api_datetime(datetime.now()),  # 写入异常识别时间字段。
            )  # 完成异常摘要对象创建。
        )  # 完成当前异常摘要追加。
        if len(anomaly_items) >= limit:  # 如果已经达到条数上限，
            break  # 就提前结束遍历。
    return anomaly_items  # 返回最终异常摘要列表。


def build_ai_summary_hint(  # 定义构造 dashboard 规则摘要提示的函数。
    diagnostics: list[dict[str, Any]],  # 接收楼栋诊断结果列表。
    anomalies: list[AnomalySummary],  # 接收异常摘要列表。
    current_end: datetime,  # 接收当前周期结束时间。
) -> str:  # 返回给前端展示的规则摘要提示文本。
    active_building_count = len([item for item in diagnostics if item["current_count"] > 0])  # 统计当前周期真实命中过电耗读数的活跃建筑数量。
    latest_time_text = require_api_datetime(current_end).strftime("%Y-%m-%d %H:%M:%S %z")  # 把当前周期结束时间格式化成明确日期文本。
    if anomalies:  # 如果当前已经识别出高能耗异常，
        top_anomaly = anomalies[0]  # 取排序最靠前的一条异常作为摘要核心对象。
        return f"当前 dashboard 默认基于 electricity 统计，数据最新时间为 {latest_time_text}；本期共有 {active_building_count} 栋活跃建筑，其中 {top_anomaly.building_id} 的规则异常最突出。异常列表为规则派生结果，不代表已建案件。"  # 返回包含明确日期和限制说明的摘要文本。
    return f"当前 dashboard 默认基于 electricity 统计，数据最新时间为 {latest_time_text}；本期共有 {active_building_count} 栋活跃建筑，暂未识别出明显高能耗建筑。异常列表为规则派生结果，不代表已建案件。"  # 如果没有异常，就返回无异常版本的摘要文本。


def build_dashboard_snapshot(  # 定义构造 dashboard 快照的函数。
    start_time: datetime | str | None,  # 接收开始时间参数。
    end_time: datetime | str | None,  # 接收结束时间参数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    chart_range: DashboardChartRange | str | None,  # 接收图表范围参数。
) -> dict[str, Any]:  # 返回 dashboard 快照字典。
    scope_rows = get_dashboard_scope_rows(site_id, building_id)  # 先查询当前 dashboard 统计范围内的建筑清单。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id] if building_id else None, site_id, DEFAULT_DASHBOARD_METER)  # 按电耗口径补齐当前 dashboard 时间范围。
    current_start, current_end, previous_start, previous_end = normalize_dashboard_window(resolved_start, resolved_end)  # 构造当前周期和上一周期时间范围。
    normalized_chart_range = normalize_dashboard_chart_range(chart_range)  # 标准化图表范围参数。
    _, _, recent_start, recent_end = build_dashboard_recent_daily_context(current_end, DASHBOARD_RECENT_DAYS)  # 先取顶部 KPI 近 N 天窗口，供聚合预热复用。
    _, _, trend_start, trend_end, trend_bucket_granularity = build_dashboard_trend_context(current_end, normalized_chart_range)  # 取折线图窗口与粒度，供聚合预热复用。
    agg_meters = {"electricity", "chilledwater"}  # 初始化需要预热的 meter 集合。
    agg_start_candidates = [previous_start, recent_start]  # 初始化聚合预热开始时间候选列表。
    agg_end_candidates = [current_end, recent_end - timedelta(microseconds=1)]  # 初始化聚合预热结束时间候选列表。
    if trend_bucket_granularity == "day":  # 只有周/月视图会走日聚合。
        agg_meters.add("lighting")  # 趋势图需要照明能耗序列。
        agg_start_candidates.append(trend_start)  # 把趋势窗口起点加入预热范围。
        agg_end_candidates.append(trend_end - timedelta(microseconds=1))  # 把趋势窗口终点（闭区间）加入预热范围。
    ensure_meter_daily_agg_window(min(agg_start_candidates), max(agg_end_candidates), sorted(agg_meters))  # 一次性预热 dashboard 本次请求所需的日聚合窗口。
    period_rows = get_dashboard_period_rows(current_start, current_end, previous_start, previous_end, site_id, building_id)  # 查询双周期聚合结果。
    diagnostics = build_building_diagnostics(period_rows)  # 基于双周期结果构造楼栋诊断列表。
    attach_latest_timestamps_for_top_anomalies(diagnostics, current_start, current_end)  # 仅给高能耗候选建筑补最新时间，避免全量 MAX(timestamp)。
    anomalies = build_dashboard_anomalies(diagnostics)  # 基于诊断结果构造异常摘要列表。
    metrics = build_dashboard_metrics(scope_rows, diagnostics)  # 基于范围和诊断结果构造指标卡片列表。
    metrics_by_key = {metric.key: metric for metric in metrics}  # 把指标卡片整理成按 key 查询的映射。
    kpi_cards, bar_charts, quick_link_stats = build_dashboard_kpi_cards_and_bars(current_end, site_id, building_id)  # 构造顶部 KPI 卡片、柱状图和快捷统计信息。
    quick_link_stats["warning_count"] = int(round((metrics_by_key.get("high_energy_buildings").value if metrics_by_key.get("high_energy_buildings") else 0)))  # 把高能耗预警数量写入快捷统计信息。
    trend_chart = build_dashboard_trend_chart(current_end, site_id, building_id, normalized_chart_range)  # 构造折线图数据。
    ai_summary_hint = build_ai_summary_hint(diagnostics, anomalies, current_end)  # 基于诊断结果和时间范围构造规则摘要文本。
    return {  # 返回 dashboard 快照字典。
        "time_range": build_api_time_range(current_start, current_end),  # 写入带时区的当前周期时间范围。
        "metrics": metrics,  # 写入指标卡片列表。
        "kpi_cards": kpi_cards,  # 写入顶部 KPI 卡片列表。
        "trend_chart": trend_chart,  # 写入折线图数据。
        "bar_charts": bar_charts,  # 写入柱状图列表。
        "quick_link_stats": quick_link_stats,  # 写入快捷跳转统计信息。
        "diagnostics": diagnostics,  # 写入楼栋诊断结果列表，供 highlights 继续复用。
        "top_anomalies": anomalies,  # 写入异常摘要列表。
        "ai_summary_hint": ai_summary_hint,  # 写入规则摘要文本。
    }  # 完成 dashboard 快照构造。


def get_dashboard_overview(  # 定义 dashboard 总览接口业务函数。
    start_time: datetime | str | None,  # 接收开始时间参数。
    end_time: datetime | str | None,  # 接收结束时间参数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    chart_range: DashboardChartRange | str | None,  # 接收图表范围参数。
) -> DashboardOverviewResponse:  # 返回 dashboard 总览响应模型。
    snapshot = build_dashboard_snapshot(start_time, end_time, site_id, building_id, chart_range)  # 先构造完整 dashboard 快照。
    quick_links = build_dashboard_highlight_items(snapshot, DASHBOARD_DEFAULT_LIMIT, snapshot.get("quick_link_stats"))  # 基于快照构造右侧快捷跳转列表。
    return DashboardOverviewResponse(  # 基于快照构造总览响应对象。
        time_range=snapshot["time_range"],  # 写入时间范围字段。
        metrics=snapshot["metrics"],  # 写入指标卡片列表字段。
        kpi_cards=snapshot["kpi_cards"],  # 写入顶部 KPI 卡片列表字段。
        trend_chart=snapshot["trend_chart"],  # 写入折线图字段。
        bar_charts=snapshot["bar_charts"],  # 写入柱状图列表字段。
        quick_links=quick_links,  # 写入右侧快捷跳转列表字段。
        top_anomalies=snapshot["top_anomalies"],  # 写入顶部异常列表字段。
        ai_summary_hint=snapshot["ai_summary_hint"],  # 写入规则摘要提示字段。
    )  # 完成 dashboard 总览响应构造。


def build_dashboard_highlight_items(  # 定义构造 dashboard 高亮项列表的函数。
    snapshot: dict[str, Any],  # 接收 dashboard 快照字典。
    limit: int,  # 接收高亮项条数上限。
    quick_link_stats: dict[str, int | float] | None = None,  # 接收快捷跳转统计信息。
) -> list[DashboardHighlight]:  # 返回高亮项模型列表。
    items: list[DashboardHighlight] = []  # 初始化高亮项列表。
    metrics_by_key = {metric.key: metric for metric in snapshot["metrics"]}  # 先把指标卡片整理成按 key 查询的映射。
    top_anomalies: list[AnomalySummary] = snapshot["top_anomalies"]  # 取出异常摘要列表，方便下面复用。
    diagnostics: list[dict[str, Any]] = snapshot["diagnostics"]  # 取出楼栋诊断结果，方便继续生成洞察和建议。
    safe_stats = quick_link_stats or {}  # 把快捷统计信息兜底成字典，避免空值分支复杂化。
    anomaly_count = int(safe_stats.get("anomaly_building_count") or len(top_anomalies))  # 读取异常建筑数量。
    pending_count = int(safe_stats.get("pending_work_order_count") or 0)  # 读取待处理工单数量。
    warning_count = int(safe_stats.get("warning_count") or 0)  # 读取高能耗预警数量。
    processed_count = int(safe_stats.get("processed_event_count") or 0)  # 读取已处理事件数量。
    if top_anomalies:  # 如果存在异常摘要，
        top_anomaly = top_anomalies[0]  # 就取第一条异常作为首条快捷跳转。
        items.append(  # 追加异常型高亮项。
            DashboardHighlight(  # 创建异常型高亮对象。
                type=DashboardHighlightType.anomaly,  # 写入高亮类型为 anomaly。
                title="异常状态工单",  # 写入异常卡片标题。
                description=f"{anomaly_count} 个异常建筑待关注，最突出对象为 {top_anomaly.building_id}。",  # 写入异常卡片描述。
                target="/energy/anomaly-analysis",  # 写入推荐跳转目标。
                target_id=top_anomaly.building_id,  # 写入推荐跳转建筑编号。
                level=DashboardQuickLinkLevel.critical,  # 写入异常卡片等级。
                count=anomaly_count,  # 写入异常卡片数量。
            )  # 完成异常型高亮对象创建。
        )  # 完成异常型高亮追加。
    total_metric = metrics_by_key.get("electricity_total")  # 读取总电耗指标卡片。
    if total_metric is not None:  # 如果能成功取到总电耗指标，
        change_rate = total_metric.change_rate or 0.0  # 读取总电耗环比变化率，没有值时回退到零。
        trend_word = "上升" if change_rate > 0 else "下降" if change_rate < 0 else "持平"  # 根据变化率生成趋势文本。
        items.append(  # 追加洞察型高亮项。
            DashboardHighlight(  # 创建洞察型高亮对象。
                type=DashboardHighlightType.insight,  # 写入高亮类型为 insight。
                title="警告状态",  # 写入洞察卡片标题。
                description=f"当前范围总电耗较上一周期{trend_word}，共有 {warning_count} 个高能耗预警对象。",  # 写入洞察卡片描述。
                target="/dashboard/overview",  # 写入建议返回总览页的目标。
                target_id=None,  # 当前洞察不绑定特定建筑编号。
                level=DashboardQuickLinkLevel.warning if warning_count > 0 else DashboardQuickLinkLevel.info,  # 根据预警数量判定洞察卡片等级。
                count=warning_count,  # 写入洞察卡片数量。
            )  # 完成洞察型高亮对象创建。
        )  # 完成洞察型高亮追加。
    high_energy_items = [item for item in diagnostics if item["is_high_energy"]]  # 取出所有高能耗建筑结果，方便生成任务建议项。
    if high_energy_items or pending_count > 0:  # 如果存在高能耗对象或待处理工单，
        focus_item = high_energy_items[0] if high_energy_items else None  # 优先取第一栋高能耗建筑作为推荐处理对象。
        focus_building_id = focus_item["building_id"] if focus_item else None  # 读取推荐处理建筑编号。
        items.append(  # 追加任务建议型高亮项。
            DashboardHighlight(  # 创建任务型高亮对象。
                type=DashboardHighlightType.task,  # 写入高亮类型为 task。
                title="待处理工单",  # 写入任务卡片标题。
                description=f"{pending_count} 个事件待处理，已处理 {processed_count} 个事件。",  # 写入任务卡片描述。
                target="/meters",  # 写入推荐跳转目标。
                target_id=focus_building_id,  # 写入推荐处理建筑编号（可空）。
                level=DashboardQuickLinkLevel.warning if pending_count > 0 else DashboardQuickLinkLevel.info,  # 根据待处理数量判定任务卡片等级。
                count=pending_count,  # 写入任务卡片数量。
            )  # 完成任务型高亮对象创建。
        )  # 完成任务型高亮追加。
    if not items:  # 如果前面的逻辑没有生成任何高亮项，
        items.append(  # 就补一条兜底的洞察项。
            DashboardHighlight(  # 创建兜底洞察项对象。
                type=DashboardHighlightType.insight,  # 写入高亮类型为 insight。
                title="当前范围暂无显著异常",  # 写入兜底标题。
                description="默认 dashboard 规则未识别出明显高能耗建筑，可以继续查看趋势图和排行结果。",  # 写入兜底描述。
                target="/dashboard/overview",  # 写入兜底跳转目标。
                target_id=None,  # 兜底高亮不绑定具体编号。
                level=DashboardQuickLinkLevel.info,  # 写入兜底卡片等级。
                count=0,  # 写入兜底卡片数量。
            )  # 完成兜底洞察项对象创建。
        )  # 完成兜底洞察项追加。
    return items[:limit]  # 按条数上限截断并返回高亮项列表。


def get_dashboard_highlights(  # 定义 dashboard 高亮接口业务函数。
    limit: int | None,  # 接收高亮条数参数。
    start_time: datetime | str | None,  # 接收开始时间参数。
    end_time: datetime | str | None,  # 接收结束时间参数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
    chart_range: DashboardChartRange | str | None,  # 接收图表范围参数。
) -> DashboardHighlightsResponse:  # 返回 dashboard 高亮响应模型。
    safe_limit = max(1, min(limit or DASHBOARD_DEFAULT_LIMIT, 10))  # 给高亮条数做默认值和范围保护。
    snapshot = build_dashboard_snapshot(start_time, end_time, site_id, building_id, chart_range)  # 按当前过滤范围构造 dashboard 快照。
    return DashboardHighlightsResponse(items=build_dashboard_highlight_items(snapshot, safe_limit, snapshot.get("quick_link_stats")))  # 构造并返回高亮列表响应。
