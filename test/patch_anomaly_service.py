from pathlib import Path

path = Path('ai/backend/anomaly_service.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
"""def _coerce_actions(value: Any, allowed_action_targets: set[str]) -> list[AIActionItem]:
    if not isinstance(value, list):
        return []
    actions: list[AIActionItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        action_type = str(item.get("action_type") or "").strip()
        target = str(item.get("target") or "").strip()
        if not (label and action_type and target):`r`n            continue`r`n        if target not in allowed_action_targets:`r`n            continue
        actions.append(
            AIActionItem(
                label=label,
                action_type=action_type,
                target=target,
                target_id=str(item.get("target_id") or "").strip() or None,
            )
        )
    return actions
""",
"""def _coerce_actions(value: Any, allowed_action_targets: set[str]) -> list[AIActionItem]:
    if not isinstance(value, list):
        return []
    actions: list[AIActionItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        action_type = str(item.get("action_type") or "").strip()
        target = str(item.get("target") or "").strip()
        if not (label and action_type and target):
            continue
        if target not in allowed_action_targets:
            continue
        actions.append(
            AIActionItem(
                label=label,
                action_type=action_type,
                target=target,
                target_id=str(item.get("target_id") or "").strip() or None,
            )
        )
    return actions
"""
)
text = text.replace(
"""def _normalize_llm_response(
    request: AIAnalyzeAnomalyRequest,
    llm_response: dict[str, Any],
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    knowledge_context: list[dict[str, Any]],
    history_context: list[dict[str, Any]],
    settings_model: str,
) -> AIAnalyzeAnomalyResponse:
""",
"""def _normalize_llm_response(
    request: AIAnalyzeAnomalyRequest,
    llm_response: dict[str, Any],
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    knowledge_context: list[dict[str, Any]],
    history_context: list[dict[str, Any]],
    settings_model: str,
    allowed_action_targets: tuple[str, ...],
) -> AIAnalyzeAnomalyResponse:
"""
)
text = text.replace(
'    actions = _coerce_actions(llm_response.get("actions")) or _build_default_actions(request)\n',
'    actions = _coerce_actions(llm_response.get("actions"), set(allowed_action_targets)) or _build_default_actions(request)\n'
)
text = text.replace(
"""        system_prompt, user_prompt = build_analyze_anomaly_prompts(
            request=payload,
            anomaly_result=anomaly_result,
            weather_result=weather_result,
            knowledge_context=knowledge_context,
            history_context=history_context,
        )
""",
"""        system_prompt, user_prompt = build_analyze_anomaly_prompts(
            request=payload,
            anomaly_result=anomaly_result,
            weather_result=weather_result,
            knowledge_context=knowledge_context,
            history_context=history_context,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )
"""
)
text = text.replace(
"""            history_context=history_context,
            settings_model=settings.llm_model,
        )
""",
"""            history_context=history_context,
            settings_model=settings.llm_model,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )
"""
)
path.write_text(text, encoding='utf-8')
