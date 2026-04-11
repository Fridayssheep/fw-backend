from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from .schemas_common import CurrentTimeContext


class SystemHealth(BaseModel):
    status: str
    database: str
    timestamp: datetime


class SystemCurrentTimeRequest(CurrentTimeContext):
    pass


class SystemCurrentTimeResponse(BaseModel):
    use_current_time: bool = Field(..., description="本次是否直接使用后端当前时间。")
    current_time: datetime = Field(..., description="后端最终解析出的当前时间。")
    timezone: str = Field(..., description="本次当前时间对应的时区名称。")
    source: str = Field(..., description="时间来源：server_now 或 custom_time。")


class RuntimeLLMSettings(BaseModel):
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    api_key_configured: bool = Field(default=False)
    model: str = Field(default="")
    timeout_seconds: float = Field(default=420)
    temperature: float = Field(default=0.2)
    top_p: float = Field(default=0.9)


class RuntimeRagFlowSettings(BaseModel):
    api_url: str = Field(default="")
    api_key: str = Field(default="")
    api_key_configured: bool = Field(default=False)
    timeout_seconds: float = Field(default=60)
    chat_model: str = Field(default="")
    dataset_ids: list[str] = Field(default_factory=list)
    default_chat_id: str = Field(default="")


class RuntimeAIFeatureSettings(BaseModel):
    enable_history: bool = Field(default=True)
    enable_knowledge: bool = Field(default=True)


class RuntimeAISettingsPayload(BaseModel):
    llm: RuntimeLLMSettings
    ragflow: RuntimeRagFlowSettings
    features: RuntimeAIFeatureSettings


class RuntimeAISettingsResponse(RuntimeAISettingsPayload):
    config_path: str


class RuntimeLLMSettingsUpdate(BaseModel):
    base_url: str = Field(default="")
    api_key: str = Field(default="")
    api_key_configured: bool | None = Field(default=None)
    model: str = Field(default="")
    timeout_seconds: float = Field(default=420)
    temperature: float = Field(default=0.2)
    top_p: float = Field(default=0.9)


class RuntimeRagFlowSettingsUpdate(BaseModel):
    api_url: str = Field(default="")
    api_key: str = Field(default="")
    api_key_configured: bool | None = Field(default=None)
    timeout_seconds: float = Field(default=60)
    chat_model: str = Field(default="")
    dataset_ids: list[str] = Field(default_factory=list)
    default_chat_id: str = Field(default="")


class RuntimeAISettingsUpdateRequest(BaseModel):
    llm: RuntimeLLMSettingsUpdate
    ragflow: RuntimeRagFlowSettingsUpdate
    features: RuntimeAIFeatureSettings


class RuntimeAISettingsUpdateResponse(RuntimeAISettingsResponse):
    message: str
