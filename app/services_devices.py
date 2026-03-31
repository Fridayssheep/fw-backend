import math  # 导入数学库，后面计算设备告警阈值时会用到平方根。
from datetime import datetime  # 导入日期时间类型，方便做类型标注。
from datetime import timedelta  # 导入时间差类型，方便定义设备状态窗口和维护记录时间。
from typing import Any  # 导入任意类型注解，方便描述松散结构。

from .database import fetch_all  # 导入多行查询函数。
from .database import fetch_one  # 导入单行查询函数。
from .schemas import Device  # 导入设备详情模型。
from .schemas import DeviceAlarm  # 导入设备告警模型。
from .schemas import DeviceAlarmListResponse  # 导入设备告警列表响应模型。
from .schemas import DeviceDetailResponse  # 导入设备详情响应模型。
from .schemas import DeviceListResponse  # 导入设备列表响应模型。
from .schemas import MaintenanceRecord  # 导入维护记录模型。
from .schemas import MaintenanceRecordListResponse  # 导入维护记录列表响应模型。
from .schemas import MetricCard  # 导入指标卡片模型。
from .schemas import Pagination  # 导入分页模型。
from .service_common import ResourceNotFoundError  # 导入资源不存在异常。
from .service_common import get_latest_timestamp  # 导入获取最新时间的函数。
from .service_common import get_meter_unit  # 导入获取表计单位的函数。
from .service_common import normalize_pagination  # 导入标准化分页参数的函数。
from .service_common import normalize_text  # 导入标准化文本的函数。
from .service_common import require_api_datetime  # 导入强制转换接口时间的函数。
from .service_common import to_api_datetime  # 导入转换接口输出时间的函数。
from .services_buildings import DEFAULT_WINDOW_DAYS  # 导入默认统计窗口天数。
from .services_buildings import get_meter_window_statistics  # 导入建筑表计窗口统计函数。


DEVICE_STATUS_ONLINE_WINDOW = timedelta(days=2)  # 定义设备判定为在线的最新活跃时间窗口。
DEVICE_STATUS_IDLE_WINDOW = timedelta(days=14)  # 定义设备判定为闲置的最新活跃时间窗口。
DEVICE_ALARM_LOOKBACK_DAYS = 30  # 定义设备告警分析默认回看天数。
DEVICE_RECENT_ALARM_LIMIT = 5  # 定义设备详情里最近告警的默认返回条数。
DEVICE_ID_SEPARATOR = "::"  # 定义设备编号里建筑和设备类型的分隔符。
DEVICE_TYPE_LABEL_MAP = {  # 定义设备类型的人类可读名称映射表。
    "electricity": "Electricity Meter",  # 电表对应展示名称。
    "water": "Water Meter",  # 水表对应展示名称。
    "gas": "Gas Meter",  # 燃气表对应展示名称。
    "hotwater": "Hot Water Meter",  # 热水表对应展示名称。
    "chilledwater": "Chilled Water Meter",  # 冷冻水表对应展示名称。
    "steam": "Steam Meter",  # 蒸汽表对应展示名称。
    "solar": "Solar Meter",  # 光伏表对应展示名称。
    "irrigation": "Irrigation Meter",  # 灌溉表对应展示名称。
}  # 结束设备类型展示名称映射定义。


def build_device_id(building_id: str, meter: str) -> str:  # 定义构造设备编号的函数。
    return f"{building_id}{DEVICE_ID_SEPARATOR}{meter}"  # 用建筑编号和表计类型拼出稳定设备编号。


def parse_device_id(device_id: str) -> tuple[str, str]:  # 定义解析设备编号的函数。
    if DEVICE_ID_SEPARATOR not in device_id:  # 如果设备编号里没有约定好的分隔符，
        raise ValueError("非法 deviceId，必须使用 buildings 列表接口返回的 device_id。")  # 就抛出更容易理解的校验错误。
    building_id, meter = device_id.rsplit(DEVICE_ID_SEPARATOR, 1)  # 从右侧拆出建筑编号和表计类型。
    if not building_id or not meter:  # 如果拆出的任意一段为空，
        raise ValueError("非法 deviceId，缺少 building_id 或 device_type。")  # 就抛出校验错误。
    return building_id, meter  # 返回拆解好的建筑编号和表计类型。


def build_device_name(building_id: str, meter: str) -> str:  # 定义生成设备展示名称的函数。
    meter_label = DEVICE_TYPE_LABEL_MAP.get(meter, meter.replace("_", " ").title())  # 先取设备类型的展示名称。
    return f"{building_id} {meter_label}"  # 把建筑编号和设备类型拼成最终展示名称。


def calculate_change_rate(current_value: float, previous_value: float) -> float | None:  # 定义计算变化率的函数。
    if previous_value == 0:  # 如果上一周期值为 0，
        return None  # 就不返回变化率，避免误导或除零。
    return round((current_value - previous_value) / previous_value, 4)  # 返回保留四位小数的变化率。


def build_device_status(last_seen_at: datetime | None, reference_latest: datetime) -> str:  # 定义根据最后活跃时间计算设备状态的函数。
    if last_seen_at is None:  # 如果设备没有任何活跃时间，
        return "offline"  # 就直接标记为离线。
    lag = reference_latest - last_seen_at  # 计算当前设备相对全局最新数据的滞后时间。
    if lag <= DEVICE_STATUS_ONLINE_WINDOW:  # 如果还在在线窗口内，
        return "online"  # 就返回在线状态。
    if lag <= DEVICE_STATUS_IDLE_WINDOW:  # 如果超过在线窗口但还没完全失联，
        return "idle"  # 就返回闲置状态。
    return "offline"  # 其余情况统一视为离线。


def get_device_base_row_or_raise(building_id: str, meter: str) -> dict[str, Any]:  # 定义查询单个设备聚合信息并在缺失时抛错的函数。
    row = fetch_one(  # 按建筑编号和表计类型查询聚合后的设备信息。
        """
        SELECT
            mr.building_id AS building_id,
            mr.meter AS device_type,
            MAX(mr.timestamp) AS last_seen_at,
            COUNT(*) AS reading_count,
            bm.yearbuilt AS yearbuilt
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE mr.building_id = :building_id
          AND mr.meter = :meter
        GROUP BY mr.building_id, mr.meter, bm.yearbuilt
        """,
        {"building_id": building_id, "meter": meter},
    )  # 执行设备聚合查询。
    if row is None:  # 如果当前建筑下没有这种设备，
        raise ResourceNotFoundError(f"未找到设备: {build_device_id(building_id, meter)}")  # 就抛出 404 语义异常。
    return row  # 返回设备聚合信息。


def map_device_row_to_model(row: dict[str, Any], reference_latest: datetime) -> Device:  # 定义把设备聚合结果映射成设备模型的函数。
    building_id = str(row["building_id"])  # 先取出当前设备所属建筑编号。
    meter = str(row["device_type"])  # 先取出当前设备的表计类型。
    return Device(  # 构造并返回设备详情模型。
        device_id=build_device_id(building_id, meter),  # 写入设备编号字段。
        device_name=build_device_name(building_id, meter),  # 写入设备名称字段。
        device_type=meter,  # 写入设备类型字段。
        building_id=building_id,  # 写入所属建筑字段。
        status=build_device_status(row.get("last_seen_at"), reference_latest),  # 写入设备状态字段。
        manufacturer=None,  # 当前数据集中没有真实制造商信息，这里保持为空。
        model=None,  # 当前数据集中没有真实型号信息，这里保持为空。
        install_date=None,  # 当前数据集中没有真实安装日期信息，这里保持为空。
        last_seen_at=to_api_datetime(row.get("last_seen_at")),  # 写入最后活跃时间字段。
    )  # 完成设备模型构造。


def build_device_recent_metrics(building_id: str, meter: str) -> list[MetricCard]:  # 定义构造设备详情最近指标卡片的函数。
    meter_stats = get_meter_window_statistics(building_id, meter)  # 先查询当前设备对应表计的窗口统计结果。
    unit = get_meter_unit(meter)  # 取出当前表计的单位。
    cards: list[MetricCard] = []  # 初始化指标卡片列表。
    cards.append(  # 先追加最新读数卡片。
        MetricCard(  # 创建最新读数卡片对象。
            key="latest_reading",  # 写入指标键。
            label="最新读数",  # 写入指标标题。
            value=meter_stats["latest_value"],  # 写入最新读数值。
            unit=unit,  # 写入当前表计单位。
        )  # 完成最新读数卡片对象创建。
    )  # 完成最新读数卡片追加。
    cards.append(  # 再追加近 7 天平均值卡片。
        MetricCard(  # 创建近 7 天平均值卡片对象。
            key="recent_average",  # 写入指标键。
            label=f"近{DEFAULT_WINDOW_DAYS}天平均值",  # 写入指标标题。
            value=meter_stats["current_average"],  # 写入当前窗口平均值。
            unit=unit,  # 写入当前表计单位。
            change_rate=calculate_change_rate(meter_stats["current_average"], meter_stats["previous_average"]),  # 写入相对上一窗口平均值的变化率。
        )  # 完成平均值卡片对象创建。
    )  # 完成平均值卡片追加。
    cards.append(  # 最后追加近 7 天峰值卡片。
        MetricCard(  # 创建近 7 天峰值卡片对象。
            key="recent_peak",  # 写入指标键。
            label=f"近{DEFAULT_WINDOW_DAYS}天峰值",  # 写入指标标题。
            value=meter_stats["current_peak"],  # 写入当前窗口峰值。
            unit=unit,  # 写入当前表计单位。
        )  # 完成峰值卡片对象创建。
    )  # 完成峰值卡片追加。
    return cards  # 返回完整设备指标卡片列表。


def build_device_alarm_items(building_id: str, meter: str) -> list[DeviceAlarm]:  # 定义根据设备读数构造设备告警列表的函数。
    device_row = get_device_base_row_or_raise(building_id, meter)  # 先确认当前设备存在，并取到其聚合信息。
    window_end = device_row.get("last_seen_at") or get_latest_timestamp([building_id], None, meter)  # 取设备最近一次活跃时间作为分析窗口终点。
    window_start = window_end - timedelta(days=DEVICE_ALARM_LOOKBACK_DAYS)  # 把告警分析窗口向前扩展指定天数。
    rows = fetch_all(  # 查询当前设备在分析窗口内的原始读数序列。
        """
        SELECT
            timestamp,
            meter_reading
        FROM meter_readings
        WHERE building_id = :building_id
          AND meter = :meter
          AND timestamp >= :start_time
          AND timestamp <= :end_time
        ORDER BY timestamp DESC
        """,
        {"building_id": building_id, "meter": meter, "start_time": window_start, "end_time": window_end},
    )  # 执行设备告警分析原始数据查询。
    if not rows:  # 如果当前设备在分析窗口内没有任何数据，
        return []  # 就直接返回空告警列表。
    values: list[float] = []  # 初始化设备读数值列表。
    for row in rows:  # 遍历所有设备读数结果。
        values.append(float(row["meter_reading"] or 0))  # 把每条读数转成浮点数后追加进列表。
    mean_value = sum(values) / len(values) if values else 0.0  # 计算当前窗口内的读数均值。
    variance = sum((value - mean_value) ** 2 for value in values) / len(values) if values else 0.0  # 计算当前窗口内的方差。
    std_value = math.sqrt(variance)  # 对方差开平方得到标准差。
    device_id = build_device_id(building_id, meter)  # 先构造当前设备的稳定设备编号。
    alarms: list[DeviceAlarm] = []  # 初始化设备告警结果列表。
    for row in rows:  # 遍历所有读数，逐个判断是否需要生成告警。
        current_value = float(row["meter_reading"] or 0)  # 读取当前时间点的设备数值。
        deviation_rate = abs(current_value - mean_value) / mean_value if mean_value else 0.0  # 计算当前值相对均值的偏离率。
        z_score = abs(current_value - mean_value) / std_value if std_value else 0.0  # 计算当前值相对均值的标准分差。
        if deviation_rate < 0.35 and z_score < 2.0:  # 如果偏离率和标准分都不够显著，
            continue  # 就认为这条读数不足以形成告警。
        if deviation_rate >= 0.8 or z_score >= 3.0:  # 如果偏离程度非常明显，
            level = "critical"  # 就把当前告警等级标成 critical。
        elif deviation_rate >= 0.5 or z_score >= 2.5:  # 如果偏离程度中等偏高，
            level = "warning"  # 就把当前告警等级标成 warning。
        else:  # 其余达到阈值但相对较轻的情况，
            level = "info"  # 就把当前告警等级标成 info。
        direction_label = "偏高" if current_value >= mean_value else "偏低"  # 根据当前值相对均值的方向生成提示文字。
        status = "open" if row["timestamp"] >= window_end - timedelta(hours=24) else "closed"  # 把最近 24 小时内的告警视为 open，其余视为 closed。
        alarms.append(  # 把当前告警对象追加到结果列表。
            DeviceAlarm(  # 创建设备告警模型。
                alarm_id=f"{device_id}{DEVICE_ID_SEPARATOR}alarm{DEVICE_ID_SEPARATOR}{row['timestamp'].strftime('%Y%m%d%H%M%S')}",  # 写入稳定的告警编号。
                device_id=device_id,  # 写入设备编号字段。
                level=level,  # 写入告警等级字段。
                code="ENERGY_SPIKE" if current_value >= mean_value else "ENERGY_DROP",  # 根据偏离方向写入告警代码。
                message=f"{meter} 设备读数出现明显{direction_label}，当前值 {round(current_value, 4)}，相对均值偏离 {round(deviation_rate * 100, 2)}%。",  # 写入人类可读的告警描述。
                status=status,  # 写入告警状态字段。
                occurred_at=require_api_datetime(row["timestamp"]),  # 写入带台湾时区的告警发生时间。
            )  # 完成设备告警对象创建。
        )  # 完成当前告警追加。
    return alarms  # 返回完整设备告警列表。


def build_device_maintenance_items(building_id: str, meter: str) -> list[MaintenanceRecord]:  # 定义构造设备维护记录列表的函数。
    device_row = get_device_base_row_or_raise(building_id, meter)  # 先确认当前设备存在，并取到其聚合信息。
    reference_time = device_row.get("last_seen_at") or get_latest_timestamp([building_id], None, meter)  # 取设备最近一次活跃时间作为维护记录参考时间。
    device_id = build_device_id(building_id, meter)  # 先构造稳定设备编号，方便后面复用。
    record_defs = [  # 定义演示环境下要返回的维护记录模板。
        ("routine_check", "例行巡检", 30, "演示环境推导记录：基于设备最近活跃时间生成的例行巡检。"),  # 定义最近一次例行巡检记录。
        ("calibration", "计量校准", 120, "演示环境推导记录：用于前端联调的周期性计量校准记录。"),  # 定义计量校准记录。
        ("communication_check", "通讯检查", 240, "演示环境推导记录：用于前端联调的通讯链路健康检查记录。"),  # 定义通讯检查记录。
    ]  # 结束维护记录模板定义。
    items: list[MaintenanceRecord] = []  # 初始化维护记录列表。
    for index, (record_key, title, days_offset, description) in enumerate(record_defs, start=1):  # 遍历所有维护记录模板，并从 1 开始编号。
        performed_at = reference_time - timedelta(days=days_offset)  # 按模板要求推导当前记录的执行时间。
        items.append(  # 把当前维护记录对象追加到结果列表。
            MaintenanceRecord(  # 创建维护记录模型。
                record_id=f"{device_id}{DEVICE_ID_SEPARATOR}maintenance{DEVICE_ID_SEPARATOR}{record_key}{DEVICE_ID_SEPARATOR}{index}",  # 写入稳定维护记录编号。
                device_id=device_id,  # 写入设备编号字段。
                title=title,  # 写入维护标题字段。
                description=description,  # 写入维护描述字段。
                performed_at=require_api_datetime(performed_at),  # 写入带台湾时区的执行时间字段。
            )  # 完成维护记录模型创建。
        )  # 完成当前维护记录追加。
    return items  # 返回完整维护记录列表。


def get_devices(  # 定义设备列表查询接口业务函数。
    building_id: str | None,  # 接收建筑编号过滤参数。
    device_type: str | None,  # 接收设备类型过滤参数。
    status: str | None,  # 接收设备状态过滤参数。
    page: int,  # 接收页码参数。
    page_size: int,  # 接收每页条数参数。
) -> DeviceListResponse:  # 返回设备列表响应模型。
    clauses: list[str] = ["1=1"]  # 先放一个恒成立条件，方便后面统一拼接。
    params: dict[str, Any] = {}  # 初始化设备列表查询参数字典。
    normalized_building_id = normalize_text(building_id)  # 标准化建筑编号过滤参数。
    if normalized_building_id:  # 如果前端传了建筑编号，
        clauses.append("mr.building_id = :building_id")  # 就增加建筑过滤条件。
        params["building_id"] = normalized_building_id  # 把建筑编号写入参数字典。
    normalized_device_type = normalize_text(device_type)  # 标准化设备类型过滤参数。
    if normalized_device_type:  # 如果前端传了设备类型，
        clauses.append("mr.meter = :device_type")  # 就增加表计类型过滤条件。
        params["device_type"] = normalized_device_type  # 把设备类型写入参数字典。
    rows = fetch_all(  # 查询当前过滤条件下的设备聚合列表。
        f"""
        SELECT
            mr.building_id AS building_id,
            mr.meter AS device_type,
            MAX(mr.timestamp) AS last_seen_at,
            COUNT(*) AS reading_count,
            bm.yearbuilt AS yearbuilt
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {' AND '.join(clauses)}
        GROUP BY mr.building_id, mr.meter, bm.yearbuilt
        ORDER BY mr.building_id ASC, mr.meter ASC
        """,
        params,
    )  # 执行设备列表聚合查询。
    reference_latest = get_latest_timestamp()  # 先取全局最新时间，方便统一推导设备状态。
    items: list[Device] = []  # 初始化设备模型列表。
    for row in rows:  # 遍历设备聚合查询结果。
        items.append(map_device_row_to_model(row, reference_latest))  # 把当前结果映射成设备模型并追加进列表。
    normalized_status = normalize_text(status)  # 标准化设备状态过滤参数。
    if normalized_status:  # 如果前端传了设备状态过滤，
        items = [item for item in items if item.status.lower() == normalized_status.lower()]  # 就只保留状态命中的设备。
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)  # 标准化分页参数。
    paged_items = items[offset : offset + safe_page_size]  # 按分页参数截取当前页设备列表。
    return DeviceListResponse(  # 构造并返回设备列表响应。
        items=paged_items,  # 写入当前页设备列表字段。
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),  # 写入分页字段。
    )  # 完成设备列表响应构造。


def get_device_detail(device_id: str) -> DeviceDetailResponse:  # 定义设备详情查询接口业务函数。
    building_id, meter = parse_device_id(device_id)  # 先解析设备编号，拿到建筑编号和表计类型。
    device_row = get_device_base_row_or_raise(building_id, meter)  # 再查询当前设备的聚合信息，不存在时直接抛错。
    reference_latest = get_latest_timestamp()  # 取全局最新时间，方便推导设备状态。
    device = map_device_row_to_model(device_row, reference_latest)  # 把聚合结果映射成设备详情模型。
    recent_alarms = build_device_alarm_items(building_id, meter)[:DEVICE_RECENT_ALARM_LIMIT]  # 只取最近若干条告警用于详情页展示。
    recent_metrics = build_device_recent_metrics(building_id, meter)  # 构造设备详情页指标卡片。
    return DeviceDetailResponse(  # 构造并返回设备详情响应。
        device=device,  # 写入设备详情字段。
        recent_alarms=recent_alarms,  # 写入最近告警字段。
        recent_metrics=recent_metrics,  # 写入最近指标字段。
    )  # 完成设备详情响应构造。


def get_device_alarms(device_id: str, page: int, page_size: int) -> DeviceAlarmListResponse:  # 定义设备告警列表接口业务函数。
    building_id, meter = parse_device_id(device_id)  # 先解析设备编号。
    items = build_device_alarm_items(building_id, meter)  # 根据设备读数生成完整告警列表。
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)  # 标准化分页参数。
    paged_items = items[offset : offset + safe_page_size]  # 按分页参数截取当前页告警结果。
    return DeviceAlarmListResponse(  # 构造并返回设备告警列表响应。
        items=paged_items,  # 写入当前页告警列表字段。
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),  # 写入分页字段。
    )  # 完成设备告警列表响应构造。


def get_device_maintenance_records(device_id: str, page: int, page_size: int) -> MaintenanceRecordListResponse:  # 定义设备维护记录列表接口业务函数。
    building_id, meter = parse_device_id(device_id)  # 先解析设备编号。
    items = build_device_maintenance_items(building_id, meter)  # 构造当前设备的维护记录列表。
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size)  # 标准化分页参数。
    paged_items = items[offset : offset + safe_page_size]  # 按分页参数截取当前页维护记录。
    return MaintenanceRecordListResponse(  # 构造并返回维护记录列表响应。
        items=paged_items,  # 写入当前页维护记录列表字段。
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=len(items)),  # 写入分页字段。
    )  # 完成维护记录列表响应构造。
