import math
import os  # 导入数学库，方便判断 NaN 等数值问题。
import re  # 导入正则库，方便兼容浏览器地址栏里未转义的时区时间字符串。
from datetime import datetime  # 导入日期时间类型，方便做时间计算。
from datetime import timedelta  # 导入时间差类型，方便补默认时间范围。
from typing import Any  # 导入任意类型注解，方便描述松散结构。
from zoneinfo import ZoneInfo  # 导入时区对象，方便统一转换到UTC+8标准时间。

from app.core.database import build_in_clause  # 导入 IN 条件构造工具函数。
from app.core.database import fetch_one  # 导入单行查询函数，方便查询表计时间范围等元信息。
from app.core.database import fetch_scalar  # 导入单值查询函数。
from app.schemas.schemas_common import DataStatus  # 导入通用数据状态枚举，方便统一表达缺失/估算/过滤。
from app.schemas.schemas_common import TimeRange  # 导入时间范围模型。


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


APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
APP_TZ = ZoneInfo(APP_TIMEZONE_NAME)


class ResourceNotFoundError(Exception):  # 定义资源不存在异常。
    pass  # 当前异常类只负责区分 404 场景，不额外添加字段。


def get_app_timezone_name() -> str:
    """返回当前应用默认时区名称。"""

    return APP_TIMEZONE_NAME


def resolve_timezone(value: str | None) -> ZoneInfo:
    """将前端传入的时区字符串转换成合法的 ZoneInfo。"""

    if value is None or not str(value).strip():
        return APP_TZ
    timezone_name = str(value).strip()
    try:
        return ZoneInfo(timezone_name)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"非法时区: {timezone_name}") from exc


def get_app_now(timezone: str | None = None) -> datetime:
    """根据可选时区返回当前时间。"""

    return datetime.now(resolve_timezone(timezone))


def get_timezone_now() -> datetime:  # 兼容旧调用点，内部统一走应用默认时区。
    return get_app_now()


def resolve_effective_current_time(
    *,
    use_current_time: bool = True,
    current_time: datetime | str | None = None,
    timezone: str | None = None,
) -> datetime:
    """统一解析“当前时间”。

    1. use_current_time=true 时直接使用后端当前时间。
    2. use_current_time=false 时使用前端指定的 current_time。
    3. custom current_time 没有时区时，按前端指定时区补齐。
    """

    effective_tz = resolve_timezone(timezone)
    if use_current_time:
        return datetime.now(effective_tz)

    parsed_time = parse_datetime_input(current_time)
    if parsed_time is None:
        raise ValueError("use_current_time=false 时必须传 current_time。")
    if parsed_time.tzinfo is None:
        return parsed_time.replace(tzinfo=effective_tz)
    return parsed_time.astimezone(effective_tz)


def resolve_request_current_time(payload: Any) -> datetime:
    """从请求模型中统一提取当前时间上下文。"""

    return resolve_effective_current_time(
        use_current_time=bool(getattr(payload, "use_current_time", True)),
        current_time=getattr(payload, "current_time", None),
        timezone=getattr(payload, "timezone", None),
    )


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
        return value  # 就按UTC+8本地时间原样使用。
    return value.astimezone(APP_TZ).replace(tzinfo=None)  # 如果传入的是带时区时间，就先转成UTC+8时间再去掉时区后查询数据库。


def to_api_datetime(value: datetime | None) -> datetime | None:  # 定义把数据库时间转换成接口输出时间的函数。
    if value is None:  # 如果当前时间为空，
        return None  # 就直接返回空。
    if value.tzinfo is None:  # 如果数据库返回的是无时区时间，
        return value.replace(tzinfo=APP_TZ)  # 就补上UTC+8标准时间时区信息。
    return value.astimezone(APP_TZ)  # 如果已经带时区，就统一转成UTC+8标准时间。


def require_api_datetime(value: datetime) -> datetime:  # 定义把必定存在的数据库时间转换成接口输出时间的函数。
    converted_value = to_api_datetime(value)  # 先复用通用转换函数把时间转成UTC+8标准时间。
    if converted_value is None:  # 如果理论上必填的时间却变成了空值，
        raise ValueError("时间字段不能为空")  # 就直接抛错，避免静默返回非法数据。
    return converted_value  # 返回已经确认非空的UTC+8标准时间。


def build_api_time_range(start_time: datetime, end_time: datetime) -> TimeRange:  # 定义构造带时区时间范围对象的函数。
    return TimeRange(  # 返回时间范围对象。
        start=require_api_datetime(start_time),  # 把开始时间转成UTC+8标准时间。
        end=require_api_datetime(end_time),  # 把结束时间转成UTC+8标准时间。
    )  # 完成时间范围对象创建。


def get_latest_timestamp(  # ????????????
    building_ids: list[str] | None = None,  # ??????????????????????
    site_id: str | None = None,  # ????????????????????
    meter: str | None = None,  # ????????????????????
) -> datetime:  # ????????????????
    where_clauses: list[str] = ["1=1"]  # ???????????????????
    params: dict[str, Any] = {}  # ??????????
    if meter:  # ?????? meter?
        where_clauses.append("mr.meter = :latest_meter")  # ??????????
        params["latest_meter"] = meter  # ??????????
    if building_ids:  # ???????????
        clause, clause_params = build_in_clause("mr.building_id", building_ids, "latest_building_id")  # ?????????
        where_clauses.append(clause)  # ??????? where ???
        params.update(clause_params)  # ??????????

    if site_id:  # ????????????????? building_metadata?
        where_clauses.append("bm.site_id = :latest_site_id")  # ?????????
        params["latest_site_id"] = site_id  # ??????????
        latest_timestamp = fetch_scalar(
            f"""
            SELECT mr.timestamp
            FROM meter_readings mr
            JOIN building_metadata bm ON mr.building_id = bm.building_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY mr.timestamp DESC
            LIMIT 1
            """,
            params,
        )  # ????????????? MAX+JOIN ???????
    else:
        latest_timestamp = fetch_scalar(
            f"""
            SELECT mr.timestamp
            FROM meter_readings mr
            WHERE {' AND '.join(where_clauses)}
            ORDER BY mr.timestamp DESC
            LIMIT 1
            """,
            params,
        )  # ????????? meter_readings ?????????
    return latest_timestamp or get_app_now().replace(tzinfo=None)  # ????????????? UTC+8 ?????????


def resolve_time_range(  # ????????????
    start_time: datetime | str | None,  # ???????
    end_time: datetime | str | None,  # ???????
    building_ids: list[str] | None = None,  # ????????????????????????
    site_id: str | None = None,  # ??????????????????????
    meter: str | None = None,  # ??????????????????????
) -> tuple[datetime, datetime]:  # ??????????????
    normalized_start = to_db_datetime(start_time)  # ?????????????????????
    normalized_end = to_db_datetime(end_time)  # ?????????????????????
    resolved_end = normalized_end  # ????????????????
    if resolved_end is None:  # ?????????????????????
        resolved_end = get_latest_timestamp(building_ids, site_id, meter)  # ??????????????????????
    resolved_start = normalized_start or (resolved_end - timedelta(days=7))  # ??????????????? 7 ??
    return resolved_start, resolved_end  # ?????????


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


def empty_string_to_none(value: Any) -> Any:  # 定义把空字符串转换成空值的函数。
    if isinstance(value, str) and not value.strip():  # 如果传入的是空字符串或全空白字符串，
        return None  # 就把它转换成真正的空值，方便接口继续走默认值。
    return value  # 其余情况原样返回。


def coerce_blank_to_default(default_value: int):  # 定义把空字符串转换成指定默认整数的工厂函数。
    def converter(value: Any) -> Any:  # 返回真正执行转换的函数。
        if isinstance(value, str) and not value.strip():  # 如果传入的是空字符串或全空白字符串，
            return default_value  # 就直接回退到约定默认值。
        return value  # 其余情况原样返回。

    return converter  # 返回转换函数，供 BeforeValidator 复用。


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


def round_optional_float(value: Any, digits: int = 4) -> float | None:  # 定义把可空数值安全四舍五入的函数。
    normalized_value = normalize_optional_float(value)  # 先把原始值标准化成浮点数。
    if normalized_value is None:  # 如果标准化后仍然为空，
        return None  # 就直接返回空，避免把缺失值误写成 0。
    return round(normalized_value, digits)  # 返回保留指定位数小数后的结果。


def resolve_numeric_data_status(  # 定义统一判定数值数据状态的函数。
    *,  # 强制后续参数必须使用关键字传参，避免调用时把语义传乱。
    has_data: bool,  # 接收当前值是否真的有源数据支撑。
    estimated: bool = False,  # 接收当前值是否属于估算值。
    filtered: bool = False,  # 接收当前值是否因异常范围被过滤。
) -> DataStatus:  # 返回统一的数据状态枚举。
    if filtered:  # 如果当前值被规则过滤掉，
        return DataStatus.filtered  # 就返回 filtered 状态。
    if not has_data:  # 如果当前值没有任何源数据，
        return DataStatus.missing  # 就返回 missing 状态。
    if estimated:  # 如果当前值是基于规则估算得到，
        return DataStatus.estimated  # 就返回 estimated 状态。
    return DataStatus.valid  # 其余情况统一视为真实有效数据。


def truncate_datetime_by_granularity(value: datetime, granularity: str) -> datetime:  # 定义按粒度截断时间的函数。
    if granularity == "hour":  # 如果当前粒度是小时，
        return value.replace(minute=0, second=0, microsecond=0)  # 就把时间对齐到整点。
    if granularity == "day":  # 如果当前粒度是天，
        return value.replace(hour=0, minute=0, second=0, microsecond=0)  # 就把时间对齐到当天 00:00。
    if granularity == "week":  # 如果当前粒度是周，
        day_start = value.replace(hour=0, minute=0, second=0, microsecond=0)  # 先把时间对齐到当天 00:00。
        return day_start - timedelta(days=day_start.weekday())  # 再把时间回退到本周周一 00:00。
    if granularity == "month":  # 如果当前粒度是月，
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)  # 就把时间对齐到当月第一天 00:00。
    return value.replace(hour=0, minute=0, second=0, microsecond=0)  # 其余非法值统一按天粒度处理。


def advance_datetime_by_granularity(value: datetime, granularity: str) -> datetime:  # 定义按粒度推进时间的函数。
    if granularity == "hour":  # 如果当前粒度是小时，
        return value + timedelta(hours=1)  # 就向后推进 1 小时。
    if granularity == "day":  # 如果当前粒度是天，
        return value + timedelta(days=1)  # 就向后推进 1 天。
    if granularity == "week":  # 如果当前粒度是周，
        return value + timedelta(weeks=1)  # 就向后推进 1 周。
    if granularity == "month":  # 如果当前粒度是月，
        next_month_anchor = value.replace(day=28) + timedelta(days=4)  # 先稳定跳到下个月。
        return next_month_anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)  # 再回到下个月第一天 00:00。
    return value + timedelta(days=1)  # 其余非法值统一按天推进。


def build_expected_time_buckets(start_time: datetime, end_time: datetime, granularity: str) -> list[datetime]:  # 定义按粒度构造完整时间桶列表的函数。
    if end_time < start_time:  # 如果结束时间早于开始时间，
        return []  # 就直接返回空列表，避免后续死循环。
    bucket_start = truncate_datetime_by_granularity(start_time, granularity)  # 先把开始时间对齐到对应粒度。
    bucket_end = truncate_datetime_by_granularity(end_time, granularity)  # 再把结束时间对齐到对应粒度。
    buckets: list[datetime] = []  # 初始化完整时间桶列表。
    current_bucket = bucket_start  # 把当前游标设为起始时间桶。
    while current_bucket <= bucket_end:  # 只要当前时间桶还没有超过结束时间桶，
        buckets.append(current_bucket)  # 就把当前时间桶写入结果列表。
        current_bucket = advance_datetime_by_granularity(current_bucket, granularity)  # 再推进到下一个时间桶。
    return buckets  # 返回最终完整时间桶列表。


def get_meter_time_bounds(building_id: str, meter: str) -> dict[str, Any]:  # 定义查询单个建筑单个表计时间范围的函数。
    row = fetch_one(  # 查询当前建筑当前表计的最早时间、最晚时间和读数条数。
        """
        SELECT
            MIN(timestamp) AS min_timestamp,
            MAX(timestamp) AS max_timestamp,
            COUNT(*) AS reading_count
        FROM meter_readings
        WHERE building_id = :building_id
          AND meter = :meter
        """,
        {"building_id": building_id, "meter": meter},
    ) or {}  # 如果完全查不到，就回退到空字典。
    return {  # 返回统一结构，方便 COP 和其他时序接口复用。
        "min_timestamp": row.get("min_timestamp"),  # 写入最早时间。
        "max_timestamp": row.get("max_timestamp"),  # 写入最晚时间。
        "reading_count": int(row.get("reading_count") or 0),  # 写入读数条数。
    }  # 完成时间范围结果构造。


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



