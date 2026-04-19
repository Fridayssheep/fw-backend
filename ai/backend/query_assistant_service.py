from __future__ import annotations

import re
from datetime import datetime
from datetime import timedelta
from typing import Any

from app.schemas import AIQueryAssistantMeta
from app.schemas import AIQueryAssistantFilters
from app.schemas import AIQueryAssistantPlan
from app.schemas import AIQueryAssistantRequest
from app.schemas import AIQueryAssistantResponse
from app.schemas import AIQueryAssistantUIPatch
from app.schemas import AIQueryIntent
from app.schemas import TimeRange
from app.services.service_common import build_api_time_range
from app.services.service_common import get_timezone_now
from app.services.service_common import normalize_granularity
from app.services.service_common import normalize_meter
from app.services.service_common import resolve_request_current_time

from .config import get_ai_settings
from .llm_client import OpenAICompatibleClient
from .prompting import build_query_assistant_prompts


# ============================================================================
# 查询助手核心业务逻辑模块
# 主要功能：
#   1. 解析自然语言查询，提取关键信息（表计类型、时间范围、粒度等）
#   2. 通过规则和 LLM 两种方式构建查询意图
#   3. 推荐合适的后端查询 API 端点和查询参数
#   4. 提供 fallback 机制确保查询意图总能被解析
# ============================================================================


ALLOWED_QUERY_ENDPOINTS = {
    '/energy/query',
    '/energy/trend',
    '/energy/compare',
    '/energy/rankings',
    '/energy/weather-correlation',
    '/energy/anomaly-analysis',
}
BUILDING_QUERY_ENDPOINT = '/buildings'
ALLOWED_BUILDING_QUERY_ENDPOINTS = {BUILDING_QUERY_ENDPOINT}

METER_KEYWORDS = {
    'electricity': ('电耗', '电能', '用电', '电量', 'electricity', 'power'),
    'water': ('水耗', '用水', 'water'),
    'gas': ('气耗', '燃气', 'gas'),
    'steam': ('蒸汽', 'steam'),
    'chilledwater': ('冷冻水', '冷量', 'chilledwater'),
    'hotwater': ('热水', 'hotwater'),
}
PRIMARY_SPACE_KEYWORDS = {
    'Office': ('办公', '办公楼', 'office'),
    'Retail': ('零售', '商业', '商场', 'retail'),
    'Education': ('教育', '学校', '教学', 'education'),
    'Healthcare': ('医疗', '医院', 'healthcare'),
}
BUILDING_STATUS_KEYWORDS = {
    'normal': ('正常', '正常运行', '运行正常'),
    'warning': ('告警', '预警', 'warning'),
    'fault': ('故障', '停机', 'fault'),
    'offline': ('离线', '掉线', 'offline'),
}
BUILDING_QUERY_SORT_FIELDS = {
    'eui': ('eui', '能效', '能耗强度'),
    'totalEnergy': ('总能耗', '能耗总量', 'energy'),
    'carbonEmission': ('碳排放', 'carbon'),
    'status': ('状态', '系统状态'),
}
BUILDING_QUERY_SEMANTIC_MARKERS = (
    '偏高',
    '偏低',
    '较高',
    '较低',
    '更高',
    '更低',
    '表现差',
    '表现好',
    '异常多',
    '问题多',
    '耗能高',
    '耗能低',
    '费电',
    '费能',
    '排除',
    '除了',
    '不要',
    '不看',
    '优先',
    '类似',
    '相关',
    '这一类',
    '那一类',
    '符合',
    '满足',
    '帮我找',
    '想看',
)

DATE_TOKEN_REGEX = r'(\d{4})(?:[-/.年])(\d{1,2})(?:[-/.月])(\d{1,2})日?'
DATE_TOKEN_PATTERN = re.compile(DATE_TOKEN_REGEX)
DATE_RANGE_PATTERN = re.compile(
    rf'(?P<start>{DATE_TOKEN_REGEX})\s*(?:到|至|~|～)\s*(?P<end>{DATE_TOKEN_REGEX})'
)
SITE_ID_PATTERN = re.compile(r'\bsite[_-]?[A-Za-z0-9]+\b', flags=re.IGNORECASE)


def _now_with_tz(request: AIQueryAssistantRequest) -> datetime:
    # 统一按前端提供的时间上下文解析“现在”，避免 AI 和页面时间基准不一致。
    return resolve_request_current_time(request)


def _extract_meter(question: str) -> str | None:
    lowered = question.lower()
    for meter, keywords in METER_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return meter
    return None


def _extract_granularity(question: str) -> str | None:
    lowered = question.lower()
    if any(keyword in lowered for keyword in ('每小时', '小时', '逐小时', 'hour')):
        return 'hour'
    if any(keyword in lowered for keyword in ('每天', '每日', '天', 'day')):
        return 'day'
    if any(keyword in lowered for keyword in ('每周', '周', 'week')):
        return 'week'
    if any(keyword in lowered for keyword in ('每月', '月', 'month')):
        return 'month'
    return None


def _extract_limit(question: str) -> int | None:
    match = re.search(r'(?:top|前)\s*(\d+)', question, flags=re.IGNORECASE)
    if not match:
        return None
    return max(1, min(int(match.group(1)), 100))


def _extract_order(question: str) -> str | None:
    lowered = question.lower()
    if any(keyword in lowered for keyword in ("最低", "最小", "升序", "asc")):
        return "asc"
    if any(keyword in lowered for keyword in ("最高", "最大", "降序", "desc")):
        return "desc"
    return None


def _extract_building_ids(question: str) -> list[str]:
    # Capture common dataset identifiers such as Bear_assembly_Angel.
    building_candidates = re.findall(r'\b[A-Za-z]+(?:_[A-Za-z0-9]+)+\b', question)
    unique_items: list[str] = []
    for item in building_candidates:
        if item not in unique_items:
            unique_items.append(item)
    return unique_items


def _extract_keyword(question: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    building_ids = _extract_building_ids(question)
    if len(building_ids) >= 2:
        warnings.append('查询页当前仅支持单次聚焦一组筛选，已优先采用第一个建筑关键词。')
    if building_ids:
        return building_ids[0], warnings
    quoted_match = re.search(r'[“"](.*?)[”"]', question)
    if quoted_match and quoted_match.group(1).strip():
        return quoted_match.group(1).strip(), warnings
    return None, warnings


def _extract_site_id(question: str) -> str | None:
    match = SITE_ID_PATTERN.search(question)
    if not match:
        return None
    return match.group(0)


def _extract_primaryspaceusage(question: str) -> str | None:
    lowered = question.lower()
    for usage, keywords in PRIMARY_SPACE_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return usage
    return None


def _extract_status(question: str) -> str | None:
    lowered = question.lower()
    for status, keywords in BUILDING_STATUS_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return status
    return None


def _extract_sort_field(question: str) -> str | None:
    lowered = question.lower()
    for field, keywords in BUILDING_QUERY_SORT_FIELDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return field
    return None


def _normalize_primaryspaceusage(value: Any) -> str | None:
    if value in (None, ''):
        return None
    lowered = str(value).strip().lower()
    if not lowered:
        return None
    for usage, keywords in PRIMARY_SPACE_KEYWORDS.items():
        if lowered == usage.lower():
            return usage
        if any(keyword.lower() == lowered for keyword in keywords):
            return usage
        if any(keyword.lower() in lowered for keyword in keywords):
            return usage
    return None


def _normalize_building_status(value: Any) -> str | None:
    if value in (None, ''):
        return None
    lowered = str(value).strip().lower()
    if not lowered:
        return None
    for status, keywords in BUILDING_STATUS_KEYWORDS.items():
        if lowered == status:
            return status
        if any(keyword.lower() == lowered for keyword in keywords):
            return status
        if any(keyword.lower() in lowered for keyword in keywords):
            return status
    return None


def _normalize_building_query_sort_field(value: Any) -> str | None:
    if value in (None, ''):
        return None
    lowered = str(value).strip().lower()
    if not lowered:
        return None
    for field, keywords in BUILDING_QUERY_SORT_FIELDS.items():
        if lowered == field.lower():
            return field
        if any(keyword.lower() == lowered for keyword in keywords):
            return field
        if any(keyword.lower() in lowered for keyword in keywords):
            return field
    return None


def _normalize_sort_order(value: Any) -> str | None:
    if value in (None, ''):
        return None
    lowered = str(value).strip().lower()
    if lowered in {'asc', 'ascending'}:
        return 'asc'
    if lowered in {'desc', 'descending'}:
        return 'desc'
    if any(keyword in lowered for keyword in ('升序', '最低', '最小', '从低到高', '由低到高')):
        return 'asc'
    if any(keyword in lowered for keyword in ('降序', '最高', '最大', '从高到低', '由高到低')):
        return 'desc'
    return None


def _coerce_float(value: Any, fallback: float | None = None) -> float | None:
    if value in (None, ''):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(',', '').strip())
    except ValueError:
        return fallback


def _coerce_int(value: Any, fallback: int | None = None) -> int | None:
    if value in (None, ''):
        return fallback
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).replace(',', '').strip()))
    except ValueError:
        return fallback


def _extract_metric_range(question: str, keywords: tuple[str, ...]) -> tuple[float | None, float | None]:
    lowered = question.lower()
    if not any(keyword.lower() in lowered for keyword in keywords):
        return None, None

    escaped_keywords = "|".join(re.escape(keyword) for keyword in keywords)
    range_match = re.search(
        rf'(?:{escaped_keywords}).*?(\d+(?:\.\d+)?)\s*(?:到|至|~|～|-)\s*(\d+(?:\.\d+)?)',
        question,
        flags=re.IGNORECASE,
    )
    if range_match:
        left = float(range_match.group(1))
        right = float(range_match.group(2))
        return (left, right) if left <= right else (right, left)

    min_match = re.search(
        rf'(?:{escaped_keywords}).*?(?:大于|高于|超过|不少于|不低于|>=)\s*(\d+(?:\.\d+)?)',
        question,
        flags=re.IGNORECASE,
    )
    max_match = re.search(
        rf'(?:{escaped_keywords}).*?(?:小于|低于|少于|不高于|不超过|<=)\s*(\d+(?:\.\d+)?)',
        question,
        flags=re.IGNORECASE,
    )
    min_value = float(min_match.group(1)) if min_match else None
    max_value = float(max_match.group(1)) if max_match else None
    return min_value, max_value


def _parse_date_token(raw_value: str, now: datetime) -> datetime | None:
    """把问题里的显式日期文本解析成当天起始时间。"""

    match = DATE_TOKEN_PATTERN.fullmatch(raw_value.strip())
    if not match:
        return None

    try:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return datetime(
            year,
            month,
            day,
            0,
            0,
            0,
            tzinfo=now.tzinfo,
        )
    except ValueError:
        return None


def _resolve_explicit_time_range(question: str, now: datetime) -> TimeRange | None:
    """优先解析问题中显式给出的绝对日期范围。"""

    range_match = DATE_RANGE_PATTERN.search(question)
    if range_match:
        start = _parse_date_token(range_match.group('start'), now)
        end = _parse_date_token(range_match.group('end'), now)
        if start and end and start <= end:
            return build_api_time_range(
                start,
                end.replace(hour=23, minute=59, second=59, microsecond=0),
            )

    date_matches = [match.group(0) for match in DATE_TOKEN_PATTERN.finditer(question)]
    unique_dates: list[str] = []
    for item in date_matches:
        if item not in unique_dates:
            unique_dates.append(item)

    if len(unique_dates) >= 2:
        start = _parse_date_token(unique_dates[0], now)
        end = _parse_date_token(unique_dates[1], now)
        if start and end and start <= end:
            return build_api_time_range(
                start,
                end.replace(hour=23, minute=59, second=59, microsecond=0),
            )

    if len(unique_dates) == 1:
        single_day = _parse_date_token(unique_dates[0], now)
        if single_day:
            return build_api_time_range(
                single_day,
                single_day.replace(hour=23, minute=59, second=59, microsecond=0),
            )

    return None


def _resolve_time_range(question: str, now: datetime) -> tuple[TimeRange, list[str]]:
    warnings: list[str] = []
    explicit_time_range = _resolve_explicit_time_range(question, now)
    if explicit_time_range is not None:
        return explicit_time_range, warnings

    text = question.lower()
    if any(keyword in text for keyword in ('今天', 'today')):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif any(keyword in text for keyword in ('昨天', 'yesterday')):
        base = now - timedelta(days=1)
        start = base.replace(hour=0, minute=0, second=0, microsecond=0)
        end = base.replace(hour=23, minute=59, second=59, microsecond=0)
    elif any(keyword in text for keyword in ('最近7天', '近7天', 'last 7 days')):
        end = now
        start = end - timedelta(days=7)
    elif any(keyword in text for keyword in ('最近30天', '近30天', 'last 30 days')):
        end = now
        start = end - timedelta(days=30)
    elif '上周' in text:
        week_start = (now - timedelta(days=now.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
        start = week_start
        end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    elif '本周' in text:
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif '本月' in text:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif '上个月' in text:
        last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
        start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = last_month_end
    else:
        end = now
        start = end - timedelta(days=7)
        warnings.append('未明确时间范围，已按最近7天处理。')
    return build_api_time_range(start, end), warnings


def _merge_with_current_filters(
    payload: AIQueryAssistantRequest,
    *,
    building_ids: list[str],
    meter: str | None,
    time_range: TimeRange | None,
    granularity: str | None,
    metric: str | None,
    limit: int | None,
    order: str | None,
) -> tuple[list[str], str | None, TimeRange | None, str | None, str | None, int | None, str | None, list[str]]:
    warnings: list[str] = []
    current_filters = payload.current_filters
    if current_filters is None:
        return building_ids, meter, time_range, granularity, metric, limit, order, warnings

    merged_building_ids = building_ids or current_filters.building_ids
    merged_meter = meter or current_filters.meter
    merged_time_range = time_range or current_filters.time_range
    merged_granularity = granularity or current_filters.granularity
    merged_metric = metric or current_filters.metric
    merged_limit = limit or current_filters.limit
    merged_order = order or current_filters.order

    if not building_ids and current_filters.building_ids:
        warnings.append("未明确建筑范围，已沿用当前页面建筑筛选。")
    if meter is None and current_filters.meter:
        warnings.append("未明确表计类型，已沿用当前页面表计筛选。")
    if time_range is None and current_filters.time_range:
        warnings.append("未明确时间范围，已沿用当前页面时间筛选。")
    if granularity is None and current_filters.granularity:
        warnings.append("未明确时间粒度，已沿用当前页面粒度。")
    return (
        merged_building_ids,
        merged_meter,
        merged_time_range,
        merged_granularity,
        merged_metric,
        merged_limit,
        merged_order,
        warnings,
    )


def _merge_building_query_with_current_filters(
    payload: AIQueryAssistantRequest,
    *,
    keyword: str | None,
    site_id: str | None,
    primaryspaceusage: str | None,
    status: str | None,
    time_range: TimeRange | None,
    min_energy: float | None,
    max_energy: float | None,
    min_eui: float | None,
    max_eui: float | None,
    min_carbon: float | None,
    max_carbon: float | None,
    sort_by: str | None,
    sort_order: str | None,
) -> tuple[str | None, str | None, str | None, str | None, TimeRange | None, float | None, float | None, float | None, float | None, float | None, float | None, str | None, str | None, list[str]]:
    warnings: list[str] = []
    current_filters = payload.current_filters
    if current_filters is None:
        return (
            keyword,
            site_id,
            primaryspaceusage,
            status,
            time_range,
            min_energy,
            max_energy,
            min_eui,
            max_eui,
            min_carbon,
            max_carbon,
            sort_by,
            sort_order,
            warnings,
        )

    merged_keyword = keyword or current_filters.keyword
    merged_site_id = site_id or current_filters.site_id
    merged_primaryspaceusage = primaryspaceusage or current_filters.primaryspaceusage
    merged_status = status or current_filters.status
    merged_time_range = time_range or current_filters.time_range
    merged_min_energy = min_energy if min_energy is not None else current_filters.min_energy
    merged_max_energy = max_energy if max_energy is not None else current_filters.max_energy
    merged_min_eui = min_eui if min_eui is not None else current_filters.min_eui
    merged_max_eui = max_eui if max_eui is not None else current_filters.max_eui
    merged_min_carbon = min_carbon if min_carbon is not None else current_filters.min_carbon
    merged_max_carbon = max_carbon if max_carbon is not None else current_filters.max_carbon
    merged_sort_by = sort_by or current_filters.sort_by
    merged_sort_order = sort_order or current_filters.sort_order

    if keyword is None and current_filters.keyword:
        warnings.append("未明确建筑关键词，已沿用当前页面关键词筛选。")
    if site_id is None and current_filters.site_id:
        warnings.append("未明确站点范围，已沿用当前页面站点筛选。")
    if primaryspaceusage is None and current_filters.primaryspaceusage:
        warnings.append("未明确建筑用途，已沿用当前页面用途筛选。")
    if status is None and current_filters.status:
        warnings.append("未明确建筑状态，已沿用当前页面状态筛选。")
    if time_range is None and current_filters.time_range:
        warnings.append("未明确时间范围，已沿用当前页面时间筛选。")
    return (
        merged_keyword,
        merged_site_id,
        merged_primaryspaceusage,
        merged_status,
        merged_time_range,
        merged_min_energy,
        merged_max_energy,
        merged_min_eui,
        merged_max_eui,
        merged_min_carbon,
        merged_max_carbon,
        merged_sort_by,
        merged_sort_order,
        warnings,
    )


def _recommend_endpoint(question: str, intent: AIQueryIntent, target_scope: str = "energy") -> str:
    if target_scope == "building_query":
        return BUILDING_QUERY_ENDPOINT
    lowered = question.lower()
    building_count = len(intent.building_ids)
    if any(keyword in lowered for keyword in ('异常', '告警', '诊断', 'anomaly')):
        return '/energy/anomaly-analysis'
    if any(keyword in lowered for keyword in ('天气', '相关性', '气温', 'weather')):
        return '/energy/weather-correlation'
    if any(keyword in lowered for keyword in ('排名', '排行', 'top', '最高', '最低')):
        return '/energy/rankings'
    if building_count >= 2 or any(keyword in lowered for keyword in ('对比', '比较', 'compare', 'vs')):
        return '/energy/compare'
    if any(keyword in lowered for keyword in ('明细', '列表', '原始', 'detail', 'list')):
        return '/energy/query'
    if any(keyword in lowered for keyword in ('趋势', '变化', '曲线', 'trend')):
        return '/energy/trend'
    if intent.time_range and intent.granularity and building_count <= 1:
        return '/energy/trend'
    return '/energy/query'


def _http_method_for_endpoint(endpoint: str) -> str:
    return 'POST' if endpoint == '/energy/anomaly-analysis' else 'GET'


def _intent_to_query_params(intent: AIQueryIntent, endpoint: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if endpoint == BUILDING_QUERY_ENDPOINT:
        params = {
            'keyword': intent.keyword,
            'site_id': intent.site_id,
            'primaryspaceusage': intent.primaryspaceusage,
            'status': intent.status,
            'start_time': intent.time_range.start.isoformat() if intent.time_range else None,
            'end_time': intent.time_range.end.isoformat() if intent.time_range else None,
            'min_energy': intent.min_energy,
            'max_energy': intent.max_energy,
            'min_eui': intent.min_eui,
            'max_eui': intent.max_eui,
            'min_carbon': intent.min_carbon,
            'max_carbon': intent.max_carbon,
            'page': intent.page,
            'page_size': intent.page_size,
        }
        return {key: value for key, value in params.items() if value not in (None, '', [], {})}
    if intent.building_ids and endpoint in {'/energy/query', '/energy/trend', '/energy/compare'}:
        params['building_ids'] = intent.building_ids
    if intent.building_id and endpoint in {'/energy/weather-correlation', '/energy/cop'}:
        params['building_id'] = intent.building_id
    if intent.site_id and endpoint in {'/energy/query', '/energy/trend'}:
        params['site_id'] = intent.site_id
    if intent.meter:
        params['meter'] = intent.meter
    if intent.time_range:
        params['start_time'] = intent.time_range.start.isoformat()
        params['end_time'] = intent.time_range.end.isoformat()
    if intent.granularity and endpoint in {'/energy/query', '/energy/trend', '/energy/anomaly-analysis'}:
        params['granularity'] = intent.granularity
    if intent.aggregation and endpoint == '/energy/query':
        params['aggregation'] = intent.aggregation
    if intent.metric and endpoint in {'/energy/compare', '/energy/rankings'}:
        params['metric'] = intent.metric
    if intent.order and endpoint == '/energy/rankings':
        params['order'] = intent.order
    if intent.limit and endpoint == '/energy/rankings':
        params['limit'] = intent.limit
    if intent.page and endpoint == '/energy/query':
        params['page'] = intent.page
    if intent.page_size and endpoint == '/energy/query':
        params['page_size'] = intent.page_size
    if endpoint == '/energy/anomaly-analysis' and intent.time_range:
        params = {
            'building_id': intent.building_id or (intent.building_ids[0] if intent.building_ids else ''),
            'meter': intent.meter,
            'time_range': {
                'start': intent.time_range.start.isoformat(),
                'end': intent.time_range.end.isoformat(),
            },
            'granularity': intent.granularity or 'hour',
            'analysis_mode': intent.analysis_mode or 'offline_event_review',
            'include_weather_context': True if intent.include_weather_context is None else intent.include_weather_context,
        }
    if endpoint == '/energy/weather-correlation':
        params = {
            'building_id': intent.building_id or (intent.building_ids[0] if intent.building_ids else ''),
            'meter': intent.meter,
            'start_time': intent.time_range.start.isoformat() if intent.time_range else None,
            'end_time': intent.time_range.end.isoformat() if intent.time_range else None,
        }
    return {key: value for key, value in params.items() if value not in (None, '', [], {})}


def _build_applied_filters(intent: AIQueryIntent, endpoint: str) -> AIQueryAssistantFilters:
    building_id = intent.building_id
    if building_id is None and endpoint in {"/energy/weather-correlation", "/energy/anomaly-analysis"} and intent.building_ids:
        building_id = intent.building_ids[0]
    return AIQueryAssistantFilters(
        building_ids=intent.building_ids,
        building_id=building_id,
        keyword=intent.keyword,
        site_id=intent.site_id,
        primaryspaceusage=intent.primaryspaceusage,
        status=intent.status,
        meter=intent.meter,
        time_range=intent.time_range,
        min_energy=intent.min_energy,
        max_energy=intent.max_energy,
        min_eui=intent.min_eui,
        max_eui=intent.max_eui,
        min_carbon=intent.min_carbon,
        max_carbon=intent.max_carbon,
        granularity=intent.granularity,
        aggregation=intent.aggregation,
        metric=intent.metric,
        order=intent.order,
        sort_by=intent.sort_by,
        sort_order=intent.sort_order,
        limit=intent.limit,
        page=intent.page,
        page_size=intent.page_size,
        analysis_mode=intent.analysis_mode,
        include_weather_context=intent.include_weather_context,
    )


def _build_ui_patch(endpoint: str, intent: AIQueryIntent) -> AIQueryAssistantUIPatch:
    if endpoint == BUILDING_QUERY_ENDPOINT:
        return AIQueryAssistantUIPatch(
            primary_view="building_table",
            chart_type=None,
            highlighted_filters=[
                "keyword",
                "site_id",
                "primaryspaceusage",
                "status",
                "time_range",
                "min_energy",
                "max_energy",
                "min_eui",
                "max_eui",
                "min_carbon",
                "max_carbon",
                "sort_by",
                "sort_order",
            ],
            suggested_interaction="update_filters_and_refresh",
        )
    if endpoint == "/energy/trend":
        return AIQueryAssistantUIPatch(
            primary_view="trend_chart",
            chart_type="line",
            highlighted_filters=["building_ids", "meter", "time_range", "granularity"],
            suggested_interaction="update_filters_and_refresh",
        )
    if endpoint == "/energy/query":
        return AIQueryAssistantUIPatch(
            primary_view="detail_table",
            chart_type=None,
            highlighted_filters=["building_ids", "site_id", "meter", "time_range", "granularity", "aggregation", "page", "page_size"],
            suggested_interaction="update_filters_and_refresh",
        )
    if endpoint == "/energy/compare":
        return AIQueryAssistantUIPatch(
            primary_view="compare_chart",
            chart_type="bar",
            highlighted_filters=["building_ids", "meter", "time_range", "metric"],
            suggested_interaction="update_filters_and_refresh",
        )
    if endpoint == "/energy/rankings":
        return AIQueryAssistantUIPatch(
            primary_view="ranking_table",
            chart_type="bar",
            highlighted_filters=["meter", "time_range", "metric", "order", "limit"],
            suggested_interaction="update_filters_and_refresh",
        )
    if endpoint == "/energy/weather-correlation":
        return AIQueryAssistantUIPatch(
            primary_view="weather_correlation_panel",
            chart_type="scatter",
            highlighted_filters=["building_id", "meter", "time_range"],
            suggested_interaction="update_filters_and_refresh",
        )
    return AIQueryAssistantUIPatch(
        primary_view="anomaly_panel",
        chart_type="line",
        highlighted_filters=["building_id", "meter", "time_range", "granularity"],
        suggested_interaction="update_filters_and_refresh",
    )


def _build_fallback_intent(payload: AIQueryAssistantRequest) -> tuple[AIQueryIntent, list[str]]:
    """基于规则构造兜底查询意图，并返回提示告警。"""
    now = _now_with_tz(payload)
    warnings: list[str] = []
    building_ids = _extract_building_ids(payload.question)
    meter = _extract_meter(payload.question)
    resolved_time_range, time_warnings = _resolve_time_range(payload.question, now)
    warnings.extend(time_warnings)
    raw_granularity = _extract_granularity(payload.question)
    granularity = normalize_granularity(raw_granularity)
    metric = 'sum' if any(keyword in payload.question.lower() for keyword in ('总', 'sum', 'total')) else None
    limit = _extract_limit(payload.question)
    order = _extract_order(payload.question)
    time_range_for_merge = resolved_time_range
    current_filters = payload.current_filters
    if (
        current_filters
        and current_filters.time_range
        and any(item == '未明确时间范围，已按最近7天处理。' for item in time_warnings)
    ):
        time_range_for_merge = None
        warnings = [item for item in warnings if item != '未明确时间范围，已按最近7天处理。']
    (
        building_ids,
        meter,
        time_range,
        granularity,
        metric,
        limit,
        order,
        current_filter_warnings,
    ) = _merge_with_current_filters(
        payload,
        building_ids=building_ids,
        meter=meter,
        time_range=time_range_for_merge,
        granularity=raw_granularity,
        metric=metric,
        limit=limit,
        order=order,
    )
    warnings.extend(current_filter_warnings)
    if meter is None:
        meter = normalize_meter(None)
        warnings.append('未明确表计类型，已按 electricity 处理。')
    if granularity is None:
        granularity = normalize_granularity(None)
        warnings.append('未明确时间粒度，已按 day 处理。')
    building_id = current_filters.building_id if current_filters else None
    page = current_filters.page if current_filters else None
    page_size = current_filters.page_size if current_filters else None
    aggregation = current_filters.aggregation if current_filters else None
    site_id = current_filters.site_id if current_filters else None
    analysis_mode = current_filters.analysis_mode if current_filters else "offline_event_review"
    include_weather_context = current_filters.include_weather_context if current_filters else True
    return (
        AIQueryIntent(
            building_ids=building_ids,
            building_id=building_id,
            keyword=None,
            site_id=site_id,
            primaryspaceusage=None,
            status=None,
            meter=meter,
            time_range=time_range,
            min_energy=None,
            max_energy=None,
            min_eui=None,
            max_eui=None,
            min_carbon=None,
            max_carbon=None,
            granularity=granularity,
            aggregation=aggregation,
            metric=metric,
            order=order,
            sort_by=None,
            sort_order=None,
            limit=limit,
            page=page,
            page_size=page_size,
            analysis_mode=analysis_mode,
            include_weather_context=include_weather_context,
        ),
        warnings,
    )


def _build_building_query_fallback_intent(payload: AIQueryAssistantRequest) -> tuple[AIQueryIntent, list[str]]:
    now = _now_with_tz(payload)
    warnings: list[str] = []
    keyword, keyword_warnings = _extract_keyword(payload.question)
    warnings.extend(keyword_warnings)
    site_id = _extract_site_id(payload.question)
    primaryspaceusage = _extract_primaryspaceusage(payload.question)
    status = _extract_status(payload.question)
    time_range, time_warnings = _resolve_time_range(payload.question, now)
    warnings.extend(time_warnings)
    min_energy, max_energy = _extract_metric_range(payload.question, ('总能耗', '能耗', 'energy'))
    min_eui, max_eui = _extract_metric_range(payload.question, ('eui', '能效', '能耗强度'))
    min_carbon, max_carbon = _extract_metric_range(payload.question, ('碳排放', 'carbon'))
    sort_by = _extract_sort_field(payload.question)
    sort_order = _extract_order(payload.question)

    if (
        payload.current_filters
        and payload.current_filters.time_range
        and any(item == '未明确时间范围，已按最近7天处理。' for item in time_warnings)
    ):
        time_range = None
        warnings = [item for item in warnings if item != '未明确时间范围，已按最近7天处理。']

    (
        keyword,
        site_id,
        primaryspaceusage,
        status,
        time_range,
        min_energy,
        max_energy,
        min_eui,
        max_eui,
        min_carbon,
        max_carbon,
        sort_by,
        sort_order,
        merge_warnings,
    ) = _merge_building_query_with_current_filters(
        payload,
        keyword=keyword,
        site_id=site_id,
        primaryspaceusage=primaryspaceusage,
        status=status,
        time_range=time_range,
        min_energy=min_energy,
        max_energy=max_energy,
        min_eui=min_eui,
        max_eui=max_eui,
        min_carbon=min_carbon,
        max_carbon=max_carbon,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    warnings.extend(merge_warnings)

    if sort_by and sort_order is None:
        sort_order = 'desc'
        warnings.append('未明确排序方向，已按降序处理。')

    current_filters = payload.current_filters
    page = current_filters.page if current_filters else None
    page_size = current_filters.page_size if current_filters else None
    return (
        AIQueryIntent(
            building_ids=[],
            building_id=None,
            keyword=keyword,
            site_id=site_id,
            primaryspaceusage=primaryspaceusage,
            status=status,
            meter=None,
            time_range=time_range,
            min_energy=min_energy,
            max_energy=max_energy,
            min_eui=min_eui,
            max_eui=max_eui,
            min_carbon=min_carbon,
            max_carbon=max_carbon,
            granularity=None,
            aggregation=None,
            metric=None,
            order=None,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=None,
            page=page,
            page_size=page_size,
            analysis_mode=None,
            include_weather_context=None,
        ),
        warnings,
    )


def _count_building_query_signals(intent: AIQueryIntent) -> int:
    signal_fields = (
        intent.keyword,
        intent.site_id,
        intent.primaryspaceusage,
        intent.status,
        intent.time_range,
        intent.min_energy,
        intent.max_energy,
        intent.min_eui,
        intent.max_eui,
        intent.min_carbon,
        intent.max_carbon,
        intent.sort_by,
        intent.sort_order,
    )
    return sum(1 for item in signal_fields if item not in (None, '', [], {}))


def _contains_building_query_semantic_markers(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in BUILDING_QUERY_SEMANTIC_MARKERS)


def _normalize_time_range(value: Any, fallback_value: TimeRange) -> TimeRange:
    if not isinstance(value, dict):
        return fallback_value
    start_raw = value.get('start')
    end_raw = value.get('end')
    try:
        if isinstance(start_raw, str) and isinstance(end_raw, str):
            start = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
            end = datetime.fromisoformat(end_raw.replace('Z', '+00:00'))
            return TimeRange(start=start, end=end)
    except ValueError:
        return fallback_value
    return fallback_value


def _normalize_llm_result(
    llm_response: dict[str, Any],
    fallback_intent: AIQueryIntent,
    fallback_warnings: list[str],
    settings_model: str,
    target_scope: str,
) -> AIQueryAssistantResponse:
    """将 LLM 输出标准化为 query-assistant 接口响应。"""
    intent_payload = llm_response.get('query_intent') if isinstance(llm_response.get('query_intent'), dict) else {}
    time_range = _normalize_time_range(intent_payload.get('time_range'), fallback_intent.time_range) if fallback_intent.time_range else None
    normalized_meter = (
        None
        if target_scope == "building_query"
        else normalize_meter(intent_payload.get('meter') or fallback_intent.meter)
    )
    normalized_granularity = (
        None
        if target_scope == "building_query"
        else normalize_granularity(intent_payload.get('granularity') or fallback_intent.granularity)
    )
    normalized_primaryspaceusage = (
        _normalize_primaryspaceusage(intent_payload.get('primaryspaceusage'))
        if target_scope == "building_query"
        else str(intent_payload.get('primaryspaceusage')).strip() if intent_payload.get('primaryspaceusage') else fallback_intent.primaryspaceusage
    )
    normalized_status = (
        _normalize_building_status(intent_payload.get('status'))
        if target_scope == "building_query"
        else str(intent_payload.get('status')).strip().lower() if intent_payload.get('status') else fallback_intent.status
    )
    normalized_sort_by = (
        _normalize_building_query_sort_field(intent_payload.get('sort_by'))
        if target_scope == "building_query"
        else str(intent_payload.get('sort_by')).strip() if intent_payload.get('sort_by') else fallback_intent.sort_by
    )
    normalized_sort_order = (
        _normalize_sort_order(intent_payload.get('sort_order'))
        if target_scope == "building_query"
        else str(intent_payload.get('sort_order')).strip() if intent_payload.get('sort_order') else fallback_intent.sort_order
    )
    intent = AIQueryIntent(
        building_ids=[str(item) for item in intent_payload.get('building_ids', []) if str(item).strip()] or fallback_intent.building_ids,
        building_id=str(intent_payload.get('building_id')).strip() if intent_payload.get('building_id') else fallback_intent.building_id,
        keyword=str(intent_payload.get('keyword')).strip() if intent_payload.get('keyword') else fallback_intent.keyword,
        site_id=str(intent_payload.get('site_id')).strip() if intent_payload.get('site_id') else fallback_intent.site_id,
        primaryspaceusage=normalized_primaryspaceusage or fallback_intent.primaryspaceusage,
        status=normalized_status or fallback_intent.status,
        meter=normalized_meter,
        time_range=time_range or fallback_intent.time_range,
        min_energy=_coerce_float(intent_payload.get('min_energy'), fallback_intent.min_energy),
        max_energy=_coerce_float(intent_payload.get('max_energy'), fallback_intent.max_energy),
        min_eui=_coerce_float(intent_payload.get('min_eui'), fallback_intent.min_eui),
        max_eui=_coerce_float(intent_payload.get('max_eui'), fallback_intent.max_eui),
        min_carbon=_coerce_float(intent_payload.get('min_carbon'), fallback_intent.min_carbon),
        max_carbon=_coerce_float(intent_payload.get('max_carbon'), fallback_intent.max_carbon),
        granularity=normalized_granularity,
        aggregation=str(intent_payload.get('aggregation')).strip() if intent_payload.get('aggregation') else fallback_intent.aggregation,
        metric=str(intent_payload.get('metric')).strip() if intent_payload.get('metric') else fallback_intent.metric,
        order=str(intent_payload.get('order')).strip() if intent_payload.get('order') else fallback_intent.order,
        sort_by=normalized_sort_by or fallback_intent.sort_by,
        sort_order=normalized_sort_order or fallback_intent.sort_order,
        limit=_coerce_int(intent_payload.get('limit'), fallback_intent.limit),
        page=_coerce_int(intent_payload.get('page'), fallback_intent.page),
        page_size=_coerce_int(intent_payload.get('page_size'), fallback_intent.page_size),
        analysis_mode=str(intent_payload.get('analysis_mode')).strip() if intent_payload.get('analysis_mode') else fallback_intent.analysis_mode,
        include_weather_context=bool(intent_payload.get('include_weather_context')) if 'include_weather_context' in intent_payload else fallback_intent.include_weather_context,
    )
    endpoint = str(llm_response.get('recommended_endpoint') or _recommend_endpoint('', intent, target_scope)).strip()
    allowed_endpoints = ALLOWED_BUILDING_QUERY_ENDPOINTS if target_scope == "building_query" else ALLOWED_QUERY_ENDPOINTS
    if endpoint not in allowed_endpoints:
        endpoint = _recommend_endpoint('', intent, target_scope)
    query_plan = AIQueryAssistantPlan(
        endpoint=endpoint,
        method=_http_method_for_endpoint(endpoint),
        params=_intent_to_query_params(intent, endpoint),
    )
    warnings = [str(item) for item in llm_response.get('warnings', []) if str(item).strip()] or fallback_warnings
    return AIQueryAssistantResponse(
        summary=str(llm_response.get('summary') or f'已将问题解析为 {endpoint} 查询。'),
        query_plan=query_plan,
        applied_filters=_build_applied_filters(intent, endpoint),
        ui_patch=_build_ui_patch(endpoint, intent),
        warnings=warnings,
        meta=AIQueryAssistantMeta(
            generated_at=get_timezone_now(),
            model=settings_model,
            used_fallback=False,
        ),
    )


def _build_fallback_response(
    payload: AIQueryAssistantRequest,
    fallback_intent: AIQueryIntent,
    fallback_warnings: list[str],
    settings_model: str,
    target_scope: str,
) -> AIQueryAssistantResponse:
    """在 LLM 失败时返回可解释的规则兜底响应。"""
    endpoint = _recommend_endpoint(payload.question, fallback_intent, target_scope)
    query_plan = AIQueryAssistantPlan(
        endpoint=endpoint,
        method=_http_method_for_endpoint(endpoint),
        params=_intent_to_query_params(fallback_intent, endpoint),
    )
    return AIQueryAssistantResponse(
        summary=f'已将问题解析为 {endpoint} 的页面筛选方案。',
        query_plan=query_plan,
        applied_filters=_build_applied_filters(fallback_intent, endpoint),
        ui_patch=_build_ui_patch(endpoint, fallback_intent),
        warnings=fallback_warnings,
        meta=AIQueryAssistantMeta(
            generated_at=get_timezone_now(),
            model=settings_model,
            used_fallback=True,
        ),
    )


def _should_use_rule_only(payload: AIQueryAssistantRequest, fallback_intent: AIQueryIntent) -> bool:
    """判断当前问题是否足够简单，可直接使用规则结果。"""

    endpoint = _recommend_endpoint(payload.question, fallback_intent, payload.target_scope)
    lowered = payload.question.lower()

    if payload.target_scope == "building_query":
        complex_markers = (
            "对比",
            "比较",
            "趋势",
            "排行",
            "排名",
            "图",
            "并且",
            "同时",
            "以及",
        )
        if any(marker in lowered for marker in complex_markers):
            return False
        if _contains_building_query_semantic_markers(lowered):
            return False

        signal_count = _count_building_query_signals(fallback_intent)
        question_length = len(payload.question.strip())

        if signal_count == 0:
            return False

        if signal_count == 1:
            return question_length <= 18

        if signal_count == 2:
            return question_length <= 32

        return True

    if endpoint not in {"/energy/query", "/energy/trend"}:
        return False

    complex_markers = (
        "对比",
        "比较",
        "排行",
        "排名",
        "top",
        "vs",
        "weather",
        "天气",
        "相关性",
        "异常",
        "诊断",
        "告警",
        "并且",
        "同时",
        "以及",
        "顺便",
        "另外",
    )
    if any(marker in lowered for marker in complex_markers):
        return False

    return True


def build_query_intent(payload: AIQueryAssistantRequest) -> AIQueryAssistantResponse:
    """查询助手主入口：将自然语言解析为结构化查询意图。"""
    settings = get_ai_settings()
    if payload.target_scope == "building_query":
        fallback_intent, fallback_warnings = _build_building_query_fallback_intent(payload)
    else:
        fallback_intent, fallback_warnings = _build_fallback_intent(payload)
    if _should_use_rule_only(payload, fallback_intent):
        return _build_fallback_response(
            payload=payload,
            fallback_intent=fallback_intent,
            fallback_warnings=fallback_warnings,
            settings_model=settings.llm_model,
            target_scope=payload.target_scope,
        )
    try:
        system_prompt, user_prompt = build_query_assistant_prompts(
            question=payload.question,
            current_time_iso=_now_with_tz(payload).isoformat(),
            target_scope=payload.target_scope,
            current_endpoint=payload.current_endpoint,
            current_filters=payload.current_filters.model_dump(mode="json") if payload.current_filters else None,
        )
        llm_response = OpenAICompatibleClient(settings).generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return _normalize_llm_result(
            llm_response=llm_response,
            fallback_intent=fallback_intent,
            fallback_warnings=fallback_warnings,
            settings_model=settings.llm_model,
            target_scope=payload.target_scope,
        )
    except Exception:
        return _build_fallback_response(
            payload=payload,
            fallback_intent=fallback_intent,
            fallback_warnings=fallback_warnings,
            settings_model=settings.llm_model,
            target_scope=payload.target_scope,
        )
