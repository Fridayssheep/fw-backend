from __future__ import annotations

from time import perf_counter
from typing import Any

from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import AIReportSummaryAction
from app.schemas import AIReportSummaryEvidence
from app.schemas import AIReportSummaryHighlight
from app.schemas import AIReportSummaryMeta
from app.schemas import AIReportSummaryRequest
from app.schemas import AIReportSummaryResponse
from app.schemas import AIReportSummarySuggestion
from app.services.service_common import get_taipei_now

from .anomaly_service import analyze_anomaly_with_ai
from .config import get_ai_settings
from .llm_client import OpenAICompatibleClient
from .prompting import build_report_summary_prompts
from .report_context import ReportAnomalySnapshot
from .report_context import ReportContext
from .report_context import ReportDiagnosisSnapshot
from .report_context import ReportMetricsSnapshot
from .report_context import ReportPageContext
from .report_context import ReportTrendSnapshot


REPORT_TYPE_VALUES = {"summary_card", "weekly_summary", "monthly_summary", "anomaly_brief"}
AUDIENCE_VALUES = {"operator", "manager", "executive"}


def _duration_ms(start_time: float) -> int:
    return int((perf_counter() - start_time) * 1000)


def _coerce_report_type(value: str) -> str:
    return value if value in REPORT_TYPE_VALUES else "summary_card"


def _coerce_audience(value: str) -> str:
    return value if value in AUDIENCE_VALUES else "manager"


def _normalize_question(payload: AIReportSummaryRequest) -> str:
    question = (payload.question or "").strip()
    if question:
        return question
    building_id = payload.context.building_id
    return f"请面向{_coerce_audience(payload.audience)}总结 {building_id} 当前报表时间范围内的能耗表现与关注点。"


def _should_include_anomaly_insight(payload: AIReportSummaryRequest) -> bool:
    return payload.include_anomaly_insight and bool(payload.context.meter)


def _build_report_context(payload: AIReportSummaryRequest, anomaly_result: Any | None) -> ReportContext:
    context = payload.context
    page_context = context.page_context
    metrics = context.metrics_snapshot
    trend = context.trend_summary
    anomaly = context.anomaly_summary
    return ReportContext(
        question=_normalize_question(payload),
        report_type=_coerce_report_type(payload.report_type),
        audience=_coerce_audience(payload.audience),
        building_id=context.building_id,
        meter=context.meter,
        time_range=context.time_range,
        page_context=ReportPageContext(
            source=page_context.source if page_context else None,
            page_type=page_context.page_type if page_context else None,
            current_chart_range=page_context.current_chart_range if page_context else None,
        ),
        metrics_snapshot=ReportMetricsSnapshot(
            total=metrics.total if metrics else None,
            average=metrics.average if metrics else None,
            peak=metrics.peak if metrics else None,
            peak_time=metrics.peak_time if metrics else None,
            unit=metrics.unit if metrics else None,
            compare_total=metrics.compare_total if metrics else None,
            compare_change_rate=metrics.compare_change_rate if metrics else None,
        ),
        trend_summary=ReportTrendSnapshot(
            direction=trend.direction if trend else None,
            change_rate=trend.change_rate if trend else None,
            peak_days=trend.peak_days if trend else [],
            low_days=trend.low_days if trend else [],
            notes=trend.notes if trend else [],
        ),
        anomaly_summary=ReportAnomalySnapshot(
            summary=(
                anomaly.summary
                if anomaly and anomaly.summary
                else (anomaly_result.summary if anomaly_result else "")
            ),
            analysis_mode=(
                anomaly.analysis_mode
                if anomaly and anomaly.analysis_mode
                else (anomaly_result.meta.analysis_mode if anomaly_result else "offline_event_review")
            ),
            event_count=(
                anomaly.event_count
                if anomaly and anomaly.event_count is not None
                else (anomaly_result.meta.event_count if anomaly_result else 0)
            ),
            detector_breakdown=(
                anomaly.detector_breakdown
                if anomaly and anomaly.detector_breakdown
                else (anomaly_result.meta.detector_breakdown if anomaly_result else [])
            ),
        ),
        diagnosis_snapshot=ReportDiagnosisSnapshot(
            summary=anomaly_result.summary if anomaly_result else "",
            status=anomaly_result.status if anomaly_result else "low_confidence",
            candidate_cause_titles=[item.title for item in anomaly_result.candidate_causes[:3]] if anomaly_result else [],
        ),
        generated_at=get_taipei_now(),
    )


def _build_anomaly_result(payload: AIReportSummaryRequest) -> Any | None:
    if not _should_include_anomaly_insight(payload):
        return None
    return analyze_anomaly_with_ai(
        AIAnalyzeAnomalyRequest(
            building_id=payload.context.building_id,
            meter=payload.context.meter or "electricity",
            time_range=payload.context.time_range,
            include_weather_context=True,
            include_history_feedback=False,
            question="请总结当前时间范围内的异常信号、变化特点和需要关注的风险。",
            max_candidate_causes=3,
        )
    )


def _build_metrics_snippet(report_context: ReportContext) -> str | None:
    metrics = report_context.metrics_snapshot
    if metrics.total is None and metrics.average is None and metrics.peak is None:
        return None
    parts: list[str] = []
    if metrics.total is not None:
        unit = metrics.unit or ""
        parts.append(f"总量 {metrics.total}{unit}")
    if metrics.average is not None:
        unit = metrics.unit or ""
        parts.append(f"均值 {metrics.average}{unit}")
    if metrics.peak is not None:
        unit = metrics.unit or ""
        parts.append(f"峰值 {metrics.peak}{unit}")
    if metrics.peak_time is not None:
        parts.append(f"峰值时间 {metrics.peak_time.isoformat()}")
    return "，".join(parts)


def _build_trend_snippet(report_context: ReportContext) -> str | None:
    trend = report_context.trend_summary
    if trend.direction is None and trend.change_rate is None and not trend.peak_days and not trend.low_days:
        return None
    parts: list[str] = []
    if trend.direction:
        parts.append(f"趋势方向为 {trend.direction}")
    if trend.change_rate is not None:
        parts.append(f"变化率 {trend.change_rate}")
    if trend.peak_days:
        parts.append(f"高峰日期 {', '.join(trend.peak_days[:3])}")
    if trend.low_days:
        parts.append(f"低谷日期 {', '.join(trend.low_days[:3])}")
    return "，".join(parts)


def _build_evidence(report_context: ReportContext, anomaly_result: Any | None) -> list[AIReportSummaryEvidence]:
    evidence: list[AIReportSummaryEvidence] = []
    metrics_snippet = _build_metrics_snippet(report_context)
    if metrics_snippet:
        evidence.append(
            AIReportSummaryEvidence(
                source_type="data",
                source="metrics_snapshot",
                snippet=metrics_snippet,
                score=0.9,
            )
        )
    trend_snippet = _build_trend_snippet(report_context)
    if trend_snippet:
        evidence.append(
            AIReportSummaryEvidence(
                source_type="data",
                source="trend_summary",
                snippet=trend_snippet,
                score=0.72,
            )
        )
    if anomaly_result:
        evidence.append(
            AIReportSummaryEvidence(
                source_type="anomaly",
                source="analyze_anomaly_with_ai",
                snippet=anomaly_result.summary,
                score=0.84,
            )
        )
    elif report_context.anomaly_summary.summary:
        evidence.append(
            AIReportSummaryEvidence(
                source_type="anomaly",
                source="anomaly_snapshot",
                snippet=report_context.anomaly_summary.summary,
                score=0.61,
            )
        )
    return evidence[:5]


def _default_highlights(report_context: ReportContext, anomaly_result: Any | None) -> list[AIReportSummaryHighlight]:
    highlights: list[AIReportSummaryHighlight] = []
    metrics = report_context.metrics_snapshot
    trend = report_context.trend_summary
    if metrics.total is not None:
        unit = metrics.unit or ""
        highlights.append(
            AIReportSummaryHighlight(
                title="总量概览",
                detail=f"当前时间范围总量为 {metrics.total}{unit}。",
                priority="high",
            )
        )
    if trend.direction or trend.change_rate is not None:
        detail_parts: list[str] = []
        if trend.direction:
            detail_parts.append(f"整体趋势方向为 {trend.direction}")
        if trend.change_rate is not None:
            detail_parts.append(f"变化率为 {trend.change_rate}")
        highlights.append(
            AIReportSummaryHighlight(
                title="趋势变化",
                detail="，".join(detail_parts) or "当前已形成可描述的趋势变化。",
                priority="medium",
            )
        )
    if anomaly_result:
        highlights.append(
            AIReportSummaryHighlight(
                title="异常关注点",
                detail=f"{anomaly_result.summary}，主要候选原因包括 {', '.join(item.title for item in anomaly_result.candidate_causes[:2])}。",
                priority="high",
            )
        )
    elif report_context.anomaly_summary.event_count > 0:
        highlights.append(
            AIReportSummaryHighlight(
                title="异常关注点",
                detail=f"当前页面记录到 {report_context.anomaly_summary.event_count} 个异常事件，建议结合趋势图继续核查。",
                priority="medium",
            )
        )
    if not highlights:
        highlights.append(
            AIReportSummaryHighlight(
                title="上下文概览",
                detail="当前报表已接收到基础时间范围和页面上下文，可据此生成简要总结。",
                priority="medium",
            )
        )
        highlights.append(
            AIReportSummaryHighlight(
                title="建议补充素材",
                detail="如补充总量、峰值和趋势摘要，报表总结会更完整。",
                priority="low",
            )
        )
    return highlights[:4]


def _default_risks(report_context: ReportContext, anomaly_result: Any | None) -> list[str]:
    risks = ["本总结基于当前页面上下文和已有报表素材，不代表新增数据查询结果。"]
    if anomaly_result or report_context.anomaly_summary.event_count > 0:
        risks.append("异常洞察属于需关注信号，不代表故障已确认，仍需人工复核。")
    return risks[:3]


def _default_suggestions(report_context: ReportContext, anomaly_result: Any | None) -> list[AIReportSummarySuggestion]:
    suggestions: list[AIReportSummarySuggestion] = []
    trend = report_context.trend_summary
    if trend.direction == "up":
        suggestions.append(
            AIReportSummarySuggestion(
                label="继续关注高耗时段的运行负荷变化",
                type="monitor",
                rationale="当前趋势呈上升方向，适合继续观察负荷变化。",
            )
        )
    if anomaly_result:
        suggestions.append(
            AIReportSummarySuggestion(
                label="复核异常高值时段的设备启停和控制策略",
                type="investigate",
                rationale=anomaly_result.summary,
            )
        )
    if not suggestions:
        suggestions.append(
            AIReportSummarySuggestion(
                label="补充对比周期和异常摘要后再生成正式周报",
                type="followup",
                rationale="当前上下文更适合生成摘要卡片。",
            )
        )
    return suggestions[:3]


def _build_actions(payload: AIReportSummaryRequest, anomaly_result: Any | None, allowed_targets: tuple[str, ...]) -> list[AIReportSummaryAction]:
    if not payload.include_actions:
        return []
    allowed = set(allowed_targets)
    actions: list[AIReportSummaryAction] = []
    if "energy_trend" in allowed:
        actions.append(AIReportSummaryAction(label="查看趋势图", action_type="open_page", target="energy_trend"))
    if anomaly_result and "energy_anomaly_analysis" in allowed:
        actions.append(AIReportSummaryAction(label="查看异常分析", action_type="open_page", target="energy_anomaly_analysis"))
    return actions[:3]


def _coerce_highlights(value: Any) -> list[AIReportSummaryHighlight]:
    if not isinstance(value, list):
        return []
    items: list[AIReportSummaryHighlight] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        items.append(
            AIReportSummaryHighlight(
                title=str(item.get("title") or "").strip() or "报表亮点",
                detail=str(item.get("detail") or "").strip() or "当前周期存在需要关注的变化。",
                priority=str(item.get("priority") or "medium"),
            )
        )
    return items


def _coerce_string_list(value: Any, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _coerce_suggestions(value: Any) -> list[AIReportSummarySuggestion]:
    if not isinstance(value, list):
        return []
    items: list[AIReportSummarySuggestion] = []
    for item in value[:4]:
        if not isinstance(item, dict):
            continue
        items.append(
            AIReportSummarySuggestion(
                label=str(item.get("label") or "").strip() or "继续关注当前趋势变化",
                type=str(item.get("type") or "monitor"),
                rationale=str(item.get("rationale") or "").strip() or None,
            )
        )
    return items


def _build_anomaly_insight(anomaly_result: Any | None) -> dict[str, Any] | None:
    if anomaly_result is None:
        return None
    return {
        "summary": anomaly_result.summary,
        "status": anomaly_result.status,
        "candidate_causes": [
            {
                "title": item.title,
                "confidence": item.confidence,
            }
            for item in anomaly_result.candidate_causes[:3]
        ],
        "meta": {
            "analysis_mode": anomaly_result.meta.analysis_mode,
            "event_count": anomaly_result.meta.event_count,
            "detector_breakdown": [
                item.model_dump(mode="json") for item in anomaly_result.meta.detector_breakdown
            ],
        },
    }


def _build_fallback_response(
    payload: AIReportSummaryRequest,
    report_context: ReportContext,
    anomaly_result: Any | None,
    stage_timings_ms: dict[str, int],
    settings_model: str,
) -> AIReportSummaryResponse:
    return AIReportSummaryResponse(
        status="ready" if report_context.metrics_snapshot.total is not None or anomaly_result else "low_confidence",
        summary=report_context.question,
        highlights=_default_highlights(report_context, anomaly_result),
        risks=_default_risks(report_context, anomaly_result),
        suggestions=_default_suggestions(report_context, anomaly_result),
        evidence=_build_evidence(report_context, anomaly_result),
        actions=_build_actions(payload, anomaly_result, get_ai_settings().ai_allowed_action_targets),
        meta=AIReportSummaryMeta(
            generated_at=get_taipei_now(),
            model=settings_model,
            report_type=report_context.report_type,
            audience=report_context.audience,
            used_tools=[] if anomaly_result is None else ["analyze_anomaly_with_ai"],
            context_source="server_enriched",
            anomaly_insight_used=anomaly_result is not None,
            stage_timings_ms=stage_timings_ms,
        ),
    )


def get_report_summary(payload: AIReportSummaryRequest) -> AIReportSummaryResponse:
    total_start = perf_counter()
    settings = get_ai_settings()
    stage_timings_ms: dict[str, int] = {}

    anomaly_result: Any | None = None
    if _should_include_anomaly_insight(payload):
        anomaly_start = perf_counter()
        anomaly_result = _build_anomaly_result(payload)
        stage_timings_ms["anomaly_analysis_ms"] = _duration_ms(anomaly_start)

    report_context = _build_report_context(payload, anomaly_result)
    anomaly_insight = _build_anomaly_insight(anomaly_result)

    try:
        llm_start = perf_counter()
        system_prompt, user_prompt = build_report_summary_prompts(
            report_context=report_context.model_dump(mode="json"),
            anomaly_insight=anomaly_insight,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )
        llm_response = OpenAICompatibleClient(settings).generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        stage_timings_ms["report_summary_llm_ms"] = _duration_ms(llm_start)
        stage_timings_ms["total_ms"] = _duration_ms(total_start)
        return AIReportSummaryResponse(
            status=str(llm_response.get("status") or ("ready" if anomaly_result or report_context.metrics_snapshot.total is not None else "low_confidence")),
            summary=str(llm_response.get("summary") or report_context.question),
            highlights=_coerce_highlights(llm_response.get("highlights")) or _default_highlights(report_context, anomaly_result),
            risks=_coerce_string_list(llm_response.get("risks")) or _default_risks(report_context, anomaly_result),
            suggestions=_coerce_suggestions(llm_response.get("suggestions")) or _default_suggestions(report_context, anomaly_result),
            evidence=_build_evidence(report_context, anomaly_result),
            actions=_build_actions(payload, anomaly_result, settings.ai_allowed_action_targets),
            meta=AIReportSummaryMeta(
                generated_at=get_taipei_now(),
                model=settings.llm_model,
                report_type=report_context.report_type,
                audience=report_context.audience,
                used_tools=[] if anomaly_result is None else ["analyze_anomaly_with_ai"],
                context_source="server_enriched",
                anomaly_insight_used=anomaly_result is not None,
                stage_timings_ms=stage_timings_ms,
            ),
        )
    except Exception:  # noqa: BLE001
        stage_timings_ms["total_ms"] = _duration_ms(total_start)
        return _build_fallback_response(
            payload=payload,
            report_context=report_context,
            anomaly_result=anomaly_result,
            stage_timings_ms=stage_timings_ms,
            settings_model=settings.llm_model,
        )
