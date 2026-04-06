from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient

from ai.backend import ops_guide_service
from ai.backend import qa_service
from ai.backend import report_summary_service
from ai.backend.anomaly_service import _normalize_llm_response
from ai.backend.config import get_ai_settings
from ai.backend.query_assistant_service import build_query_intent
from app.main import app
from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import AIFeedbackPrompt
from app.schemas import AIActionItem
from app.schemas import AIAnalyzeAnomalyMeta
from app.schemas import AIAnalyzeAnomalyResponse
from app.schemas import AIQAMeta
from app.schemas import AICandidateCause
from app.schemas import AIEvidenceItem
from app.schemas import AIQueryAssistantRequest
from app.schemas import AnomalyDetectorBreakdownItem
from app.schemas import DetectedAnomalyEvent
from app.schemas import EnergyAnomalyAnalysisResponse
from app.schemas import EnergyPoint
from app.schemas import EnergySeries
from app.schemas import TimeRange

REPORT_JSON_PATH = BASE_DIR / "test" / "ai_smoke_report.json"


def build_dummy_anomaly_response() -> EnergyAnomalyAnalysisResponse:
    time_range = TimeRange(
        start=datetime.fromisoformat("2017-01-01T00:00:00+00:00"),
        end=datetime.fromisoformat("2017-01-02T00:00:00+00:00"),
    )
    return EnergyAnomalyAnalysisResponse(
        building_id="Bear_assembly_Angel",
        meter="electricity",
        time_range=time_range,
        is_anomalous=True,
        summary="检测到 2 个离线异常事件，包含 1 个突发极值和 1 个隐性周期异常。",
        analysis_mode="offline_event_review",
        event_count=2,
        detector_breakdown=[
            AnomalyDetectorBreakdownItem(detected_by="z_score_detector", event_type="point_outlier", count=1),
            AnomalyDetectorBreakdownItem(detected_by="isolation_forest", event_type="contextual_outlier", count=1),
        ],
        detected_events=[
            DetectedAnomalyEvent(
                event_id="evt_1",
                start_time=datetime.fromisoformat("2017-01-01T18:00:00+00:00"),
                end_time=datetime.fromisoformat("2017-01-01T18:00:00+00:00"),
                severity="high",
                detected_by="z_score_detector",
                event_type="point_outlier",
                description="出现突发性异常高值。",
                peak_deviation=41.61,
            )
        ],
        series=EnergySeries(
            building_id="Bear_assembly_Angel",
            meter="electricity",
            unit="kWh",
            points=[
                EnergyPoint(
                    timestamp=datetime.fromisoformat("2017-01-01T18:00:00+00:00"),
                    building_id="Bear_assembly_Angel",
                    meter="electricity",
                    value=927.0,
                )
            ],
        ),
        weather_context=None,
    )


def build_dummy_ai_anomaly_response() -> AIAnalyzeAnomalyResponse:
    return AIAnalyzeAnomalyResponse(
        analysis_id="ana_smoke_001",
        status="needs_confirmation",
        summary="检测到夜间电耗异常升高。",
        answer="夜间电耗显著高于基线，建议优先排查设备排班和异常运行负载。",
        candidate_causes=[
            AICandidateCause(
                cause_id="load_shift",
                title="负荷模式变化",
                description="夜间负荷比基线显著偏高。",
                confidence=0.82,
                rank=1,
                recommended_checks=["检查夜间是否有临时加班或额外设备开启"],
                evidence_ids=["evi_001"],
            ),
            AICandidateCause(
                cause_id="unexpected_usage",
                title="异常用能增加",
                description="存在临时高耗能设备持续运行的可能。",
                confidence=0.56,
                rank=2,
                recommended_checks=["核对设备运行日志和开关机记录"],
                evidence_ids=["evi_002"],
            ),
        ],
        highlights=["夜间电耗异常升高", "天气因素不足以单独解释本次波动"],
        evidence=[
            AIEvidenceItem(
                evidence_id="evi_001",
                type="data",
                source="energy_anomaly_analysis",
                snippet="夜间 01:00-03:00 电耗明显高于基线。",
                weight=0.91,
            ),
            AIEvidenceItem(
                evidence_id="evi_002",
                type="history_case",
                source="ai_anomaly_feedback",
                snippet="历史上相似波动曾由夜间额外设备运行导致。",
                weight=0.44,
            ),
        ],
        actions=[
            AIActionItem(
                label="查看异常趋势",
                action_type="open_tool",
                target="energy_trend",
            ),
            AIActionItem(
                label="提交反馈",
                action_type="open_api",
                target="/ai/anomaly-feedback",
            ),
        ],
        risk_notice="当前结果属于诊断建议，不代表已确认故障。",
        feedback_prompt=AIFeedbackPrompt(
            enabled=True,
            message="请选择最可能原因并评分。",
            allow_score=True,
            allow_comment=True,
        ),
        meta=AIAnalyzeAnomalyMeta(
            building_id="Bear_assembly_Angel",
            meter="electricity",
            time_range=TimeRange(
                start=datetime.fromisoformat("2017-01-01T00:00:00+00:00"),
                end=datetime.fromisoformat("2017-01-02T00:00:00+00:00"),
            ),
            analysis_mode="offline_event_review",
            generated_at=datetime.fromisoformat("2026-04-02T12:00:00+08:00"),
            model="qwen3.5-plus",
            event_count=2,
            detector_breakdown=[
                AnomalyDetectorBreakdownItem(detected_by="z_score_detector", event_type="point_outlier", count=1)
            ],
            knowledge_hits=1,
            history_feedback_hits=1,
            used_fallback=False,
        ),
    )


@contextmanager
def patched_ai_dependencies() -> Any:
    """为 /ai/qa 和 /ai/ops-guide smoke test 打补丁，避免依赖真实环境。"""

    orig_search = qa_service.search_domain_knowledge_references
    orig_generate = qa_service.OpenAICompatibleClient.generate_json
    orig_query = qa_service.build_query_intent
    orig_analyze = qa_service.analyze_anomaly_with_ai
    orig_ops_search = ops_guide_service.search_domain_knowledge_references
    orig_ops_generate = ops_guide_service.OpenAICompatibleClient.generate_json
    orig_ops_analyze = ops_guide_service.analyze_anomaly_with_ai
    orig_ops_history = ops_guide_service.retrieve_similar_feedback_cases
    orig_report_generate = report_summary_service.OpenAICompatibleClient.generate_json
    orig_report_analyze = report_summary_service.analyze_anomaly_with_ai

    def fake_search(question: str, *, top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        return {
            "chunks": [
                {
                    "document_id": "doc_1",
                    "document_name": "SLS单级单吸离心泵.pdf",
                    "chunk_id": "chunk_1",
                    "content": "周围环境温度不超过40℃，海拔高度不高于1000m，相对湿度不超过95%。",
                    "similarity": 0.91,
                    "dataset_id": "kb_1",
                }
            ],
            "doc_aggs": [
                {
                    "document_id": "doc_1",
                    "document_name": "SLS单级单吸离心泵.pdf",
                    "count": 1,
                }
            ],
        }

    def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, str]:
        if "运维指导助手" in system_prompt:
            return {
                "status": "actionable",
                "summary": "建议先核查排班与运行日历，再检查异常时段设备启停和控制策略。",
                "preconditions": [
                    "确认当前建筑、表计和时间范围与接手事件一致。",
                    "确认当前指导基于离线异常事件分析结果。"
                ],
                "steps": [
                    {
                        "step_id": "step_1",
                        "title": "优先排查：负荷模式变化",
                        "instruction": "先核查异常时段是否处于节假日、调休或特殊排班。",
                        "priority": "high",
                        "expected_result": "判断是否属于业务侧导致的规律变化。",
                        "if_not_met": "若无明显排班变化，继续核查设备启停记录。"
                    },
                    {
                        "step_id": "step_2",
                        "title": "继续核查：异常用能增加",
                        "instruction": "检查异常时段是否存在额外设备开启或异常启停。",
                        "priority": "medium",
                        "expected_result": "确认是否存在突发负荷来源。",
                        "if_not_met": "若仍无法确认，查看历史相似案例并升级处理。"
                    }
                ],
                "risk_notice": [
                    "当前结果属于运维指导，不代表故障已确认。"
                ],
                "applicability": {
                    "applies_to": ["离线异常事件接手后的排查场景"],
                    "not_applies_to": ["缺少上下文的自由问答场景"]
                }
            }
        if "报表总结助手" in system_prompt:
            return {
                "status": "ready",
                "summary": "本周期总用电整体平稳，存在少量异常波动，建议结合趋势图继续关注高值时段。",
                "highlights": [
                    {
                        "title": "总量概览",
                        "detail": "当前时间范围总量和均值处于可控范围内。",
                        "priority": "high",
                    },
                    {
                        "title": "异常关注点",
                        "detail": "存在离线异常事件，需要继续核查高值时段设备启停。",
                        "priority": "medium",
                    }
                ],
                "risks": [
                    "当前异常洞察属于需关注信号，不代表故障已确认。"
                ],
                "suggestions": [
                    {
                        "label": "查看异常高值时段设备启停记录",
                        "type": "investigate",
                        "rationale": "当前窗口存在突发性高值波动。"
                    }
                ],
            }
        if "综合问答助手" in system_prompt:
            return {
                "answer": "综合来看，知识库说明这台泵的环境要求是温度不超过40℃、海拔不高于1000m；同时如果你还要判断异常原因，建议继续查看最近趋势和异常分析结果。"
            }
        return {
            "answer": "根据知识库资料，这类泵正常工作时环境温度不超过40℃、海拔高度不高于1000m、相对湿度不超过95%。"
        }

    def fake_build_query_intent(payload: AIQueryAssistantRequest) -> Any:
        return SimpleNamespace(
            summary="已将问题解析为 /energy/trend 的查询意图。",
            recommended_endpoint="/energy/trend",
            recommended_http_method="GET",
            recommended_query_params={
                "building_ids": ["Bear_assembly_Angel"],
                "meter": "electricity",
                "start_time": "2017-01-01T00:00:00+00:00",
                "end_time": "2017-01-07T00:00:00+00:00",
                "granularity": "day",
            },
            warnings=[],
        )

    def fake_analyze_anomaly(payload: AIAnalyzeAnomalyRequest) -> AIAnalyzeAnomalyResponse:
        return build_dummy_ai_anomaly_response()

    def fake_retrieve_history_cases(
        building_id: str,
        meter: str,
        start_time: str,
        end_time: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        _ = building_id, meter, start_time, end_time, limit
        return [
            {
                "analysis_id": "ana_hist_001",
                "selected_cause_id": "load_shift",
                "selected_score": 4,
                "resolution_status": "confirmed",
                "comment": "历史上同类波动与节假日排班变化有关。",
                "created_at": "2026-04-01T10:00:00+08:00",
            }
        ]

    qa_service.search_domain_knowledge_references = fake_search
    qa_service.OpenAICompatibleClient.generate_json = fake_generate_json
    qa_service.build_query_intent = fake_build_query_intent
    qa_service.analyze_anomaly_with_ai = fake_analyze_anomaly
    ops_guide_service.search_domain_knowledge_references = fake_search
    ops_guide_service.OpenAICompatibleClient.generate_json = fake_generate_json
    ops_guide_service.analyze_anomaly_with_ai = fake_analyze_anomaly
    ops_guide_service.retrieve_similar_feedback_cases = fake_retrieve_history_cases
    report_summary_service.OpenAICompatibleClient.generate_json = fake_generate_json
    report_summary_service.analyze_anomaly_with_ai = fake_analyze_anomaly
    try:
        yield
    finally:
        qa_service.search_domain_knowledge_references = orig_search
        qa_service.OpenAICompatibleClient.generate_json = orig_generate
        qa_service.build_query_intent = orig_query
        qa_service.analyze_anomaly_with_ai = orig_analyze
        ops_guide_service.search_domain_knowledge_references = orig_ops_search
        ops_guide_service.OpenAICompatibleClient.generate_json = orig_ops_generate
        ops_guide_service.analyze_anomaly_with_ai = orig_ops_analyze
        ops_guide_service.retrieve_similar_feedback_cases = orig_ops_history
        report_summary_service.OpenAICompatibleClient.generate_json = orig_report_generate
        report_summary_service.analyze_anomaly_with_ai = orig_report_analyze


def run_service_query_assistant_test() -> dict[str, Any]:
    payload = AIQueryAssistantRequest(question="查 Bear_assembly_Angel 最近7天电耗趋势")
    result = build_query_intent(payload)
    return {
        "summary": result.summary,
        "recommended_endpoint": result.recommended_endpoint,
        "recommended_http_method": result.recommended_http_method,
        "meter": result.query_intent.meter,
        "granularity": result.query_intent.granularity,
        "used_fallback": result.meta.used_fallback,
        "recommended_query_params": result.recommended_query_params,
    }


def run_http_query_assistant_test() -> dict[str, Any]:
    client = TestClient(app)
    response = client.post(
        "/ai/query-assistant",
        json={
            "question": "查 Bear_assembly_Angel 最近7天电耗趋势",
        },
    )
    body = response.json()
    return {
        "status_code": response.status_code,
        "recommended_endpoint": body.get("recommended_endpoint"),
        "recommended_http_method": body.get("recommended_http_method"),
        "used_fallback": body.get("meta", {}).get("used_fallback"),
    }


def run_action_whitelist_test() -> dict[str, Any]:
    request = AIAnalyzeAnomalyRequest(
        building_id="Bear_assembly_Angel",
        meter="electricity",
        time_range=TimeRange(
            start=datetime.fromisoformat("2017-01-01T00:00:00+00:00"),
            end=datetime.fromisoformat("2017-01-02T00:00:00+00:00"),
        ),
    )
    result = _normalize_llm_response(
        request=request,
        llm_response={
            "summary": "异常建议",
            "status": "needs_confirmation",
            "answer": "请优先排查负荷模式变化。",
            "candidate_causes": [
                {
                    "cause_id": "load_shift",
                    "title": "负荷模式变化",
                    "description": "晚间负荷偏高。",
                    "confidence": 0.8,
                    "rank": 1,
                    "recommended_checks": ["查看排班记录"],
                    "evidence_ids": ["evi_001"],
                },
                {
                    "cause_id": "unexpected_usage",
                    "title": "临时用电增加",
                    "description": "存在临时高耗能设备。",
                    "confidence": 0.5,
                    "rank": 2,
                    "recommended_checks": ["检查设备运行日志"],
                    "evidence_ids": ["evi_002"],
                },
            ],
            "evidence": [
                {
                    "evidence_id": "evi_001",
                    "type": "data",
                    "source": "energy_anomaly_analysis",
                    "snippet": "异常点集中在晚间。",
                    "weight": 0.9,
                }
            ],
            "actions": [
                {
                    "label": "查看趋势",
                    "action_type": "open_tool",
                    "target": "energy_trend",
                },
                {
                    "label": "查看设备状态",
                    "action_type": "open_tool",
                    "target": "device_status",
                },
            ],
            "risk_notice": "这是诊断建议，不是已确认故障。",
            "feedback_prompt": {
                "enabled": True,
                "message": "请选择最可能原因并评分。",
                "allow_score": True,
                "allow_comment": True,
            },
        },
        anomaly_result=build_dummy_anomaly_response(),
        weather_result=None,
        knowledge_context=[],
        history_context=[],
        settings_model=get_ai_settings().llm_model,
        allowed_action_targets=get_ai_settings().ai_allowed_action_targets,
    )
    return {
        "actions": [item.model_dump() for item in result.actions],
        "all_targets_allowed": all(item.target in set(get_ai_settings().ai_allowed_action_targets) for item in result.actions),
    }


def run_ai_qa_knowledge_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/qa",
            json={
                "question": "这台泵对环境温度和海拔有什么要求？",
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "question_type": body.get("question_type"),
        "used_tools": [item.get("tool_name") for item in body.get("used_tools", [])],
        "knowledge_reference_count": len((body.get("references") or {}).get("knowledge", [])),
        "answer_preview": (body.get("answer") or "")[:120],
    }


def run_ai_qa_data_query_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/qa",
            json={
                "question": "查 Bear_assembly_Angel 最近7天电耗趋势",
                "context": {
                    "page": "dashboard",
                    "building_id": "Bear_assembly_Angel",
                    "meter": "electricity",
                    "time_range": {
                        "start": "2017-01-01T00:00:00+00:00",
                        "end": "2017-01-07T00:00:00+00:00",
                    },
                },
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "question_type": body.get("question_type"),
        "used_tools": [item.get("tool_name") for item in body.get("used_tools", [])],
        "data_reference_count": len((body.get("references") or {}).get("data", [])),
        "suggested_actions": [item.get("target") for item in body.get("suggested_actions", [])],
    }


def run_ai_qa_fault_without_context_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/qa",
            json={
                "question": "为什么这个建筑昨天晚上报警了？",
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "question_type": body.get("question_type"),
        "used_tools_count": len(body.get("used_tools", [])),
        "suggested_actions": [item.get("target") for item in body.get("suggested_actions", [])],
        "answer_preview": (body.get("answer") or "")[:120],
    }


def run_ai_qa_mixed_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/qa",
            json={
                "question": "这台泵为什么报警？顺便告诉我说明书里对环境温度有什么要求，再帮我看看最近7天电耗趋势",
                "context": {
                    "page": "anomaly_detail",
                    "building_id": "Bear_assembly_Angel",
                    "device_id": "pump_sls_001",
                    "meter": "electricity",
                    "time_range": {
                        "start": "2017-01-01T00:00:00+00:00",
                        "end": "2017-01-07T00:00:00+00:00",
                    },
                },
            },
        )
    body = response.json()
    references = body.get("references") or {}
    return {
        "status_code": response.status_code,
        "question_type": body.get("question_type"),
        "used_tools": [item.get("tool_name") for item in body.get("used_tools", [])],
        "knowledge_reference_count": len(references.get("knowledge", [])),
        "data_reference_count": len(references.get("data", [])),
        "history_reference_count": len(references.get("history_cases", [])),
        "suggested_actions": [item.get("target") for item in body.get("suggested_actions", [])],
        "answer_preview": (body.get("answer") or "")[:160],
    }


def run_ai_ops_guide_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/ops-guide",
            json={
                "guide_mode": "standard_sop",
                "context": {
                    "building_id": "Bear_assembly_Angel",
                    "meter": "electricity",
                    "time_range": {
                        "start": "2017-01-01T00:00:00+00:00",
                        "end": "2017-01-02T00:00:00+00:00",
                    },
                    "incident_ref": {
                        "incident_id": "inc_smoke_001",
                        "message_id": "msg_smoke_001",
                    },
                    "page_context": {
                        "source": "message_center",
                        "page_type": "anomaly_takeover",
                        "current_chart_range": "7d",
                    },
                    "operator_context": {
                        "operator_id": "op_001",
                        "operator_name": "Codex Tester",
                    },
                    "anomaly_snapshot": {
                        "summary": "检测到 2 个离线异常事件。",
                        "analysis_mode": "offline_event_review",
                        "event_count": 2,
                        "detector_breakdown": [
                            {
                                "detected_by": "z_score_detector",
                                "event_type": "point_outlier",
                                "count": 1,
                            }
                        ],
                        "event_ids": ["evt_1"],
                    },
                },
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "status": body.get("status"),
        "incident_id": body.get("incident_id"),
        "step_count": len(body.get("steps", [])),
        "first_step_title": (body.get("steps") or [{}])[0].get("title"),
        "evidence_count": len(body.get("evidence", [])),
        "action_targets": [item.get("target") for item in body.get("actions", [])],
        "used_tools": body.get("meta", {}).get("used_tools", []),
        "knowledge_hits": body.get("meta", {}).get("knowledge_hits"),
        "history_feedback_hits": body.get("meta", {}).get("history_feedback_hits"),
    }


def run_ai_ops_guide_without_actions_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/ops-guide",
            json={
                "guide_mode": "quick_check",
                "include_actions": False,
                "include_knowledge": False,
                "include_history": False,
                "context": {
                    "building_id": "Bear_assembly_Angel",
                    "meter": "electricity",
                    "time_range": {
                        "start": "2017-01-01T00:00:00+00:00",
                        "end": "2017-01-02T00:00:00+00:00",
                    },
                },
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "status": body.get("status"),
        "step_count": len(body.get("steps", [])),
        "action_count": len(body.get("actions", [])),
        "knowledge_hits": body.get("meta", {}).get("knowledge_hits"),
        "history_feedback_hits": body.get("meta", {}).get("history_feedback_hits"),
    }


def run_ai_report_summary_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/report-summary",
            json={
                "report_type": "weekly_summary",
                "audience": "manager",
                "context": {
                    "building_id": "Bear_assembly_Angel",
                    "meter": "electricity",
                    "time_range": {
                        "start": "2017-01-01T00:00:00+00:00",
                        "end": "2017-01-07T00:00:00+00:00",
                    },
                    "page_context": {
                        "source": "report_center",
                        "page_type": "weekly_card",
                        "current_chart_range": "7d",
                    },
                    "metrics_snapshot": {
                        "total": 4210.4,
                        "average": 601.5,
                        "peak": 927.0,
                        "peak_time": "2017-01-01T18:00:00+00:00",
                        "unit": "kWh",
                        "compare_change_rate": -0.08,
                    },
                    "trend_summary": {
                        "direction": "down",
                        "change_rate": -0.08,
                        "peak_days": ["2017-01-01"],
                        "low_days": ["2017-01-03"],
                    },
                    "anomaly_summary": {
                        "summary": "检测到 2 个离线异常事件。",
                        "analysis_mode": "offline_event_review",
                        "event_count": 2,
                        "detector_breakdown": [
                            {
                                "detected_by": "z_score_detector",
                                "event_type": "point_outlier",
                                "count": 1,
                            }
                        ],
                    },
                },
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "status": body.get("status"),
        "highlight_count": len(body.get("highlights", [])),
        "risk_count": len(body.get("risks", [])),
        "suggestion_types": [item.get("type") for item in body.get("suggestions", [])],
        "evidence_count": len(body.get("evidence", [])),
        "action_targets": [item.get("target") for item in body.get("actions", [])],
        "used_tools": body.get("meta", {}).get("used_tools", []),
        "anomaly_insight_used": body.get("meta", {}).get("anomaly_insight_used"),
    }


def run_ai_report_summary_without_anomaly_test() -> dict[str, Any]:
    with patched_ai_dependencies():
        client = TestClient(app)
        response = client.post(
            "/ai/report-summary",
            json={
                "report_type": "summary_card",
                "audience": "executive",
                "include_anomaly_insight": False,
                "include_actions": False,
                "context": {
                    "building_id": "Bear_assembly_Angel",
                    "time_range": {
                        "start": "2017-01-01T00:00:00+00:00",
                        "end": "2017-01-07T00:00:00+00:00",
                    },
                    "metrics_snapshot": {
                        "total": 4210.4,
                        "unit": "kWh",
                    },
                },
            },
        )
    body = response.json()
    return {
        "status_code": response.status_code,
        "status": body.get("status"),
        "action_count": len(body.get("actions", [])),
        "used_tools": body.get("meta", {}).get("used_tools", []),
        "anomaly_insight_used": body.get("meta", {}).get("anomaly_insight_used"),
    }


def main() -> None:
    report = {
        "service_query_assistant": run_service_query_assistant_test(),
        "http_query_assistant": run_http_query_assistant_test(),
        "action_whitelist": run_action_whitelist_test(),
        "ai_qa_knowledge": run_ai_qa_knowledge_test(),
        "ai_qa_data_query": run_ai_qa_data_query_test(),
        "ai_qa_fault_without_context": run_ai_qa_fault_without_context_test(),
        "ai_qa_mixed": run_ai_qa_mixed_test(),
        "ai_ops_guide": run_ai_ops_guide_test(),
        "ai_ops_guide_without_actions": run_ai_ops_guide_without_actions_test(),
        "ai_report_summary": run_ai_report_summary_test(),
        "ai_report_summary_without_anomaly": run_ai_report_summary_without_anomaly_test(),
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
