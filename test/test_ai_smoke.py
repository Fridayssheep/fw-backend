from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from ai.backend import qa_service
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


BASE_DIR = Path(__file__).resolve().parents[1]
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
def patched_qa_dependencies() -> Any:
    """为 /ai/qa smoke test 打补丁，避免依赖真实环境。"""

    orig_search = qa_service.search_domain_knowledge_references
    orig_generate = qa_service.OpenAICompatibleClient.generate_json
    orig_query = qa_service.build_query_intent
    orig_analyze = qa_service.analyze_anomaly_with_ai

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

    qa_service.search_domain_knowledge_references = fake_search
    qa_service.OpenAICompatibleClient.generate_json = fake_generate_json
    qa_service.build_query_intent = fake_build_query_intent
    qa_service.analyze_anomaly_with_ai = fake_analyze_anomaly
    try:
        yield
    finally:
        qa_service.search_domain_knowledge_references = orig_search
        qa_service.OpenAICompatibleClient.generate_json = orig_generate
        qa_service.build_query_intent = orig_query
        qa_service.analyze_anomaly_with_ai = orig_analyze


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
    with patched_qa_dependencies():
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
    with patched_qa_dependencies():
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
    with patched_qa_dependencies():
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
    with patched_qa_dependencies():
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


def main() -> None:
    report = {
        "service_query_assistant": run_service_query_assistant_test(),
        "http_query_assistant": run_http_query_assistant_test(),
        "action_whitelist": run_action_whitelist_test(),
        "ai_qa_knowledge": run_ai_qa_knowledge_test(),
        "ai_qa_data_query": run_ai_qa_data_query_test(),
        "ai_qa_fault_without_context": run_ai_qa_fault_without_context_test(),
        "ai_qa_mixed": run_ai_qa_mixed_test(),
    }
    REPORT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
