from pathlib import Path

path = Path('ai/backend/anomaly_service.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
"""def _build_fallback_response(
    request: AIAnalyzeAnomalyRequest,
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    history_context: list[dict[str, Any]],
    settings_model: str,
) -> AIAnalyzeAnomalyResponse:
""",
"""def _build_fallback_response(
    request: AIAnalyzeAnomalyRequest,
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    history_context: list[dict[str, Any]],
    settings_model: str,
    allowed_action_targets: tuple[str, ...],
) -> AIAnalyzeAnomalyResponse:
"""
)
text = text.replace(
'        actions=_build_default_actions(request),\n',
'        actions=[item for item in _build_default_actions(request) if item.target in set(allowed_action_targets)],\n'
)
path.write_text(text, encoding='utf-8')
