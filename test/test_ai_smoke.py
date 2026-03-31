from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault('PYTHONPATH', r'D:\code\服外\fw-backend')
os.environ.setdefault('AI_ALLOWED_ACTION_TARGETS', 'energy_trend,energy_compare,energy_weather_correlation,energy_anomaly_analysis,/ai/anomaly-feedback')
os.environ.setdefault('LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
os.environ.setdefault('LLM_API_KEY', 'ollama')
os.environ.setdefault('LLM_MODEL', 'qwen3.5:latest')
os.environ.setdefault('LLM_TIMEOUT_SECONDS', '30')

from fastapi.testclient import TestClient

from ai.backend.anomaly_service import _normalize_llm_response
from ai.backend.config import get_ai_settings
from ai.backend.query_assistant_service import build_query_intent
from app.main import app
from app.schemas import AIAnalyzeAnomalyRequest
from app.schemas import AIQueryAssistantRequest
from app.schemas import EnergyAnomalyAnalysisResponse
from app.schemas import EnergyPoint
from app.schemas import EnergySeries
from app.schemas import TimeRange


def build_dummy_anomaly_response() -> EnergyAnomalyAnalysisResponse:
    time_range = TimeRange(
        start=datetime.fromisoformat('2017-01-01T00:00:00+00:00'),
        end=datetime.fromisoformat('2017-01-02T00:00:00+00:00'),
    )
    return EnergyAnomalyAnalysisResponse(
        building_id='Bear_assembly_Angel',
        meter='electricity',
        time_range=time_range,
        is_anomalous=True,
        summary='检测到 2 个异常点，最大偏离率为 41.61%。',
        baseline_mode='overall_mean',
        detected_points=[],
        series=EnergySeries(
            building_id='Bear_assembly_Angel',
            meter='electricity',
            unit='kWh',
            points=[
                EnergyPoint(
                    timestamp=datetime.fromisoformat('2017-01-01T18:00:00+00:00'),
                    building_id='Bear_assembly_Angel',
                    meter='electricity',
                    value=927.0,
                )
            ],
        ),
        weather_context=None,
    )


def run_service_test() -> dict:
    payload = AIQueryAssistantRequest(question='查 Bear_assembly_Angel 最近7天电耗趋势')
    result = build_query_intent(payload)
    return {
        'summary': result.summary,
        'recommended_endpoint': result.recommended_endpoint,
        'recommended_http_method': result.recommended_http_method,
        'meter': result.query_intent.meter,
        'granularity': result.query_intent.granularity,
        'used_fallback': result.meta.used_fallback,
        'recommended_query_params': result.recommended_query_params,
    }


def run_http_test() -> dict:
    client = TestClient(app)
    response = client.post(
        '/ai/query-assistant',
        json={
            'question': '查 Bear_assembly_Angel 最近7天电耗趋势',
        },
    )
    body = response.json()
    return {
        'status_code': response.status_code,
        'recommended_endpoint': body.get('recommended_endpoint'),
        'recommended_http_method': body.get('recommended_http_method'),
        'used_fallback': body.get('meta', {}).get('used_fallback'),
    }


def run_whitelist_test() -> dict:
    request = AIAnalyzeAnomalyRequest(
        building_id='Bear_assembly_Angel',
        meter='electricity',
        time_range=TimeRange(
            start=datetime.fromisoformat('2017-01-01T00:00:00+00:00'),
            end=datetime.fromisoformat('2017-01-02T00:00:00+00:00'),
        ),
    )
    result = _normalize_llm_response(
        request=request,
        llm_response={
            'summary': '异常建议',
            'status': 'needs_confirmation',
            'answer': '请优先排查负荷模式变化。',
            'candidate_causes': [
                {
                    'cause_id': 'load_shift',
                    'title': '负荷模式变化',
                    'description': '晚间负荷偏高。',
                    'confidence': 0.8,
                    'rank': 1,
                    'recommended_checks': ['查看排班记录'],
                    'evidence_ids': ['evi_001'],
                },
                {
                    'cause_id': 'unexpected_usage',
                    'title': '临时用电增加',
                    'description': '存在临时高耗能设备。',
                    'confidence': 0.5,
                    'rank': 2,
                    'recommended_checks': ['检查设备运行日志'],
                    'evidence_ids': ['evi_002'],
                },
            ],
            'evidence': [
                {
                    'evidence_id': 'evi_001',
                    'type': 'data',
                    'source': 'energy_anomaly_analysis',
                    'snippet': '异常点集中在晚间。',
                    'weight': 0.9,
                }
            ],
            'actions': [
                {
                    'label': '查看趋势',
                    'action_type': 'open_tool',
                    'target': 'energy_trend',
                },
                {
                    'label': '查看设备状态',
                    'action_type': 'open_tool',
                    'target': 'device_status',
                },
            ],
            'risk_notice': '这是诊断建议，不是已确认故障。',
            'feedback_prompt': {
                'enabled': True,
                'message': '请选择最可能原因并评分。',
                'allow_score': True,
                'allow_comment': True,
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
        'actions': [item.model_dump() for item in result.actions],
        'all_targets_allowed': all(item.target in set(get_ai_settings().ai_allowed_action_targets) for item in result.actions),
    }


def main() -> None:
    report = {
        'service_query_assistant': run_service_test(),
        'http_query_assistant': run_http_test(),
        'action_whitelist': run_whitelist_test(),
    }
    out_path = Path(r'D:\code\服外\fw-backend\test\ai_smoke_report.json')
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
