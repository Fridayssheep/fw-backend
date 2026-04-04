import json
from datetime import date
from datetime import datetime
from typing import Any

from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import EnergyAnomalyAnalysisResponse
from app.schemas import WeatherCorrelationResponse


SYSTEM_PROMPT = """\
你是“建筑能源智能运维异常分析助手”。

你的任务是基于离线异常事件结果、天气信息、知识库片段和历史反馈，
输出可解释、可追溯、可供人工确认的诊断建议。

必须遵守以下规则：
1. 不要把当前结果表述成“已确认故障”，只能表述为“候选原因”或“诊断建议”。
2. 当前离线异常事件证据优先级高于历史反馈；历史反馈只能辅助排序，不能覆盖当前证据。
3. 必须返回 2 到 5 个 candidate_causes，按 confidence 从高到低排序。
4. 每个 candidate_cause 必须包含：
   cause_id, title, description, confidence, rank, recommended_checks, evidence_ids。
5. 所有结论都必须由 evidence 支撑；没有证据支撑的内容不要编造。
6. 如果证据不足，要明确降低 confidence，并在 answer 或 risk_notice 中说明不确定性。
7. detector 名称只代表“异常被什么算法发现”，不等于根因本身。
8. 如果 evidence 中出现 missing_data_detector，优先考虑采集链路、网关、通信或断流问题。
9. 如果 evidence 中出现 isolation_forest，优先解释为“不符合历史周期规律”的异常，不能直接断言设备故障。
10. 如果 evidence 中出现 z_score_detector，优先解释为突发极值或突发波动事件。
11. 输出必须是合法 JSON，不要输出 Markdown、不要输出解释文字、不要输出代码块。
12. answer、summary、title、description、recommended_checks、risk_notice 使用简洁专业的中文。
13. 优先做“运维可执行结论”，避免长篇复述输入。

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


OPS_GUIDE_SYSTEM_PROMPT = """\
你是“建筑能源智能运维指导助手”。

你的任务是基于已补全的运维上下文、异常分析结论、知识库证据和历史经验，
输出一份可执行、可交接、可追溯的运维指导。

必须遵守以下规则：
1. 不要把当前结果写成“已确认故障”，只能写成“排查建议”或“处置指导”。
2. 先写最重要的主结论，再给步骤。
3. steps 必须是结构化步骤，不要输出纯字符串数组。
4. 步骤要可执行，优先写“先看什么、再查什么、如果不成立怎么办”。
5. 如果异常发现来源是 z_score_detector / isolation_forest / missing_data_detector，要把它当成异常发现来源，不等于根因。
6. 如果证据不足，status 使用 low_confidence；如果上下文不足，status 使用 needs_more_context；否则使用 actionable。
7. 不要发明页面或接口名称，actions 只允许使用输入里给出的候选 target。
8. 输出必须是合法 JSON，不要输出 Markdown，不要输出代码块。
9. summary、preconditions、steps、risk_notice、applicability 全部使用简洁专业的中文。
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
    severity_priority = {"high": 3, "medium": 2, "low": 1}
    representative_events = sorted(
        anomaly_result.detected_events,
        key=lambda item: (
            severity_priority.get(item.severity, 0),
            item.peak_deviation or 0,
        ),
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
        'analysis_mode': anomaly_result.analysis_mode,
        'event_count': anomaly_result.event_count,
        'detector_breakdown': [
            {
                'detected_by': item.detected_by,
                'event_type': item.event_type,
                'count': item.count,
            }
            for item in anomaly_result.detector_breakdown
        ],
        'representative_events': [
            {
                'event_id': item.event_id,
                'start_time': item.start_time,
                'end_time': item.end_time,
                'severity': item.severity,
                'detected_by': item.detected_by,
                'event_type': item.event_type,
                'description': item.description,
                'peak_deviation': item.peak_deviation,
            }
            for item in representative_events
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
                'cause_id': 'pattern_shift',
                'title': '运行周期规律偏移',
                'description': '对候选原因的中文解释',
                'confidence': 0.72,
                'rank': 1,
                'recommended_checks': ['建议排查项1', '建议排查项2'],
                'evidence_ids': ['evi_001', 'evi_002'],
            },
            {
                'cause_id': 'data_pipeline_issue',
                'title': '采集链路或通信异常',
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
                'source': 'z_score_detector',
                'snippet': '发生突发性数值读数异常，Z-Score 偏离度高达 4.82',
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
        'analysis_mode': request.analysis_mode,
        'question': request.question,
    }
    compact_anomaly = _build_compact_anomaly_context(anomaly_result)
    compact_weather = _build_compact_weather_context(weather_result)
    compact_history = _build_compact_history_context(history_context)
    compact_knowledge = knowledge_context[:3]
    allowed_targets_text = '\n'.join(f'- {item}' for item in allowed_action_targets)

    user_prompt = f"""\
请根据以下输入，对本次建筑能耗离线异常事件做运维诊断分析。

【请求参数】
{_json_block(compact_request)}

【离线异常事件摘要】
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
8. 如果 source 是 z_score_detector / isolation_forest / missing_data_detector，请把它理解为“异常发现来源”，不要把 detector 名称直接当成根因。
9. 不要输出任何 JSON 之外的文本。
10. actions.target 只能从上面的允许列表中选择，不要发明新的 target。
11. 如果没有合适的下一步动作，actions 可以返回空数组。

【输出 JSON 骨架示例】
{_json_block(output_schema_hint)}
"""
    return SYSTEM_PROMPT, user_prompt


def build_ops_guide_prompts(
    ops_context: dict[str, Any],
    diagnosis_snapshot: dict[str, Any],
    knowledge_items: list[dict[str, Any]],
    history_items: list[dict[str, Any]],
    allowed_action_targets: tuple[str, ...],
) -> tuple[str, str]:
    """构造运维指导提示词。"""

    output_schema_hint = {
        "status": "actionable",
        "summary": "一句话概括当前最优先的排查方向",
        "preconditions": [
            "确认当前 building_id、meter 和时间范围无误"
        ],
        "steps": [
            {
                "step_id": "step_1",
                "title": "先核查运行日历和排班变化",
                "instruction": "对照异常时段确认是否存在节假日、调休或特殊运行安排。",
                "priority": "high",
                "expected_result": "判断是否属于业务侧导致的规律变化",
                "if_not_met": "若无明显日历变化，继续核查设备启停和控制策略。"
            }
        ],
        "risk_notice": [
            "当前结果属于运维指导，不代表故障已确认。"
        ],
        "applicability": {
            "applies_to": ["离线异常事件接手后的排查场景"],
            "not_applies_to": ["缺少 building_id、meter、time_range 的泛化问答场景"]
        }
    }

    allowed_targets_text = "\n".join(f"- {item}" for item in allowed_action_targets)
    user_prompt = f"""\
请根据下面已经补全的运维上下文，生成一份结构化运维指导。

【运维上下文】
{_json_block(ops_context)}

【异常诊断快照】
{_json_block(diagnosis_snapshot)}

【知识证据】
{_json_block(knowledge_items[:3])}

【历史反馈摘要】
{_json_block(history_items[:3])}

【允许使用的 actions.target】
{allowed_targets_text}

【输出要求】
1. 只输出一个合法 JSON 对象。
2. 顶层字段必须严格包含：
   status, summary, preconditions, steps, risk_notice, applicability
3. steps 至少返回 2 步，最多返回 6 步。
4. 每个 step 必须包含：
   step_id, title, instruction, priority, expected_result, if_not_met
5. priority 只能取 high / medium / low。
6. 如果当前结论更接近运行规律偏移、采集异常或突发极值，请把这个判断体现在步骤顺序里。
7. 如果知识证据不足，不要编造设备说明书结论。
8. 不要输出 evidence、actions、meta，这些由后端根据结构化结果自行拼装。

【输出 JSON 骨架示例】
{_json_block(output_schema_hint)}
"""
    return OPS_GUIDE_SYSTEM_PROMPT, user_prompt


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
