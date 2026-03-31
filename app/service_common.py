import math  # 导入数学库，方便判断 NaN 等数值问题。
import re  # 导入正则库，方便兼容浏览器地址栏里未转义的时区时间字符串。
from datetime import datetime  # 导入日期时间类型，方便做时间计算。
from datetime import timedelta  # 导入时间差类型，方便补默认时间范围。
from typing import Any  # 导入任意类型注解，方便描述松散结构。
from zoneinfo import ZoneInfo  # 导入时区对象，方便统一转换到台湾标准时间。

from .database import build_in_clause  # 导入 IN 条件构造工具函数。
from .database import fetch_scalar  # 导入单值查询函数。
from .schemas import TimeRange  # 导入时间范围模型。


METER_UNIT_MAP = {  # 定义表计类型和默认单位的映射表。
    "electricity": "kWh",  # 电力默认使用千瓦时。
    "water": "m3",  # 水量默认使用立方米。
    "gas": "m3",  # 燃气默认使用立方米。
    "hotwater": "kWh",  # 热水这里先按演示口径返回千瓦时。
    "chilledwater": "kWh",  # 冷冻水这里先按演示口径返回千瓦时。
    "steam": "kWh",  # 蒸汽这里先按演示口径返回千瓦时。
    "solar": "kWh",  # 光伏发电默认使用千瓦时。
    "irrigation": "m3",  # 灌溉默认使用立方米。
}  # 结束单位映射定义。


GRANULARITY_MAP = {  # 定义允许使用的时间粒度映射表。
    "hour": "hour",  # 小时粒度直接映射到 PostgreSQL 的 hour。
    "day": "day",  # 天粒度直接映射到 PostgreSQL 的 day。
    "week": "week",  # 周粒度直接映射到 PostgreSQL 的 week。
    "month": "month",  # 月粒度直接映射到 PostgreSQL 的 month。
}  # 结束粒度映射定义。


TAIPEI_TZ = ZoneInfo("Asia/Taipei")  # 定义台湾标准时间时区对象，后续统一把接口时间转成这个时区。


class ResourceNotFoundError(Exception):  # 定义资源不存在异常。
    pass  # 当前异常类只负责区分 404 场景，不额外添加字段。


def get_taipei_now() -> datetime:  # 定义获取当前台湾时间的函数。
    return datetime.now(TAIPEI_TZ)  # 返回带有 Asia/Taipei 时区信息的当前时间。


def parse_datetime_input(value: datetime | str | None) -> datetime | None:  # 定义把前端传入的时间文本解析成 datetime 的函数。
    if value is None:  # 如果前端没有传时间，
        return None  # 就直接返回空。
    if isinstance(value, datetime):  # 如果当前已经是 datetime 对象，
        return value  # 就直接返回原对象。
    cleaned_value = value.strip()  # 先去掉首尾空白字符。
    if not cleaned_value:  # 如果清理后变成空字符串，
        return None  # 就按没传处理。
    if cleaned_value.endswith("Z"):  # 如果前端传的是 Z 结尾的 UTC 时间，
        cleaned_value = f"{cleaned_value[:-1]}+00:00"  # 就把它改成 Python fromisoformat 能识别的偏移格式。
    if re.search(r"T\d{2}:\d{2}:\d{2}\s\d{2}:\d{2}$", cleaned_value):  # 如果浏览器把 +08:00 解码成了空格 08:00，
        date_part, offset_part = cleaned_value.rsplit(" ", 1)  # 就拆出主体时间和时区偏移部分。
        cleaned_value = f"{date_part}+{offset_part}"  # 再把空格恢复成加号，兼容未转义的地址栏输入。
    try:  # 尝试按 ISO 时间解析。
        return datetime.fromisoformat(cleaned_value)  # 返回解析出的 datetime。
    except ValueError as exc:  # 如果解析失败，
        raise ValueError(f"非法时间格式: {value}") from exc  # 就抛出更容易看懂的中文错误。


def to_db_datetime(value: datetime | str | None) -> datetime | None:  # 定义把输入时间转换成数据库查询时间的函数。
    value = parse_datetime_input(value)  # 先把前端原始输入解析成 datetime。
    if value is None:  # 如果调用方没有传时间，
        return None  # 就直接返回空。
    if value.tzinfo is None:  # 如果传入的是无时区时间，
        return value  # 就按台湾本地时间原样使用。
    return value.astimezone(TAIPEI_TZ).replace(tzinfo=None)  # 如果传入的是带时区时间，就先转成台湾时间再去掉时区后查询数据库。


def to_api_datetime(value: datetime | None) -> datetime | None:  # 定义把数据库时间转换成接口输出时间的函数。
    if value is None:  # 如果当前时间为空，
        return None  # 就直接返回空。
    if value.tzinfo is None:  # 如果数据库返回的是无时区时间，
        return value.replace(tzinfo=TAIPEI_TZ)  # 就补上台湾标准时间时区信息。
    return value.astimezone(TAIPEI_TZ)  # 如果已经带时区，就统一转成台湾标准时间。


def require_api_datetime(value: datetime) -> datetime:  # 定义把必定存在的数据库时间转换成接口输出时间的函数。
    converted_value = to_api_datetime(value)  # 先复用通用转换函数把时间转成台湾标准时间。
    if converted_value is None:  # 如果理论上必填的时间却变成了空值，
        raise ValueError("时间字段不能为空")  # 就直接抛错，避免静默返回非法数据。
    return converted_value  # 返回已经确认非空的台湾标准时间。


def build_api_time_range(start_time: datetime, end_time: datetime) -> TimeRange:  # 定义构造带时区时间范围对象的函数。
    return TimeRange(  # 返回时间范围对象。
        start=require_api_datetime(start_time),  # 把开始时间转成台湾标准时间。
        end=require_api_datetime(end_time),  # 把结束时间转成台湾标准时间。
    )  # 完成时间范围对象创建。


def get_latest_timestamp(  # 定义获取最新时间的函数。
    building_ids: list[str] | None = None,  # 接收建筑编号列表，用于按过滤条件取最新时间。
    site_id: str | None = None,  # 接收园区编号，用于按过滤条件取最新时间。
    meter: str | None = None,  # 接收表计类型，用于按过滤条件取最新时间。
) -> datetime:  # 返回符合当前过滤条件的最新时间。
    where_clauses: list[str] = ["1=1"]  # 先放一个恒成立条件，方便后面统一拼接。
    params: dict[str, Any] = {}  # 初始化查询参数字典。
    if building_ids:  # 如果前端传了建筑列表，
        clause, clause_params = build_in_clause("mr.building_id", building_ids, "latest_building_id")  # 就构造建筑过滤条件。
        where_clauses.append(clause)  # 把建筑条件拼进 where 子句。
        params.update(clause_params)  # 把建筑参数写入字典。
    if site_id:  # 如果前端传了 site_id，
        where_clauses.append("bm.site_id = :latest_site_id")  # 就加上园区过滤条件。
        params["latest_site_id"] = site_id  # 把园区参数写入字典。
    if meter:  # 如果前端传了 meter，
        where_clauses.append("mr.meter = :latest_meter")  # 就加上表计过滤条件。
        params["latest_meter"] = meter  # 把表计参数写入字典。
    latest_timestamp = fetch_scalar(  # 查询符合当前过滤条件的最大时间。
        f"""
        SELECT MAX(mr.timestamp)
        FROM meter_readings mr
        LEFT JOIN building_metadata bm ON mr.building_id = bm.building_id
        WHERE {' AND '.join(where_clauses)}
        """,
        params,
    )  # 执行最大时间查询。
    return latest_timestamp or get_taipei_now().replace(tzinfo=None)  # 如果查不到数据，就退回当前台湾时间的无时区版本。


def resolve_time_range(  # 定义补齐时间范围的函数。
    start_time: datetime | str | None,  # 接收开始时间。
    end_time: datetime | str | None,  # 接收结束时间。
    building_ids: list[str] | None = None,  # 接收建筑编号列表，方便按当前过滤条件补默认时间。
    site_id: str | None = None,  # 接收园区编号，方便按当前过滤条件补默认时间。
    meter: str | None = None,  # 接收表计类型，方便按当前过滤条件补默认时间。
) -> tuple[datetime, datetime]:  # 返回补齐后的开始和结束时间。
    normalized_start = to_db_datetime(start_time)  # 先把开始时间标准化成数据库使用的时间格式。
    normalized_end = to_db_datetime(end_time)  # 先把结束时间标准化成数据库使用的时间格式。
    latest_timestamp = get_latest_timestamp(building_ids, site_id, meter)  # 先取符合当前过滤条件的最新时间。
    resolved_end = normalized_end or latest_timestamp  # 如果没传结束时间，就默认取最新时间。
    resolved_start = normalized_start or (resolved_end - timedelta(days=7))  # 如果没传开始时间，就默认向前推 7 天。
    return resolved_start, resolved_end  # 返回最终时间范围。


def normalize_meter(meter: str | None) -> str:  # 定义标准化表计类型的函数。
    return meter or "electricity"  # 如果没有传表计类型，就默认按电表处理。


def normalize_granularity(granularity: str | None) -> str:  # 定义标准化粒度的函数。
    return GRANULARITY_MAP.get((granularity or "day").lower(), "day")  # 如果粒度非法，就回退到 day。


def get_meter_unit(meter: str | None) -> str:  # 定义取表计单位的函数。
    return METER_UNIT_MAP.get(meter or "", "")  # 从映射表里查单位，查不到就返回空字符串。


def normalize_text(value: Any) -> str | None:  # 定义把任意输入值标准化成非空文本的函数。
    if value is None:  # 如果输入本身就是空值，
        return None  # 就直接返回空。
    text_value = str(value).strip()  # 先把输入转成字符串并清理首尾空白。
    if not text_value:  # 如果清理后变成空字符串，
        return None  # 就按空值处理。
    if text_value.lower() == "none":  # 如果文本其实是字面量 None，
        return None  # 也按空值处理。
    return text_value  # 返回标准化后的文本值。


def normalize_optional_float(value: Any) -> float | None:  # 定义把任意输入值标准化成浮点数的函数。
    if value is None:  # 如果输入本身为空，
        return None  # 就直接返回空。
    try:  # 尝试把输入转换成浮点数。
        normalized_value = float(value)  # 执行浮点数转换。
    except (TypeError, ValueError):  # 如果无法转换成浮点数，
        return None  # 就按空值处理。
    if math.isnan(normalized_value):  # 如果转换结果是 NaN，
        return None  # 也按空值处理。
    return normalized_value  # 返回已经确认有效的浮点数。


def normalize_optional_int(value: Any) -> int | None:  # 定义把任意输入值标准化成整数的函数。
    normalized_value = normalize_optional_float(value)  # 先复用浮点标准化函数。
    if normalized_value is None:  # 如果浮点标准化后为空，
        return None  # 就直接返回空。
    return int(normalized_value)  # 返回转成整数后的结果。


def normalize_metadata_flag(value: Any) -> bool:  # 定义把元数据里是否有表计的字段转成布尔值的函数。
    normalized_text = normalize_text(value)  # 先把原始值标准化成文本。
    if normalized_text is None:  # 如果标准化后为空，
        return False  # 就说明当前字段不表示可用。
    return normalized_text.lower() in {"yes", "true", "1", "y"}  # 只把明确表示肯定的值视为可用。


def normalize_pagination(  # 定义标准化分页参数的函数。
    page: int,  # 接收页码参数。
    page_size: int,  # 接收每页条数参数。
    max_page_size: int = 200,  # 接收每页最大条数限制。
) -> tuple[int, int, int]:  # 返回标准化后的页码、每页条数和偏移量。
    safe_page = max(page, 1)  # 防止页码传成小于 1 的非法值。
    safe_page_size = max(1, min(page_size, max_page_size))  # 防止 page_size 传成非法值或过大值。
    offset = (safe_page - 1) * safe_page_size  # 按标准分页公式计算偏移量。
    return safe_page, safe_page_size, offset  # 返回完整分页结果。
