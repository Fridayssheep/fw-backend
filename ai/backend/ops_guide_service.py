from __future__ import annotations

from time import perf_counter
from typing import Any

from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import AIOpsGuideAction
from app.schemas import AIOpsGuideApplicability
from app.schemas import AIOpsGuideDiagnosisSnapshot
from app.schemas import AIOpsGuideEvidence
from app.schemas import AIOpsGuideMeta
from app.schemas import AIOpsGuideRequest
from app.schemas import AIOpsGuideResponse
from app.schemas import AIOpsGuideStep
from app.services.service_common import get_taipei_now

from .anomaly_service import analyze_anomaly_with_ai
from .config import get_ai_settings
from .history import retrieve_similar_feedback_cases
from .knowledge import build_compact_knowledge_items
from .knowledge import search_domain_knowledge_references
from .llm_client import OpenAICompatibleClient
from .ops_context import OpsAnomalySnapshot
from .ops_context import OpsContext
from .ops_context import OpsDiagnosisSnapshot
from .ops_context import OpsIncidentRef
from .ops_context import OpsOperatorContext
from .ops_context import OpsPageContext
from .prompting import build_ops_guide_prompts


GUIDE_MODE_STEP_LIMIT = {
    "quick_check": 2,
    "standard_sop": 3,
    "expert": 4,
}


def _duration_ms(start_time: float) -> int:
    return int((perf_counter() - start_time) * 1000)


def _normalize_question(payload: AIOpsGuideRequest) -> str:
    question = (payload.question or "").strip()
    if question:
        return question
    meter = payload.context.meter
    return f"请给我一份关于当前 {meter} 异常的运维排查指导。"


def _coerce_guide_mode(value: str) -> str:
    return value if value in GUIDE_MODE_STEP_LIMIT else "standard_sop"


def _build_diagnosis_snapshot(anomaly_result: Any) -> OpsDiagnosisSnapshot:
    return OpsDiagnosisSnapshot(
        summary=anomaly_result.summary,
        status=anomaly_result.status,
        candidate_cause_titles=[item.title for item in anomaly_result.candidate_causes[:4]],
        knowledge_hits=anomaly_result.meta.knowledge_hits,
        history_feedback_hits=anomaly_result.meta.history_feedback_hits,
    )


def _build_ops_context(payload: AIOpsGuideRequest, anomaly_result: Any) -> OpsContext:
    request_context = payload.context
    snapshot = request_context.anomaly_snapshot
    incident_ref = request_context.incident_ref
    operator_context = request_context.operator_context
    page_context = request_context.page_context
    return OpsContext(
        question=_normalize_question(payload),
        guide_mode=_coerce_guide_mode(payload.guide_mode),
        building_id=request_context.building_id,
        meter=request_context.meter,
        time_range=request_context.time_range,
        incident_ref=OpsIncidentRef(
            incident_id=incident_ref.incident_id if incident_ref else None,
            message_id=incident_ref.message_id if incident_ref else None,
        ),
        operator_context=OpsOperatorContext(
            operator_id=operator_context.operator_id if operator_context else None,
            operator_name=operator_context.operator_name if operator_context else None,
        ),
        page_context=OpsPageContext(
            source=page_context.source if page_context else None,
            page_type=page_context.page_type if page_context else None,
            current_chart_range=page_context.current_chart_range if page_context else None,
        ),
        anomaly_snapshot=OpsAnomalySnapshot(
            summary=(snapshot.summary if snapshot and snapshot.summary else anomaly_result.summary),
            analysis_mode=(
                snapshot.analysis_mode
                if snapshot and snapshot.analysis_mode
                else anomaly_result.meta.analysis_mode
            ),
            event_count=(
                snapshot.event_count
                if snapshot and snapshot.event_count is not None
                else anomaly_result.meta.event_count
            ),
            detector_breakdown=(
                snapshot.detector_breakdown
                if snapshot and snapshot.detector_breakdown
                else anomaly_result.meta.detector_breakdown
            ),
            event_ids=(snapshot.event_ids if snapshot else []),
        ),
        diagnosis_snapshot=_build_diagnosis_snapshot(anomaly_result),
        generated_at=get_taipei_now(),
    )


def _build_knowledge_query(ops_context: OpsContext, anomaly_result: Any) -> str:
    cause_titles = "；".join(item.title for item in anomaly_result.candidate_causes[:2])
    return (
        f"{ops_context.meter} 异常排查。"
        f"异常摘要：{anomaly_result.summary}。"
        f"优先候选原因：{cause_titles}。"
        f"用户诉求：{ops_context.question}"
    )


def _build_knowledge_items(payload: AIOpsGuideRequest, ops_context: OpsContext, anomaly_result: Any) -> list[dict[str, Any]]:
    if not payload.include_knowledge:
        return []
    references = search_domain_knowledge_references(
        _build_knowledge_query(ops_context, anomaly_result),
        top_k=3,
    )
    return build_compact_knowledge_items(
        references,
        max_items=3,
        snippet_length=220,
    )


def _build_history_items(payload: AIOpsGuideRequest, ops_context: OpsContext) -> list[dict[str, Any]]:
    if not payload.include_history:
        return []
    return retrieve_similar_feedback_cases(
        building_id=ops_context.building_id,
        meter=ops_context.meter,
        start_time=ops_context.time_range.start.isoformat(),
        end_time=ops_context.time_range.end.isoformat(),
        limit=3,
    )


def _build_ops_evidence(
    anomaly_result: Any,
    knowledge_items: list[dict[str, Any]],
    history_items: list[dict[str, Any]],
) -> list[AIOpsGuideEvidence]:
    evidence: list[AIOpsGuideEvidence] = []
    for item in anomaly_result.evidence[:3]:
        source_type = "data"
        if item.type in {"knowledge", "rule"}:
            source_type = "knowledge"
        elif item.type == "history_case":
            source_type = "history_case"
        evidence.append(
            AIOpsGuideEvidence(
                source_type=source_type,
                source=item.source,
                snippet=item.snippet,
                score=item.weight,
            )
        )
    for item in knowledge_items[:2]:
        evidence.append(
            AIOpsGuideEvidence(
                source_type="knowledge",
                source=item.get("document_name") or "knowledge_base",
                snippet=item.get("snippet") or "",
                score=item.get("score"),
            )
        )
    if history_items:
        evidence.append(
            AIOpsGuideEvidence(
                source_type="history_case",
                source="ai_anomaly_feedback",
                snippet=f"命中 {len(history_items)} 条相似历史反馈，可作为排查顺序参考。",
                score=0.42,
            )
        )
    return evidence[:6]


def _build_ops_actions(payload: AIOpsGuideRequest, anomaly_result: Any) -> list[AIOpsGuideAction]:
    if not payload.include_actions:
        return []
    actions: list[AIOpsGuideAction] = []
    for item in anomaly_result.actions[:3]:
        action_type = "call_api" if item.action_type == "open_api" else "open_page"
        actions.append(
            AIOpsGuideAction(
                label=item.label,
                action_type=action_type,
                target=item.target,
            )
        )
    return actions


def _build_default_preconditions(ops_context: OpsContext) -> list[str]:
    items = [
        "确认当前建筑、表计和时间范围与接手事件一致。",
        "确认当前指导基于离线异常事件分析结果，不代表故障已确认。",
    ]
    if ops_context.operator_context.operator_name:
        items.append(f"当前由 {ops_context.operator_context.operator_name} 接手处理，请同步记录排查结论。")
    return items[:3]


def _step_title_from_cause(index: int, title: str) -> str:
    if index == 1:
        return f"优先排查：{title}"
    return f"继续核查：{title}"


def _build_default_steps(ops_context: OpsContext, anomaly_result: Any) -> list[AIOpsGuideStep]:
    limit = GUIDE_MODE_STEP_LIMIT.get(ops_context.guide_mode, 3)
    steps: list[AIOpsGuideStep] = []
    for index, cause in enumerate(anomaly_result.candidate_causes[:limit], start=1):
        instruction = "；".join(cause.recommended_checks[:2]) if cause.recommended_checks else cause.description
        next_title = (
            anomaly_result.candidate_causes[index].title
            if index < len(anomaly_result.candidate_causes[:limit])
            else "升级给高级运维继续处理"
        )
        steps.append(
            AIOpsGuideStep(
                step_id=f"step_{index}",
                title=_step_title_from_cause(index, cause.title),
                instruction=instruction,
                priority="high" if index == 1 else ("medium" if index == 2 else "low"),
                expected_result=cause.description,
                if_not_met=f"若该方向不成立，继续转向“{next_title}”对应的排查路径。",
            )
        )
    if not steps:
        steps.append(
            AIOpsGuideStep(
                step_id="step_1",
                title="先确认异常上下文是否完整",
                instruction="核对当前异常事件、时间范围、表计类型和趋势截图是否一致。",
                priority="high",
                expected_result="确认本次指导基于正确的异常对象。",
                if_not_met="若上下文不一致，先刷新页面上下文再重新生成指导。",
            )
        )
        steps.append(
            AIOpsGuideStep(
                step_id="step_2",
                title="回看异常趋势和原始事件",
                instruction="查看异常趋势、事件时间点和检测器来源，确认是否属于突发极值、规律偏移或采集异常。",
                priority="medium",
                expected_result="形成明确的首要排查方向。",
                if_not_met="若仍无法定位方向，升级给高级运维或扩大分析窗口。",
            )
        )
    return steps


def _build_default_applicability(ops_context: OpsContext) -> AIOpsGuideApplicability:
    applies_to = [
        "离线异常事件接手后的排查场景",
        f"{ops_context.meter} 表计的异常排查场景",
    ]
    not_applies_to = [
        "缺少 building_id、meter、time_range 的自由问答场景",
        "需要直接执行报表总结的管理汇报场景",
    ]
    return AIOpsGuideApplicability(applies_to=applies_to, not_applies_to=not_applies_to)


def _build_diagnosis_snapshot_response(anomaly_result: Any) -> AIOpsGuideDiagnosisSnapshot:
    return AIOpsGuideDiagnosisSnapshot(
        analysis_mode=anomaly_result.meta.analysis_mode,
        event_count=anomaly_result.meta.event_count,
        detector_breakdown=anomaly_result.meta.detector_breakdown,
        candidate_cause_titles=[item.title for item in anomaly_result.candidate_causes[:4]],
    )


def _coerce_preconditions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:4]


def _coerce_steps(value: Any) -> list[AIOpsGuideStep]:
    if not isinstance(value, list):
        return []
    steps: list[AIOpsGuideStep] = []
    for index, item in enumerate(value[:6], start=1):
        if not isinstance(item, dict):
            continue
        steps.append(
            AIOpsGuideStep(
                step_id=str(item.get("step_id") or f"step_{index}"),
                title=str(item.get("title") or f"步骤 {index}"),
                instruction=str(item.get("instruction") or ""),
                priority=str(item.get("priority") or "medium"),
                expected_result=str(item.get("expected_result") or "") or None,
                if_not_met=str(item.get("if_not_met") or "") or None,
            )
        )
    return steps


def _coerce_applicability(value: Any) -> AIOpsGuideApplicability | None:
    if not isinstance(value, dict):
        return None
    return AIOpsGuideApplicability(
        applies_to=[str(item) for item in value.get("applies_to", []) if str(item).strip()],
        not_applies_to=[str(item) for item in value.get("not_applies_to", []) if str(item).strip()],
    )


def _build_fallback_response(
    payload: AIOpsGuideRequest,
    ops_context: OpsContext,
    anomaly_result: Any,
    knowledge_items: list[dict[str, Any]],
    history_items: list[dict[str, Any]],
    stage_timings_ms: dict[str, int],
    settings_model: str,
) -> AIOpsGuideResponse:
    return AIOpsGuideResponse(
        incident_id=ops_context.incident_ref.incident_id,
        status="actionable" if anomaly_result.meta.event_count > 0 else "low_confidence",
        summary=anomaly_result.summary,
        preconditions=_build_default_preconditions(ops_context),
        steps=_build_default_steps(ops_context, anomaly_result),
        evidence=_build_ops_evidence(anomaly_result, knowledge_items, history_items),
        actions=_build_ops_actions(payload, anomaly_result),
        risk_notice=[
            "当前结果属于运维指导，不代表故障已确认。",
            "如涉及现场操作，请先确认停送电、设备联锁和安全条件。",
        ],
        applicability=_build_default_applicability(ops_context),
        diagnosis_snapshot=_build_diagnosis_snapshot_response(anomaly_result),
        meta=AIOpsGuideMeta(
            generated_at=get_taipei_now(),
            model=settings_model,
            used_tools=["analyze_anomaly_with_ai", *([] if not knowledge_items else ["search_domain_knowledge"]), *([] if not history_items else ["retrieve_similar_feedback_cases"])],
            context_source="server_enriched",
            knowledge_hits=len(knowledge_items),
            history_feedback_hits=len(history_items),
            stage_timings_ms=stage_timings_ms,
        ),
    )


def get_ops_guide(payload: AIOpsGuideRequest) -> AIOpsGuideResponse:
    total_start = perf_counter()
    settings = get_ai_settings()
    stage_timings_ms: dict[str, int] = {}

    anomaly_start = perf_counter()
    anomaly_result = analyze_anomaly_with_ai(
        AIAnalyzeAnomalyRequest(
            building_id=payload.context.building_id,
            meter=payload.context.meter,
            time_range=payload.context.time_range,
            include_weather_context=True,
            include_history_feedback=payload.include_history,
            question=_normalize_question(payload),
            max_candidate_causes=4 if payload.guide_mode == "expert" else 3,
        )
    )
    stage_timings_ms["anomaly_analysis_ms"] = _duration_ms(anomaly_start)

    ops_context = _build_ops_context(payload, anomaly_result)

    knowledge_start = perf_counter()
    knowledge_items = _build_knowledge_items(payload, ops_context, anomaly_result)
    stage_timings_ms["knowledge_retrieval_ms"] = _duration_ms(knowledge_start)

    history_start = perf_counter()
    history_items = _build_history_items(payload, ops_context)
    stage_timings_ms["history_lookup_ms"] = _duration_ms(history_start)

    diagnosis_snapshot = {
        "summary": anomaly_result.summary,
        "status": anomaly_result.status,
        "candidate_causes": [
            {
                "title": item.title,
                "description": item.description,
                "confidence": item.confidence,
                "recommended_checks": item.recommended_checks,
            }
            for item in anomaly_result.candidate_causes[:4]
        ],
        "highlights": anomaly_result.highlights,
        "meta": {
            "analysis_mode": anomaly_result.meta.analysis_mode,
            "event_count": anomaly_result.meta.event_count,
            "detector_breakdown": [
                item.model_dump(mode="json")
                for item in anomaly_result.meta.detector_breakdown
            ],
            "knowledge_hits": anomaly_result.meta.knowledge_hits,
            "history_feedback_hits": anomaly_result.meta.history_feedback_hits,
        },
    }

    try:
        llm_start = perf_counter()
        system_prompt, user_prompt = build_ops_guide_prompts(
            ops_context=ops_context.model_dump(mode="json"),
            diagnosis_snapshot=diagnosis_snapshot,
            knowledge_items=knowledge_items,
            history_items=history_items,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )
        llm_response = OpenAICompatibleClient(settings).generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        stage_timings_ms["ops_guide_llm_ms"] = _duration_ms(llm_start)
        stage_timings_ms["total_ms"] = _duration_ms(total_start)
        return AIOpsGuideResponse(
            incident_id=ops_context.incident_ref.incident_id,
            status=str(llm_response.get("status") or ("actionable" if anomaly_result.meta.event_count > 0 else "low_confidence")),
            summary=str(llm_response.get("summary") or anomaly_result.summary),
            preconditions=_coerce_preconditions(llm_response.get("preconditions")) or _build_default_preconditions(ops_context),
            steps=_coerce_steps(llm_response.get("steps")) or _build_default_steps(ops_context, anomaly_result),
            evidence=_build_ops_evidence(anomaly_result, knowledge_items, history_items),
            actions=_build_ops_actions(payload, anomaly_result),
            risk_notice=[
                str(item).strip()
                for item in llm_response.get("risk_notice", [])
                if str(item).strip()
            ] or [
                "当前结果属于运维指导，不代表故障已确认。",
                "如涉及现场操作，请先确认停送电、设备联锁和安全条件。",
            ],
            applicability=_coerce_applicability(llm_response.get("applicability")) or _build_default_applicability(ops_context),
            diagnosis_snapshot=_build_diagnosis_snapshot_response(anomaly_result),
            meta=AIOpsGuideMeta(
                generated_at=get_taipei_now(),
                model=settings.llm_model,
                used_tools=["analyze_anomaly_with_ai", *([] if not knowledge_items else ["search_domain_knowledge"]), *([] if not history_items else ["retrieve_similar_feedback_cases"])],
                context_source="server_enriched",
                knowledge_hits=len(knowledge_items),
                history_feedback_hits=len(history_items),
                stage_timings_ms=stage_timings_ms,
            ),
        )
    except Exception:  # noqa: BLE001
        stage_timings_ms["total_ms"] = _duration_ms(total_start)
        return _build_fallback_response(
            payload=payload,
            ops_context=ops_context,
            anomaly_result=anomaly_result,
            knowledge_items=knowledge_items,
            history_items=history_items,
            stage_timings_ms=stage_timings_ms,
            settings_model=settings.llm_model,
        )
