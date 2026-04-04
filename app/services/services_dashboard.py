from datetime import datetime  # 导入日期时间类型，方便做 dashboard 时间计算。
from datetime import timedelta  # 导入时间差类型，方便构造上一统计周期。
from typing import Any  # 导入任意类型注解，方便描述松散的中间数据结构。

from app.core.database import fetch_all  # 导入多行查询函数，方便查询建筑范围和聚合结果。
from app.core.database import fetch_one  # 导入单行查询函数，方便做建筑存在性检查。
from app.schemas.schemas_common import MetricCard  # 导入通用指标卡片模型，方便复用现有前端结构。
from app.schemas.schemas_dashboard import AnomalySummary  # 导入 dashboard 异常摘要模型。
from app.schemas.schemas_dashboard import DashboardHighlight  # 导入 dashboard 高亮模型。
from app.schemas.schemas_dashboard import DashboardHighlightsResponse  # 导入 dashboard 高亮列表响应模型。
from app.schemas.schemas_dashboard import DashboardHighlightType  # 导入 dashboard 高亮类型枚举。
from app.schemas.schemas_dashboard import DashboardOverviewResponse  # 导入 dashboard 总览响应模型。
from .service_common import ResourceNotFoundError  # 导入资源不存在异常，方便返回一致的 404 语义。
from .service_common import build_api_time_range  # 导入接口时间范围构造函数，方便统一输出台湾时区。
from .service_common import require_api_datetime  # 导入必填时间转换函数，方便输出 API 时间。
from .service_common import resolve_time_range  # 导入时间范围补齐函数，方便沿用现有默认时间逻辑。


DEFAULT_DASHBOARD_METER = "electricity"  # 定义 dashboard 默认以电耗作为主统计口径。
DASHBOARD_DEFAULT_LIMIT = 3  # 定义 dashboard highlights 默认返回条数。
DASHBOARD_ANOMALY_LIMIT = 5  # 定义 dashboard overview 默认最多返回的异常条数。
DASHBOARD_HIGH_ENERGY_MULTIPLIER = 1.25  # 定义高能耗建筑判定时相对基线的放大倍数。
CARBON_FACTOR_KG_PER_KWH = 0.554  # 定义比赛版估算碳排时使用的固定电力排放因子。


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
    where_sql, params = build_dashboard_scope_filters(site_id, building_id)  # 先构造 dashboard 范围过滤条件。
    rows = fetch_all(  # 查询每栋楼在当前周期和上一周期的聚合电耗。
        f"""
        SELECT
            bm.building_id AS building_id,
            bm.site_id AS site_id,
            bm.primaryspaceusage AS primaryspaceusage,
            bm.sqm AS sqm,
            COALESCE(SUM(CASE WHEN mr.timestamp >= :current_start AND mr.timestamp <= :current_end THEN mr.meter_reading END), 0) AS current_total,
            COALESCE(SUM(CASE WHEN mr.timestamp >= :previous_start AND mr.timestamp < :previous_end THEN mr.meter_reading END), 0) AS previous_total,
            MAX(CASE WHEN mr.timestamp >= :current_start AND mr.timestamp <= :current_end THEN mr.timestamp END) AS latest_timestamp
        FROM building_metadata bm
        LEFT JOIN meter_readings mr
            ON bm.building_id = mr.building_id
           AND mr.meter = :dashboard_meter
           AND mr.timestamp >= :previous_start
           AND mr.timestamp <= :current_end
        WHERE {where_sql}
        GROUP BY bm.building_id, bm.site_id, bm.primaryspaceusage, bm.sqm
        ORDER BY bm.building_id ASC
        """,
        {
            **params,
            "dashboard_meter": DEFAULT_DASHBOARD_METER,
            "current_start": current_start,
            "current_end": current_end,
            "previous_start": previous_start,
            "previous_end": previous_end,
        },
    )  # 执行双周期聚合查询。
    return rows  # 返回按建筑聚合后的结果列表。


def to_float(value: Any) -> float:  # 定义把任意输入安全转换成浮点数的函数。
    return round(float(value or 0), 4)  # 返回保留四位小数的浮点值，方便统一口径。


def safe_divide(numerator: float, denominator: float) -> float:  # 定义安全除法函数。
    if denominator <= 0:  # 如果分母小于等于零，
        return 0.0  # 就返回零，避免除零异常和误导性结果。
    return round(numerator / denominator, 4)  # 返回保留四位小数的除法结果。


def calculate_change_rate(current_value: float, previous_value: float) -> float | None:  # 定义变化率计算函数。
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


def build_building_diagnostics(  # 定义构造楼栋级诊断结果的函数。
    period_rows: list[dict[str, Any]],  # 接收按建筑聚合后的双周期结果列表。
) -> list[dict[str, Any]]:  # 返回包含异常判定信息的中间结果列表。
    diagnostics: list[dict[str, Any]] = []  # 初始化楼栋诊断结果列表。
    active_rows = [row for row in period_rows if to_float(row.get("current_total")) > 0]  # 先筛出当前周期有电耗数据的建筑。
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
        if current_total > 0 and single_scope_mode and previous_total > 0:  # 如果当前是单建筑场景且上一周期也有数据，
            deviation_rate = max(calculate_change_rate(current_eui or current_total, previous_eui or previous_total) or 0.0, 0.0)  # 就按同建筑前后周期变化率做异常偏离率。
            is_high_energy = deviation_rate >= (DASHBOARD_HIGH_ENERGY_MULTIPLIER - 1)  # 如果增长超过约定阈值，就标记为高能耗。
            if is_high_energy:  # 如果该建筑确实触发了高能耗判定，
                anomaly_title = f"{row['building_id']} 电耗较上一周期上升 {round(deviation_rate * 100, 2)}%"  # 生成单建筑场景下的异常标题。
        elif current_total > 0 and current_eui > 0 and comparison_baseline_eui > 0:  # 如果是多建筑场景且能拿到有效 EUI 基线，
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


def build_dashboard_metrics(  # 定义构造 dashboard 指标卡片列表的函数。
    scope_rows: list[dict[str, Any]],  # 接收 dashboard 范围内建筑清单。
    diagnostics: list[dict[str, Any]],  # 接收楼栋诊断结果列表。
) -> list[MetricCard]:  # 返回 dashboard 指标卡片列表。
    scoped_building_count = len(scope_rows)  # 统计当前范围内的建筑总数。
    scoped_site_count = len({str(row["site_id"]) for row in scope_rows})  # 统计当前范围覆盖的站点数量。
    current_active_buildings = [item for item in diagnostics if item["current_total"] > 0]  # 取出当前周期有电耗数据的建筑列表。
    previous_active_buildings = [item for item in diagnostics if item["previous_total"] > 0]  # 取出上一周期有电耗数据的建筑列表。
    current_total = round(sum(item["current_total"] for item in diagnostics), 4)  # 计算当前周期总电耗。
    previous_total = round(sum(item["previous_total"] for item in diagnostics), 4)  # 计算上一周期总电耗。
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
        MetricCard(key="electricity_total", label="本期总电耗", value=current_total, unit="kWh", change_rate=calculate_change_rate(current_total, previous_total)),  # 返回总电耗卡片。
        MetricCard(key="electricity_eui", label="本期电耗EUI", value=current_eui, unit="kWh/sqm", change_rate=calculate_change_rate(current_eui, previous_eui)),  # 返回电耗 EUI 卡片。
        MetricCard(key="estimated_carbon", label="估算碳排", value=current_carbon, unit="kgCO2e", change_rate=calculate_change_rate(current_carbon, previous_carbon)),  # 返回估算碳排卡片。
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
    active_building_count = len([item for item in diagnostics if item["current_total"] > 0])  # 统计当前周期活跃建筑数量。
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
) -> dict[str, Any]:  # 返回 dashboard 快照字典。
    scope_rows = get_dashboard_scope_rows(site_id, building_id)  # 先查询当前 dashboard 统计范围内的建筑清单。
    resolved_start, resolved_end = resolve_time_range(start_time, end_time, [building_id] if building_id else None, site_id, DEFAULT_DASHBOARD_METER)  # 按电耗口径补齐当前 dashboard 时间范围。
    current_start, current_end, previous_start, previous_end = normalize_dashboard_window(resolved_start, resolved_end)  # 构造当前周期和上一周期时间范围。
    diagnostics = build_building_diagnostics(get_dashboard_period_rows(current_start, current_end, previous_start, previous_end, site_id, building_id))  # 查询并构造楼栋诊断结果。
    anomalies = build_dashboard_anomalies(diagnostics)  # 基于诊断结果构造异常摘要列表。
    metrics = build_dashboard_metrics(scope_rows, diagnostics)  # 基于范围和诊断结果构造指标卡片列表。
    ai_summary_hint = build_ai_summary_hint(diagnostics, anomalies, current_end)  # 基于诊断结果和时间范围构造规则摘要文本。
    return {  # 返回 dashboard 快照字典。
        "time_range": build_api_time_range(current_start, current_end),  # 写入带时区的当前周期时间范围。
        "metrics": metrics,  # 写入指标卡片列表。
        "diagnostics": diagnostics,  # 写入楼栋诊断结果列表，供 highlights 继续复用。
        "top_anomalies": anomalies,  # 写入异常摘要列表。
        "ai_summary_hint": ai_summary_hint,  # 写入规则摘要文本。
    }  # 完成 dashboard 快照构造。


def get_dashboard_overview(  # 定义 dashboard 总览接口业务函数。
    start_time: datetime | str | None,  # 接收开始时间参数。
    end_time: datetime | str | None,  # 接收结束时间参数。
    site_id: str | None,  # 接收站点编号参数。
    building_id: str | None,  # 接收建筑编号参数。
) -> DashboardOverviewResponse:  # 返回 dashboard 总览响应模型。
    snapshot = build_dashboard_snapshot(start_time, end_time, site_id, building_id)  # 先构造完整 dashboard 快照。
    return DashboardOverviewResponse(  # 基于快照构造总览响应对象。
        time_range=snapshot["time_range"],  # 写入时间范围字段。
        metrics=snapshot["metrics"],  # 写入指标卡片列表字段。
        top_anomalies=snapshot["top_anomalies"],  # 写入顶部异常列表字段。
        ai_summary_hint=snapshot["ai_summary_hint"],  # 写入规则摘要提示字段。
    )  # 完成 dashboard 总览响应构造。


def build_dashboard_highlight_items(  # 定义构造 dashboard 高亮项列表的函数。
    snapshot: dict[str, Any],  # 接收 dashboard 快照字典。
    limit: int,  # 接收高亮项条数上限。
) -> list[DashboardHighlight]:  # 返回高亮项模型列表。
    items: list[DashboardHighlight] = []  # 初始化高亮项列表。
    metrics_by_key = {metric.key: metric for metric in snapshot["metrics"]}  # 先把指标卡片整理成按 key 查询的映射。
    top_anomalies: list[AnomalySummary] = snapshot["top_anomalies"]  # 取出异常摘要列表，方便下面复用。
    diagnostics: list[dict[str, Any]] = snapshot["diagnostics"]  # 取出楼栋诊断结果，方便继续生成洞察和建议。
    if top_anomalies:  # 如果存在异常摘要，
        top_anomaly = top_anomalies[0]  # 就取第一条异常作为首条高亮。
        items.append(  # 追加异常型高亮项。
            DashboardHighlight(  # 创建异常型高亮对象。
                type=DashboardHighlightType.anomaly,  # 写入高亮类型为 anomaly。
                title=top_anomaly.title,  # 写入异常高亮标题。
                description="该异常来自 dashboard 规则派生结果，建议优先进入异常分析页核查同周期负载变化。",  # 写入异常高亮描述。
                target="/energy/anomaly-analysis",  # 写入推荐跳转目标。
                target_id=top_anomaly.building_id,  # 写入推荐跳转建筑编号。
            )  # 完成异常型高亮对象创建。
        )  # 完成异常型高亮追加。
    total_metric = metrics_by_key.get("electricity_total")  # 读取总电耗指标卡片。
    if total_metric is not None:  # 如果能成功取到总电耗指标，
        change_rate = total_metric.change_rate or 0.0  # 读取总电耗环比变化率，没有值时回退到零。
        trend_word = "上升" if change_rate > 0 else "下降" if change_rate < 0 else "持平"  # 根据变化率生成趋势文本。
        items.append(  # 追加洞察型高亮项。
            DashboardHighlight(  # 创建洞察型高亮对象。
                type=DashboardHighlightType.insight,  # 写入高亮类型为 insight。
                title=f"总电耗较上一周期{trend_word}",  # 写入总电耗趋势标题。
                description=f"当前范围总电耗为 {total_metric.value} {total_metric.unit or ''}，变化率为 {round(abs(change_rate) * 100, 2)}%。",  # 写入总电耗趋势描述。
                target="/dashboard/overview",  # 写入建议返回总览页的目标。
                target_id=None,  # 当前洞察不绑定特定建筑编号。
            )  # 完成洞察型高亮对象创建。
        )  # 完成洞察型高亮追加。
    high_energy_items = [item for item in diagnostics if item["is_high_energy"]]  # 取出所有高能耗建筑结果，方便生成建议项。
    if high_energy_items:  # 如果存在高能耗建筑，
        focus_item = high_energy_items[0]  # 就取最需要优先处理的一栋楼。
        items.append(  # 追加任务建议型高亮项。
            DashboardHighlight(  # 创建任务型高亮对象。
                type=DashboardHighlightType.task,  # 写入高亮类型为 task。
                title=f"建议优先检查 {focus_item['building_id']}",  # 写入建议处理标题。
                description=f"该建筑当前周期电耗为 {focus_item['current_total']} kWh，主要用途为 {focus_item['primaryspaceusage']}。",  # 写入建议处理描述。
                target="/buildings/{buildingId}",  # 写入推荐跳转目标模板。
                target_id=focus_item["building_id"],  # 写入推荐跳转建筑编号。
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
            )  # 完成兜底洞察项对象创建。
        )  # 完成兜底洞察项追加。
    return items[:limit]  # 按条数上限截断并返回高亮项列表。


def get_dashboard_highlights(limit: int | None) -> DashboardHighlightsResponse:  # 定义 dashboard 高亮接口业务函数。
    safe_limit = max(1, min(limit or DASHBOARD_DEFAULT_LIMIT, 10))  # 给高亮条数做默认值和范围保护。
    snapshot = build_dashboard_snapshot(None, None, None, None)  # 按默认全局范围构造 dashboard 快照。
    return DashboardHighlightsResponse(items=build_dashboard_highlight_items(snapshot, safe_limit))  # 构造并返回高亮列表响应。
