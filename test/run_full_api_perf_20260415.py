from __future__ import annotations

import json
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("API_TEST_TIMEOUT_SECONDS", "30"))
NOW_TAG = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__))
OUTPUT_PATH = os.path.join(OUTPUT_DIR, f"full_api_perf_results_{NOW_TAG}.json")


@dataclass
class Case:
    case_id: str
    operation: str
    method: str
    path_template: str
    expected_status: list[int]
    repeat: int = 1
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    sse: bool = False
    builder: Any = None
    notes: str | None = None


def _json_dumps(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _preview_json(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {"type": "object", "keys": list(payload.keys())[:20]}
    if isinstance(payload, list):
        return {"type": "array", "length": len(payload)}
    return {"type": type(payload).__name__}


def _preview_text(text: str, max_chars: int = 220) -> str:
    normalized = text.replace("\r", " ").replace("\n", " ").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars] + "..."


def _safe_json_loads(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _resolve_path(path_template: str, path_params: dict[str, Any] | None = None) -> str:
    path = path_template
    for key, value in (path_params or {}).items():
        encoded = quote(str(value), safe="")
        path = path.replace("{" + key + "}", encoded)
    return path


def call_api(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    sse: bool = False,
) -> dict[str, Any]:
    query = urlencode(params, doseq=True) if params else ""
    url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")

    req_headers = dict(headers or {})
    body: bytes | None = None
    if json_body is not None:
        body = _json_dumps(json_body)
        req_headers["Content-Type"] = "application/json; charset=utf-8"
    if sse:
        req_headers["Accept"] = "text/event-stream"

    request = Request(url=url, method=method.upper(), data=body, headers=req_headers)
    started = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if sse:
                # SSE 仅验证握手成功，不等待消息体，避免阻塞。
                raw_bytes = b""
            else:
                raw_bytes = response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            status_code = int(response.status)
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        raw_bytes = exc.read()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        status_code = int(exc.code)
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
    except URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "url": url,
            "status_code": None,
            "duration_ms": round(elapsed_ms, 3),
            "content_type": None,
            "response_size_bytes": 0,
            "json": None,
            "text_preview": None,
            "network_error": str(exc),
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "url": url,
            "status_code": None,
            "duration_ms": round(elapsed_ms, 3),
            "content_type": None,
            "response_size_bytes": 0,
            "json": None,
            "text_preview": None,
            "network_error": str(exc),
        }

    decoded_text = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else ""
    parsed_json = _safe_json_loads(decoded_text) if decoded_text else None

    return {
        "url": url,
        "status_code": status_code,
        "duration_ms": round(elapsed_ms, 3),
        "content_type": content_type,
        "response_size_bytes": len(raw_bytes),
        "json": parsed_json,
        "json_preview": _preview_json(parsed_json) if parsed_json is not None else None,
        "text_preview": _preview_text(decoded_text) if decoded_text else "",
        "network_error": None,
    }


def bootstrap_runtime() -> dict[str, Any]:
    health = call_api("GET", "/health")
    if health.get("status_code") != 200:
        raise RuntimeError(f"Health check failed: {health}")

    buildings = call_api("GET", "/buildings", params={"page": 1, "page_size": 1})
    buildings_json = buildings.get("json") or {}
    first_building = (buildings_json.get("items") or [{}])[0]
    building_id = first_building.get("building_id")
    site_id = first_building.get("site_id")
    if not building_id:
        raise RuntimeError("No building_id available from /buildings")

    meters = call_api("GET", "/meters", params={"building_id": building_id, "page": 1, "page_size": 5})
    meters_json = meters.get("json") or {}
    meter_items = meters_json.get("items") or []
    if not meter_items:
        meters = call_api("GET", "/meters", params={"page": 1, "page_size": 5})
        meters_json = meters.get("json") or {}
        meter_items = meters_json.get("items") or []
    if not meter_items:
        raise RuntimeError("No meter_id available from /meters")

    first_meter = meter_items[0]
    meter_id = first_meter.get("meter_id")
    meter_type = first_meter.get("meter_type") or "electricity"
    if not meter_id:
        raise RuntimeError("No meter_id available in meter item")

    overview = call_api("GET", "/dashboard/overview", params={"chart_range": "week"})
    overview_json = overview.get("json") or {}
    time_range = overview_json.get("time_range") or {}
    start_time = time_range.get("start")
    end_time = time_range.get("end")
    if not start_time or not end_time:
        start_time = "2017-06-23T00:00:00+08:00"
        end_time = "2017-06-29T23:00:00+08:00"

    ai_settings = call_api("GET", "/system/ai-settings")
    ai_settings_payload = ai_settings.get("json") or {}
    ai_settings_update_payload = {
        "llm": ai_settings_payload.get("llm", {}),
        "ragflow": ai_settings_payload.get("ragflow", {}),
        "features": ai_settings_payload.get("features", {}),
    }

    return {
        "building_id": building_id,
        "site_id": site_id,
        "meter_id": meter_id,
        "meter_type": meter_type,
        "start_time": start_time,
        "end_time": end_time,
        "time_range": {"start": start_time, "end": end_time},
        "ai_settings_payload": ai_settings_update_payload,
    }


def build_cases(rt: dict[str, Any]) -> list[Case]:
    building_id = rt["building_id"]
    site_id = rt["site_id"]
    meter_id = rt["meter_id"]
    meter_type = rt["meter_type"]
    start_time = rt["start_time"]
    end_time = rt["end_time"]
    time_range = rt["time_range"]
    ai_settings_payload = rt["ai_settings_payload"]

    def default(case_path: str, *, params: dict[str, Any] | None = None, json_body: Any | None = None, path_params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "path": _resolve_path(case_path, path_params),
            "params": params or {},
            "json_body": json_body,
            "headers": {},
        }

    anomaly_payload = {
        "building_id": building_id,
        "meter": meter_type,
        "time_range": time_range,
        "granularity": "hour",
        "analysis_mode": "offline_event_review",
        "include_weather_context": False,
    }
    ai_analyze_payload = {
        **anomaly_payload,
        "question": "请分析当前建筑能耗异常原因。",
        "include_history_feedback": False,
        "max_candidate_causes": 3,
    }
    ai_ops_context = {
        "building_id": building_id,
        "meter": meter_type,
        "time_range": time_range,
    }
    ai_report_context = {
        "building_id": building_id,
        "meter": meter_type,
        "time_range": time_range,
    }

    return [
        Case("health", "GET /health", "GET", "/health", [200], repeat=3, builder=lambda: default("/health")),
        Case(
            "current_time",
            "POST /system/current-time",
            "POST",
            "/system/current-time",
            [200],
            repeat=3,
            builder=lambda: default("/system/current-time", json_body={"use_current_time": True, "timezone": "Asia/Taipei"}),
        ),
        Case("ai_settings_get", "GET /system/ai-settings", "GET", "/system/ai-settings", [200], repeat=3, builder=lambda: default("/system/ai-settings")),
        Case(
            "ai_settings_put",
            "PUT /system/ai-settings",
            "PUT",
            "/system/ai-settings",
            [200],
            builder=lambda: default("/system/ai-settings", json_body=ai_settings_payload),
            notes="写回当前配置，不变更业务配置。",
        ),
        Case(
            "dataset_anomaly_progress",
            "GET /dataset/anomaly-progress",
            "GET",
            "/dataset/anomaly-progress",
            [200],
            timeout_seconds=8,
            sse=True,
            builder=lambda: default("/dataset/anomaly-progress"),
        ),
        Case(
            "dataset_trigger_detection",
            "POST /dataset/trigger-detection",
            "POST",
            "/dataset/trigger-detection",
            [200],
            builder=lambda: default("/dataset/trigger-detection"),
        ),
        Case(
            "upload_metadata_no_file",
            "POST /dataset/upload/metadata",
            "POST",
            "/dataset/upload/metadata",
            [422],
            builder=lambda: default("/dataset/upload/metadata"),
            notes="为避免清空线上测试数据，本轮仅做缺参校验。",
        ),
        Case(
            "upload_weather_no_file",
            "POST /dataset/upload/weather",
            "POST",
            "/dataset/upload/weather",
            [422],
            builder=lambda: default("/dataset/upload/weather"),
            notes="为避免清空线上测试数据，本轮仅做缺参校验。",
        ),
        Case(
            "upload_raw_no_file",
            "POST /dataset/upload/raw/{meter_type}",
            "POST",
            "/dataset/upload/raw/{meter_type}",
            [422],
            builder=lambda: default("/dataset/upload/raw/{meter_type}", path_params={"meter_type": meter_type}),
            notes="为避免污染表计库，本轮仅做缺参校验。",
        ),
        Case(
            "buildings_list",
            "GET /buildings",
            "GET",
            "/buildings",
            [200],
            repeat=3,
            builder=lambda: default("/buildings", params={"site_id": site_id, "page": 1, "page_size": 20}),
        ),
        Case(
            "building_detail",
            "GET /buildings/{buildingId}",
            "GET",
            "/buildings/{buildingId}",
            [200],
            repeat=3,
            builder=lambda: default("/buildings/{buildingId}", path_params={"buildingId": building_id}),
        ),
        Case(
            "building_energy_summary",
            "GET /buildings/{buildingId}/energy/summary",
            "GET",
            "/buildings/{buildingId}/energy/summary",
            [200],
            repeat=3,
            builder=lambda: default(
                "/buildings/{buildingId}/energy/summary",
                path_params={"buildingId": building_id},
                params={"meter": meter_type, "start_time": start_time, "end_time": end_time, "granularity": "day"},
            ),
        ),
        Case(
            "dashboard_overview",
            "GET /dashboard/overview",
            "GET",
            "/dashboard/overview",
            [200],
            repeat=3,
            builder=lambda: default(
                "/dashboard/overview",
                params={"site_id": site_id, "building_id": building_id, "start_time": start_time, "end_time": end_time, "chart_range": "week"},
            ),
        ),
        Case(
            "dashboard_highlights",
            "GET /dashboard/highlights",
            "GET",
            "/dashboard/highlights",
            [200],
            repeat=3,
            builder=lambda: default(
                "/dashboard/highlights",
                params={"limit": 5, "site_id": site_id, "building_id": building_id, "start_time": start_time, "end_time": end_time, "chart_range": "week"},
            ),
        ),
        Case(
            "meters_list",
            "GET /meters",
            "GET",
            "/meters",
            [200],
            repeat=3,
            builder=lambda: default("/meters", params={"building_id": building_id, "meter_type": meter_type, "page": 1, "page_size": 20}),
        ),
        Case(
            "meter_detail",
            "GET /meters/{meterId}",
            "GET",
            "/meters/{meterId}",
            [200],
            repeat=3,
            builder=lambda: default("/meters/{meterId}", path_params={"meterId": meter_id}),
        ),
        Case(
            "meter_alarms",
            "GET /meters/{meterId}/alarms",
            "GET",
            "/meters/{meterId}/alarms",
            [200],
            repeat=3,
            builder=lambda: default("/meters/{meterId}/alarms", path_params={"meterId": meter_id}, params={"page": 1, "page_size": 20}),
        ),
        Case(
            "meter_maintenance",
            "GET /meters/{meterId}/maintenance-records",
            "GET",
            "/meters/{meterId}/maintenance-records",
            [200],
            repeat=3,
            builder=lambda: default("/meters/{meterId}/maintenance-records", path_params={"meterId": meter_id}, params={"page": 1, "page_size": 20}),
        ),
        Case(
            "energy_query",
            "GET /energy/query",
            "GET",
            "/energy/query",
            [200],
            repeat=3,
            builder=lambda: default(
                "/energy/query",
                params={
                    "site_id": site_id,
                    "meter": meter_type,
                    "start_time": start_time,
                    "end_time": end_time,
                    "granularity": "hour",
                    "aggregation": "sum",
                    "page": 1,
                    "page_size": 100,
                },
            ),
        ),
        Case(
            "energy_trend",
            "GET /energy/trend",
            "GET",
            "/energy/trend",
            [200],
            repeat=3,
            builder=lambda: default(
                "/energy/trend",
                params={"site_id": site_id, "meter": meter_type, "start_time": start_time, "end_time": end_time, "granularity": "day"},
            ),
        ),
        Case(
            "energy_compare",
            "GET /energy/compare",
            "GET",
            "/energy/compare",
            [200],
            repeat=3,
            builder=lambda: default(
                "/energy/compare",
                params={"meter": meter_type, "start_time": start_time, "end_time": end_time, "metric": "sum"},
            ),
        ),
        Case(
            "energy_rankings",
            "GET /energy/rankings",
            "GET",
            "/energy/rankings",
            [200],
            repeat=3,
            builder=lambda: default(
                "/energy/rankings",
                params={"meter": meter_type, "start_time": start_time, "end_time": end_time, "metric": "sum", "order": "desc", "limit": 20},
            ),
        ),
        Case(
            "energy_cop",
            "GET /energy/cop",
            "GET",
            "/energy/cop",
            [200],
            repeat=3,
            builder=lambda: default(
                "/energy/cop",
                params={"building_id": building_id, "start_time": start_time, "end_time": end_time, "granularity": "day"},
            ),
        ),
        Case(
            "energy_weather_correlation",
            "GET /energy/weather-correlation",
            "GET",
            "/energy/weather-correlation",
            [200],
            repeat=3,
            builder=lambda: default(
                "/energy/weather-correlation",
                params={"building_id": building_id, "meter": meter_type, "start_time": start_time, "end_time": end_time},
            ),
        ),
        Case(
            "energy_anomaly_analysis",
            "POST /energy/anomaly-analysis",
            "POST",
            "/energy/anomaly-analysis",
            [200],
            repeat=2,
            builder=lambda: default("/energy/anomaly-analysis", json_body=anomaly_payload),
        ),
        Case(
            "reports_generate",
            "POST /reports/generate",
            "POST",
            "/reports/generate",
            [200],
            builder=lambda: default(
                "/reports/generate",
                json_body={
                    "report_type": "daily_summary",
                    "building_id": building_id,
                    "time_range": time_range,
                    "include_ai_summary": False,
                },
            ),
        ),
        Case(
            "reports_get",
            "GET /reports/{reportId}",
            "GET",
            "/reports/{reportId}",
            [200, 404],
            repeat=2,
            builder=lambda: default("/reports/{reportId}", path_params={"reportId": "{REPORT_ID}"}),
        ),
        Case(
            "reports_get_download",
            "GET /reports/{reportId}",
            "GET",
            "/reports/{reportId}",
            [200, 404],
            builder=lambda: default(
                "/reports/{reportId}",
                path_params={"reportId": "{REPORT_ID}"},
                params={"download": "true", "format": "md"},
            ),
        ),
        Case(
            "reports_delete",
            "DELETE /reports/{reportId}",
            "DELETE",
            "/reports/{reportId}",
            [200, 404],
            builder=lambda: default("/reports/{reportId}", path_params={"reportId": "{REPORT_ID}"}),
        ),
        Case(
            "ai_status",
            "GET /ai/status",
            "GET",
            "/ai/status",
            [200],
            timeout_seconds=8,
            sse=True,
            builder=lambda: default("/ai/status"),
        ),
        Case(
            "ai_analyze_anomaly",
            "POST /ai/analyze-anomaly",
            "POST",
            "/ai/analyze-anomaly",
            [200, 500, 502, 503, 504],
            builder=lambda: default("/ai/analyze-anomaly", json_body=ai_analyze_payload),
        ),
        Case(
            "ai_query_assistant",
            "POST /ai/query-assistant",
            "POST",
            "/ai/query-assistant",
            [200, 500, 502, 503, 504],
            builder=lambda: default("/ai/query-assistant", json_body={"question": "请帮我查询最近一周电耗趋势", "timezone": "Asia/Taipei"}),
        ),
        Case(
            "ai_anomaly_feedback",
            "POST /ai/anomaly-feedback",
            "POST",
            "/ai/anomaly-feedback",
            [200, 500],
            builder=lambda: default(
                "/ai/anomaly-feedback",
                json_body={
                    "analysis_id": "manual-" + uuid.uuid4().hex[:12],
                    "building_id": building_id,
                    "meter": meter_type,
                    "time_range": time_range,
                    "selected_cause_id": "cause-1",
                    "selected_score": 5,
                    "selected_cause_title": "测试反馈",
                    "resolution_status": "open",
                    "comment": "自动化联调测试反馈",
                },
            ),
        ),
        Case(
            "ai_ops_guide",
            "POST /ai/ops-guide",
            "POST",
            "/ai/ops-guide",
            [200, 500, 502, 503, 504],
            builder=lambda: default(
                "/ai/ops-guide",
                json_body={
                    "question": "请给出排查步骤",
                    "guide_mode": "standard_sop",
                    "context": ai_ops_context,
                    "include_knowledge": False,
                    "include_history": False,
                    "include_actions": True,
                },
            ),
        ),
        Case(
            "ai_report_summary",
            "POST /ai/report-summary",
            "POST",
            "/ai/report-summary",
            [200, 500, 502, 503, 504],
            builder=lambda: default(
                "/ai/report-summary",
                json_body={
                    "report_type": "summary_card",
                    "audience": "manager",
                    "context": ai_report_context,
                    "include_anomaly_insight": False,
                    "include_actions": True,
                },
            ),
        ),
        Case(
            "ai_qa",
            "POST /ai/qa",
            "POST",
            "/ai/qa",
            [200, 500, 502, 503, 504],
            builder=lambda: default(
                "/ai/qa",
                json_body={
                    "question": "请总结当前建筑最近一周能耗情况。",
                    "timezone": "Asia/Taipei",
                    "context": ai_report_context,
                },
            ),
        ),
        Case(
            "ai_delete_session",
            "DELETE /ai/qa/sessions/{sessionId}",
            "DELETE",
            "/ai/qa/sessions/{sessionId}",
            [200, 404],
            builder=lambda: default("/ai/qa/sessions/{sessionId}", path_params={"sessionId": "{SESSION_ID}"}),
        ),
    ]


def summarize_results(result_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in result_rows:
        grouped.setdefault(row["operation"], []).append(row)

    summaries: list[dict[str, Any]] = []
    for operation, rows in grouped.items():
        durations = [item["duration_ms"] for item in rows if isinstance(item.get("duration_ms"), (int, float))]
        status_counter = Counter(str(item.get("status_code")) for item in rows)
        summaries.append(
            {
                "operation": operation,
                "calls": len(rows),
                "avg_duration_ms": round(sum(durations) / len(durations), 3) if durations else None,
                "min_duration_ms": round(min(durations), 3) if durations else None,
                "max_duration_ms": round(max(durations), 3) if durations else None,
                "status_counts": dict(status_counter),
                "expected_pass_rate": round(
                    sum(1 for item in rows if item.get("expected_matched")) / len(rows),
                    4,
                ),
            }
        )
    return sorted(summaries, key=lambda item: item["operation"])


def load_openapi_operations() -> list[str]:
    spec = call_api("GET", "/openapi.json")
    if spec.get("status_code") != 200 or not isinstance(spec.get("json"), dict):
        return []
    paths = spec["json"].get("paths", {})
    operations: list[str] = []
    for path, methods in paths.items():
        for method in methods.keys():
            if method.lower().startswith("x-"):
                continue
            operations.append(f"{method.upper()} {path}")
    return sorted(operations)


def run() -> None:
    runtime = bootstrap_runtime()
    openapi_operations = load_openapi_operations()
    cases = build_cases(runtime)

    report_id = "rpt_nonexistent_" + uuid.uuid4().hex[:8]
    qa_session_id = "qa_nonexistent_" + uuid.uuid4().hex[:8]

    raw_results: list[dict[str, Any]] = []
    encoded_report_token = quote("{REPORT_ID}", safe="")
    encoded_session_token = quote("{SESSION_ID}", safe="")

    for case in cases:
        for attempt in range(1, case.repeat + 1):
            built = case.builder()
            path = built["path"]
            params = dict(built.get("params") or {})
            json_body = built.get("json_body")
            headers = dict(built.get("headers") or {})

            path = (
                path.replace("{REPORT_ID}", quote(report_id, safe=""))
                .replace("{SESSION_ID}", quote(qa_session_id, safe=""))
                .replace(encoded_report_token, quote(report_id, safe=""))
                .replace(encoded_session_token, quote(qa_session_id, safe=""))
            )
            params = {
                key: (value.replace("{REPORT_ID}", report_id).replace("{SESSION_ID}", qa_session_id) if isinstance(value, str) else value)
                for key, value in params.items()
            }
            if isinstance(json_body, str):
                json_body = json_body.replace("{REPORT_ID}", report_id).replace("{SESSION_ID}", qa_session_id)

            response = call_api(
                method=case.method,
                path=path,
                params=params,
                json_body=json_body,
                headers=headers,
                timeout_seconds=case.timeout_seconds,
                sse=case.sse,
            )

            expected_matched = response.get("status_code") in case.expected_status
            row = {
                "case_id": case.case_id,
                "operation": case.operation,
                "method": case.method,
                "path": path,
                "attempt": attempt,
                "expected_status": case.expected_status,
                "expected_matched": expected_matched,
                "duration_ms": response.get("duration_ms"),
                "status_code": response.get("status_code"),
                "response_size_bytes": response.get("response_size_bytes"),
                "content_type": response.get("content_type"),
                "network_error": response.get("network_error"),
                "request_params": params,
                "request_json": json_body,
                "response_json_preview": response.get("json_preview"),
                "response_text_preview": response.get("text_preview"),
                "notes": case.notes,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            raw_results.append(row)

            if case.case_id == "reports_generate" and response.get("status_code") == 200:
                payload = response.get("json")
                if isinstance(payload, dict) and payload.get("report_id"):
                    report_id = str(payload["report_id"])
            if case.case_id == "ai_qa" and response.get("status_code") == 200:
                payload = response.get("json")
                if isinstance(payload, dict) and payload.get("session_id"):
                    qa_session_id = str(payload["session_id"])

    operation_summary = summarize_results(raw_results)
    tested_operations = sorted(set(item["operation"] for item in raw_results))
    missing_operations = sorted(set(openapi_operations) - set(tested_operations))

    output_payload = {
        "meta": {
            "base_url": BASE_URL,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "output_path": OUTPUT_PATH,
            "default_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        "bootstrap": runtime,
        "final_runtime_state": {
            "report_id": report_id,
            "qa_session_id": qa_session_id,
        },
        "coverage": {
            "openapi_operation_count": len(openapi_operations),
            "tested_operation_count": len(tested_operations),
            "missing_operations": missing_operations,
        },
        "openapi_operations": openapi_operations,
        "results": raw_results,
        "operation_summary": operation_summary,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(output_payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")

    print(json.dumps({"status": "ok", "output_path": OUTPUT_PATH, "coverage": output_payload["coverage"]}, ensure_ascii=False))


if __name__ == "__main__":
    run()
