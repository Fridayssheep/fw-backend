import json
from datetime import date
from datetime import datetime
from typing import Any

from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import EnergyAnomalyAnalysisResponse
from app.schemas import WeatherCorrelationResponse


SYSTEM_PROMPT = """\
你是“建筑能源智能运维异常分析助手”。

你的任务是基于结构化异常结果、天气信息、知识库片段和历史反馈，
输出可解释、可追溯、可供人工确认的诊断建议。

必须遵守以下规则：
1. 不要把当前结果表述成“已确认故障”，只能表述为“候选原因”或“诊断建议”。
2. 当前异常证据优先级高于历史反馈；历史反馈只能辅助排序，不能覆盖当前证据。
3. 必须返回 2 到 5 个 candidate_causes，按 confidence 从高到低排序。
4. 每个 candidate_cause 必须包含：
   cause_id, title, description, confidence, rank, recommended_checks, evidence_ids。
5. 所有结论都必须由 evidence 支撑；没有证据支撑的内容不要编造。
6. 如果证据不足，要明确降低 confidence，并在 answer 或 risk_notice 中说明不确定性。
7. 输出必须是合法 JSON，不要输出 Markdown、不要输出解释文字、不要输出代码块。
8. answer、summary、title、description、recommended_checks、risk_notice 使用简洁专业的中文。
9. 优先做“运维可执行结论”，避免长篇复述输入。

状态字段约束：
- 如果检测到明显异常，status 使用 needs_confirmation
- 如果异常信号较弱，status 使用 low_confidence
- 不要输出其他随意状态值
"""


QUERY_ASSISTANT_SYSTEM_PROMPT = """\
你是“建筑能源查询意图解析助手”。

你的任务是把用户的自然语言问题解析成结构化查询意图，
并推荐应该调用的后端 energy 接口。

必须遵守以下规则：
1. 只做意图解析和接口推荐，不要假装自己已经执行了查询。
2. 输出必须是合法 JSON，不要输出 Markdown、解释文字或代码块。
3. 如果用户问题信息不足，可以补一个合理默认值，但要在 warnings 中明确说明。
4. recommended_endpoint 只能从以下值中选择：
   /energy/query
   /energy/trend
   /energy/compare
   /energy/rankings
   /energy/weather-correlation
   /energy/anomaly-analysis
5. 如果 recommended_endpoint 是 /energy/anomaly-analysis，则 recommended_http_method 必须是 POST。
6. 其他推荐接口的 recommended_http_method 一律使用 GET。
7. 输出字段必须包含：
   summary, query_intent, recommended_endpoint, recommended_http_method, recommended_query_params, warnings
8. answer 不是这个接口需要的字段，不要输出。
"""


def _json_default_serializer(value: Any) -> Any:
    """JSON 序列化兜底：时间类型转 ISO 字符串。"""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_block(value: Any) -> str:
    """将对象格式化为可读的 JSON 文本块。"""
    return json.dumps(value, ensure_ascii=False, indent=2, default=_json_default_serializer)


def _build_compact_anomaly_context(anomaly_result: EnergyAnomalyAnalysisResponse) -> dict[str, Any]:
    """压缩异常分析结果，减少提示词 token 占用。"""
    detected_points = sorted(
        anomaly_result.detected_points,
        key=lambda item: item.deviation_rate,
        reverse=True,
    )[:5]
    series_points = anomaly_result.series.points
    compact_series = []
    if series_points:
        for point in series_points[:3]:
            compact_series.append({
                'timestamp': point.timestamp,
                'value': point.value,
            })
        if len(series_points) > 6:
            compact_series.append({'ellipsis': f'{len(series_points) - 6} middle points omitted'})
        for point in series_points[-3:]:
            compact_series.append({
                'timestamp': point.timestamp,
                'value': point.value,
            })
    return {
        'building_id': anomaly_result.building_id,
        'meter': anomaly_result.meter,
        'time_range': anomaly_result.time_range,
        'is_anomalous': anomaly_result.is_anomalous,
        'summary': anomaly_result.summary,
        'baseline_mode': anomaly_result.baseline_mode,
        'detected_points': [
            {
                'timestamp': item.timestamp,
                'actual_value': item.actual_value,
                'baseline_value': item.baseline_value,
                'deviation_rate': item.deviation_rate,
                'severity': item.severity,
            }
            for item in detected_points
        ],
        'series_excerpt': compact_series,
    }


def _build_compact_weather_context(weather_result: WeatherCorrelationResponse | None) -> dict[str, Any] | None:
    """压缩天气相关性上下文，保留关键因子。"""
    if weather_result is None:
        return None
    strongest_factor = None
    if weather_result.factors:
        strongest_factor = max(weather_result.factors, key=lambda item: abs(item.coefficient))
    return {
        'building_id': weather_result.building_id,
        'meter': weather_result.meter,
        'correlation_coefficient': weather_result.correlation_coefficient,
        'strongest_factor': {
            'name': strongest_factor.name,
            'coefficient': strongest_factor.coefficient,
            'direction': strongest_factor.direction,
        } if strongest_factor else None,
        'factors': [
            {
                'name': item.name,
                'coefficient': item.coefficient,
                'direction': item.direction,
            }
            for item in weather_result.factors
        ],
    }


def _build_compact_history_context(history_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """压缩历史反馈，仅保留最有代表性的字段。"""
    compact_items: list[dict[str, Any]] = []
    for item in history_context[:3]:
        compact_items.append(
            {
                'analysis_id': item.get('analysis_id'),
                'selected_cause_id': item.get('selected_cause_id'),
                'selected_score': item.get('selected_score'),
                'resolution_status': item.get('resolution_status'),
                'comment': item.get('comment'),
                'created_at': item.get('created_at'),
            }
        )
    return compact_items


def build_analyze_anomaly_prompts(
    request: AIAnalyzeAnomalyRequest,
    anomaly_result: EnergyAnomalyAnalysisResponse,
    weather_result: WeatherCorrelationResponse | None,
    knowledge_context: list[dict[str, Any]],
    history_context: list[dict[str, Any]],
    allowed_action_targets: tuple[str, ...],
) -> tuple[str, str]:
    """构造异常分析提示词（系统提示 + 用户提示）。"""

    output_schema_hint = {
        'summary': '一句话结论',
        'status': 'needs_confirmation',
        'answer': '完整分析说明',
        'candidate_causes': [
            {
                'cause_id': 'load_shift',
                'title': '负荷模式变化',
                'description': '对候选原因的中文解释',
                'confidence': 0.72,
                'rank': 1,
                'recommended_checks': ['建议排查项1', '建议排查项2'],
                'evidence_ids': ['evi_001', 'evi_002'],
            },
            {
                'cause_id': 'efficiency_drop',
                'title': '设备效率下降',
                'description': '对候选原因的中文解释',
                'confidence': 0.51,
                'rank': 2,
                'recommended_checks': ['建议排查项1'],
                'evidence_ids': ['evi_003'],
            },
        ],
        'highlights': ['关键观察1', '关键观察2'],
        'evidence': [
            {
                'evidence_id': 'evi_001',
                'type': 'data',
                'source': 'energy_anomaly_analysis',
                'snippet': '证据摘要',
                'weight': 0.91,
            }
        ],
        'actions': [
            {
                'label': '查看趋势',
                'action_type': 'open_tool',
                'target': 'energy_trend',
            }
        ],
        'risk_notice': '当前结果属于诊断建议，不代表已确认故障。',
        'feedback_prompt': {
            'enabled': True,
            'message': '请选择最可能原因并进行评分。',
            'allow_score': True,
            'allow_comment': True,
        },
    }

    compact_request = {
        'building_id': request.building_id,
        'meter': request.meter,
        'time_range': request.time_range,
        'granularity': request.granularity,
        'baseline_mode': request.baseline_mode,
        'question': request.question,
    }
    compact_anomaly = _build_compact_anomaly_context(anomaly_result)
    compact_weather = _build_compact_weather_context(weather_result)
    compact_history = _build_compact_history_context(history_context)
    compact_knowledge = knowledge_context[:3]
    allowed_targets_text = '\n'.join(f'- {item}' for item in allowed_action_targets)

    user_prompt = f"""\
请根据以下输入，对本次建筑能耗异常做运维诊断分析。

【请求参数】
{_json_block(compact_request)}

【异常检测摘要】
{_json_block(compact_anomaly)}

【天气摘要】
{_json_block(compact_weather)}

【知识库摘要】
{_json_block(compact_knowledge)}

【历史反馈摘要】
{_json_block(compact_history)}

【允许使用的 actions.target】
{allowed_targets_text}

【输出要求】
1. 只输出一个合法 JSON 对象。
2. 顶层字段必须严格包含：
   summary, status, answer, candidate_causes, highlights, evidence, actions, risk_notice, feedback_prompt
3. candidate_causes 数量必须在 2 到 5 之间。
4. candidate_causes 按 confidence 从高到低排序，rank 必须连续。
5. evidence 中每项必须包含：
   evidence_id, type, source, snippet, weight
6. risk_notice 必须明确说明“这是诊断建议，不是已确认故障”。
7. 如果历史反馈命中了相似案例，可以在 evidence 中加入 type=history_case 的证据。
8. 不要输出任何 JSON 之外的文本。
9. actions.target 只能从上面的允许列表中选择，不要发明新的 target。
10. 如果没有合适的下一步动作，actions 可以返回空数组。

【输出 JSON 骨架示例】
{_json_block(output_schema_hint)}
"""
    return SYSTEM_PROMPT, user_prompt


def build_query_assistant_prompts(
    question: str,
    current_time_iso: str,
) -> tuple[str, str]:
    """构造 query-assistant 的提示词模板。"""
    output_schema_hint = {
        'summary': '一句话说明当前问题会被解析成什么查询',
        'query_intent': {
            'building_ids': ['Bear_assembly_Angel'],
            'site_id': None,
            'meter': 'electricity',
            'time_range': {
                'start': '2026-03-25T00:00:00+08:00',
                'end': '2026-04-01T00:00:00+08:00',
            },
            'granularity': 'day',
            'aggregation': None,
            'metric': None,
            'limit': None,
        },
        'recommended_endpoint': '/energy/trend',
        'recommended_http_method': 'GET',
        'recommended_query_params': {
            'building_ids': ['Bear_assembly_Angel'],
            'meter': 'electricity',
            'start_time': '2026-03-25T00:00:00+08:00',
            'end_time': '2026-04-01T00:00:00+08:00',
            'granularity': 'day',
        },
        'warnings': ['未明确时间范围，已按最近7天处理。'],
    }

    user_prompt = f"""\
请把下面这句自然语言问题解析成建筑能源查询意图，并推荐后续应调用的 energy 接口。

【当前时间】
{current_time_iso}

【用户问题】
{question}

【输出要求】
1. 只输出一个合法 JSON 对象。
2. 顶层字段必须严格包含：
   summary, query_intent, recommended_endpoint, recommended_http_method, recommended_query_params, warnings
3. query_intent 中允许的字段只有：
   building_ids, site_id, meter, time_range, granularity, aggregation, metric, limit
4. 如果无法确定 building_ids，可以返回空数组。
5. 如果无法确定 meter，默认使用 electricity，但必须在 warnings 中说明。
6. 如果无法确定时间范围，可以按最近7天补默认值，但必须在 warnings 中说明。
7. 不要返回真实查询结果。

【输出 JSON 骨架示例】
{_json_block(output_schema_hint)}
"""
    return QUERY_ASSISTANT_SYSTEM_PROMPT, user_prompt
