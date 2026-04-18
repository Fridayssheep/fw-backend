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
from app.core.events import broker
from app.services.services_energy import get_energy_compare
from app.services.services_energy import get_energy_query
from app.services.services_energy import get_energy_rankings
from app.services.services_energy import get_energy_trend
from app.services.services_energy import get_energy_weather_correlation
from app.services.service_common import get_timezone_now
from app.services.service_common import resolve_request_current_time
from ai.mcp.formatters import _summarize_energy_compare
from ai.mcp.formatters import _summarize_energy_query
from ai.mcp.formatters import _summarize_energy_rankings
from ai.mcp.formatters import _summarize_energy_trend
from ai.mcp.formatters import _summarize_weather_correlation

from .anomaly_service import analyze_anomaly_with_ai
from .config import get_ai_settings
from .knowledge import answer_with_domain_knowledge
from .knowledge import build_compact_knowledge_items
from .knowledge import search_domain_knowledge_references
from .llm_client import OpenAICompatibleClient
from .qa_session_service import build_effective_context
from .qa_session_service import get_or_create_session
from .qa_session_service import load_recent_messages
from .qa_session_service import rewrite_followup_question
from .qa_session_service import save_assistant_message
from .qa_session_service import save_error_message
from .qa_session_service import save_user_message
from .qa_session_service import update_session_failure_state
from .qa_session_service import update_session_state
from .query_assistant_service import build_query_intent


MAX_QA_REFERENCE_ITEMS = 5
MAX_QA_SNIPPET_LENGTH = 320


def _publish_qa_status(message: str, context: str = "", event_type: str = "ai_status") -> None:
    broker.publish_sync(message=message, context=context, event_type=event_type)

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
ASSISTANT_CAPABILITY_PATTERNS = (
    "你可以做什么",
    "你能做什么",
    "你会什么",
    "你会做什么",
    "能帮我做什么",
    "可以帮我做什么",
    "你支持什么",
    "有什么能力",
    "你的能力",
    "你能帮我",
    "怎么用你",
    "如何使用你",
    "你是什么",
    "你是谁",
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
4. 数据查询类结果可能是“已执行查询”或“仅推荐接口”。如果 data_execution_mode 是 executed，可以直接陈述查询结果；如果是 planned，必须明确那只是建议调用。
5. 不要把次要知识片段扩写成新的规则结论，除非它已经在子结果中被明确写出。
6. 输出必须是合法 JSON，且只包含一个字段：
   - answer
"""

DATA_TOOL_SELECTION_SYSTEM_PROMPT = """\
你是“建筑能源总览 AI”中的数据工具选择器。

你的任务是根据用户问题、解析出的查询意图以及候选工具清单，选择最合适的一个数据工具。

必须遵守以下规则：
1. 只能从给定的 allowed_tools 中选择 tool_name。
2. 优先选择能直接回答用户问题的工具。
3. 如果用户明显在问趋势/变化，优先 energy_trend。
4. 如果用户明显在问明细/列表/原始数据，优先 energy_query。
5. 如果用户明显在问对比，优先 energy_compare。
6. 如果用户明显在问排行，优先 energy_rankings。
7. 如果用户明显在问天气相关性，优先 energy_weather_correlation。

输出必须是合法 JSON，且只包含：
- tool_name
- reason
"""

DATA_RESULT_QA_SYSTEM_PROMPT = """\
你是“建筑能源总览 AI”中的数据分析助手。

请基于已经执行完成的数据工具结果，用简洁、自然、可信的中文回答用户问题。

必须遵守以下规则：
1. 只能基于给定的数据工具结果作答，不要编造不存在的数值或趋势。
2. 优先回答用户最关心的结论，再补充 1-2 个关键观察。
3. 如果当前结果不足以直接回答问题，要明确说明不足之处。
4. 不要输出原始 JSON，不要把内部字段名直接抛给用户。

输出必须是合法 JSON，且只包含：
- answer
"""

QUESTION_ROUTER_SYSTEM_PROMPT = """\
你是“建筑能源总览 AI”中的问题路由器。

你的任务是理解用户真实意图，并把问题路由到最合适的能力类型。

允许的 question_type 只有：
- assistant_capability
- knowledge
- data_query
- fault_analysis
- mixed
- other

路由规则：
1. 如果用户在问“你是谁、你能做什么、怎么用你、支持哪些能力”之类的助手自述问题，选 assistant_capability。
2. 如果用户主要在问概念解释、规范、原理、术语、排查方法、说明文档等知识内容，选 knowledge。
3. 如果用户主要想查看、统计、比较、排行、趋势分析真实业务数据，选 data_query。
4. 如果用户主要在问异常原因、故障诊断、报警排查、为什么异常、如何定位问题，选 fault_analysis。
5. 如果用户明显同时需要两种及以上能力，例如既要查数据又要解释原因，或既要知识解释又要结合当前异常分析，选 mixed。
6. 只有在问题过于模糊、只是寒暄、或无法稳定判断时，才选 other。

重要约束：
1. 不要因为出现个别关键词就机械分类，要按用户真实意图判断。
2. 即使当前上下文不足以真正执行异常分析，只要用户意图明显是诊断异常，也应该选 fault_analysis，由后续链路负责提示缺少上下文。
3. 如果只是让助手介绍自己，不要路由到 knowledge。

输出必须是合法 JSON，且只包含：
- question_type
- reason
"""

DATA_TOOL_NAME_BY_ENDPOINT = {
    "/energy/query": "energy_query",
    "/energy/trend": "energy_trend",
    "/energy/compare": "energy_compare",
    "/energy/rankings": "energy_rankings",
    "/energy/weather-correlation": "energy_weather_correlation",
}
VALID_QUESTION_TYPES = {
    "assistant_capability",
    "knowledge",
    "data_query",
    "fault_analysis",
    "mixed",
    "other",
}


def _trim_text(value: str, max_length: int = MAX_QA_SNIPPET_LENGTH) -> str:
    """裁剪长文本，避免返回过长引用。"""

    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _classify_question_type_by_rules(question: str) -> str:
    """规则兜底分类，供模型路由失败时回退。"""

    if _is_assistant_capability_question(question):
        return "assistant_capability"

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


def _classify_question_type(question: str, context: AIQAContext | None) -> tuple[str, str]:
    """优先使用模型理解问题意图，失败时回退到规则分类。"""

    settings = get_ai_settings()
    client = OpenAICompatibleClient(settings)
    context_summary = {
        "building_id": context.building_id if context else None,
        "meter": context.meter if context else None,
        "time_range": (
            {
                "start": context.time_range.start,
                "end": context.time_range.end,
            }
            if context and context.time_range
            else None
        ),
    }
    user_prompt = (
        f"【用户问题】\n{question}\n\n"
        f"【当前上下文】\n{context_summary}\n"
    )
    try:
        result = client.generate_json(QUESTION_ROUTER_SYSTEM_PROMPT, user_prompt)
    except Exception:  # noqa: BLE001
        fallback_type = _classify_question_type_by_rules(question)
        return fallback_type, "模型路由失败，已回退到规则分类。"

    question_type = str(result.get("question_type") or "").strip()
    if question_type not in VALID_QUESTION_TYPES:
        fallback_type = _classify_question_type_by_rules(question)
        return fallback_type, "模型路由返回了非法类型，已回退到规则分类。"

    reason = str(result.get("reason") or "").strip() or "主模型根据问题语义完成了能力路由。"
    return question_type, reason


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


def _is_assistant_capability_question(question: str) -> bool:
    """识别用户是否在询问助手本身的定位、能力边界或使用方式。"""

    normalized = question.strip().lower()
    return any(pattern in normalized for pattern in ASSISTANT_CAPABILITY_PATTERNS)


def _has_context_for_fault_analysis(context: AIQAContext | None) -> bool:
    """判断当前上下文是否足够支持异常分析。"""

    return bool(
        context
        and (context.building_id or context.site_id)
        and context.meter
        and context.time_range
    )


def _build_meta(settings_model: str, used_tools: list[AIUsedToolItem], references: AIQAReferences) -> AIQAMeta:
    """统一构造 /ai/qa 元信息。"""

    has_references = bool(references.knowledge or references.data or references.history_cases)
    return AIQAMeta(
        provider="orchestrated",
        model=settings_model,
        generated_at=get_timezone_now(),
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
            document_name=query_result.query_plan.endpoint,
            chunk_id=None,
            snippet=_trim_text(
                f"{query_result.summary} 参数: {query_result.query_plan.params}",
                max_length=220,
            ),
            score=None,
        )
    ]


def _build_executed_data_reference_items(tool_result: dict[str, Any]) -> list[AIReferenceItem]:
    """把真实执行后的数据工具结果压成前端可展示的数据证据。"""

    items: list[AIReferenceItem] = [
        AIReferenceItem(
            source_type="data",
            document_id=None,
            document_name=str(tool_result.get("tool_name") or "data_tool"),
            chunk_id=None,
            snippet=_trim_text(str(tool_result.get("summary") or ""), max_length=220),
            score=None,
        )
    ]
    for highlight in list(tool_result.get("highlights") or [])[:2]:
        items.append(
            AIReferenceItem(
                source_type="data",
                document_id=None,
                document_name=str(tool_result.get("tool_name") or "data_tool"),
                chunk_id=None,
                snippet=_trim_text(str(highlight), max_length=220),
                score=None,
            )
        )
    return items[:MAX_QA_REFERENCE_ITEMS]


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


def _build_query_action(query_result: Any, tool_name: str | None = None) -> list[AISuggestedAction]:
    """把 query-assistant 推荐或真实执行结果映射成前端动作。"""

    return [
        AISuggestedAction(
            label="查看查询结果" if tool_name else "查看推荐查询",
            action_type="call_api",
            target=tool_name or query_result.query_plan.endpoint,
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
    data_execution_mode = "planned"
    if response.question_type == "data_query" and any(item.tool_type == "mcp_tool" for item in response.used_tools):
        data_execution_mode = "executed"
    return {
        "source": source,
        "question_type": response.question_type,
        "answer": response.answer.strip(),
        "has_substantive_findings": _response_has_substantive_findings(response),
        "data_execution_mode": data_execution_mode,
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
        "如果数据结果标记为 data_execution_mode=planned，请明确这是建议，不要伪装成已经执行的结果；"
        "如果标记为 executed，则可以直接陈述数据结论。\n"
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


def _select_data_tool(question: str, query_result: Any) -> tuple[str, str]:
    """让主模型在白名单内选择数据工具，失败时回退到 query-assistant 推荐。"""

    fallback_tool_name = DATA_TOOL_NAME_BY_ENDPOINT.get(
        query_result.query_plan.endpoint,
        "energy_query",
    )
    allowed_tools = list(DATA_TOOL_NAME_BY_ENDPOINT.values())
    settings = get_ai_settings()
    client = OpenAICompatibleClient(settings)
    user_prompt = (
        f"【用户问题】\n{question}\n\n"
        f"【查询助手解析结果】\n"
        f"query_plan_endpoint={query_result.query_plan.endpoint}\n"
        f"query_plan_method={query_result.query_plan.method}\n"
        f"query_plan_params={query_result.query_plan.params}\n"
        f"warnings={query_result.warnings}\n\n"
        f"【allowed_tools】\n{allowed_tools}\n"
    )
    try:
        result = client.generate_json(DATA_TOOL_SELECTION_SYSTEM_PROMPT, user_prompt)
    except Exception:  # noqa: BLE001
        return fallback_tool_name, "主模型工具选择失败，已回退到 query_assistant 推荐的数据工具。"

    tool_name = str(result.get("tool_name") or "").strip()
    if tool_name not in allowed_tools:
        return fallback_tool_name, "主模型返回了非法工具名，已回退到 query_assistant 推荐的数据工具。"
    reason = str(result.get("reason") or "").strip() or "主模型根据用户问题和查询意图选择了该数据工具。"
    return tool_name, reason


def _execute_data_tool(tool_name: str, query_params: dict[str, Any]) -> dict[str, Any]:
    """执行受控白名单内的数据工具，并统一返回 MCP 风格结果。"""

    if tool_name == "energy_query":
        _publish_qa_status("执行能耗明细查询...", tool_name, event_type="mcp_tool")
        response = get_energy_query(
            building_ids=query_params.get("building_ids"),
            site_id=query_params.get("site_id"),
            meter=query_params.get("meter"),
            start_time=query_params.get("start_time"),
            end_time=query_params.get("end_time"),
            granularity=query_params.get("granularity"),
            aggregation=query_params.get("aggregation"),
            page=int(query_params.get("page") or 1),
            page_size=int(query_params.get("page_size") or 100),
        )
        return _summarize_energy_query(
            response.model_dump(mode="json"),
            building_ids=list(query_params.get("building_ids") or []),
            meter=str(query_params.get("meter") or "electricity"),
            aggregation=query_params.get("aggregation"),
        )

    if tool_name == "energy_trend":
        _publish_qa_status("执行能耗趋势分析...", tool_name, event_type="mcp_tool")
        response = get_energy_trend(
            building_ids=query_params.get("building_ids"),
            site_id=query_params.get("site_id"),
            meter=query_params.get("meter"),
            start_time=query_params.get("start_time"),
            end_time=query_params.get("end_time"),
            granularity=query_params.get("granularity"),
        )
        return _summarize_energy_trend(
            response.model_dump(mode="json"),
            building_ids=list(query_params.get("building_ids") or []),
            meter=str(query_params.get("meter") or "electricity"),
            granularity=query_params.get("granularity"),
        )

    if tool_name == "energy_compare":
        _publish_qa_status("执行建筑能耗对比...", tool_name, event_type="mcp_tool")
        response = get_energy_compare(
            building_ids=query_params.get("building_ids"),
            meter=query_params.get("meter"),
            start_time=query_params.get("start_time"),
            end_time=query_params.get("end_time"),
            metric=query_params.get("metric"),
        )
        return _summarize_energy_compare(
            response.model_dump(mode="json"),
            building_ids=list(query_params.get("building_ids") or []),
            meter=str(query_params.get("meter") or "electricity"),
            metric=str(query_params.get("metric") or "sum"),
        )

    if tool_name == "energy_rankings":
        _publish_qa_status("执行能耗排行榜查询...", tool_name, event_type="mcp_tool")
        response = get_energy_rankings(
            meter=query_params.get("meter"),
            start_time=query_params.get("start_time"),
            end_time=query_params.get("end_time"),
            metric=query_params.get("metric"),
            order=query_params.get("order"),
            limit=int(query_params.get("limit") or 10),
        )
        return _summarize_energy_rankings(
            response.model_dump(mode="json"),
            meter=str(query_params.get("meter") or "electricity"),
            metric=str(query_params.get("metric") or "sum"),
            order=str(query_params.get("order") or "desc"),
            limit=int(query_params.get("limit") or 10),
        )

    if tool_name == "energy_weather_correlation":
        _publish_qa_status("执行天气相关性分析...", tool_name, event_type="mcp_tool")
        building_id = str(
            query_params.get("building_id")
            or (list(query_params.get("building_ids") or [])[:1] or [""])[0]
        ).strip()
        response = get_energy_weather_correlation(
            building_id=building_id or None,
            meter=query_params.get("meter"),
            start_time=query_params.get("start_time"),
            end_time=query_params.get("end_time"),
        )
        return _summarize_weather_correlation(
            response.model_dump(mode="json"),
            building_id=building_id,
            meter=str(query_params.get("meter") or "electricity"),
        )

    raise ValueError(f"当前不支持的数据工具: {tool_name}")


def _fallback_data_answer(query_result: Any, tool_result: dict[str, Any] | None = None) -> str:
    """在数据工具总结失败时，使用确定性方式兜底回答。"""

    if tool_result:
        highlights = "；".join(str(item) for item in list(tool_result.get("highlights") or [])[:3])
        return f"{tool_result.get('summary') or '已执行数据查询。'} {highlights}".strip()
    warning_text = f" 注意事项：{'；'.join(query_result.warnings)}。" if query_result.warnings else ""
    return (
        f"{query_result.summary} 建议调用 {query_result.query_plan.endpoint} "
        f"（{query_result.query_plan.method}），推荐参数为 {query_result.query_plan.params}。"
        f"{warning_text}"
    )


def _generate_data_answer(question: str, tool_result: dict[str, Any], query_warnings: list[str]) -> str:
    """基于真实执行后的数据工具结果生成最终回答。"""

    settings = get_ai_settings()
    client = OpenAICompatibleClient(settings)
    user_prompt = (
        f"【用户问题】\n{question}\n\n"
        f"【数据工具结果】\n{tool_result}\n\n"
        f"【解析阶段提示】\n{query_warnings}\n"
    )
    try:
        result = client.generate_json(DATA_RESULT_QA_SYSTEM_PROMPT, user_prompt)
    except Exception:  # noqa: BLE001
        return _fallback_data_answer(query_result=None, tool_result=tool_result)
    answer = str(result.get("answer") or "").strip()
    return answer or _fallback_data_answer(query_result=None, tool_result=tool_result)


def _build_capability_answer(context: AIQAContext | None) -> str:
    """生成助手能力说明，避免元问题误触发知识库检索。"""

    capability_lines = [
        "我主要能做四类事情：",
        "1. 回答运维知识问题，比如设备原理、维保规范、排查思路和术语解释。",
        "2. 查询和解读能耗数据，比如趋势、排行、对比、明细和天气相关性。",
        "3. 在上下文足够时做异常分析，比如结合建筑、表计和时间范围解释异常原因并给出排查建议。",
        "4. 进行多轮追问，并把知识、数据和异常分析结果整理成一段可执行的结论。",
        "",
        "你可以直接这样问我：",
        "- 最近一周哪些建筑能耗异常？",
        "- 冷却水泵效率异常通常怎么排查？",
        "- 分析 1A 楼最近 30 天电表能耗趋势。",
        "- 解释这个建筑当前异常的可能原因，并给出处理建议。",
        "",
        "我当前不适合直接替你执行页面操作或修改业务数据，但我可以告诉你该查什么、为什么查，以及下一步建议去哪个页面。你也可以继续直接说你的目标，我会自动选择合适链路。"
    ]

    if context and context.building_id:
        capability_lines.append("")
        capability_lines.append(
            f"当前如果你围绕建筑 {context.building_id} 继续提问，我会优先结合这部分上下文来回答。"
        )

    return "\n".join(capability_lines)


def _handle_assistant_capability_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理用户询问助手能力、定位和使用方式的元问题。"""

    total_start = perf_counter()
    _publish_qa_status("生成助手能力说明...", "assistant_capability")
    references = AIQAReferences()
    used_tools: list[AIUsedToolItem] = []
    suggested_actions: list[AISuggestedAction] = []
    answer = _build_capability_answer(payload.context)
    stage_timings_ms = {
        "total_ms": _duration_ms(total_start),
    }
    return AIQAResponse(
        session_id="",
        answer=answer,
        question_type="assistant_capability",
        references=references,
        used_tools=used_tools,
        suggested_actions=suggested_actions,
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_other_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理寒暄、模糊问题或暂不适合直接进入工具链的问题。"""

    total_start = perf_counter()
    _publish_qa_status("生成通用引导回复...", "other_response")
    references = AIQAReferences()
    used_tools: list[AIUsedToolItem] = []
    suggested_actions: list[AISuggestedAction] = []
    answer = (
        "我已经收到你的问题，但这轮意图还不够具体。"
        "你可以直接告诉我想查什么数据、想解释什么知识，或者想分析哪个建筑/表计在什么时间范围内的异常。"
        "\n\n例如：\n"
        "- 查最近一周能耗异常的建筑\n"
        "- 解释冷却水泵效率异常通常怎么排查\n"
        "- 分析 1A 楼最近 30 天电表能耗趋势\n"
        "- 判断这个建筑当前异常的可能原因"
    )
    stage_timings_ms = {
        "total_ms": _duration_ms(total_start),
    }
    return AIQAResponse(
        session_id="",
        answer=answer,
        question_type="other",
        references=references,
        used_tools=used_tools,
        suggested_actions=suggested_actions,
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_knowledge_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理知识库问答类问题。"""

    total_start = perf_counter()
    stage_timings_ms: dict[str, int] = {}

    _publish_qa_status("检索知识库相关资料...", "search_domain_knowledge", event_type="mcp_tool")
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
    _publish_qa_status("基于知识片段生成回答...", "knowledge_answer")
    knowledge_llm_start = perf_counter()
    answer = _generate_knowledge_answer(payload.question, knowledge_references, settings_model)
    stage_timings_ms["knowledge_llm_ms"] = _duration_ms(knowledge_llm_start)

    if _knowledge_answer_is_insufficient(answer):
        _publish_qa_status("结构化证据不足，尝试补充 RAG 对话检索...", "answer_with_domain_knowledge", event_type="mcp_tool")
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
        session_id="",
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
    _publish_qa_status("解析查询意图并抽取参数...", "query_assistant", event_type="mcp_tool")
    query_assistant_start = perf_counter()
    query_result = build_query_intent(
        AIQueryAssistantRequest(
            question=payload.question,
            use_current_time=payload.use_current_time,
            current_time=resolve_request_current_time(payload) if not payload.use_current_time else None,
            timezone=payload.timezone,
        )
    )
    stage_timings_ms = {
        "query_assistant_ms": _duration_ms(query_assistant_start),
    }
    used_tools = [
        AIUsedToolItem(
            tool_name="query_assistant",
            tool_type="internal_service",
            reason="问题属于数据检索场景，需要先解析查询意图并准备数据工具参数。",
        )
    ]
    references = AIQAReferences()
    suggested_actions: list[AISuggestedAction] = []
    answer = ""

    try:
        _publish_qa_status("为当前问题选择最合适的数据工具...", "data_tool_selection")
        tool_selection_start = perf_counter()
        tool_name, tool_reason = _select_data_tool(payload.question, query_result)
        stage_timings_ms["data_tool_selection_ms"] = _duration_ms(tool_selection_start)
        used_tools.append(
            AIUsedToolItem(
                tool_name=tool_name,
                tool_type="mcp_tool",
                reason=tool_reason,
            )
        )

        execution_start = perf_counter()
        tool_result = _execute_data_tool(tool_name, query_result.query_plan.params)
        stage_timings_ms["data_tool_execution_ms"] = _duration_ms(execution_start)

        references = AIQAReferences(data=_build_executed_data_reference_items(tool_result))
        suggested_actions = _build_query_action(query_result, tool_name=tool_name)

        _publish_qa_status("整理数据结果并生成结论...", "data_answer")
        data_answer_start = perf_counter()
        answer = _generate_data_answer(payload.question, tool_result, query_result.warnings)
        stage_timings_ms["data_answer_ms"] = _duration_ms(data_answer_start)
    except Exception:  # noqa: BLE001
        _publish_qa_status("数据工具执行失败，回退为推荐查询方案。", "data_query_fallback")
        references = AIQAReferences(data=_build_data_reference_items(query_result))
        suggested_actions = _build_query_action(query_result)
        answer = _fallback_data_answer(query_result)

    stage_timings_ms["total_ms"] = _duration_ms(total_start)
    return AIQAResponse(
        session_id="",
        answer=answer,
        question_type="data_query",
        references=references,
        used_tools=used_tools,
        suggested_actions=suggested_actions,
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_fault_analysis_question(payload: AIQARequest, settings_model: str) -> AIQAResponse:
    """处理带业务上下文的异常/故障分析类问题。"""

    total_start = perf_counter()
    # 如果完全没有上下文（建筑、站点、表计、时间），则不能执行直接诊断
    if not _has_context_for_fault_analysis(payload.context):
        _publish_qa_status("由于当前缺少明确的诊断对象，AI 助手将尝试通过知识库和数据检索提供一般性分析。", "fault_analysis_context_fallback")
        
        # 这种场景下，我们将其重定向到 mixed 逻辑，但强制开启知识和数据信号
        fallback_signals = {
            "knowledge": True,
            "data_query": True,
            "fault_analysis": False,  # 当前确实没法直接做诊断
        }
        # 使用特定的混合处理逻辑，告诉用户现状并提供背景知识和数据建议
        return _handle_fallback_mixed_question(payload, settings_model, fallback_signals, total_start)

    context = payload.context
    _publish_qa_status("调用异常诊断能力分析当前上下文...", "analyze_anomaly_with_ai", event_type="mcp_tool")
    anomaly_analysis_start = perf_counter()
    anomaly_result = analyze_anomaly_with_ai(
        AIAnalyzeAnomalyRequest(
            building_id=context.building_id,
            site_id=context.site_id,
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
        session_id="",
        answer=anomaly_result.answer,
        question_type="fault_analysis",
        references=references,
        used_tools=used_tools,
        suggested_actions=_build_actions_from_anomaly(anomaly_result),
        meta=_build_meta_with_timings(settings_model, used_tools, references, stage_timings_ms),
    )


def _handle_fallback_mixed_question(
    payload: AIQARequest,
    settings_model: str,
    signals: dict[str, bool],
    total_start: float,
) -> AIQAResponse:
    """内部使用的混合处理逻辑，用于处理诊断场景下的上下文缺失。"""

    used_tools: list[AIUsedToolItem] = []
    suggested_actions: list[AISuggestedAction] = []
    reference_groups: list[AIQAReferences] = []
    answer_parts: list[dict[str, Any]] = []
    stage_timings_ms: dict[str, int] = {}

    # 1. 尝试检索知识库，给出排查方法论
    if signals["knowledge"]:
        knowledge_response = _handle_knowledge_question(payload, settings_model)
        reference_groups.append(knowledge_response.references)
        used_tools.extend(knowledge_response.used_tools)
        suggested_actions.extend(knowledge_response.suggested_actions)
        answer_parts.append(_build_mixed_part("knowledge", knowledge_response))
        stage_timings_ms.update(
            _prefix_stage_timings("knowledge", knowledge_response.meta.stage_timings_ms)
        )

    # 2. 尝试执行通用的数据查询（例如查找异常建筑、查找 EUI 高的楼）
    if signals["data_query"]:
        data_response = _handle_data_query_question(payload, settings_model)
        reference_groups.append(data_response.references)
        used_tools.extend(data_response.used_tools)
        suggested_actions.extend(data_response.suggested_actions)
        answer_parts.append(_build_mixed_part("data_query", data_response))
        stage_timings_ms.update(
            _prefix_stage_timings("data_query", data_response.meta.stage_timings_ms)
        )

    references = _merge_references(*reference_groups)
    deduped_actions = _dedupe_actions(suggested_actions)

    _publish_qa_status("汇总知识库与数据检索结果...", "mixed_synthesis")
    mixed_synthesis_start = perf_counter()
    answer = _synthesize_mixed_answer(payload.question, answer_parts)
    stage_timings_ms["mixed_synthesis_ms"] = _duration_ms(mixed_synthesis_start)
    stage_timings_ms["total_ms"] = _duration_ms(total_start)

    return AIQAResponse(
        session_id="",
        answer=answer,
        question_type="fault_analysis",  # 保持诊断意图，但内容是综合的
        references=references,
        used_tools=used_tools,
        suggested_actions=deduped_actions,
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
    _publish_qa_status("识别到综合问题，开始并行编排多种能力...", "mixed_orchestration")
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
    _publish_qa_status("汇总多路结果并生成最终回答...", "mixed_synthesis")
    mixed_synthesis_start = perf_counter()
    answer = _synthesize_mixed_answer(payload.question, answer_parts)
    stage_timings_ms["mixed_synthesis_ms"] = _duration_ms(mixed_synthesis_start)
    stage_timings_ms["total_ms"] = _duration_ms(total_start)
    return AIQAResponse(
        session_id="",
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
    _publish_qa_status("初始化会话并整理上下文...", "qa_session")
    session = get_or_create_session(payload.session_id, payload.context)
    recent_messages = load_recent_messages(session.session_id)
    effective_context = build_effective_context(session, payload.context, recent_messages)
    rewritten_question = rewrite_followup_question(payload.question, effective_context, recent_messages)

    runtime_payload = AIQARequest(
        question=rewritten_question,
        session_id=session.session_id,
        context=effective_context,
        use_current_time=payload.use_current_time,
        current_time=payload.current_time,
        timezone=payload.timezone,
    )
    save_user_message(session.session_id, payload.question, effective_context)
    try:
        routing_start = perf_counter()
        question_type, route_reason = _classify_question_type(runtime_payload.question, effective_context)
        routing_ms = _duration_ms(routing_start)
        _publish_qa_status(f"已识别问题类型：{question_type}", route_reason or "question_classification")
        if question_type == "data_query":
            response = _handle_data_query_question(runtime_payload, settings.llm_model)
        elif question_type == "assistant_capability":
            response = _handle_assistant_capability_question(runtime_payload, settings.llm_model)
        elif question_type == "mixed":
            response = _handle_mixed_question(runtime_payload, settings.llm_model)
        elif question_type == "fault_analysis":
            response = _handle_fault_analysis_question(runtime_payload, settings.llm_model)
        elif question_type == "other":
            response = _handle_other_question(runtime_payload, settings.llm_model)
        else:
            response = _handle_knowledge_question(runtime_payload, settings.llm_model)

        response.used_tools = [
            AIUsedToolItem(
                tool_name="qa_intent_router",
                tool_type="internal_service",
                reason=route_reason,
            ),
            *response.used_tools,
        ]
        response.meta.used_tools_count = len(response.used_tools)
        response.meta.stage_timings_ms = {
            "question_routing_ms": routing_ms,
            **response.meta.stage_timings_ms,
        }
        response.session_id = session.session_id
        _publish_qa_status("回答已生成，正在写入会话记录...", "save_session_state")
        save_assistant_message(session.session_id, response, effective_context)
        update_session_state(session.session_id, payload.question, response, effective_context)
        return response
    except Exception as exc:  # noqa: BLE001
        _publish_qa_status(f"调用链路失败：{type(exc).__name__}", "qa_error")
        error_message = f"调用工具失败：{type(exc).__name__}: {exc}"
        save_error_message(session.session_id, error_message, effective_context)
        update_session_failure_state(
            session.session_id,
            payload.question,
            error_message,
            effective_context,
        )
        raise
