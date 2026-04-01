from datetime import datetime
from typing import Any

from ai.mcp.config import ALLOWED_METERS

def _build_tool_result(
    *,
    tool_name: str,
    summary: str,
    highlights: list[str] | None = None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
    request_context: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一 MCP 工具返回结构，便于前端/调用方稳定消费。"""
    return {
        "tool_name": tool_name,
        "summary": summary,
        "highlights": highlights or [],
        "warnings": warnings or [],
        "next_actions": next_actions or [],
        "request_context": request_context or {},
        "data": data or {},
    }

def _clean_none_values(payload: dict[str, Any]) -> dict[str, Any]:
    """剔除值为 None 的键，避免无效参数传给后端。"""
    return {key: value for key, value in payload.items() if value is not None}

def _format_number(value: Any, digits: int = 4) -> str:
    """统一数值展示格式，失败时原样转字符串。"""
    try:
        return str(round(float(value), digits))
    except (TypeError, ValueError):
        return str(value)

def _normalize_datetime_text(value: str) -> str:
    """规范化并校验 ISO8601 时间文本。"""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("时间参数不能为空字符串。")
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    if "T" in cleaned and " " in cleaned.rsplit("T", 1)[-1]:
        date_part, offset_part = cleaned.rsplit(" ", 1)
        cleaned = f"{date_part}+{offset_part}"
    try:
        datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"非法时间格式: {value}。请使用 ISO 8601，例如 2026-03-31T00:00:00+08:00。"
        ) from exc
    return cleaned

def _validate_time_range(start_time: str, end_time: str) -> tuple[str, str]:
    """校验开始/结束时间，确保 start <= end。"""
    normalized_start = _normalize_datetime_text(start_time)
    normalized_end = _normalize_datetime_text(end_time)
    if datetime.fromisoformat(normalized_start) > datetime.fromisoformat(normalized_end):
        raise ValueError("开始时间不能晚于结束时间。")
    return normalized_start, normalized_end

def _validate_meter(meter: str) -> str:
    """校验并标准化表计类型。"""
    normalized_meter = meter.strip().lower()
    if normalized_meter not in ALLOWED_METERS:
        raise ValueError(
            f"非法 meter: {meter}。允许值为: {', '.join(sorted(ALLOWED_METERS))}。"
        )
    return normalized_meter

def _validate_choice(name: str, value: str | None, allowed: set[str]) -> str | None:
    """校验枚举型参数。"""
    if value is None:
        return None
    normalized_value = value.strip().lower()
    if normalized_value not in allowed:
        raise ValueError(
            f"非法 {name}: {value}。允许值为: {', '.join(sorted(allowed))}。"
        )
    return normalized_value

def _validate_positive_int(name: str, value: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    """校验正整数边界。"""
    if value < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}。")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} 不能大于 {maximum}。")
    return value

def _validate_building_ids(
    building_ids: list[str] | None,
    *,
    min_count: int = 1,
    allow_empty: bool = False,
) -> list[str]:
    """校验 building_id 列表，过滤空白并检查最小数量。"""
    normalized_ids = []
    for building_id in building_ids or []:
        normalized = building_id.strip()
        if normalized:
            normalized_ids.append(normalized)
    if allow_empty and not normalized_ids:
        return []
    if len(normalized_ids) < min_count:
        if min_count == 1:
            raise ValueError("building_ids 不能为空，且至少需要一个有效建筑 ID。")
        raise ValueError(f"building_ids 至少需要 {min_count} 个有效建筑 ID。")
    return normalized_ids
