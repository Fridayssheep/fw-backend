import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "runtime" / "ai_settings.json"
)


def _parse_csv_text(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value or not value.strip():
        return default
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    return parsed or default


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _parse_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_string(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _parse_string_list(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, list):
        parsed = tuple(str(item).strip() for item in value if str(item).strip())
        return parsed or default
    if isinstance(value, str):
        return _parse_csv_text(value, default)
    return default


def _runtime_config_path() -> Path:
    env_value = os.getenv("AI_RUNTIME_CONFIG_PATH")
    if env_value and env_value.strip():
        return Path(env_value).expanduser().resolve()
    return DEFAULT_RUNTIME_CONFIG_PATH


def _read_runtime_config() -> dict[str, Any]:
    path = _runtime_config_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_runtime_config(payload: dict[str, Any]) -> Path:
    path = _runtime_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    return path


@dataclass(frozen=True)
class AISettings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    llm_temperature: float
    llm_top_p: float
    ai_enable_history: bool
    ai_enable_knowledge: bool
    ragflow_api_url: str
    ragflow_api_key: str
    ragflow_timeout_seconds: float
    ragflow_chat_model: str
    ragflow_dataset_ids: tuple[str, ...]
    ragflow_default_chat_id: str


def get_runtime_ai_config_payload() -> dict[str, Any]:
    settings = get_ai_settings()
    return {
        "llm": {
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key,
            "api_key_configured": bool(settings.llm_api_key),
            "model": settings.llm_model,
            "timeout_seconds": settings.llm_timeout_seconds,
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
        },
        "ragflow": {
            "api_url": settings.ragflow_api_url,
            "api_key": settings.ragflow_api_key,
            "api_key_configured": bool(settings.ragflow_api_key),
            "timeout_seconds": settings.ragflow_timeout_seconds,
            "chat_model": settings.ragflow_chat_model,
            "dataset_ids": list(settings.ragflow_dataset_ids),
            "default_chat_id": settings.ragflow_default_chat_id,
        },
        "features": {
            "enable_history": settings.ai_enable_history,
            "enable_knowledge": settings.ai_enable_knowledge,
        },
    }


def update_runtime_ai_config_payload(payload: dict[str, Any]) -> Path:
    current = _read_runtime_config()
    llm_current = current.get("llm") if isinstance(current.get("llm"), dict) else {}
    ragflow_current = current.get("ragflow") if isinstance(current.get("ragflow"), dict) else {}
    features_current = current.get("features") if isinstance(current.get("features"), dict) else {}

    llm_payload = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
    ragflow_payload = payload.get("ragflow") if isinstance(payload.get("ragflow"), dict) else {}
    features_payload = payload.get("features") if isinstance(payload.get("features"), dict) else {}

    llm_api_key = str(llm_payload.get("api_key") or "").strip()
    ragflow_api_key = str(ragflow_payload.get("api_key") or "").strip()
    llm_should_clear_key = llm_payload.get("api_key_configured") is False and not llm_api_key
    ragflow_should_clear_key = ragflow_payload.get("api_key_configured") is False and not ragflow_api_key

    merged = {
        "llm": {
            "base_url": str(llm_payload.get("base_url") or llm_current.get("base_url") or "").strip(),
            "api_key": "" if llm_should_clear_key else (llm_api_key or str(llm_current.get("api_key") or "").strip()),
            "model": str(llm_payload.get("model") or llm_current.get("model") or "").strip(),
            "timeout_seconds": _parse_float(
                llm_payload.get("timeout_seconds"),
                _parse_float(llm_current.get("timeout_seconds"), 420.0),
            ),
            "temperature": _parse_float(
                llm_payload.get("temperature"),
                _parse_float(llm_current.get("temperature"), 0.2),
            ),
            "top_p": _parse_float(
                llm_payload.get("top_p"),
                _parse_float(llm_current.get("top_p"), 0.9),
            ),
        },
        "ragflow": {
            "api_url": str(ragflow_payload.get("api_url") or ragflow_current.get("api_url") or "").strip(),
            "api_key": "" if ragflow_should_clear_key else (ragflow_api_key or str(ragflow_current.get("api_key") or "").strip()),
            "timeout_seconds": _parse_float(
                ragflow_payload.get("timeout_seconds"),
                _parse_float(ragflow_current.get("timeout_seconds"), 60.0),
            ),
            "chat_model": str(ragflow_payload.get("chat_model") or ragflow_current.get("chat_model") or "").strip(),
            "dataset_ids": list(
                _parse_string_list(
                    ragflow_payload.get("dataset_ids"),
                    _parse_string_list(ragflow_current.get("dataset_ids"), ()),
                )
            ),
            "default_chat_id": str(
                ragflow_payload.get("default_chat_id") or ragflow_current.get("default_chat_id") or ""
            ).strip(),
        },
        "features": {
            "enable_history": _parse_bool(
                features_payload.get("enable_history"),
                _parse_bool(features_current.get("enable_history"), True),
            ),
            "enable_knowledge": _parse_bool(
                features_payload.get("enable_knowledge"),
                _parse_bool(features_current.get("enable_knowledge"), True),
            ),
        },
    }
    return _write_runtime_config(merged)


def get_runtime_ai_config_path() -> str:
    return str(_runtime_config_path())


def get_ai_settings() -> AISettings:
    runtime_payload = _read_runtime_config()
    llm_runtime = runtime_payload.get("llm") if isinstance(runtime_payload.get("llm"), dict) else {}
    ragflow_runtime = runtime_payload.get("ragflow") if isinstance(runtime_payload.get("ragflow"), dict) else {}
    features_runtime = runtime_payload.get("features") if isinstance(runtime_payload.get("features"), dict) else {}

    return AISettings(
        llm_base_url=_parse_string(llm_runtime.get("base_url"), os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")),
        llm_api_key=_parse_string(llm_runtime.get("api_key"), os.getenv("LLM_API_KEY", "ollama")),
        llm_model=_parse_string(llm_runtime.get("model"), os.getenv("LLM_MODEL", "qwen3.5:latest")),
        llm_timeout_seconds=_parse_float(llm_runtime.get("timeout_seconds"), _parse_float(os.getenv("LLM_TIMEOUT_SECONDS"), 420.0)),
        llm_temperature=_parse_float(llm_runtime.get("temperature"), _parse_float(os.getenv("LLM_TEMPERATURE"), 0.2)),
        llm_top_p=_parse_float(llm_runtime.get("top_p"), _parse_float(os.getenv("LLM_TOP_P"), 0.9)),
        ai_enable_history=_parse_bool(features_runtime.get("enable_history"), _parse_bool(os.getenv("AI_ENABLE_HISTORY"), True)),
        ai_enable_knowledge=_parse_bool(features_runtime.get("enable_knowledge"), _parse_bool(os.getenv("AI_ENABLE_KNOWLEDGE"), True)),
        ragflow_api_url=_parse_string(ragflow_runtime.get("api_url"), os.getenv("RAGFLOW_API_URL", "http://127.0.0.1:9380/api/v1")),
        ragflow_api_key=_parse_string(ragflow_runtime.get("api_key"), os.getenv("RAGFLOW_API_KEY", "")),
        ragflow_timeout_seconds=_parse_float(
            ragflow_runtime.get("timeout_seconds"),
            _parse_float(os.getenv("RAGFLOW_TIMEOUT_SECONDS"), 60.0),
        ),
        ragflow_chat_model=_parse_string(ragflow_runtime.get("chat_model"), os.getenv("RAGFLOW_CHAT_MODEL", "ragflow-chat")),
        ragflow_dataset_ids=_parse_string_list(
            ragflow_runtime.get("dataset_ids"),
            _parse_csv_text(os.getenv("RAGFLOW_DATASET_IDS"), ()),
        ),
        ragflow_default_chat_id=_parse_string(
            ragflow_runtime.get("default_chat_id"),
            os.getenv("RAGFLOW_DEFAULT_CHAT_ID", ""),
        ),
    )
