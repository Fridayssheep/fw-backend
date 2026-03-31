import os
from dataclasses import dataclass


DEFAULT_ALLOWED_ACTION_TARGETS = (
    'energy_trend',
    'energy_compare',
    'energy_weather_correlation',
    'energy_anomaly_analysis',
    '/ai/anomaly-feedback',
)


def _parse_csv_env(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into a normalized tuple."""

    if not value or not value.strip():
        return default
    parsed = tuple(item.strip() for item in value.split(',') if item.strip())
    return parsed or default


@dataclass(frozen=True)
class AISettings:
    """Centralized runtime settings for AI-related services."""

    llm_base_url: str = os.getenv('LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
    llm_api_key: str = os.getenv('LLM_API_KEY', 'ollama')
    llm_model: str = os.getenv('LLM_MODEL', 'qwen3.5:latest')
    llm_timeout_seconds: float = float(os.getenv('LLM_TIMEOUT_SECONDS', '420'))
    llm_temperature: float = float(os.getenv('LLM_TEMPERATURE', '0.2'))
    llm_top_p: float = float(os.getenv('LLM_TOP_P', '0.9'))
    ai_enable_history: bool = os.getenv('AI_ENABLE_HISTORY', 'true').lower() in {'1', 'true', 'yes', 'y'}
    ai_enable_knowledge: bool = os.getenv('AI_ENABLE_KNOWLEDGE', 'true').lower() in {'1', 'true', 'yes', 'y'}
    ai_allowed_action_targets: tuple[str, ...] = _parse_csv_env(
        os.getenv('AI_ALLOWED_ACTION_TARGETS'),
        DEFAULT_ALLOWED_ACTION_TARGETS,
    )


def get_ai_settings() -> AISettings:
    """Build a fresh settings object from environment variables."""

    return AISettings()
