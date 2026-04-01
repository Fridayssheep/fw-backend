from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.database import fetch_all
from app.main import app
from app.service_common import get_latest_timestamp
from app.services_meters import build_meter_status


BASE_DIR = Path(__file__).resolve().parents[1]
DOC_PATH = BASE_DIR / "meters接口详细操作文档.md"
PARAM_JSON_PATH = BASE_DIR / "test" / "meter_api_parameter_values.json"
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "15432")


def format_type(schema_fragment: dict[str, Any]) -> str:
    if "$ref" in schema_fragment:
        return schema_fragment["$ref"].split("/")[-1]
    if "anyOf" in schema_fragment:
        return " | ".join(format_type(item) for item in schema_fragment["anyOf"])
    if schema_fragment.get("type") == "array":
        return f"array<{format_type(schema_fragment.get('items', {}))}>"
    if schema_fragment.get("format"):
        return f"{schema_fragment['type']}({schema_fragment['format']})"
    if "enum" in schema_fragment:
        return "enum[" + ", ".join(str(item) for item in schema_fragment["enum"]) + "]"
    return str(schema_fragment.get("type", "object"))


def render_schema_table(name: str, schema: dict[str, Any], components: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.append(f"### {name}")
    lines.append("")
    description_parts: list[str] = []
    if schema.get("title"):
        description_parts.append(f"title=`{schema['title']}`")
    if "enum" in schema:
        description_parts.append("enum=" + ", ".join(str(item) for item in schema["enum"]))
    if description_parts:
        lines.append("- " + "；".join(description_parts))
        lines.append("")

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    if properties:
        lines.append("| 字段 | 类型 | 必填 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for field_name, field_schema in properties.items():
            desc = []
            if field_name in required:
                desc.append("接口必填")
            if "$ref" in field_schema:
                desc.append(f"引用 `{field_schema['$ref'].split('/')[-1]}`")
            if "enum" in field_schema:
                desc.append("可选值: " + ", ".join(str(item) for item in field_schema["enum"]))
            if field_schema.get("type") == "array" and "$ref" in field_schema.get("items", {}):
                desc.append(f"数组元素引用 `{field_schema['items']['$ref'].split('/')[-1]}`")
            lines.append(
                f"| `{field_name}` | `{format_type(field_schema)}` | `{'是' if field_name in required else '否'}` | {'；'.join(desc) or '-'} |"
            )
        lines.append("")
    else:
        lines.append("- 标量 schema，无对象字段。")
        lines.append("")
    return lines


def pick_sample_meter(client: TestClient, meter_ids: list[str]) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    fallback_meter_id = meter_ids[0]
    fallback_detail = client.get(f"/meters/{quote(fallback_meter_id, safe='')}").json()
    fallback_alarms = client.get(f"/meters/{quote(fallback_meter_id, safe='')}/alarms", params={"page": 1, "page_size": 3}).json()
    fallback_maintenance = client.get(
        f"/meters/{quote(fallback_meter_id, safe='')}/maintenance-records",
        params={"page": 1, "page_size": 3},
    ).json()
    if fallback_alarms.get("items"):
        return fallback_meter_id, fallback_detail, fallback_alarms, fallback_maintenance

    for meter_id in meter_ids[1:20]:
        detail = client.get(f"/meters/{quote(meter_id, safe='')}").json()
        alarms = client.get(f"/meters/{quote(meter_id, safe='')}/alarms", params={"page": 1, "page_size": 3}).json()
        maintenance = client.get(
            f"/meters/{quote(meter_id, safe='')}/maintenance-records",
            params={"page": 1, "page_size": 3},
        ).json()
        if alarms.get("items"):
            return meter_id, detail, alarms, maintenance
    return fallback_meter_id, fallback_detail, fallback_alarms, fallback_maintenance


def main() -> None:
    client = TestClient(app)
    openapi = client.get("/openapi.json").json()
    components = openapi["components"]["schemas"]

    meter_type_rows = fetch_all(
        """
        SELECT meter, COUNT(*) AS reading_count
        FROM meter_readings
        GROUP BY meter
        ORDER BY meter
        """
    )
    building_rows = fetch_all(
        """
        SELECT DISTINCT building_id
        FROM meter_readings
        ORDER BY building_id
        """
    )
    meter_id_rows = fetch_all(
        """
        SELECT building_id || '::' || meter AS meter_id
        FROM meter_readings
        GROUP BY building_id, meter
        ORDER BY building_id, meter
        """
    )
    grouped_rows = fetch_all(
        """
        SELECT building_id, meter, MAX(timestamp) AS last_seen_at
        FROM meter_readings
        GROUP BY building_id, meter
        ORDER BY building_id, meter
        """
    )
    reference_latest = get_latest_timestamp()
    status_counts = Counter(build_meter_status(row["last_seen_at"], reference_latest).value for row in grouped_rows)

    building_ids = [row["building_id"] for row in building_rows]
    meter_ids = [row["meter_id"] for row in meter_id_rows]
    meter_types = [row["meter"] for row in meter_type_rows]

    health_body = client.get("/health").json()
    list_body = client.get("/meters", params={"page": 1, "page_size": 3}).json()
    sample_meter_id, detail_body, alarms_body, maintenance_body = pick_sample_meter(client, meter_ids)

    parameter_values = {
        "generated_at": datetime.now().isoformat(),
        "database_connection": {
            "host": DB_HOST,
            "port": DB_PORT,
            "health": health_body,
        },
        "building_ids": building_ids,
        "meter_types": meter_types,
        "meter_type_reading_counts": {row["meter"]: int(row["reading_count"]) for row in meter_type_rows},
        "status_supported_values": openapi["components"]["schemas"]["MeterStatus"]["enum"],
        "status_current_dataset_counts": dict(status_counts),
        "meter_ids": meter_ids,
    }
    PARAM_JSON_PATH.write_text(json.dumps(parameter_values, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# meters 接口详细操作文档")
    lines.append("")
    lines.append(f"- 生成时间：`{datetime.now().isoformat()}`")
    lines.append(f"- 数据源：Docker PostgreSQL `{DB_HOST}:{DB_PORT}` + 当前 FastAPI OpenAPI")
    lines.append(f"- 数据库健康状态：`{health_body.get('database')}`")
    lines.append(f"- 全量 `building_id` 数量：`{len(building_ids)}`")
    lines.append(f"- 全量 `meter_id` 数量：`{len(meter_ids)}`")
    lines.append(f"- `meter_type` 数量：`{len(meter_types)}`")
    lines.append(f"- 当前全局最新数据时间：`{reference_latest.isoformat()}`")
    lines.append("")
    lines.append("## 1. 范围")
    lines.append("")
    lines.append("本文只覆盖本次 `device -> meter` 迁移后的四个接口：")
    lines.append("")
    lines.append("- `GET /meters`")
    lines.append("- `GET /meters/{meterId}`")
    lines.append("- `GET /meters/{meterId}/alarms`")
    lines.append("- `GET /meters/{meterId}/maintenance-records`")
    lines.append("")
    lines.append("## 2. 通用规则")
    lines.append("")
    lines.append("- `meterId` 规则：`{building_id}::{meter_type}`。")
    lines.append("- 路径里传 `meterId` 时，`::` 需要 URL 编码为 `%3A%3A`。")
    lines.append("- 所有时间字段均为 `date-time`，当前接口返回带 `+08:00` 的台湾时区时间。")
    lines.append("- 分页统一使用 `page` 和 `page_size`，`page >= 1`，`1 <= page_size <= 100`。")
    lines.append("- `status` 不是数据库原生列，而是后端基于每个表计的 `last_seen_at` 相对全局最新时间推导得到。")
    lines.append("")
    lines.append("## 3. 参数合法取值")
    lines.append("")
    lines.append("### 3.1 `building_id`")
    lines.append("")
    lines.append("- 来源：`meter_readings.building_id` 去重后的真实值。")
    lines.append(f"- 总数：`{len(building_ids)}`")
    lines.append(f"- 前 20 个示例：`{', '.join(building_ids[:20])}`")
    lines.append("- 全量合法值见本文附录 A，机器可读版本见 `test/meter_api_parameter_values.json` 的 `building_ids`。")
    lines.append("")
    lines.append("### 3.2 `meter_type`")
    lines.append("")
    lines.append("- 来源：`meter_readings.meter` 去重后的真实值。")
    lines.append(f"- 合法值：`{', '.join(meter_types)}`")
    lines.append("- 各类型读数条数：")
    lines.append("")
    lines.append("| meter_type | reading_count |")
    lines.append("| --- | ---: |")
    for row in meter_type_rows:
        lines.append(f"| `{row['meter']}` | `{int(row['reading_count'])}` |")
    lines.append("")
    lines.append("### 3.3 `status`")
    lines.append("")
    lines.append("- 接口允许值：`online`, `warning`, `fault`, `offline`")
    lines.append("- 当前数据库内容下的实际命中数量：")
    lines.append("")
    lines.append("| status | meter_count |")
    lines.append("| --- | ---: |")
    for status_name in ["online", "warning", "fault", "offline"]:
        lines.append(f"| `{status_name}` | `{status_counts.get(status_name, 0)}` |")
    lines.append("")
    lines.append("### 3.4 `meterId`")
    lines.append("")
    lines.append("- 来源：数据库中真实存在的 `(building_id, meter_type)` 组合。")
    lines.append(f"- 总数：`{len(meter_ids)}`")
    lines.append(f"- 前 20 个示例：`{', '.join(meter_ids[:20])}`")
    lines.append("- 全量合法值见本文附录 B，机器可读版本见 `test/meter_api_parameter_values.json` 的 `meter_ids`。")
    lines.append("")
    lines.append("### 3.5 `page` / `page_size`")
    lines.append("")
    lines.append("- `page`：正整数，最小为 `1`。")
    lines.append("- `page_size`：正整数，最小为 `1`，最大为 `100`。")
    lines.append("- 超出范围时会被 FastAPI / Query 校验拦截。")
    lines.append("")
    lines.append("## 4. 接口说明")
    lines.append("")
    lines.append("### 4.1 `GET /meters`")
    lines.append("")
    lines.append("- 功能：获取表计列表。")
    lines.append("- 当前第一页样例总数：")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(list_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("| 参数 | 位置 | 类型 | 必填 | 合法取值 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append("| `building_id` | query | `string` | 否 | 附录 A 全量列表 | 只接受数据库真实存在的 `building_id`。 |")
    lines.append("| `meter_type` | query | `string` | 否 | " + " / ".join(meter_types) + " | 只接受数据库真实存在的表计类型。 |")
    lines.append("| `status` | query | `enum` | 否 | `online` / `warning` / `fault` / `offline` | 当前数据集命中数量见 3.3。 |")
    lines.append("| `page` | query | `integer` | 否 | `>= 1` | 默认 `1`。 |")
    lines.append("| `page_size` | query | `integer` | 否 | `1..100` | 默认 `20`。 |")
    lines.append("")
    lines.append("- 成功响应 schema：`MeterListResponse`")
    lines.append("- 失败响应：`422`（非法枚举、非法分页参数）")
    lines.append("")
    lines.append("### 4.2 `GET /meters/{meterId}`")
    lines.append("")
    lines.append("- 功能：获取单个表计详情、最近告警和最近指标。")
    lines.append(f"- 当前样例 `meterId`：`{sample_meter_id}`")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(detail_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("| 参数 | 位置 | 类型 | 必填 | 合法取值 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append("| `meterId` | path | `string` | 是 | 附录 B 全量列表 | 必须使用真实存在的 `meter_id`，格式 `{building_id}::{meter_type}`。 |")
    lines.append("")
    lines.append("- 成功响应 schema：`MeterDetailResponse`")
    lines.append("- 失败响应：")
    lines.append("  - `422`：`meterId` 格式非法")
    lines.append("  - `404`：`meterId` 格式合法但数据库不存在")
    lines.append("")
    lines.append("### 4.3 `GET /meters/{meterId}/alarms`")
    lines.append("")
    lines.append("- 功能：获取表计告警记录。")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(alarms_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("| 参数 | 位置 | 类型 | 必填 | 合法取值 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append("| `meterId` | path | `string` | 是 | 附录 B 全量列表 | 同上。 |")
    lines.append("| `page` | query | `integer` | 否 | `>= 1` | 默认 `1`。 |")
    lines.append("| `page_size` | query | `integer` | 否 | `1..100` | 默认 `20`。 |")
    lines.append("")
    lines.append("- 成功响应 schema：`MeterAlarmListResponse`")
    lines.append("- 告警等级合法值：`info` / `warning` / `critical`")
    lines.append("- 告警状态合法值：`open` / `closed`")
    lines.append("")
    lines.append("### 4.4 `GET /meters/{meterId}/maintenance-records`")
    lines.append("")
    lines.append("- 功能：获取表计维护记录。")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(maintenance_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("| 参数 | 位置 | 类型 | 必填 | 合法取值 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append("| `meterId` | path | `string` | 是 | 附录 B 全量列表 | 同上。 |")
    lines.append("| `page` | query | `integer` | 否 | `>= 1` | 默认 `1`。 |")
    lines.append("| `page_size` | query | `integer` | 否 | `1..100` | 默认 `20`。 |")
    lines.append("")
    lines.append("- 成功响应 schema：`MaintenanceRecordListResponse`")
    lines.append("- 失败响应：`422` / `404` 规则与详情接口一致。")
    lines.append("")
    lines.append("## 5. 接口与 schema 对照")
    lines.append("")
    lines.append("| 接口 | 成功响应 schema | 主要嵌套 schema |")
    lines.append("| --- | --- | --- |")
    lines.append("| `GET /meters` | `MeterListResponse` | `Meter`, `Pagination` |")
    lines.append("| `GET /meters/{meterId}` | `MeterDetailResponse` | `Meter`, `MeterAlarm`, `MetricCard` |")
    lines.append("| `GET /meters/{meterId}/alarms` | `MeterAlarmListResponse` | `MeterAlarm`, `Pagination` |")
    lines.append("| `GET /meters/{meterId}/maintenance-records` | `MaintenanceRecordListResponse` | `MaintenanceRecord`, `Pagination` |")
    lines.append("")
    lines.append("## 6. Schema 详解")
    lines.append("")
    for schema_name in [
        "MeterStatus",
        "MeterAlarmLevel",
        "MeterAlarmStatus",
        "Pagination",
        "MetricCard",
        "Meter",
        "MeterListResponse",
        "MeterAlarm",
        "MeterAlarmListResponse",
        "MeterDetailResponse",
        "MaintenanceRecord",
        "MaintenanceRecordListResponse",
        "ErrorResponse",
    ]:
        lines.extend(render_schema_table(schema_name, components[schema_name], components))
    lines.append("## 7. 真实错误响应样例")
    lines.append("")
    invalid_status_body = client.get("/meters", params={"status": "idle", "page": 1, "page_size": 1}).json()
    invalid_meter_id_body = client.get("/meters/not-a-valid-meter-id").json()
    not_found_body = client.get("/meters/not_exists%3A%3Aelectricity").json()
    lines.append("### 7.1 非法 `status=idle`")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(invalid_status_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("### 7.2 非法 `meterId` 格式")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(invalid_meter_id_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("### 7.3 不存在的 `meterId`")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(not_found_body, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 附录 A：`building_id` 全量合法值")
    lines.append("")
    lines.append("```text")
    lines.extend(building_ids)
    lines.append("```")
    lines.append("")
    lines.append("## 附录 B：`meterId` 全量合法值")
    lines.append("")
    lines.append("```text")
    lines.extend(meter_ids)
    lines.append("```")
    lines.append("")

    DOC_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "doc_path": str(DOC_PATH),
                "param_json_path": str(PARAM_JSON_PATH),
                "building_id_count": len(building_ids),
                "meter_id_count": len(meter_ids),
                "meter_type_count": len(meter_types),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
