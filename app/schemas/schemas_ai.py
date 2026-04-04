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


class AIOpsGuideIncidentRef(BaseModel):
    incident_id: str | None = Field(None, description="故障/异常事件主键")
    message_id: str | None = Field(None, description="消息中心消息 ID")


class AIOpsGuideOperatorContext(BaseModel):
    operator_id: str | None = Field(None, description="接手人 ID")
    operator_name: str | None = Field(None, description="接手人名称")


class AIOpsGuidePageContext(BaseModel):
    source: str | None = Field(None, description="入口来源，如 message_center、anomaly_detail")
    page_type: str | None = Field(None, description="当前页面类型")
    current_chart_range: str | None = Field(None, description="当前图表时间范围标记")


class AIOpsGuideAnomalySnapshotInput(BaseModel):
    summary: str | None = Field(None, description="前端当前页面已有的异常摘要")
    analysis_mode: str | None = Field(None, description="异常分析模式")
    event_count: int | None = Field(None, description="当前页面已知异常事件数")
    detector_breakdown: list[AnomalyDetectorBreakdownItem] = Field(default_factory=list, description="检测器分布")
    event_ids: list[str] = Field(default_factory=list, description="当前页面已知异常事件 ID 列表")


class AIOpsGuideContextInput(BaseModel):
    building_id: str = Field(..., description="当前处理建筑 ID")
    meter: str = Field(..., description="当前处理表计类型")
    time_range: TimeRange = Field(..., description="当前处理时间范围")
    incident_ref: AIOpsGuideIncidentRef | None = Field(None, description="可选的故障/消息引用")
    page_context: AIOpsGuidePageContext | None = Field(None, description="页面来源和展示上下文")
    operator_context: AIOpsGuideOperatorContext | None = Field(None, description="当前接手人信息")
    anomaly_snapshot: AIOpsGuideAnomalySnapshotInput | None = Field(None, description="前端已有的异常快照")


class AIOpsGuideRequest(BaseModel):
    question: str | None = Field(None, description="可选补充问题，不传则使用默认运维指导问题")
    guide_mode: str = Field(default="standard_sop", description="指导模式：quick_check / standard_sop / expert")
    context: AIOpsGuideContextInput = Field(..., description="前端已知的最小故障上下文")
    include_knowledge: bool = Field(default=True, description="是否补充知识库证据")
    include_history: bool = Field(default=True, description="是否补充历史反馈经验")
    include_actions: bool = Field(default=True, description="是否返回建议动作")


class AIOpsGuideStep(BaseModel):
    step_id: str = Field(..., description="步骤 ID")
    title: str = Field(..., description="步骤标题")
    instruction: str = Field(..., description="具体执行说明")
    priority: str = Field(..., description="优先级：high / medium / low")
    expected_result: str | None = Field(None, description="预期结果")
    if_not_met: str | None = Field(None, description="未满足预期时的下一步")


class AIOpsGuideEvidence(BaseModel):
    source_type: str = Field(..., description="证据来源类型：data / knowledge / history_case")
    source: str = Field(..., description="证据来源名")
    snippet: str = Field(..., description="证据摘要")
    score: float | None = Field(None, description="相关性或证据权重")


class AIOpsGuideAction(BaseModel):
    label: str = Field(..., description="动作文案")
    action_type: str = Field(..., description="动作类型")
    target: str | None = Field(None, description="动作目标")


class AIOpsGuideApplicability(BaseModel):
    applies_to: list[str] = Field(default_factory=list, description="适用场景")
    not_applies_to: list[str] = Field(default_factory=list, description="不适用场景")


class AIOpsGuideDiagnosisSnapshot(BaseModel):
    analysis_mode: str = Field(default="offline_event_review", description="诊断分析模式")
    event_count: int = Field(default=0, description="异常事件数量")
    detector_breakdown: list[AnomalyDetectorBreakdownItem] = Field(default_factory=list, description="检测器分布")
    candidate_cause_titles: list[str] = Field(default_factory=list, description="主要候选原因标题")


class AIOpsGuideMeta(BaseModel):
    generated_at: datetime = Field(..., description="生成时间")
    model: str = Field(..., description="本次使用的主模型")
    used_tools: list[str] = Field(default_factory=list, description="内部已使用工具")
    context_source: str = Field(default="server_enriched", description="上下文补全来源")
    knowledge_hits: int = Field(default=0, description="知识命中数")
    history_feedback_hits: int = Field(default=0, description="历史反馈命中数")
    stage_timings_ms: dict[str, int] = Field(default_factory=dict, description="分阶段耗时")


class AIOpsGuideResponse(BaseModel):
    incident_id: str | None = Field(None, description="故障/异常事件主键")
    status: str = Field(..., description="结果状态：actionable / low_confidence / needs_more_context")
    summary: str = Field(..., description="运维指导摘要")
    preconditions: list[str] = Field(default_factory=list, description="执行前前置条件")
    steps: list[AIOpsGuideStep] = Field(default_factory=list, description="结构化排查步骤")
    evidence: list[AIOpsGuideEvidence] = Field(default_factory=list, description="关键证据")
    actions: list[AIOpsGuideAction] = Field(default_factory=list, description="建议前端动作")
    risk_notice: list[str] = Field(default_factory=list, description="风险提醒")
    applicability: AIOpsGuideApplicability = Field(default_factory=AIOpsGuideApplicability, description="适用范围")
    diagnosis_snapshot: AIOpsGuideDiagnosisSnapshot = Field(default_factory=AIOpsGuideDiagnosisSnapshot, description="诊断快照")
    meta: AIOpsGuideMeta = Field(..., description="调用元信息")


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
