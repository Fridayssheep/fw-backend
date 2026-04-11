from ai.backend.config import get_runtime_ai_config_path
from ai.backend.config import get_runtime_ai_config_payload
from ai.backend.config import update_runtime_ai_config_payload

from app.core.database import fetch_scalar
from app.schemas.schemas_system import RuntimeAIFeatureSettings
from app.schemas.schemas_system import RuntimeAISettingsResponse
from app.schemas.schemas_system import RuntimeAISettingsUpdateRequest
from app.schemas.schemas_system import RuntimeAISettingsUpdateResponse
from app.schemas.schemas_system import RuntimeLLMSettings
from app.schemas.schemas_system import RuntimeRagFlowSettings
from app.schemas.schemas_system import SystemCurrentTimeRequest
from app.schemas.schemas_system import SystemCurrentTimeResponse
from app.schemas.schemas_system import SystemHealth

from .service_common import get_app_timezone_name
from .service_common import get_timezone_now
from .service_common import resolve_effective_current_time


def get_system_health() -> SystemHealth:
    fetch_scalar("SELECT 1")
    return SystemHealth(
        status="ok",
        database="ok",
        timestamp=get_timezone_now(),
    )


def get_system_current_time(payload: SystemCurrentTimeRequest) -> SystemCurrentTimeResponse:
    """统一解析前端传入的当前时间上下文，供 AI 和图表共用。"""

    effective_time = resolve_effective_current_time(
        use_current_time=payload.use_current_time,
        current_time=payload.current_time,
        timezone=payload.timezone,
    )
    return SystemCurrentTimeResponse(
        use_current_time=payload.use_current_time,
        current_time=effective_time,
        timezone=effective_time.tzinfo.key if getattr(effective_time.tzinfo, "key", None) else (payload.timezone or get_app_timezone_name()),
        source="server_now" if payload.use_current_time else "custom_time",
    )


def get_runtime_ai_settings() -> RuntimeAISettingsResponse:
    payload = get_runtime_ai_config_payload()
    return RuntimeAISettingsResponse(
        config_path=get_runtime_ai_config_path(),
        llm=RuntimeLLMSettings(**payload["llm"]),
        ragflow=RuntimeRagFlowSettings(**payload["ragflow"]),
        features=RuntimeAIFeatureSettings(**payload["features"]),
    )


def update_runtime_ai_settings(payload: RuntimeAISettingsUpdateRequest) -> RuntimeAISettingsUpdateResponse:
    update_runtime_ai_config_payload(payload.model_dump(mode="json"))
    latest = get_runtime_ai_settings()
    return RuntimeAISettingsUpdateResponse(
        message="AI runtime settings updated.",
        config_path=latest.config_path,
        llm=latest.llm,
        ragflow=latest.ragflow,
        features=latest.features,
    )
