from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.schemas import AIActionItem
from app.schemas import AIAnalyzeAnomalyMeta
from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import AIAnalyzeAnomalyResponse
from app.schemas import AICandidateCause
from app.schemas import AIEvidenceItem
from app.schemas import AIFeedbackPrompt
from app.schemas import EnergyAnomalyAnalysisRequest
from app.schemas import WeatherCorrelationResponse
from app.service_common import get_taipei_now
from app.services_energy import get_energy_anomaly_analysis
from app.services_energy import get_energy_weather_correlation

from .config import get_ai_settings
from .history import retrieve_similar_feedback_cases
from .knowledge import retrieve_anomaly_knowledge
from .llm_client import OpenAICompatibleClient
from .prompting import build_analyze_anomaly_prompts


# ============================================================================
# AI 异常分析核心业务逻辑模块
# 主要功能：
#   1. 调用能耗异常检测接口获取异常数据
#   2. 收集天气、知识库、历史反馈等上下文信息
#   3. 调用 LLM 进行根因诊断和结构化分析
#   4. 提供 fallback 机制确保服务可用性
# ============================================================================


def _build_analysis_id() -> str:
    """生成一次异常分析的唯一 ID。"""
    return f"ana_{uuid4().hex[:16]}"


def _collect_highlights(anomaly_summary: str, weather_result: WeatherCorrelationResponse | None) -> list[str]:
    highlights = [anomaly_summary]
    if weather_result and weather_result.factors:
        strongest = max(weather_result.factors, key=lambda item: abs(item.coefficient))
        highlights.append(
            f"Strongest weather factor: {strongest.name} ({strongest.coefficient:.4f}, {strongest.direction})"
        )
    return highlights[:3]


def _build_default_candidate_causes(
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    max_candidate_causes: int,
) -> list[AICandidateCause]:
    candidates = [
        AICandidateCause(
            cause_id="load_shift",
            title="负荷模式变化",
            description="当前能耗与基线出现明显偏离，可能由节假日、排班调整或使用强度变化引起。",
            confidence=0.62,
            rank=1,
            recommended_checks=[
                "核对异常时间段内的人员活动和排班是否有变化。",
                "对比前一周或去年同期的同类时段负荷水平。",
            ],
            evidence_ids=["evi_data_anomaly"],
        ),
        AICandidateCause(
            cause_id="efficiency_drop",
            title="设备效率下降或控制漂移",
            description="持续偏高或偏低的负荷，可能和设备效率下降、控制参数漂移或运行策略异常有关。",
            confidence=0.51,
            rank=2,
            recommended_checks=[
                "检查主要设备的效率指标、控制设定值和启停逻辑。",
                "回看最近是否有运维调参、维修或策略切换。",
            ],
            evidence_ids=["evi_data_anomaly"],
        ),
    ]
    if weather_result and weather_result.factors:
        candidates.append(
            AICandidateCause(
                cause_id="weather_driven_load",
                title="天气驱动的负荷波动",
                description="天气相关性提示当前异常中有一部分可能由室外环境变化带动，而非单纯设备故障。",
                confidence=0.43,
                rank=3,
                recommended_checks=[
                    "结合室外温度和天气变化，检查运行策略是否同步调整。",
                    "确认异常窗口是否处于极端气候或季节切换阶段。",
                ],
                evidence_ids=["evi_weather_corr"],
            )
        )
    if not anomaly_result.detected_points:
        candidates.append(
            AICandidateCause(
                cause_id="insufficient_signal",
                title="异常信号不足",
                description="当前时间窗口中的异常信号不够强，暂时不足以支撑高置信度的根因排序。",
                confidence=0.25,
                rank=len(candidates) + 1,
                recommended_checks=[
                    "扩大时间窗口后再与更长周期基线对比。",
                    "确认当前表计数据覆盖是否完整，避免缺测影响判断。",
                ],
                evidence_ids=["evi_data_anomaly"],
            )
        )
    return candidates[:max(2, min(max_candidate_causes, 5))]


def _build_default_evidence(
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    history_context: list[dict[str, Any]],
) -> list[AIEvidenceItem]:
    evidence: list[AIEvidenceItem] = [
        AIEvidenceItem(
            evidence_id="evi_data_anomaly",
            type="data",
            source="energy_anomaly_analysis",
            snippet=anomaly_result.summary,
            weight=0.9 if anomaly_result.is_anomalous else 0.4,
        )
    ]
    if weather_result:
        evidence.append(
            AIEvidenceItem(
                evidence_id="evi_weather_corr",
                type="weather",
                source="energy_weather_correlation",
                snippet=f"Main weather correlation coefficient: {weather_result.correlation_coefficient:.4f}",
                weight=0.6,
            )
        )
    if history_context:
        evidence.append(
            AIEvidenceItem(
                evidence_id="evi_history_cases",
                type="history_case",
                source="ai_anomaly_feedback",
                snippet=f"Retrieved {len(history_context)} similar historical feedback cases.",
                weight=0.45,
            )
        )
    return evidence


def _build_default_actions(request: AIAnalyzeAnomalyRequest) -> list[AIActionItem]:
    return [
        AIActionItem(
            label="查看异常趋势",
            action_type="open_tool",
            target="energy_trend",
        ),
        AIActionItem(
            label="提交人工反馈",
            action_type="open_api",
            target="/ai/anomaly-feedback",
        ),
        AIActionItem(
            label="查看天气相关性",
            action_type="open_tool",
            target="energy_weather_correlation",
        ),
    ]


def _filter_allowed_actions(actions: list[AIActionItem], allowed_action_targets: tuple[str, ...]) -> list[AIActionItem]:
    allowed_targets = set(allowed_action_targets)
    return [item for item in actions if item.target in allowed_targets]


def _coerce_candidate_causes(value: Any, max_candidate_causes: int) -> list[AICandidateCause]:
    if not isinstance(value, list):
        raise ValueError("candidate_causes must be a list")
    candidates: list[AICandidateCause] = []
    for index, item in enumerate(value[:5], start=1):
        if not isinstance(item, dict):
            continue
        candidates.append(
            AICandidateCause(
                cause_id=str(item.get("cause_id") or f"candidate_{index}"),
                title=str(item.get("title") or f"Candidate cause {index}"),
                description=str(item.get("description") or ""),
                confidence=float(item.get("confidence") or 0.3),
                rank=int(item.get("rank") or index),
                recommended_checks=[str(v) for v in item.get("recommended_checks", []) if str(v).strip()],
                evidence_ids=[str(v) for v in item.get("evidence_ids", []) if str(v).strip()],
            )
        )
    candidates = candidates[: max(2, min(max_candidate_causes, 5))]
    if len(candidates) < 2:
        raise ValueError("candidate_causes must contain at least two items")
    return candidates


def _coerce_evidence(value: Any) -> list[AIEvidenceItem]:
    if not isinstance(value, list):
        return []
    evidence_items: list[AIEvidenceItem] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        evidence_items.append(
            AIEvidenceItem(
                evidence_id=str(item.get("evidence_id") or f"evi_{index:03d}"),
                type=str(item.get("type") or "knowledge"),
                source=str(item.get("source") or "llm"),
                snippet=str(item.get("snippet") or ""),
                weight=float(item.get("weight") or 0.3),
            )
        )
    return evidence_items


def _coerce_actions(value: Any, allowed_action_targets: set[str]) -> list[AIActionItem]:
    if not isinstance(value, list):
        return []
    actions: list[AIActionItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        action_type = str(item.get("action_type") or "").strip()
        target = str(item.get("target") or "").strip()
        if not (label and action_type and target):
            continue
        if target not in allowed_action_targets:
            continue
        actions.append(
            AIActionItem(
                label=label,
                action_type=action_type,
                target=target,
                target_id=str(item.get("target_id") or "").strip() or None,
            )
        )
    return actions


def _coerce_feedback_prompt(value: Any) -> AIFeedbackPrompt:
    if not isinstance(value, dict):
        return AIFeedbackPrompt(
            enabled=True,
            message="请选择最符合现场情况的候选原因，并评价本次分析结果。",
            allow_score=True,
            allow_comment=True,
        )
    return AIFeedbackPrompt(
        enabled=bool(value.get("enabled", True)),
        message=str(value.get("message") or "请选择最符合现场情况的候选原因，并评价本次分析结果。"),
        allow_score=bool(value.get("allow_score", True)),
        allow_comment=bool(value.get("allow_comment", True)),
    )


def _build_fallback_answer(
    anomaly_result: Any,
    candidate_causes: list[AICandidateCause],
    weather_result: WeatherCorrelationResponse | None,
) -> str:
    """构造给前端可直接展示的中文 fallback 诊断摘要。"""

    segments = [f"根据当前异常检测结果，{anomaly_result.summary}"]

    if candidate_causes:
        top_causes = "；".join(
            f"{item.title}（置信度 {item.confidence:.0%}）"
            for item in candidate_causes[:2]
        )
        segments.append(f"当前优先怀疑的原因包括：{top_causes}。")

    if weather_result is not None:
        segments.append(
            f"天气相关性系数约为 {weather_result.correlation_coefficient:.2f}，请结合现场运行工况综合判断。"
        )

    segments.append("这是一份基于结构化结果生成的辅助诊断建议，仍需结合现场排班、设备日志和运维记录进一步确认。")
    return " ".join(segments)


def _build_fallback_response(
    request: AIAnalyzeAnomalyRequest,
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    history_context: list[dict[str, Any]],
    settings_model: str,
    allowed_action_targets: tuple[str, ...],
) -> AIAnalyzeAnomalyResponse:
    """在 LLM 不可用或输出非法时，构造可落地的兜底响应。"""
    analysis_id = _build_analysis_id()
    generated_at = get_taipei_now()
    candidate_causes = _build_default_candidate_causes(
        anomaly_result=anomaly_result,
        weather_result=weather_result,
        max_candidate_causes=request.max_candidate_causes,
    )
    return AIAnalyzeAnomalyResponse(
        analysis_id=analysis_id,
        status="needs_confirmation" if anomaly_result.is_anomalous else "low_confidence",
        summary=anomaly_result.summary,
        answer=_build_fallback_answer(anomaly_result, candidate_causes, weather_result),
        candidate_causes=candidate_causes,
        highlights=_collect_highlights(anomaly_result.summary, weather_result),
        evidence=_build_default_evidence(anomaly_result, weather_result, history_context),
        actions=_filter_allowed_actions(_build_default_actions(request), allowed_action_targets),
        risk_notice="当前结果属于辅助诊断建议，不代表故障已经确认，请结合现场记录和人工排查进一步核实。",
        feedback_prompt=AIFeedbackPrompt(
            enabled=True,
            message="请选择最符合现场情况的候选原因，并反馈本次分析是否有帮助。",
            allow_score=True,
            allow_comment=True,
        ),
        meta=AIAnalyzeAnomalyMeta(
            building_id=request.building_id,
            meter=request.meter,
            time_range=request.time_range,
            baseline_mode=request.baseline_mode or "overall_mean",
            generated_at=generated_at,
            model=settings_model,
            knowledge_hits=0,
            history_feedback_hits=len(history_context),
            used_fallback=True,
        ),
    )


def _normalize_llm_response(
    request: AIAnalyzeAnomalyRequest,
    llm_response: dict[str, Any],
    anomaly_result: Any,
    weather_result: WeatherCorrelationResponse | None,
    knowledge_context: list[dict[str, Any]],
    history_context: list[dict[str, Any]],
    settings_model: str,
    allowed_action_targets: tuple[str, ...],
) -> AIAnalyzeAnomalyResponse:
    """将 LLM 原始 JSON 归一化为后端响应模型。"""
    analysis_id = _build_analysis_id()
    generated_at = get_taipei_now()
    candidate_causes = _coerce_candidate_causes(llm_response.get("candidate_causes"), request.max_candidate_causes)
    evidence = _coerce_evidence(llm_response.get("evidence")) or _build_default_evidence(
        anomaly_result, weather_result, history_context
    )
    actions = _coerce_actions(llm_response.get("actions"), set(allowed_action_targets)) or _filter_allowed_actions(
        _build_default_actions(request),
        allowed_action_targets,
    )
    return AIAnalyzeAnomalyResponse(
        analysis_id=analysis_id,
        status=str(llm_response.get("status") or ("needs_confirmation" if anomaly_result.is_anomalous else "low_confidence")),
        summary=str(llm_response.get("summary") or anomaly_result.summary),
        answer=str(llm_response.get("answer") or anomaly_result.summary),
        candidate_causes=candidate_causes,
        highlights=[str(item) for item in llm_response.get("highlights", []) if str(item).strip()] or _collect_highlights(
            anomaly_result.summary, weather_result
        ),
        evidence=evidence,
        actions=actions,
        risk_notice=str(
            llm_response.get("risk_notice")
            or "This output is a diagnosis suggestion and should not be treated as a confirmed fault."
        ),
        feedback_prompt=_coerce_feedback_prompt(llm_response.get("feedback_prompt")),
        meta=AIAnalyzeAnomalyMeta(
            building_id=request.building_id,
            meter=request.meter,
            time_range=request.time_range,
            baseline_mode=request.baseline_mode or "overall_mean",
            generated_at=generated_at,
            model=settings_model,
            knowledge_hits=len(knowledge_context),
            history_feedback_hits=len(history_context),
            used_fallback=False,
        ),
    )


def analyze_anomaly_with_ai(payload: AIAnalyzeAnomalyRequest) -> AIAnalyzeAnomalyResponse:
    """AI 异常分析总编排入口。

    流程：
    1. 先调用能耗异常检测接口拿到结构化结果。
    2. 按配置可选补充天气、知识库、历史反馈上下文。
    3. 调用 LLM 生成结构化诊断。
    4. 若 LLM 失败，返回可用的 fallback 结果。
    """

    energy_payload = EnergyAnomalyAnalysisRequest(
        building_id=payload.building_id,
        meter=payload.meter,
        time_range=payload.time_range,
        granularity=payload.granularity,
        baseline_mode=payload.baseline_mode,
        include_weather_context=payload.include_weather_context,
    )
    anomaly_result = get_energy_anomaly_analysis(energy_payload)

    weather_result: WeatherCorrelationResponse | None = None
    if payload.include_weather_context:
        weather_result = get_energy_weather_correlation(
            building_id=payload.building_id,
            meter=payload.meter,
            start_time=payload.time_range.start,
            end_time=payload.time_range.end,
        )

    settings = get_ai_settings()
    knowledge_context = (
        retrieve_anomaly_knowledge(payload.meter, anomaly_result.summary, payload.question)
        if settings.ai_enable_knowledge
        else []
    )
    history_context = (
        retrieve_similar_feedback_cases(
            building_id=payload.building_id,
            meter=payload.meter,
            start_time=payload.time_range.start.isoformat(),
            end_time=payload.time_range.end.isoformat(),
        )
        if settings.ai_enable_history
        else []
    )

    try:
        system_prompt, user_prompt = build_analyze_anomaly_prompts(
            request=payload,
            anomaly_result=anomaly_result,
            weather_result=weather_result,
            knowledge_context=knowledge_context,
            history_context=history_context,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )
        llm_response = OpenAICompatibleClient(settings).generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return _normalize_llm_response(
            request=payload,
            llm_response=llm_response,
            anomaly_result=anomaly_result,
            weather_result=weather_result,
            knowledge_context=knowledge_context,
            history_context=history_context,
            settings_model=settings.llm_model,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )
    except Exception:
        # Keep the route usable even before the model side is fully stable.
        return _build_fallback_response(
            request=payload,
            anomaly_result=anomaly_result,
            weather_result=weather_result,
            history_context=history_context,
            settings_model=settings.llm_model,
            allowed_action_targets=settings.ai_allowed_action_targets,
        )

