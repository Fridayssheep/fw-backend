from __future__ import annotations

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import app
from app.services_meters import build_meter_status
from app.services_meters import parse_meter_id


BASE_DIR = Path(__file__).resolve().parents[1]
REPORT_JSON_PATH = BASE_DIR / "test" / "meter_api_migration_validation.json"
REPORT_MD_PATH = BASE_DIR / "test" / "meter_api_migration_report.md"
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "15432"))
METER_SCAN_LIMIT = 5


def add_check(
    results: list[dict[str, Any]],
    category: str,
    name: str,
    ok: bool,
    detail: str,
) -> None:
    results.append(
        {
            "category": category,
            "name": name,
            "ok": ok,
            "detail": detail,
        }
    )


def probe_database() -> tuple[bool, str]:
    try:
        with socket.create_connection((DB_HOST, DB_PORT), timeout=2):
            return True, f"{DB_HOST}:{DB_PORT} reachable"
    except OSError as exc:
        return False, f"{DB_HOST}:{DB_PORT} unreachable: {exc}"


def api_get(client: TestClient, path: str, **params: Any):
    filtered_params = {key: value for key, value in params.items() if value is not None}
    return client.get(path, params=filtered_params)


def pick_sample_meter(client: TestClient, items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not items:
        raise RuntimeError("meters list is empty, cannot pick sample meter")

    fallback_item = items[0]
    fallback_detail = api_get(client, f"/meters/{quote(fallback_item['meter_id'], safe='')}").json()
    for item in items[:METER_SCAN_LIMIT]:
        response = api_get(client, f"/meters/{quote(item['meter_id'], safe='')}")
        if response.status_code != 200:
            continue
        detail_body = response.json()
        if detail_body.get("recent_alarms"):
            return item, detail_body
        fallback_item = item
        fallback_detail = detail_body
    return fallback_item, fallback_detail


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Meter API Migration Report")
    lines.append("")
    lines.append(f"- Generated at: `{report['generated_at']}`")
    lines.append(f"- Database probe: `{report['database_probe']['detail']}`")
    if report.get("sample_meter"):
        sample_meter = report["sample_meter"]
        lines.append(f"- Sample meter: `{sample_meter['meter_id']}`")
        lines.append(f"- Sample meter type: `{sample_meter['meter_type']}`")
        lines.append(f"- Sample status: `{sample_meter['status']}`")
        lines.append(f"- Sample recent alarms: `{sample_meter['recent_alarm_count']}`")
        lines.append(f"- Sample maintenance records: `{sample_meter['maintenance_count']}`")
        lines.append(f"- Meters total: `{sample_meter['list_total']}`")
    lines.append("")
    lines.append("## Changes")
    lines.append("")
    for item in report["changes"]:
        lines.append(f"- {item}")
    lines.append("")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report["checks"]:
        grouped.setdefault(item["category"], []).append(item)

    for category in ["contract", "live", "logic"]:
        category_items = grouped.get(category, [])
        if not category_items:
            continue
        lines.append(f"## {category.title()} Checks")
        lines.append("")
        for item in category_items:
            status = "PASS" if item["ok"] else "FAIL"
            lines.append(f"- {item['name']}: `{status}` - {item['detail']}")
        lines.append("")

    passed = sum(1 for item in report["checks"] if item["ok"])
    total = len(report["checks"])
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Passed: `{passed}/{total}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    client = TestClient(app)
    results: list[dict[str, Any]] = []
    database_ok, database_detail = probe_database()

    add_check(results, "live", "Database probe", database_ok, database_detail)

    openapi = client.get("/openapi.json").json()
    meter_paths = sorted([path for path in openapi["paths"].keys() if "meter" in path or "device" in path])
    add_check(
        results,
        "contract",
        "OpenAPI meter paths",
        meter_paths == [
            "/meters",
            "/meters/{meterId}",
            "/meters/{meterId}/alarms",
            "/meters/{meterId}/maintenance-records",
        ],
        f"paths={meter_paths}",
    )

    add_check(
        results,
        "contract",
        "OpenAPI removes legacy device paths",
        "/devices" not in openapi["paths"],
        f"has_devices_path={'/devices' in openapi['paths']}",
    )

    list_params = [item["name"] for item in openapi["paths"]["/meters"]["get"]["parameters"]]
    add_check(
        results,
        "contract",
        "List query params",
        list_params == ["building_id", "meter_type", "status", "page", "page_size"],
        f"params={list_params}",
    )

    maintenance_props = openapi["components"]["schemas"]["MaintenanceRecord"]["properties"].keys()
    add_check(
        results,
        "contract",
        "MaintenanceRecord field rename",
        "meter_id" in maintenance_props and "device_id" not in maintenance_props,
        f"maintenance_props={sorted(maintenance_props)}",
    )

    detail_props = openapi["components"]["schemas"]["MeterDetailResponse"]["properties"].keys()
    add_check(
        results,
        "contract",
        "MeterDetailResponse top-level field",
        "meter" in detail_props and "device" not in detail_props,
        f"detail_props={sorted(detail_props)}",
    )

    status_enum = openapi["components"]["schemas"]["MeterStatus"]["enum"]
    add_check(
        results,
        "contract",
        "Status enum",
        status_enum == ["online", "warning", "fault", "offline"],
        f"enum={status_enum}",
    )

    health_response = api_get(client, "/health")
    health_body = health_response.json()
    add_check(
        results,
        "live",
        "Health endpoint",
        health_response.status_code == 200 and health_body.get("database") == "ok",
        f"status={health_response.status_code}, body={health_body}",
    )

    list_response = api_get(client, "/meters", page=1, page_size=10)
    list_body = list_response.json()
    list_items = list_body.get("items", [])
    add_check(
        results,
        "live",
        "Meters list endpoint",
        list_response.status_code == 200
        and bool(list_items)
        and "meter_id" in list_items[0]
        and "device_id" not in list_items[0],
        f"status={list_response.status_code}, total={list_body.get('pagination', {}).get('total')}, first_item_keys={sorted(list_items[0].keys()) if list_items else []}",
    )

    if not list_items:
        raise RuntimeError("meters list is empty, cannot continue live validation")

    sample_item, detail_body = pick_sample_meter(client, list_items)
    sample_meter_id = sample_item["meter_id"]
    sample_meter_type = sample_item["meter_type"]
    sample_status = sample_item["status"]

    meter_type_response = api_get(client, "/meters", meter_type=sample_meter_type, page=1, page_size=5)
    meter_type_body = meter_type_response.json()
    meter_type_items = meter_type_body.get("items", [])
    add_check(
        results,
        "live",
        "meter_type filter",
        meter_type_response.status_code == 200
        and all(item["meter_type"] == sample_meter_type for item in meter_type_items),
        f"status={meter_type_response.status_code}, returned_types={sorted({item['meter_type'] for item in meter_type_items}) if meter_type_items else []}",
    )

    status_response = api_get(client, "/meters", status=sample_status, page=1, page_size=5)
    status_body = status_response.json()
    status_items = status_body.get("items", [])
    add_check(
        results,
        "live",
        "status filter",
        status_response.status_code == 200
        and all(item["status"] == sample_status for item in status_items),
        f"status={status_response.status_code}, returned_statuses={sorted({item['status'] for item in status_items}) if status_items else []}",
    )

    detail_response = api_get(client, f"/meters/{quote(sample_meter_id, safe='')}")
    add_check(
        results,
        "live",
        "Meter detail endpoint",
        detail_response.status_code == 200
        and detail_body.get("meter", {}).get("meter_id") == sample_meter_id
        and "device" not in detail_body,
        f"status={detail_response.status_code}, top_keys={sorted(detail_body.keys())}, recent_alarms={len(detail_body.get('recent_alarms', []))}",
    )

    alarms_response = api_get(
        client,
        f"/meters/{quote(sample_meter_id, safe='')}/alarms",
        page=1,
        page_size=3,
    )
    alarms_body = alarms_response.json()
    alarm_items = alarms_body.get("items", [])
    alarm_shape_ok = (
        "pagination" in alarms_body
        and "items" in alarms_body
        and (not alarm_items or ("meter_id" in alarm_items[0] and "device_id" not in alarm_items[0]))
    )
    add_check(
        results,
        "live",
        "Meter alarms endpoint",
        alarms_response.status_code == 200 and alarm_shape_ok,
        f"status={alarms_response.status_code}, total={alarms_body.get('pagination', {}).get('total')}, first_alarm_keys={sorted(alarm_items[0].keys()) if alarm_items else []}",
    )

    maintenance_response = api_get(
        client,
        f"/meters/{quote(sample_meter_id, safe='')}/maintenance-records",
        page=1,
        page_size=3,
    )
    maintenance_body = maintenance_response.json()
    maintenance_items = maintenance_body.get("items", [])
    maintenance_shape_ok = (
        "pagination" in maintenance_body
        and "items" in maintenance_body
        and maintenance_items
        and "meter_id" in maintenance_items[0]
        and "device_id" not in maintenance_items[0]
    )
    add_check(
        results,
        "live",
        "Meter maintenance endpoint",
        maintenance_response.status_code == 200 and maintenance_shape_ok,
        f"status={maintenance_response.status_code}, total={maintenance_body.get('pagination', {}).get('total')}, first_record_keys={sorted(maintenance_items[0].keys()) if maintenance_items else []}",
    )

    invalid_status_response = api_get(client, "/meters", status="idle", page=1, page_size=1)
    add_check(
        results,
        "live",
        "Reject legacy idle status",
        invalid_status_response.status_code == 422,
        f"status={invalid_status_response.status_code}, body={invalid_status_response.json()}",
    )

    invalid_meter_id_response = api_get(client, "/meters/not-a-valid-meter-id")
    add_check(
        results,
        "live",
        "Reject invalid meterId format",
        invalid_meter_id_response.status_code == 422,
        f"status={invalid_meter_id_response.status_code}, body={invalid_meter_id_response.json()}",
    )

    missing_meter_response = api_get(client, "/meters/not_exists%3A%3Aelectricity")
    add_check(
        results,
        "live",
        "Missing meter returns 404",
        missing_meter_response.status_code == 404,
        f"status={missing_meter_response.status_code}, body={missing_meter_response.json()}",
    )

    parsed_building_id, parsed_meter_type = parse_meter_id(sample_meter_id)
    add_check(
        results,
        "logic",
        "Meter ID parsing",
        parsed_building_id == sample_item["building_id"] and parsed_meter_type == sample_meter_type,
        f"parsed=({parsed_building_id}, {parsed_meter_type})",
    )

    reference_time = datetime(2026, 4, 1, 12, 0, 0)
    status_matrix = {
        "online": build_meter_status(datetime(2026, 3, 31, 12, 0, 0), reference_time).value,
        "warning": build_meter_status(datetime(2026, 3, 27, 12, 0, 0), reference_time).value,
        "fault": build_meter_status(datetime(2026, 3, 23, 12, 0, 0), reference_time).value,
        "offline": build_meter_status(datetime(2026, 3, 10, 12, 0, 0), reference_time).value,
    }
    add_check(
        results,
        "logic",
        "Status transition logic",
        status_matrix == {
            "online": "online",
            "warning": "warning",
            "fault": "fault",
            "offline": "offline",
        },
        f"status_matrix={status_matrix}",
    )

    report = {
        "generated_at": datetime.now().isoformat(),
        "database_probe": {"ok": database_ok, "detail": database_detail},
        "sample_meter": {
            "meter_id": sample_meter_id,
            "meter_type": sample_meter_type,
            "status": sample_status,
            "recent_alarm_count": len(detail_body.get("recent_alarms", [])),
            "maintenance_count": maintenance_body.get("pagination", {}).get("total"),
            "list_total": list_body.get("pagination", {}).get("total"),
        },
        "changes": [
            "将 `/devices` 资源整体迁移为 `/meters`，包括列表、详情、告警和维护记录四个接口。",
            "将响应模型从 `Device*` 改为 `Meter*`，并把 JSON 字段 `device_id/device_name/device_type` 收敛为 `meter_id/meter_name/meter_type`。",
            "将告警和维护记录中的关联字段统一为 `meter_id`，避免路径是 meter 但返回体仍引用 device。",
            "将列表过滤参数从 `device_type` 更正为 `meter_type`，并把状态逻辑从旧的 `idle` 模型调整为 `online/warning/fault/offline`。",
            "保留了服务层旧的 `get_device_*` 兼容导出，降低内部调用链立即失效的风险。",
        ],
        "checks": results,
    }

    REPORT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_MD_PATH.write_text(render_markdown(report), encoding="utf-8")

    passed = sum(1 for item in results if item["ok"])
    total = len(results)
    print(
        json.dumps(
            {
                "passed": passed,
                "total": total,
                "report_json": str(REPORT_JSON_PATH),
                "report_md": str(REPORT_MD_PATH),
                "sample_meter_id": sample_meter_id,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
