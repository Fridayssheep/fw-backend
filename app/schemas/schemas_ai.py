from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from .schemas_common import TimeRange
from .schemas_energy import AnomalyDetectorBreakdownItem


class AIActionItem(BaseModel):
    label: str
    action_type: str
    target: str
    target_id: str | None = None


class AIEvidenceItem(BaseModel):
    evidence_id: str
    type: str
    source: str
    snippet: str
    weight: float | None = None


class AICandidateCause(BaseModel):
    cause_id: str
    title: str
    description: str
    confidence: float
    rank: int
    recommended_checks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class AIFeedbackPrompt(BaseModel):
    enabled: bool = True
    message: str
    allow_score: bool = True
    allow_comment: bool = True


class AIAnalyzeAnomalyMeta(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    analysis_mode: str = "offline_event_review"
    generated_at: datetime
    model: str
    event_count: int = 0
    detector_breakdown: list[AnomalyDetectorBreakdownItem] = Field(default_factory=list)
    knowledge_hits: int = 0
    history_feedback_hits: int = 0
    offline_context_used: bool = True
    used_fallback: bool = False


class AIAnalyzeAnomalyRequest(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    granularity: str | None = "hour"
    analysis_mode: str | None = "offline_event_review"
    include_weather_context: bool = False
    question: str | None = None
    include_history_feedback: bool = True
    max_candidate_causes: int = 3


class AIAnalyzeAnomalyResponse(BaseModel):
    analysis_id: str
    status: str
    summary: str
    answer: str
    candidate_causes: list[AICandidateCause]
    highlights: list[str] = Field(default_factory=list)
    evidence: list[AIEvidenceItem] = Field(default_factory=list)
    actions: list[AIActionItem] = Field(default_factory=list)
    risk_notice: str
    feedback_prompt: AIFeedbackPrompt
    meta: AIAnalyzeAnomalyMeta


class AIQueryIntent(BaseModel):
    building_ids: list[str] = Field(default_factory=list)
    site_id: str | None = None
    meter: str | None = None
    time_range: TimeRange | None = None
    granularity: str | None = None
    aggregation: str | None = None
    metric: str | None = None
    limit: int | None = None


class AIQueryAssistantRequest(BaseModel):
    question: str
    current_time: datetime | None = None


class AIQueryAssistantMeta(BaseModel):
    generated_at: datetime
    model: str
    used_fallback: bool = False


class AIQueryAssistantResponse(BaseModel):
    summary: str
    query_intent: AIQueryIntent
    recommended_endpoint: str
    recommended_http_method: str
    recommended_query_params: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    meta: AIQueryAssistantMeta


class CandidateFeedbackItem(BaseModel):
    cause_id: str
    score: int
    title: str | None = None


class SelectedCauseSummary(BaseModel):
    cause_id: str
    title: str
    score: int


class AnomalyFeedbackMeta(BaseModel):
    building_id: str
    meter: str
    resolution_status: str
    created_at: datetime


class AnomalyFeedbackRequest(BaseModel):
    analysis_id: str
    building_id: str
    meter: str
    time_range: TimeRange
    selected_cause_id: str
    selected_score: int
    selected_cause_title: str | None = None
    candidate_feedbacks: list[CandidateFeedbackItem] = Field(default_factory=list)
    comment: str | None = None
    operator_id: str | None = None
    operator_name: str | None = None
    resolution_status: str
    model_name: str | None = None
    analysis_mode: str | None = None


class AnomalyFeedbackResponse(BaseModel):
    feedback_id: str
    analysis_id: str
    stored: bool
    message: str
    selected_cause: SelectedCauseSummary
    meta: AnomalyFeedbackMeta


class AIQARequest(BaseModel):
    question: str = Field(..., description="用户提出的问题")
    session_id: str | None = Field(None, description="会话 ID，用于保持多轮对话上下文")
    context: "AIQAContext | None" = Field(None, description="页面上下文，用于异常分析等需要业务上下文的场景")


class AIQAContext(BaseModel):
    building_id: str | None = Field(None, description="当前页面建筑 ID")
    meter: str | None = Field(None, description="当前页面表计类型")
    time_range: TimeRange | None = Field(None, description="当前页面时间范围")


class AIReferenceItem(BaseModel):
    source_type: str = Field(..., description="引用来源类型：knowledge/data/history_case")
    document_id: str | None = Field(None, description="文档 ID")
    document_name: str | None = Field(None, description="文档名或来源名")
    chunk_id: str | None = Field(None, description="知识片段或证据 ID")
    snippet: str = Field(default="", description="引用摘要")
    score: float | None = Field(None, description="相关性或权重分数")


class AIQAReferences(BaseModel):
    knowledge: list["AIReferenceItem"] = Field(default_factory=list, description="知识库引用")
    data: list["AIReferenceItem"] = Field(default_factory=list, description="数据类引用")
    history_cases: list["AIReferenceItem"] = Field(default_factory=list, description="历史案例引用")


class AIUsedToolItem(BaseModel):
    tool_name: str = Field(..., description="内部调用工具名")
    tool_type: str = Field(..., description="工具类型")
    reason: str = Field(..., description="调用原因")


class AISuggestedAction(BaseModel):
    label: str = Field(..., description="前端展示动作文案")
    action_type: str = Field(..., description="动作类型，如 open_page/call_api/view_reference")
    target: str | None = Field(None, description="动作目标")


class AIQAReferenceChunk(BaseModel):
    chunk_id: str | None = Field(None, description="知识片段 ID")
    document_id: str | None = Field(None, description="文档 ID")
    document_name: str | None = Field(None, description="文档名称")
    dataset_id: str | None = Field(None, description="知识库 ID")
    content: str = Field(default="", description="知识片段内容")
    similarity: float | None = Field(None, description="相似度分数")
    metadata: dict[str, Any] = Field(default_factory=dict, description="原始元数据")


class AIQAReferenceDocAgg(BaseModel):
    document_id: str | None = Field(None, description="文档 ID")
    document_name: str | None = Field(None, description="文档名称")
    count: int | None = Field(None, description="命中的片段数量")


class AIQAReference(BaseModel):
    chunks: list[AIQAReferenceChunk] = Field(default_factory=list, description="引用的知识片段")
    doc_aggs: list[AIQAReferenceDocAgg] = Field(default_factory=list, description="按文档聚合的命中信息")


class AIQAMeta(BaseModel):
    provider: str = Field(..., description="本次回答提供方")
    model: str = Field(..., description="本次回答使用的主模型")
    generated_at: datetime = Field(..., description="生成时间")
    used_tools_count: int = Field(default=0, description="本次调用的工具数量")
    has_references: bool = Field(default=False, description="是否返回了可展示引用")
    stage_timings_ms: dict[str, int] = Field(default_factory=dict, description="分阶段耗时")


class AIQAResponse(BaseModel):
    answer: str = Field(..., description="AI 的回答")
    question_type: str = Field(..., description="识别后的问题类型")
    references: AIQAReferences = Field(default_factory=AIQAReferences, description="统一证据引用")
    used_tools: list[AIUsedToolItem] = Field(default_factory=list, description="内部已使用工具")
    suggested_actions: list[AISuggestedAction] = Field(default_factory=list, description="建议前端动作")
    meta: AIQAMeta = Field(..., description="调用元信息")
