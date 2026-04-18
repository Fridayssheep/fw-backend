from datetime import datetime  # 导入日期时间类型，方便做类型标注。
from datetime import timedelta  # 导入时间差类型，方便做统计窗口计算。
from typing import Any  # 导入任意类型注解，方便描述松散结构。

from app.core.database import fetch_all  # 导入多行查询函数。
from app.core.database import fetch_one  # 导入单行查询函数。
from app.core.database import fetch_scalar  # 导入单值查询函数。
from app.schemas.schemas_buildings import Building  # 导入建筑基础信息模型。
from app.schemas.schemas_buildings import BuildingDetailResponse  # 导入建筑详情响应模型。
from app.schemas.schemas_buildings import BuildingListResponse  # 导入建筑列表响应模型。
from app.schemas.schemas_buildings import MeterAvailability  # 导入表计可用性模型。
from app.schemas.schemas_common import MetricCard  # 导入指标卡片模型。
from app.schemas.schemas_common import Pagination  # 导入分页模型。
from app.schemas.schemas_energy import EnergySummaryResponse  # 导入建筑级能耗摘要响应模型。
from .service_common import METER_UNIT_MAP  # 导入标准表计单位映射表。
from .service_common import ResourceNotFoundError  # 导入资源不存在异常。
from .service_common import build_api_time_range  # 导入构造接口时间范围对象的函数。
from .service_common import get_latest_timestamp  # 导入获取最新时间的函数。
from .service_common import get_meter_unit  # 导入获取表计单位的函数。
from .service_common import normalize_granularity  # 导入标准化粒度的函数。
from .service_common import normalize_metadata_flag  # 导入标准化元数据表计标记的函数。
from .service_common import normalize_meter  # 导入标准化表计类型的函数。
from .service_common import normalize_optional_float  # 导入标准化浮点数的函数。
from .service_common import normalize_optional_int  # 导入标准化整数的函数。
from .service_common import normalize_pagination  # 导入标准化分页参数的函数。
from .service_common import normalize_text  # 导入标准化文本的函数。
from .service_common import resolve_numeric_data_status  # 导入统一数据状态判定函数，方便区分缺失值和真实零值。
from .service_common import resolve_time_range  # 导入补齐时间范围的函数。
from .service_common import round_optional_float  # 导入可空数值四舍五入函数，避免把缺失值误写成 0。
from .services_energy import build_summary  # 导入能耗摘要构造函数。


DEFAULT_WINDOW_DAYS = 7  # 定义指标卡片默认统计窗口天数。
DEFAULT_METER_PRIORITY = ["electricity", "chilledwater", "hotwater", "steam", "water", "gas", "solar", "irrigation"]  # 定义默认优先展示的表计顺序。
CARBON_FACTOR = 0.554  # 统一碳排放因子

def map_building_row_to_model(row: dict[str, Any]) -> Building:  # 定义把建筑查询结果映射成建筑模型的函数。
    return Building(  # 返回建筑基础信息模型。
        building_id=str(row["building_id"]),  # 写入建筑编号字段。
        site_id=str(row.get("site_id") or ""),  # 写入园区编号字段。
        primaryspaceusage=str(row.get("primaryspaceusage") or "Unknown"),  # 写入主要用途字段。
        sub_primaryspaceusage=normalize_text(row.get("sub_primaryspaceusage")),  # 写入次级用途字段。
        sqm=normalize_optional_float(row.get("sqm")),  # 写入建筑面积字段。
        lat=normalize_optional_float(row.get("lat")),  # 写入纬度字段。
        lng=normalize_optional_float(row.get("lng")),  # 写入经度字段。
        timezone=normalize_text(row.get("timezone")),  # 写入时区字段。
        yearbuilt=normalize_optional_int(row.get("yearbuilt")),  # 写入建成年份字段。
        leed_level=normalize_text(row.get("leed_level")),  # 写入 LEED 等级字段。
        # --- 新增：动态计算字段映射 ---
        energy=round_optional_float(row.get("energy")),
        eui=round_optional_float(row.get("eui")),
        carbon=round_optional_float(row.get("carbon")),
        meter_count=int(row.get("meter_count") or 0),
        status=normalize_text(row.get("status")),
        status_text=normalize_text(row.get("status_text")),
    )  # 完成建筑模型构造。


def build_building_filters(  # 定义构造建筑列表过滤条件的函数。
    keyword: str | None,  # 接收关键字参数。
    site_id: str | None,  # 接收园区编号参数。
    primaryspaceusage: str | None,  # 接收主要用途参数。
) -> tuple[str, dict[str, Any]]:  # 返回 where 条件和参数字典。
    clauses: list[str] = ["1=1"]  # 先放一个恒成立条件，方便统一拼接。
    params: dict[str, Any] = {}  # 初始化查询参数字典。
    normalized_keyword = normalize_text(keyword)  # 标准化关键字参数。
    if normalized_keyword:  # 如果前端传了关键字，
        clauses.append("(bm.building_id ILIKE :keyword OR bm.site_id ILIKE :keyword OR bm.primaryspaceusage ILIKE :keyword OR COALESCE(bm.sub_primaryspaceusage, '') ILIKE :keyword)")  # 就把多个文本字段都纳入模糊搜索。
        params["keyword"] = f"%{normalized_keyword}%"  # 生成 ILIKE 模糊搜索所需的参数。
    normalized_site_id = normalize_text(site_id)  # 标准化园区编号参数。
    if normalized_site_id:  # 如果前端传了园区编号，
        clauses.append("bm.site_id = :site_id")  # 就增加园区过滤条件。
        params["site_id"] = normalized_site_id  # 写入园区参数。
    normalized_usage = normalize_text(primaryspaceusage)  # 标准化主要用途参数。
    if normalized_usage:  # 如果前端传了主要用途，
        clauses.append("bm.primaryspaceusage ILIKE :primaryspaceusage")  # 就增加用途过滤条件。
        params["primaryspaceusage"] = normalized_usage  # 写入用途参数。
    return " AND ".join(clauses), params  # 返回完整 where 条件和参数字典。


def get_buildings(  # 定义建筑列表查询接口业务函数。
    keyword: str | None,
    site_id: str | None,
    primaryspaceusage: str | None,
    min_energy: float | None,
    max_energy: float | None,
    min_eui: float | None,
    max_eui: float | None,
    min_carbon: float | None,
    max_carbon: float | None,
    status: str | None,
    start_time: str | None,
    end_time: str | None,
    page: int,
    page_size: int,
) -> BuildingListResponse:  # 返回建筑列表响应模型。
    # 1. 确定时间范围（用于能耗聚合）
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, [], None, 'electricity')
    
    # 2. 构造基础过滤条件
    where_sql, params = build_building_filters(keyword, site_id, primaryspaceusage)
    normalized_status = normalize_text(status)
    if normalized_status:
        normalized_status = normalized_status.lower()
    if normalized_status not in {"normal", "warning", "fault", "offline"}:
        normalized_status = None
    
    # 3. 准备 SQL 参数
    params.update({
        "start_time": resolved_start,
        "end_time": resolved_end,
        "min_energy": min_energy if min_energy is not None else None,
        "max_energy": max_energy if max_energy is not None else None,
        "min_eui": min_eui if min_eui is not None else None,
        "max_eui": max_eui if max_eui is not None else None,
        "min_carbon": min_carbon if min_carbon is not None else None,
        "max_carbon": max_carbon if max_carbon is not None else None,
        "status": normalized_status,
    })

    # 4. 编写带聚合筛选的 SQL。这里直接按请求时间窗读取明细表，避免依赖 dashboard 才会刷新的日聚合表。
    sql_base = f"""
        WITH aggregated_energy AS (
            SELECT 
                mr.building_id,
                SUM(mr.meter_reading) as total_energy,
                SUM(mr.meter_reading) * {CARBON_FACTOR} as total_carbon
            FROM meter_readings mr
            WHERE mr.timestamp >= :start_time
              AND mr.timestamp <= :end_time
              AND mr.meter = 'electricity'
            GROUP BY mr.building_id
        ),
        meter_status_source AS (
            SELECT
                mr.building_id AS building_id,
                mr.meter AS meter_type,
                MAX(mr.timestamp) AS last_seen_at
            FROM meter_readings mr
            WHERE mr.timestamp >= :start_time
              AND mr.timestamp <= :end_time
            GROUP BY mr.building_id, mr.meter
        ),
        meter_status AS (
            SELECT
                building_id,
                meter_type,
                CASE
                    WHEN last_seen_at IS NULL THEN 'offline'
                    WHEN :end_time - last_seen_at <= INTERVAL '2 days' THEN 'online'
                    WHEN :end_time - last_seen_at <= INTERVAL '7 days' THEN 'warning'
                    WHEN :end_time - last_seen_at <= INTERVAL '14 days' THEN 'fault'
                    ELSE 'offline'
                END AS computed_status
            FROM meter_status_source
        ),
        building_status_rollup AS (
            SELECT
                building_id,
                COUNT(*) AS meter_count,
                BOOL_OR(computed_status = 'fault') AS has_fault,
                BOOL_OR(computed_status = 'warning') AS has_warning,
                BOOL_OR(computed_status = 'offline') AS has_offline,
                BOOL_AND(computed_status = 'offline') AS all_offline
            FROM meter_status
            GROUP BY building_id
        ),
        final_buildings AS (
            SELECT
                bm.building_id,
                bm.site_id,
                bm.primaryspaceusage,
                bm.sub_primaryspaceusage,
                bm.sqm,
                bm.lat,
                bm.lng,
                bm.timezone,
                bm.yearbuilt,
                bm.leed_level,
                COALESCE(ae.total_energy, 0) as energy,
                COALESCE(ae.total_carbon, 0) as carbon,
                CASE WHEN bm.sqm > 0 THEN COALESCE(ae.total_energy, 0) / bm.sqm ELSE 0 END as eui,
                COALESCE(bsr.meter_count, 0) AS meter_count,
                CASE
                    WHEN COALESCE(bsr.meter_count, 0) = 0 THEN 'offline'
                    WHEN bsr.has_fault THEN 'fault'
                    WHEN bsr.has_warning THEN 'warning'
                    WHEN bsr.all_offline THEN 'offline'
                    WHEN bsr.has_offline THEN 'warning'
                    ELSE 'normal'
                END AS status,
                CASE
                    WHEN COALESCE(bsr.meter_count, 0) = 0 THEN '时段无数据'
                    WHEN bsr.has_fault THEN '故障停机'
                    WHEN bsr.has_warning THEN '告警状态'
                    WHEN bsr.all_offline THEN '离线'
                    WHEN bsr.has_offline THEN '部分离线'
                    ELSE '正常运行'
                END AS status_text
            FROM building_metadata bm
            LEFT JOIN aggregated_energy ae ON bm.building_id = ae.building_id
            LEFT JOIN building_status_rollup bsr ON bm.building_id = bsr.building_id
            WHERE {where_sql}
        )
        SELECT * FROM final_buildings
        WHERE (:min_energy IS NULL OR energy >= :min_energy)
          AND (:max_energy IS NULL OR energy <= :max_energy)
          AND (:min_eui IS NULL OR eui >= :min_eui)
          AND (:max_eui IS NULL OR eui <= :max_eui)
          AND (:min_carbon IS NULL OR carbon >= :min_carbon)
          AND (:max_carbon IS NULL OR carbon <= :max_carbon)
          AND (:status IS NULL OR status = :status)
    """

    # 5. 执行分页与总数查询
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)
    
    # 获取总数 (修正参数传递)
    total = int(fetch_scalar(f"SELECT COUNT(*) FROM ({sql_base}) AS t", params) or 0)
    
    # 获取列表数据
    rows = fetch_all(
        f"{sql_base} ORDER BY building_id ASC LIMIT :limit OFFSET :offset",
        {**params, "limit": safe_page_size, "offset": offset},
    )

    items = [map_building_row_to_model(row) for row in rows]
    return BuildingListResponse(
        items=items,
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=total),
    )


def get_building_row_or_raise(building_id: str) -> dict[str, Any]:  # 定义查询单个建筑基础信息并在缺失时抛错的函数。
    row = fetch_one(  # 查询指定建筑的元数据。
        """
        SELECT *
        FROM building_metadata
        WHERE building_id = :building_id
        """,
        {"building_id": building_id},
    )  # 执行建筑元数据查询。
    if row is None:  # 如果没查到建筑，
        raise ResourceNotFoundError(f"未找到建筑: {building_id}")  # 就抛出 404 语义的异常。
    return row  # 返回查到的建筑元数据。


def get_building_available_meter_names(building_id: str, building_row: dict[str, Any]) -> list[str]:  # 定义获取建筑可用表计列表的函数。
    available_meters: set[str] = set()  # 初始化可用表计集合。
    for meter_name in METER_UNIT_MAP:  # 遍历系统内置的所有标准表计类型。
        if normalize_metadata_flag(building_row.get(meter_name)):  # 如果元数据里明确标记了当前表计可用，
            available_meters.add(meter_name)  # 就把这个表计加入可用集合。
    rows = fetch_all(  # 再查询数据库里当前建筑真实出现过的表计类型。
        """
        SELECT DISTINCT meter
        FROM meter_readings
        WHERE building_id = :building_id
        ORDER BY meter ASC
        """,
        {"building_id": building_id},
    )  # 执行建筑表计列表查询。
    for row in rows:  # 遍历所有真实出现过的表计类型。
        meter_name = normalize_text(row.get("meter"))  # 标准化当前表计类型文本。
        if meter_name:  # 如果当前表计文本有效，
            available_meters.add(meter_name)  # 就把它也纳入可用集合。
    ordered_meters: list[str] = []  # 初始化有序表计列表。
    for meter_name in METER_UNIT_MAP:  # 先按系统标准顺序遍历所有内置表计。
        if meter_name in available_meters:  # 如果当前表计在可用集合里，
            ordered_meters.append(meter_name)  # 就先按标准顺序放入结果列表。
    extra_meters = sorted(meter_name for meter_name in available_meters if meter_name not in METER_UNIT_MAP)  # 把标准表计之外的额外表计按字典序排好。
    for meter_name in extra_meters:  # 遍历所有额外表计。
        ordered_meters.append(meter_name)  # 把额外表计追加到结果列表尾部。
    return ordered_meters  # 返回当前建筑的有序可用表计列表。


def build_meter_availability_items(building_id: str, building_row: dict[str, Any]) -> list[MeterAvailability]:  # 定义构造建筑表计可用性列表的函数。
    available_meter_names = set(get_building_available_meter_names(building_id, building_row))  # 先取当前建筑实际可用的表计集合。
    ordered_meter_names = list(METER_UNIT_MAP.keys())  # 先按标准顺序初始化表计名称列表。
    for meter_name in sorted(available_meter_names):  # 遍历所有可用表计，准备补充额外类型。
        if meter_name not in ordered_meter_names:  # 如果当前表计不在系统标准列表中，
            ordered_meter_names.append(meter_name)  # 就把它追加到展示列表尾部。
    items: list[MeterAvailability] = []  # 初始化表计可用性结果列表。
    for meter_name in ordered_meter_names:  # 遍历最终要展示的全部表计。
        items.append(  # 把当前表计的可用性对象追加到结果列表。
            MeterAvailability(  # 创建表计可用性模型。
                meter=meter_name,  # 写入表计类型字段。
                available=meter_name in available_meter_names,  # 写入当前表计是否可用。
            )  # 完成当前表计可用性模型创建。
        )  # 完成当前对象追加。
    return items  # 返回完整表计可用性列表。


def select_focus_meter(available_meters: list[str], preferred_meter: str | None = None) -> str | None:  # 定义选择默认聚焦表计的函数。
    normalized_preferred_meter = normalize_text(preferred_meter)  # 先标准化前端指定的表计类型。
    if normalized_preferred_meter:  # 如果前端明确指定了表计类型，
        return normalized_preferred_meter  # 就优先使用前端指定的表计。
    for meter_name in DEFAULT_METER_PRIORITY:  # 按默认优先级遍历候选表计。
        if meter_name in available_meters:  # 如果当前候选表计在建筑可用列表中，
            return meter_name  # 就把它作为默认聚焦表计返回。
    if available_meters:  # 如果默认优先级里一个都没命中，但建筑仍有可用表计，
        return available_meters[0]  # 就回退到列表里的第一个表计。
    return None  # 如果确实没有任何可用表计，就返回空。


def get_meter_window_statistics(building_id: str, meter: str, window_days: int = DEFAULT_WINDOW_DAYS) -> dict[str, Any]:  # 定义查询建筑某个表计窗口统计信息的函数。
    window_end = get_latest_timestamp([building_id], None, meter)  # 先取当前建筑和表计在数据库中的最新时间。
    current_start = window_end - timedelta(days=window_days)  # 计算当前统计窗口的开始时间。
    previous_end = current_start  # 把上一窗口结束时间设为当前窗口开始时间。
    previous_start = previous_end - timedelta(days=window_days)  # 计算上一统计窗口的开始时间。
    stats_row = fetch_one(  # 用单条 SQL 同时查询当前窗口和上一窗口的关键统计值。
        """
        SELECT
            COUNT(CASE WHEN timestamp >= :current_start AND timestamp <= :current_end THEN meter_reading END) AS current_count,
            COUNT(CASE WHEN timestamp >= :previous_start AND timestamp < :previous_end THEN meter_reading END) AS previous_count,
            SUM(CASE WHEN timestamp >= :current_start AND timestamp <= :current_end THEN meter_reading END) AS current_total,
            SUM(CASE WHEN timestamp >= :previous_start AND timestamp < :previous_end THEN meter_reading END) AS previous_total,
            AVG(CASE WHEN timestamp >= :current_start AND timestamp <= :current_end THEN meter_reading END) AS current_average,
            AVG(CASE WHEN timestamp >= :previous_start AND timestamp < :previous_end THEN meter_reading END) AS previous_average,
            MAX(CASE WHEN timestamp >= :current_start AND timestamp <= :current_end THEN meter_reading END) AS current_peak
        FROM meter_readings
        WHERE building_id = :building_id
          AND meter = :meter
          AND timestamp >= :previous_start
          AND timestamp <= :current_end
        """,
        {
            "building_id": building_id,
            "meter": meter,
            "current_start": current_start,
            "current_end": window_end,
            "previous_start": previous_start,
            "previous_end": previous_end,
        },
    ) or {}  # 如果当前设备完全没有命中数据，就退回空字典做兜底。
    latest_row = fetch_one(  # 再单独查询当前表计的最新一条读数。
        """
        SELECT
            timestamp,
            meter_reading
        FROM meter_readings
        WHERE building_id = :building_id
          AND meter = :meter
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        {"building_id": building_id, "meter": meter},
    )  # 执行最新读数查询。
    current_count = int(stats_row.get("current_count") or 0)  # 读取当前窗口真实命中的读数条数。
    previous_count = int(stats_row.get("previous_count") or 0)  # 读取上一窗口真实命中的读数条数。
    return {  # 返回统一的窗口统计结果字典。
        "window_end": window_end,  # 写入窗口结束时间。
        "current_start": current_start,  # 写入当前窗口开始时间。
        "previous_start": previous_start,  # 写入上一窗口开始时间。
        "current_total": round_optional_float(stats_row.get("current_total")),  # 写入当前窗口总量；如果缺失则明确返回空值。
        "previous_total": round_optional_float(stats_row.get("previous_total")),  # 写入上一窗口总量；如果缺失则明确返回空值。
        "current_average": round_optional_float(stats_row.get("current_average")),  # 写入当前窗口均值；如果缺失则明确返回空值。
        "previous_average": round_optional_float(stats_row.get("previous_average")),  # 写入上一窗口均值；如果缺失则明确返回空值。
        "current_peak": round_optional_float(stats_row.get("current_peak")),  # 写入当前窗口峰值；如果缺失则明确返回空值。
        "latest_value": round_optional_float((latest_row or {}).get("meter_reading")),  # 写入最新一条读数；如果缺失则明确返回空值。
        "latest_timestamp": (latest_row or {}).get("timestamp"),  # 写入最新一条读数时间。
        "current_count": current_count,  # 写入当前窗口真实命中的读数条数。
        "previous_count": previous_count,  # 写入上一窗口真实命中的读数条数。
    }  # 完成统计字典构造。


def calculate_change_rate(current_value: float | None, previous_value: float | None) -> float | None:  # 定义计算变化率的函数。
    if current_value is None or previous_value is None:  # 如果当前值或上一值缺失，
        return None  # 就直接返回空，避免把缺失值误算成变化率。
    if previous_value == 0:  # 如果上一周期值为 0，
        return None  # 就不返回变化率，避免误导或除零。
    return round((current_value - previous_value) / previous_value, 4)  # 返回保留四位小数的变化率。


def build_building_summary_metrics(building_id: str, building_row: dict[str, Any], available_meters: list[str]) -> list[MetricCard]:  # 定义构造建筑详情摘要指标卡片的函数。
    cards: list[MetricCard] = []  # 初始化指标卡片列表。
    sqm_value = normalize_optional_float(building_row.get("sqm")) or 0.0  # 读取建筑面积，没有值时用 0 兜底。
    cards.append(  # 先写入面积卡片。
        MetricCard(  # 创建面积指标卡片。
            key="sqm",  # 写入指标键。
            label="建筑面积",  # 写入指标标题。
            value=round(sqm_value, 4),  # 写入指标数值。
            unit="sqm",  # 写入面积单位。
        )  # 完成面积卡片对象创建。
    )  # 完成面积卡片追加。
    cards.append(  # 再写入可用表计数量卡片。
        MetricCard(  # 创建表计数量指标卡片。
            key="available_meters",  # 写入指标键。
            label="可用表计数",  # 写入指标标题。
            value=float(len(available_meters)),  # 写入可用表计数量。
            unit="count",  # 写入数量单位。
        )  # 完成表计数量卡片对象创建。
    )  # 完成表计数量卡片追加。
    focus_meter = select_focus_meter(available_meters)  # 选出默认最值得展示的表计类型。
    if focus_meter:  # 如果当前建筑至少有一个可分析表计，
        meter_stats = get_meter_window_statistics(building_id, focus_meter)  # 就查询该表计最近窗口的统计数据。
        cards.append(  # 把最近 7 天总量卡片追加到结果中。
            MetricCard(  # 创建近 7 天总量卡片。
                key=f"{focus_meter}_recent_total",  # 写入指标键。
                label=f"近{DEFAULT_WINDOW_DAYS}天 {focus_meter} 总量",  # 写入指标标题。
                value=meter_stats["current_total"],  # 写入当前窗口总量。
                unit=get_meter_unit(focus_meter),  # 写入当前表计对应的单位。
                change_rate=calculate_change_rate(meter_stats["current_total"], meter_stats["previous_total"]),  # 写入相对上一窗口的变化率。
                data_status=resolve_numeric_data_status(has_data=meter_stats["current_count"] > 0),  # 写入当前卡片数据状态，避免把缺失值误认为 0。
                data_note=None if meter_stats["current_count"] > 0 else f"近{DEFAULT_WINDOW_DAYS}天窗口内没有命中的 {focus_meter} 读数。",  # 在缺失时补充明确说明。
            )  # 完成最近窗口总量卡片对象创建。
        )  # 完成最近窗口总量卡片追加。
    return cards  # 返回完整指标卡片列表。


def get_building_detail(building_id: str) -> BuildingDetailResponse:  # 定义建筑详情查询接口业务函数。
    building_row = get_building_row_or_raise(building_id)  # 先查询当前建筑的基础元数据，不存在时直接抛错。
    available_meters = get_building_available_meter_names(building_id, building_row)  # 再查询当前建筑的可用表计列表。
    meter_items = build_meter_availability_items(building_id, building_row)  # 构造文档要求的表计可用性列表。
    summary_metrics = build_building_summary_metrics(building_id, building_row, available_meters)  # 构造建筑详情摘要指标卡片。
    return BuildingDetailResponse(  # 构造并返回建筑详情响应。
        building=map_building_row_to_model(building_row),  # 写入建筑基础信息字段。
        meters=meter_items,  # 写入表计可用性列表字段。
        summary_metrics=summary_metrics,  # 写入摘要指标卡片字段。
    )  # 完成建筑详情响应构造。


def get_building_energy_summary(  # 定义建筑级能耗摘要接口业务函数。
    building_id: str,  # 接收建筑编号参数。
    meter: str | None,  # 接收表计类型参数。
    start_time: datetime | str | None,  # 接收开始时间参数。
    end_time: datetime | str | None,  # 接收结束时间参数。
    granularity: str | None,  # 接收粒度参数。
) -> EnergySummaryResponse:  # 返回建筑级能耗摘要响应模型。
    building_row = get_building_row_or_raise(building_id)  # 先确认当前建筑确实存在。
    available_meters = get_building_available_meter_names(building_id, building_row)  # 取出当前建筑的可用表计列表。
    normalize_granularity(granularity)  # 标准化粒度参数，保证接口兼容文档中的输入。
    effective_meter = select_focus_meter(available_meters, meter) or normalize_meter(meter)  # 选出真正要用于摘要计算的表计类型。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id], None, effective_meter)  # 按建筑和表计条件补齐默认时间范围。
    summary = build_summary(effective_meter, resolved_start, resolved_end, [building_id], None)  # 复用既有 energy 摘要逻辑计算当前建筑摘要。
    return EnergySummaryResponse(  # 构造并返回建筑级能耗摘要响应。
        building_id=building_id,  # 写入建筑编号字段。
        time_range=build_api_time_range(resolved_start, resolved_end),  # 写入带时区的时间范围字段。
        summary=summary,  # 写入能耗摘要字段。
    )  # 完成建筑级能耗摘要响应构造。
