from __future__ import annotations

from typing import Any

from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import AIQAContext
from app.schemas import AIQAMeta
from app.schemas import AIQAReferences
from app.schemas import AIQARequest
from app.schemas import AIQAResponse
from app.schemas import AIReferenceItem
from app.schemas import AISuggestedAction
from app.schemas import AIUsedToolItem
from app.schemas import AIQueryAssistantRequest
from app.service_common import get_taipei_now

from .anomaly_service import analyze_anomaly_with_ai
from .config import get_ai_settings
from .llm_client import OpenAICompatibleClient
from .query_assistant_service import build_query_intent
from .ragflow_client import ragflow_client


MAX_QA_REFERENCE_ITEMS = 5
MAX_QA_SNIPPET_LENGTH = 320

KNOWLEDGE_KEYWORDS = (
    "怎么",
    "如何",
    "要求",
    "规范",
    "说明书",
    "手册",
    "故障代码",
    "原理",
    "meaning",
    "manual",
)
DATA_QUERY_KEYWORDS = (
    "能耗",
    "趋势",
    "排行",
    "排名",
    "对比",
    "比较",
    "天气",
    "查询",
    "数据",
    "cop",
    "电耗",
    "水耗",
)
FAULT_ANALYSIS_KEYWORDS = (
    "异常",
    "故障",
    "报警",
    "告警",
    "诊断",
    "排查",
    "原因",
    "为什么",
)

KNOWLEDGE_QA_SYSTEM_PROMPT = """\
你是“建筑能源总览 AI”中的知识问答助手。

你必须只基于给定的知识片段回答问题，不要把未提供的内容当作已知事实。
如果证据不足，要明确说明“当前知识片段不足以确认”。

输出必须是合法 JSON，且只包含一个字段：
- answer
"""


def _trim_text(value: str, max_length: int = MAX_QA_SNIPPET_LENGTH) -> str:
    """裁剪长文本，避免返回过长引用。"""

    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _classify_question_type(question: str) -> str:
    """对问题做轻量分类，供总览式 AI 选择下一步工具。"""

    lowered = question.lower()
    fault_hits = sum(1 for item in FAULT_ANALYSIS_KEYWORDS if item.lower() in lowered)
    data_hits = sum(1 for item in DATA_QUERY_KEYWORDS if item.lower() in lowered)
    knowledge_hits = sum(1 for item in KNOWLEDGE_KEYWORDS if item.lower() in lowered)

    if fault_hits and data_hits:
        return "mixed"
    if fault_hits:
        return "fault_analysis"
    if data_hits:
        return "data_query"
    if knowledge_hits:
        return "knowledge"
    return "other"


def _has_context_for_fault_analysis(context: AIQAContext | None) -> bool:
    """判断当前上下文是否足够支持异常分析。"""

    return bool(
        context
        and context.building_id
        and context.meter
        and context.time_range
    )


def _build_meta(settings_model: str, used_tools: list[AIUsedToolItem], references: AIQAReferences) -> AIQAMeta:
    """统一构造 /ai/qa 元信息。"""

    has_references = bool(references.knowledge or references.data or references.history_cases)
    return AIQAMeta(
        provider="orchestrated",
        model=settings_model,
        generated_at=get_taipei_now(),
        used_tools_count=len(used_tools),
        has_references=has_references,
    )


def _build_knowledge_reference_items(references: dict[str, Any]) -> list[AIReferenceItem]:
    """把 retrieval 结果压成适合前端显示的知识库引用。"""

    items: list[AIReferenceItem] = []
    for chunk in (references.get("chunks", []) or [])[:MAX_QA_REFERENCE_ITEMS]:
        items.append(
            AIReferenceItem(
                source_type="knowledge",
                document_id=chunk.get("document_id"),
                document_name=chunk.get("document_name"),
                chunk_id=chunk.get("chunk_id"),
                snippet=_trim_text(str(chunk.get("content") or "")),
                score=chunk.get("similarity"),
            )
        )
    return items


def _build_data_reference_items(query_result: Any) -> list[AIReferenceItem]:
    """把 query-assistant 的结果压成数据查询证据。"""

    return [
        AIReferenceItem(
            source_type="data",
            document_id=None,
            document_name=query_result.recommended_endpoint,
            chunk_id=None,
            snippet=_trim_text(
                f"{query_result.summary} 参数: {query_result.recommended_query_params}",
                max_length=220,
            ),
            score=None,
        )
    ]


def _build_references_from_anomaly(anomaly_result: Any) -> AIQAReferences:
    """把异常分析结果中的 evidence 统一映射到 /ai/qa 引用结构。"""

    references = AIQAReferences()
    for item in anomaly_result.evidence[:MAX_QA_REFERENCE_ITEMS]:
        reference = AIReferenceItem(
            source_type="data",
            document_id=None,
            document_name=item.source,
            chunk_id=item.evidence_id,
            snippet=_trim_text(item.snippet),
            score=item.weight,
        )
        if item.type in {"knowledge", "rule"}:
            reference.source_type = "knowledge"
            references.knowledge.append(reference)
        elif item.type == "history_case":
            reference.source_type = "history_case"
            references.history_cases.append(reference)
        else:
            references.data.append(reference)
    return references


def _build_actions_from_anomaly(anomaly_result: Any) -> list[AISuggestedAction]:
    """把异常分析里的 actions 映射成总览式 /ai/qa 的动作结构。"""

    actions: list[AISuggestedAction] = []
    for item in anomaly_result.actions[:3]:
        action_type = "call_api" if item.action_type == "open_api" else "open_page"
        actions.append(
            AISuggestedAction(
                label=item.label,
                action_type=action_type,
                target=item.target,
            )
        )
    return actions


def _build_query_action(query_result: Any) -> list[AISuggestedAction]:
    """把 query-assistant 推荐结果映射成前端动作。"""

    return [
        AISuggestedAction(
            label="查看推荐查询",
            action_type="call_api",
            target=query_result.recommended_endpoint,
        )
    ]


def _fallback_knowledge_answer(question: str, knowledge_references: list[AIReferenceItem]) -> str:
    """在 LLM 不可用时，用命中片段兜底生成回答。"""

    if not knowledge_references:
        return "当前知识库中没有检索到足够相关的证据，建议换一种问法，或补充设备型号、场景和故障现象。"
    first = knowledge_references[0]
    doc_name = first.document_name or "未命名文档"
    return (
        f"根据知识库命中的资料《{doc_name}》，当前最相关的证据是：{first.snippet}。"
        "如果你需要，我可以继续结合更多上下文做更完整的解释。"
    )


def _generate_knowledge_answer(question: str, knowledge_references: list[AIReferenceItem], settings_model: str) -> str:
    """使用主模型基于知识片段生成最终回答。"""

    if not knowledge_references:
        return _fallback_knowledge_answer(question, knowledge_references)

    snippets = [
        {
            "document_name": item.document_name,
            "chunk_id": item.chunk_id,
            "snippet": item.snippet,
            "score": item.score,
        }
        for item in knowledge_references[:3]
    ]
    user_prompt = (
        "请基于下面这些知识片段回答用户问题。\n"
        "如果证据不足，请明确说不足，不要编造。\n\n"
        f"【用户问题】\n{question}\n\n"
        f"【知识片段】\n{snippets}\n"
    )
    settings = get_ai_settings()
    client = OpenAICompatibleClient(settings)
    try:
        result = client.generate_json(KNOWLEDGE_QA_SYSTEM_PROMPT, user_prompt)
    except Exception:  # noqa: BLE001
        return _fallback_knowledge_answer(question, knowledge_references)
    answer = str(result.get("answer") or "").strip()
    return answer or _fallback_knowledge_answer(question, knowledge_references)


def _handle_knowledge_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理知识库问答类问题。"""

    retrieval_references = ragflow_client.retrieve_references(
        question=payload.question,
        top_k=MAX_QA_REFERENCE_ITEMS,
    )
    knowledge_references = _build_knowledge_reference_items(retrieval_references)
    references = AIQAReferences(knowledge=knowledge_references)
    used_tools = [
        AIUsedToolItem(
            tool_name="search_domain_knowledge",
            tool_type="internal_service",
            reason="问题属于知识库检索场景，需要先获取文档证据。",
        )
    ]
    suggested_actions = [
        AISuggestedAction(
            label="查看知识引用",
            action_type="view_reference",
            target="knowledge_reference_panel",
        )
    ] if knowledge_references else []
    return AIQAResponse(
        answer=_generate_knowledge_answer(payload.question, knowledge_references, settings_model),
        question_type="knowledge",
        references=references,
        used_tools=used_tools,
        suggested_actions=suggested_actions,
        meta=_build_meta(settings_model, used_tools, references),
    )


def _handle_data_query_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理数据查询类问题。"""

    query_result = build_query_intent(
        AIQueryAssistantRequest(
            question=payload.question,
            current_time=get_taipei_now(),
        )
    )
    references = AIQAReferences(data=_build_data_reference_items(query_result))
    used_tools = [
        AIUsedToolItem(
            tool_name="query_assistant",
            tool_type="internal_service",
            reason="问题属于数据检索场景，需要先解析查询意图和推荐下游接口。",
        )
    ]
    warning_text = f" 注意事项：{'；'.join(query_result.warnings)}。" if query_result.warnings else ""
    answer = (
        f"{query_result.summary} 建议调用 {query_result.recommended_endpoint} "
        f"（{query_result.recommended_http_method}），推荐参数为 {query_result.recommended_query_params}。"
        f"{warning_text}"
    )
    return AIQAResponse(
        answer=answer,
        question_type="data_query",
        references=references,
        used_tools=used_tools,
        suggested_actions=_build_query_action(query_result),
        meta=_build_meta(settings_model, used_tools, references),
    )


def _handle_fault_analysis_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理带业务上下文的异常/故障分析类问题。"""

    if not _has_context_for_fault_analysis(payload.context):
        references = AIQAReferences()
        used_tools: list[AIUsedToolItem] = []
        return AIQAResponse(
            answer=(
                "这个问题更像异常/故障分析，但当前缺少必要上下文。"
                "请至少提供 building_id、meter 和 time_range，或从异常详情页带着上下文发起提问。"
            ),
            question_type="fault_analysis",
            references=references,
            used_tools=used_tools,
            suggested_actions=[
                AISuggestedAction(
                    label="前往异常分析页",
                    action_type="open_page",
                    target="anomaly_detail",
                )
            ],
            meta=_build_meta(settings_model, used_tools, references),
        )

    context = payload.context
    anomaly_result = analyze_anomaly_with_ai(
        AIAnalyzeAnomalyRequest(
            building_id=context.building_id or "",
            meter=context.meter or "electricity",
            time_range=context.time_range,
            include_weather_context=True,
            question=payload.question,
        )
    )
    references = _build_references_from_anomaly(anomaly_result)
    used_tools = [
        AIUsedToolItem(
            tool_name="analyze_anomaly_with_ai",
            tool_type="internal_service",
            reason="问题属于异常/故障分析场景，且上下文已足够支持单次诊断。",
        )
    ]
    return AIQAResponse(
        answer=anomaly_result.answer,
        question_type="fault_analysis",
        references=references,
        used_tools=used_tools,
        suggested_actions=_build_actions_from_anomaly(anomaly_result),
        meta=_build_meta(settings_model, used_tools, references),
    )


def ask_ai_question(payload: AIQARequest) -> AIQAResponse:
    """总览式 /ai/qa 编排入口。

    第一版策略：
    1. 先做问题分类
    2. 知识型问题走 RAG 检索 + 主模型归纳
    3. 数据型问题走 query-assistant
    4. 故障分析型问题在上下文充分时走 analyze-anomaly
    """

    settings = get_ai_settings()
    question_type = _classify_question_type(payload.question)

    if question_type == "data_query":
        return _handle_data_query_question(payload, settings.llm_model)
    if question_type in {"fault_analysis", "mixed"}:
        return _handle_fault_analysis_question(payload, settings.llm_model)
    return _handle_knowledge_question(payload, settings.llm_model)
