from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from .schemas_common import TimeRange


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
    baseline_mode: str
    generated_at: datetime
    model: str
    knowledge_hits: int = 0
    history_feedback_hits: int = 0
    used_fallback: bool = False


class AIAnalyzeAnomalyRequest(BaseModel):
    building_id: str
    meter: str
    time_range: TimeRange
    granularity: str | None = "hour"
    baseline_mode: str | None = "overall_mean"
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
    baseline_mode: str | None = None


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
    provider: str = Field(..., description="上游知识问答服务提供方")
    chat_id: str | None = Field(None, description="RAGFlow Chat ID")
    used_openai_compatible: bool = Field(default=True, description="是否使用 OpenAI-compatible 接口")


class AIQAResponse(BaseModel):
    answer: str = Field(..., description="AI 的回答")
    session_id: str | None = Field(None, description="当前会话 ID")
    references: AIQAReference = Field(default_factory=AIQAReference, description="知识库引用信息")
    meta: AIQAMeta = Field(..., description="调用元信息")
