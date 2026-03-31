from __future__ import annotations

import re
from datetime import datetime
from datetime import timedelta
from typing import Any

from app.schemas import AIQueryAssistantMeta
from app.schemas import AIQueryAssistantRequest
from app.schemas import AIQueryAssistantResponse
from app.schemas import AIQueryIntent
from app.schemas import TimeRange
from app.service_common import build_api_time_range
from app.service_common import get_taipei_now
from app.service_common import normalize_granularity
from app.service_common import normalize_meter

from .config import get_ai_settings
from .llm_client import OpenAICompatibleClient
from .prompting import build_query_assistant_prompts


ALLOWED_QUERY_ENDPOINTS = {
    '/energy/query',
    '/energy/trend',
    '/energy/compare',
    '/energy/rankings',
    '/energy/weather-correlation',
    '/energy/anomaly-analysis',
}

METER_KEYWORDS = {
    'electricity': ('电耗', '电能', '用电', '电量', 'electricity', 'power'),
    'water': ('水耗', '用水', 'water'),
    'gas': ('气耗', '燃气', 'gas'),
    'steam': ('蒸汽', 'steam'),
    'chilledwater': ('冷冻水', '冷量', 'chilledwater'),
    'hotwater': ('热水', 'hotwater'),
}


def _now_with_tz(request: AIQueryAssistantRequest) -> datetime:
    return request.current_time or get_taipei_now()


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


def _extract_building_ids(question: str) -> list[str]:
    # Capture common dataset identifiers such as Bear_assembly_Angel.
    building_candidates = re.findall(r'\b[A-Za-z]+(?:_[A-Za-z0-9]+)+\b', question)
    unique_items: list[str] = []
    for item in building_candidates:
        if item not in unique_items:
            unique_items.append(item)
    return unique_items


def _resolve_time_range(question: str, now: datetime) -> tuple[TimeRange, list[str]]:
    warnings: list[str] = []
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


def _recommend_endpoint(question: str, intent: AIQueryIntent) -> str:
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
    if intent.building_ids and endpoint in {'/energy/query', '/energy/trend', '/energy/compare'}:
        params['building_ids'] = intent.building_ids
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
    if intent.limit and endpoint == '/energy/rankings':
        params['limit'] = intent.limit
    if endpoint == '/energy/anomaly-analysis' and intent.time_range:
        params = {
            'building_id': intent.building_ids[0] if intent.building_ids else '',
            'meter': intent.meter,
            'time_range': {
                'start': intent.time_range.start.isoformat(),
                'end': intent.time_range.end.isoformat(),
            },
            'granularity': intent.granularity or 'hour',
            'baseline_mode': 'overall_mean',
            'include_weather_context': True,
        }
    if endpoint == '/energy/weather-correlation':
        params = {
            'building_id': intent.building_ids[0] if intent.building_ids else '',
            'meter': intent.meter,
            'start_time': intent.time_range.start.isoformat() if intent.time_range else None,
            'end_time': intent.time_range.end.isoformat() if intent.time_range else None,
        }
    return {key: value for key, value in params.items() if value not in (None, '', [], {})}


def _build_fallback_intent(payload: AIQueryAssistantRequest) -> tuple[AIQueryIntent, list[str]]:
    now = _now_with_tz(payload)
    warnings: list[str] = []
    building_ids = _extract_building_ids(payload.question)
    meter = _extract_meter(payload.question)
    if meter is None:
        meter = normalize_meter(None)
        warnings.append('未明确表计类型，已按 electricity 处理。')
    time_range, time_warnings = _resolve_time_range(payload.question, now)
    warnings.extend(time_warnings)
    granularity = normalize_granularity(_extract_granularity(payload.question))
    if _extract_granularity(payload.question) is None:
        warnings.append('未明确时间粒度，已按 day 处理。')
    metric = 'sum' if any(keyword in payload.question.lower() for keyword in ('总', 'sum', 'total')) else None
    limit = _extract_limit(payload.question)
    return (
        AIQueryIntent(
            building_ids=building_ids,
            meter=meter,
            time_range=time_range,
            granularity=granularity,
            metric=metric,
            limit=limit,
        ),
        warnings,
    )


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
) -> AIQueryAssistantResponse:
    intent_payload = llm_response.get('query_intent') if isinstance(llm_response.get('query_intent'), dict) else {}
    time_range = _normalize_time_range(intent_payload.get('time_range'), fallback_intent.time_range) if fallback_intent.time_range else None
    intent = AIQueryIntent(
        building_ids=[str(item) for item in intent_payload.get('building_ids', []) if str(item).strip()] or fallback_intent.building_ids,
        site_id=str(intent_payload.get('site_id')).strip() if intent_payload.get('site_id') else fallback_intent.site_id,
        meter=normalize_meter(intent_payload.get('meter') or fallback_intent.meter),
        time_range=time_range or fallback_intent.time_range,
        granularity=normalize_granularity(intent_payload.get('granularity') or fallback_intent.granularity),
        aggregation=str(intent_payload.get('aggregation')).strip() if intent_payload.get('aggregation') else fallback_intent.aggregation,
        metric=str(intent_payload.get('metric')).strip() if intent_payload.get('metric') else fallback_intent.metric,
        limit=int(intent_payload.get('limit')) if intent_payload.get('limit') else fallback_intent.limit,
    )
    endpoint = str(llm_response.get('recommended_endpoint') or _recommend_endpoint('', intent)).strip()
    if endpoint not in ALLOWED_QUERY_ENDPOINTS:
        endpoint = _recommend_endpoint('', intent)
    query_params = _intent_to_query_params(intent, endpoint)
    warnings = [str(item) for item in llm_response.get('warnings', []) if str(item).strip()] or fallback_warnings
    return AIQueryAssistantResponse(
        summary=str(llm_response.get('summary') or f'已将问题解析为 {endpoint} 查询。'),
        query_intent=intent,
        recommended_endpoint=endpoint,
        recommended_http_method=_http_method_for_endpoint(endpoint),
        recommended_query_params=query_params,
        warnings=warnings,
        meta=AIQueryAssistantMeta(
            generated_at=get_taipei_now(),
            model=settings_model,
            used_fallback=False,
        ),
    )


def _build_fallback_response(
    payload: AIQueryAssistantRequest,
    fallback_intent: AIQueryIntent,
    fallback_warnings: list[str],
    settings_model: str,
) -> AIQueryAssistantResponse:
    endpoint = _recommend_endpoint(payload.question, fallback_intent)
    return AIQueryAssistantResponse(
        summary=f'已将问题解析为 {endpoint} 的查询意图。',
        query_intent=fallback_intent,
        recommended_endpoint=endpoint,
        recommended_http_method=_http_method_for_endpoint(endpoint),
        recommended_query_params=_intent_to_query_params(fallback_intent, endpoint),
        warnings=fallback_warnings,
        meta=AIQueryAssistantMeta(
            generated_at=get_taipei_now(),
            model=settings_model,
            used_fallback=True,
        ),
    )


def build_query_intent(payload: AIQueryAssistantRequest) -> AIQueryAssistantResponse:
    settings = get_ai_settings()
    fallback_intent, fallback_warnings = _build_fallback_intent(payload)
    try:
        system_prompt, user_prompt = build_query_assistant_prompts(
            question=payload.question,
            current_time_iso=_now_with_tz(payload).isoformat(),
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
        )
    except Exception:
        return _build_fallback_response(
            payload=payload,
            fallback_intent=fallback_intent,
            fallback_warnings=fallback_warnings,
            settings_model=settings.llm_model,
        )
