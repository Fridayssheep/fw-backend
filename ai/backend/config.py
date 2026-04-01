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
    # basic ai api settings
    llm_base_url: str = os.getenv('LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
    llm_api_key: str = os.getenv('LLM_API_KEY', 'ollama')
    llm_model: str = os.getenv('LLM_MODEL', 'qwen3.5:latest')
    llm_timeout_seconds: float = float(os.getenv('LLM_TIMEOUT_SECONDS', '420'))
    llm_temperature: float = float(os.getenv('LLM_TEMPERATURE', '0.2'))
    llm_top_p: float = float(os.getenv('LLM_TOP_P', '0.9'))
    ai_enable_history: bool = os.getenv('AI_ENABLE_HISTORY', 'true').lower() in {'1', 'true', 'yes', 'y'}
    ai_enable_knowledge: bool = os.getenv('AI_ENABLE_KNOWLEDGE', 'true').lower() in {'1', 'true', 'yes', 'y'}

    # RAGFlow settings
    ragflow_api_url: str = os.getenv('RAGFLOW_API_URL', 'http://127.0.0.1:9380/api/v1')
    ragflow_api_key: str = os.getenv('RAGFLOW_API_KEY', '')
    ragflow_timeout_seconds: float = float(os.getenv('RAGFLOW_TIMEOUT_SECONDS', '60'))
    # RAGFlow 的 OpenAI-compatible 聊天接口要求带 model 字段，但服务端会自行解析，开发期传固定占位值即可。
    ragflow_chat_model: str = os.getenv('RAGFLOW_CHAT_MODEL', 'ragflow-chat')
    ragflow_dataset_ids: tuple[str, ...] = _parse_csv_env(
        os.getenv('RAGFLOW_DATASET_IDS'),
        default=()
    )
    ragflow_default_chat_id: str = os.getenv('RAGFLOW_DEFAULT_CHAT_ID', '')

    ai_allowed_action_targets: tuple[str, ...] = _parse_csv_env(
        os.getenv('AI_ALLOWED_ACTION_TARGETS'),
        DEFAULT_ALLOWED_ACTION_TARGETS,
    )


def get_ai_settings() -> AISettings:
    """Build a fresh settings object from environment variables."""

    return AISettings()
