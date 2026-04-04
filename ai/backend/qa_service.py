from __future__ import annotations

from time import perf_counter
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
from app.services.service_common import get_taipei_now

from .anomaly_service import analyze_anomaly_with_ai
from .config import get_ai_settings
from .knowledge import answer_with_domain_knowledge
from .knowledge import build_compact_knowledge_items
from .knowledge import search_domain_knowledge_references
from .llm_client import OpenAICompatibleClient
from .query_assistant_service import build_query_intent


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
    "趋势",
    "排行",
    "排名",
    "对比",
    "比较",
    "天气",
    "查询",
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

MIXED_QA_SYSTEM_PROMPT = """\
你是“建筑能源总览 AI”中的综合问答助手。

你的任务是把多个工具结果整合成一段清晰、可信、可执行的中文回答。

必须遵守以下规则：
1. 只能基于给定的工具结果作答，不要编造不存在的事实。
2. 先输出最明确、最直接的主结论，再补充建议动作。
3. 只有在某个子结果明确标记为信息不足时，才能说“当前信息不足”；如果子结果已经给出明确结论，就不要额外弱化。
4. 数据查询类结果本质上是“推荐接口与参数”，不要写成已经执行过查询。
5. 不要把次要知识片段扩写成新的规则结论，除非它已经在子结果中被明确写出。
6. 输出必须是合法 JSON，且只包含一个字段：
   - answer
"""


def _trim_text(value: str, max_length: int = MAX_QA_SNIPPET_LENGTH) -> str:
    """裁剪长文本，避免返回过长引用。"""

    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _classify_question_type(question: str) -> str:
    """对问题做轻量分类，供总览式 AI 选择下一步工具。"""

    signals = _detect_question_signals(question)
    hit_count = sum(1 for value in signals.values() if value)
    if hit_count >= 2:
        return "mixed"
    if signals["fault_analysis"]:
        return "fault_analysis"
    if signals["data_query"]:
        return "data_query"
    if signals["knowledge"]:
        return "knowledge"
    return "other"


def _detect_question_signals(question: str) -> dict[str, bool]:
    """识别问题中是否同时包含知识、数据、异常三类诉求。"""

    lowered = question.lower()
    knowledge_hit = any(item.lower() in lowered for item in KNOWLEDGE_KEYWORDS)
    if "《" in question and "》" in question:
        knowledge_hit = True
    return {
        "fault_analysis": any(item.lower() in lowered for item in FAULT_ANALYSIS_KEYWORDS),
        "data_query": any(item.lower() in lowered for item in DATA_QUERY_KEYWORDS),
        "knowledge": knowledge_hit,
    }


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
        stage_timings_ms={},
    )


def _build_meta_with_timings(
    settings_model: str,
    used_tools: list[AIUsedToolItem],
    references: AIQAReferences,
    stage_timings_ms: dict[str, int],
) -> AIQAMeta:
    """统一构造带阶段耗时的 /ai/qa 元信息。"""

    meta = _build_meta(settings_model, used_tools, references)
    meta.stage_timings_ms = stage_timings_ms
    return meta


def _duration_ms(start_time: float) -> int:
    """把 perf_counter 差值转成毫秒。"""

    return int((perf_counter() - start_time) * 1000)


def _prefix_stage_timings(prefix: str, stage_timings_ms: dict[str, int]) -> dict[str, int]:
    """给子链路耗时打前缀，便于 mixed 场景归因。"""

    return {
        f"{prefix}_{key}": value
        for key, value in stage_timings_ms.items()
    }


def _merge_references(*reference_groups: AIQAReferences) -> AIQAReferences:
    """合并多路引用，并限制每类最多保留若干条。"""

    merged = AIQAReferences()
    for group in reference_groups:
        if not group:
            continue
        merged.knowledge.extend(group.knowledge)
        merged.data.extend(group.data)
        merged.history_cases.extend(group.history_cases)
    merged.knowledge = merged.knowledge[:MAX_QA_REFERENCE_ITEMS]
    merged.data = merged.data[:MAX_QA_REFERENCE_ITEMS]
    merged.history_cases = merged.history_cases[:MAX_QA_REFERENCE_ITEMS]
    return merged


def _dedupe_actions(actions: list[AISuggestedAction]) -> list[AISuggestedAction]:
    """按 action_type + target 去重动作列表。"""

    deduped: list[AISuggestedAction] = []
    seen: set[tuple[str, str | None]] = set()
    for item in actions:
        key = (item.action_type, item.target)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_knowledge_reference_items(references: dict[str, Any]) -> list[AIReferenceItem]:
    """把 retrieval 结果压成适合前端显示的知识库引用。"""

    items: list[AIReferenceItem] = []
    compact_items = build_compact_knowledge_items(
        references,
        max_items=MAX_QA_REFERENCE_ITEMS,
        snippet_length=MAX_QA_SNIPPET_LENGTH,
    )
    for chunk in compact_items:
        items.append(
            AIReferenceItem(
                source_type="knowledge",
                document_id=chunk.get("document_id"),
                document_name=chunk.get("document_name"),
                chunk_id=chunk.get("chunk_id"),
                snippet=chunk.get("snippet") or "",
                score=chunk.get("score"),
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


def _fallback_mixed_answer(question: str, answer_parts: list[str]) -> str:
    """在综合回答的 LLM 汇总失败时，使用确定性拼接兜底。"""

    clean_parts = [item.strip() for item in answer_parts if item and item.strip()]
    if not clean_parts:
        return (
            f"我理解你的问题是：{question}。"
            "不过当前没有拿到足够的工具结果，建议补充上下文后再试。"
        )
    return "\n\n".join(clean_parts)


def _response_has_substantive_findings(response: AIQAResponse) -> bool:
    """判断子响应是否已经给出足够明确的业务结论。"""

    if response.references.knowledge or response.references.data or response.references.history_cases:
        return True
    answer = response.answer.strip()
    return bool(answer and "缺少必要上下文" not in answer and "当前信息不足" not in answer)


def _extract_key_evidence(response: AIQAResponse) -> list[str]:
    """抽取 mixed 汇总用的关键证据片段。"""

    evidence_items = (
        response.references.knowledge[:2]
        + response.references.data[:2]
        + response.references.history_cases[:1]
    )
    return [
        item.snippet
        for item in evidence_items
        if item.snippet.strip()
    ][:3]


def _build_mixed_part(source: str, response: AIQAResponse) -> dict[str, Any]:
    """把子响应压成结构化 mixed 汇总输入。"""

    primary_action = response.suggested_actions[0].target if response.suggested_actions else None
    return {
        "source": source,
        "question_type": response.question_type,
        "answer": response.answer.strip(),
        "has_substantive_findings": _response_has_substantive_findings(response),
        "reference_counts": {
            "knowledge": len(response.references.knowledge),
            "data": len(response.references.data),
            "history_cases": len(response.references.history_cases),
        },
        "key_evidence": _extract_key_evidence(response),
        "used_tools": [item.tool_name for item in response.used_tools],
        "suggested_action_targets": [item.target for item in response.suggested_actions if item.target],
        "primary_action_target": primary_action,
    }


def _synthesize_mixed_answer(
    question: str,
    answer_parts: list[dict[str, Any]],
) -> str:
    """把多路工具结果合成为一段最终回答。"""

    clean_parts = [
        item
        for item in answer_parts
        if str(item.get("answer", "")).strip()
    ]
    if not clean_parts:
        return _fallback_mixed_answer(question, [])

    settings = get_ai_settings()
    client = OpenAICompatibleClient(settings)
    user_prompt = (
        "请把下面这些工具结果整理成一段简洁、可信、对用户有帮助的最终回答。\n"
        "如果其中某部分只是建议或推荐，请明确这是建议，不要伪装成已经执行的结果。\n"
        "如果某一部分已经给出明确结论，不要再额外加“信息不足”之类的弱化表述。\n\n"
        f"【用户问题】\n{question}\n\n"
        f"【工具结果】\n{clean_parts}\n"
    )
    try:
        result = client.generate_json(MIXED_QA_SYSTEM_PROMPT, user_prompt)
    except Exception:  # noqa: BLE001
        return _fallback_mixed_answer(question, [str(item["answer"]) for item in clean_parts])
    answer = str(result.get("answer") or "").strip()
    return answer or _fallback_mixed_answer(question, [str(item["answer"]) for item in clean_parts])


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


def _knowledge_answer_is_insufficient(answer: str) -> bool:
    """判断知识问答当前是否仍表现为证据不足。"""

    normalized = answer.strip()
    insufficient_markers = (
        "当前知识片段不足以确认",
        "知识片段不足以确认",
        "没有检索到足够相关的证据",
        "证据不足",
        "无法确认",
    )
    return any(marker in normalized for marker in insufficient_markers)


def _handle_knowledge_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理知识库问答类问题。"""

    total_start = perf_counter()
    stage_timings_ms: dict[str, int] = {}

    retrieval_start = perf_counter()
    retrieval_references = search_domain_knowledge_references(
        payload.question,
        top_k=MAX_QA_REFERENCE_ITEMS,
    )
    stage_timings_ms["retrieval_ms"] = _duration_ms(retrieval_start)
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
    knowledge_llm_start = perf_counter()
    answer = _generate_knowledge_answer(payload.question, knowledge_references, settings_model)
    stage_timings_ms["knowledge_llm_ms"] = _duration_ms(knowledge_llm_start)

    if _knowledge_answer_is_insufficient(answer):
        rag_chat_start = perf_counter()
        rag_chat_result = answer_with_domain_knowledge(payload.question)
        stage_timings_ms["rag_chat_ms"] = _duration_ms(rag_chat_start)
        rag_chat_answer = str(rag_chat_result.get("answer") or "").strip()
        if rag_chat_answer:
            answer = rag_chat_answer
            used_tools.append(
                AIUsedToolItem(
                    tool_name="answer_with_domain_knowledge",
                    tool_type="internal_service",
                    reason="结构化检索证据不足，追加使用 RAGFlow chat 尝试补充知识回答。",
                )
            )

    stage_timings_ms["total_ms"] = _duration_ms(total_start)
    return AIQAResponse(
        answer=answer,
        question_type="knowledge",
        references=references,
        used_tools=used_tools,
        suggested_actions=suggested_actions,
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_data_query_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理数据查询类问题。"""

    total_start = perf_counter()
    query_assistant_start = perf_counter()
    query_result = build_query_intent(
        AIQueryAssistantRequest(
            question=payload.question,
            current_time=get_taipei_now(),
        )
    )
    stage_timings_ms = {
        "query_assistant_ms": _duration_ms(query_assistant_start),
    }
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
    stage_timings_ms["total_ms"] = _duration_ms(total_start)
    return AIQAResponse(
        answer=answer,
        question_type="data_query",
        references=references,
        used_tools=used_tools,
        suggested_actions=_build_query_action(query_result),
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_fault_analysis_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理带业务上下文的异常/故障分析类问题。"""

    total_start = perf_counter()
    if not _has_context_for_fault_analysis(payload.context):
        references = AIQAReferences()
        used_tools: list[AIUsedToolItem] = []
        stage_timings_ms = {
            "total_ms": _duration_ms(total_start),
        }
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
            meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
        )

    context = payload.context
    anomaly_analysis_start = perf_counter()
    anomaly_result = analyze_anomaly_with_ai(
        AIAnalyzeAnomalyRequest(
            building_id=context.building_id or "",
            meter=context.meter or "electricity",
            time_range=context.time_range,
            include_weather_context=True,
            question=payload.question,
        )
    )
    stage_timings_ms = {
        "anomaly_analysis_ms": _duration_ms(anomaly_analysis_start),
    }
    references = _build_references_from_anomaly(anomaly_result)
    used_tools = [
        AIUsedToolItem(
            tool_name="analyze_anomaly_with_ai",
            tool_type="internal_service",
            reason="问题属于异常/故障分析场景，且上下文已足够支持单次诊断。",
        )
    ]
    stage_timings_ms["total_ms"] = _duration_ms(total_start)
    return AIQAResponse(
        answer=anomaly_result.answer,
        question_type="fault_analysis",
        references=references,
        used_tools=used_tools,
        suggested_actions=_build_actions_from_anomaly(anomaly_result),
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_mixed_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理混合型问题。

    当前第一版策略：
    1. 先识别知识 / 数据 / 异常三个子诉求
    2. 命中哪个就调用哪个能力
    3. 将多路结果合成为一个统一回答
    """

    total_start = perf_counter()
    signals = _detect_question_signals(payload.question)
    used_tools: list[AIUsedToolItem] = []
    suggested_actions: list[AISuggestedAction] = []
    reference_groups: list[AIQAReferences] = []
    answer_parts: list[dict[str, Any]] = []
    stage_timings_ms: dict[str, int] = {}

    if signals["knowledge"]:
        knowledge_response = _handle_knowledge_question(payload, settings_model)
        reference_groups.append(knowledge_response.references)
        used_tools.extend(knowledge_response.used_tools)
        suggested_actions.extend(knowledge_response.suggested_actions)
        answer_parts.append(_build_mixed_part("knowledge", knowledge_response))
        stage_timings_ms.update(
            _prefix_stage_timings("knowledge", knowledge_response.meta.stage_timings_ms)
        )

    if signals["data_query"]:
        data_response = _handle_data_query_question(payload, settings_model)
        reference_groups.append(data_response.references)
        used_tools.extend(data_response.used_tools)
        suggested_actions.extend(data_response.suggested_actions)
        answer_parts.append(_build_mixed_part("data_query", data_response))
        stage_timings_ms.update(
            _prefix_stage_timings("data_query", data_response.meta.stage_timings_ms)
        )

    if signals["fault_analysis"]:
        fault_response = _handle_fault_analysis_question(payload, settings_model)
        reference_groups.append(fault_response.references)
        used_tools.extend(fault_response.used_tools)
        suggested_actions.extend(fault_response.suggested_actions)
        answer_parts.append(_build_mixed_part("fault_analysis", fault_response))
        stage_timings_ms.update(
            _prefix_stage_timings("fault_analysis", fault_response.meta.stage_timings_ms)
        )

    references = _merge_references(*reference_groups)
    deduped_actions = _dedupe_actions(suggested_actions)
    mixed_synthesis_start = perf_counter()
    answer = _synthesize_mixed_answer(payload.question, answer_parts)
    stage_timings_ms["mixed_synthesis_ms"] = _duration_ms(mixed_synthesis_start)
    stage_timings_ms["total_ms"] = _duration_ms(total_start)
    return AIQAResponse(
        answer=answer,
        question_type="mixed",
        references=references,
        used_tools=used_tools,
        suggested_actions=deduped_actions,
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
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
    if question_type == "mixed":
        return _handle_mixed_question(payload, settings.llm_model)
    if question_type == "fault_analysis":
        return _handle_fault_analysis_question(payload, settings.llm_model)
    return _handle_knowledge_question(payload, settings.llm_model)
