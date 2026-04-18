from __future__ import annotations  # 启用前向引用语法，避免类型注解顺序限制。

from collections import defaultdict  # 导入默认字典，方便做多表计结果聚合统计。
import json  # 导入 JSON 库，用于报表内容序列化与反序列化。
import uuid  # 导入 UUID 库，用于生成报表 ID。
from datetime import datetime  # 导入日期时间类型，用于时间字段处理。
from threading import Thread  # 导入轻量线程，用于非 FastAPI 调用场景下继续后台生成。
from typing import Any  # 导入任意类型注解，方便描述动态结构。

from ai.backend.report_summary_service import get_report_summary  # 导入 AI 报表总结服务。
from app.core.database import execute_sql  # 导入写库函数，用于持久化报表。
from app.core.database import fetch_all  # 导入多行查询函数，用于查询建筑可用表计列表。
from app.core.database import fetch_one  # 导入单行查询函数，用于查询报表详情。
from app.schemas.schemas_ai import AIReportSummaryAnomalySnapshotInput  # 导入 AI 异常快照输入模型。
from app.schemas.schemas_ai import AIReportSummaryContextInput  # 导入 AI 报表上下文输入模型。
from app.schemas.schemas_ai import AIReportSummaryMetricsSnapshotInput  # 导入 AI 指标快照输入模型。
from app.schemas.schemas_ai import AIReportSummaryRequest  # 导入 AI 报表请求模型。
from app.schemas.schemas_ai import AIReportSummaryTrendInput  # 导入 AI 趋势输入模型。
from app.schemas.schemas_common import TimeRange  # 导入统一时间范围模型。
from app.schemas.schemas_energy import EnergyAnomalyAnalysisRequest  # 导入异常分析请求模型。
from app.schemas.schemas_reports import AIInsight
from app.schemas.schemas_reports import DeleteReportResponse  # 导入报表内 AI 洞察模型。
from app.schemas.schemas_reports import GenerateReportRequest  # 导入创建报表请求模型。
from app.schemas.schemas_reports import GenerateReportResponse  # 导入创建报表响应模型。
from app.schemas.schemas_reports import ReportDetailResponse  # 导入报表详情响应模型。
from app.schemas.schemas_reports import ReportExport  # 导入报表导出描述模型。
from app.schemas.schemas_reports import ReportListItem
from app.schemas.schemas_reports import ReportListResponse
from app.schemas.schemas_reports import ReportSection  # 导入报表分节模型。
from app.schemas.schemas_reports import ReportStatus  # 导入报表状态枚举。
from app.schemas.schemas_common import Pagination
from .service_common import ResourceNotFoundError  # 导入统一 404 异常类型。
from .service_common import build_api_time_range  # 导入时间范围标准化函数。
from .service_common import normalize_meter  # 导入表计标准化函数。
from .service_common import parse_datetime_input  # 导入时间文本解析函数。
from .service_common import require_api_datetime  # 导入必填时间转换函数。
from .service_common import resolve_time_range  # 导入默认时间补齐函数。
from .service_common import to_api_datetime  # 导入时间输出转换函数。
from .services_anomaly import get_energy_anomaly_analysis  # 导入能耗异常分析服务。
from .services_energy import build_summary  # 导入能耗摘要服务函数。
from .services_energy import get_energy_rankings  # 导入排行服务函数。
from .services_energy import get_energy_trend  # 导入趋势服务函数。
from .services_energy import get_energy_weather_correlation  # 导入天气相关性服务函数。


AI_REPORT_TYPE_MAP = {  # 定义“报表类型”到“AI 报表类型”的映射关系。
    "daily_summary": "summary_card",  # 每日报表映射到 AI 摘要卡片类型。
    "weekly_summary": "weekly_summary",  # 周报直接映射到周报类型。
    "monthly_summary": "monthly_summary",  # 月报直接映射到月报类型。
    "custom_summary": "summary_card",  # 自定义时间范围报表复用通用摘要卡片类型。
    "anomaly_report": "anomaly_brief",  # 异常报表映射到异常简报类型。
}  # 结束报表类型映射定义。


SUPPORTED_EXPORT_FORMATS = {"md"}  # 按需求仅支持基础 Markdown 导出。
DEFAULT_REPORT_METER = "electricity"  # 定义报表默认表计类型（与 API 文档一致，不从请求体接收）。
DEFAULT_REPORT_GRANULARITY = "day"  # 定义报表默认粒度（内部固定使用 day）。
DEFAULT_REPORT_RANKING_LIMIT = 10  # 定义报表默认排行条数（内部固定为 Top10）。
REPORT_MULTI_METER_LABEL = "multi_meter"  # 定义多表计报表在响应中的标识。
REPORT_METER_PRIORITY = (  # 定义报表优先展示的表计顺序。
    "electricity",
    "chilledwater",
    "hotwater",
    "steam",
    "gas",
    "water",
    "irrigation",
    "solar",
)


def _build_report_id() -> str:  # 定义生成报表 ID 的函数。
    return f"rpt_{uuid.uuid4().hex[:16]}"  # 返回固定前缀+16位随机串作为报表 ID。


def _sort_report_meters(meters: list[str]) -> list[str]:  # 定义报表表计排序函数。
    cleaned: list[str] = []  # 初始化清洗后表计列表。
    seen: set[str] = set()  # 初始化去重集合。
    for meter in meters:  # 遍历输入表计列表。
        meter_text = str(meter or "").strip()  # 标准化表计文本。
        if not meter_text or meter_text in seen:  # 如果为空或重复，
            continue  # 跳过当前项。
        seen.add(meter_text)  # 记录已出现表计。
        cleaned.append(meter_text)  # 写入清洗后的表计列表。
    priority_map = {name: index for index, name in enumerate(REPORT_METER_PRIORITY)}  # 构造优先级映射字典。
    return sorted(cleaned, key=lambda item: (priority_map.get(item, len(priority_map)), item))  # 按预设优先级排序并返回。


def _list_building_meters(  # 定义查询建筑可用表计列表函数。
    building_id: str,  # 接收建筑编号。
    start_time: datetime,  # 接收查询开始时间。
    end_time: datetime,  # 接收查询结束时间。
) -> list[str]:  # 返回当前建筑在时间范围内可用的表计列表。
    rows = fetch_all(  # 先按当前报表时间范围查询有读数的表计类型。
        """
        SELECT DISTINCT mr.meter
        FROM meter_readings mr
        WHERE mr.building_id = :building_id
          AND mr.timestamp >= :start_time
          AND mr.timestamp <= :end_time
        ORDER BY mr.meter ASC
        """,
        {"building_id": building_id, "start_time": start_time, "end_time": end_time},
    )  # 执行范围内表计查询。
    meters = [str(row.get("meter") or "").strip() for row in rows if str(row.get("meter") or "").strip()]  # 提取非空表计值。
    if meters:  # 如果范围内已查到可用表计，
        return _sort_report_meters(meters)  # 直接返回排序后的结果。
    fallback_rows = fetch_all(  # 如果范围内无数据，则回退到建筑全量历史数据再查一次。
        """
        SELECT DISTINCT mr.meter
        FROM meter_readings mr
        WHERE mr.building_id = :building_id
        ORDER BY mr.meter ASC
        """,
        {"building_id": building_id},
    )  # 执行全量表计查询。
    fallback_meters = [str(row.get("meter") or "").strip() for row in fallback_rows if str(row.get("meter") or "").strip()]  # 提取非空表计值。
    return _sort_report_meters(fallback_meters)  # 返回排序后的兜底表计列表。


def _select_primary_meter(meters: list[str]) -> str:  # 定义选择报表主表计函数。
    ordered_meters = _sort_report_meters(meters)  # 先按优先级排序。
    if ordered_meters:  # 如果存在可用表计，
        return ordered_meters[0]  # 返回优先级最高的表计作为主口径。
    return normalize_meter(DEFAULT_REPORT_METER)  # 如果没有可用表计，回退到默认 electricity。


def _build_download_url(report_id: str, base_url: str | None = None) -> str:  # 定义构造下载地址函数。
    suffix = f"/reports/{report_id}?download=true"  # 统一下载地址后缀，默认导出 md。
    if not base_url:  # 如果没有提供基础地址，
        return suffix  # 就返回相对路径，便于内部调用。
    return f"{base_url.rstrip('/')}{suffix}"  # 否则返回完整绝对 URL。


def _coerce_report_json(raw_value: Any) -> dict[str, Any]:  # 定义把数据库字段转为字典的函数。
    if isinstance(raw_value, dict):  # 如果原始值已经是字典，
        return raw_value  # 就直接返回。
    if isinstance(raw_value, str) and raw_value.strip():  # 如果原始值是非空 JSON 字符串，
        try:  # 尝试解析 JSON。
            parsed = json.loads(raw_value)  # 执行 JSON 反序列化。
            if isinstance(parsed, dict):  # 如果解析结果是字典，
                return parsed  # 就返回解析结果。
        except ValueError:  # 如果 JSON 解析失败，
            return {}  # 返回空字典作为兜底。
    return {}  # 其余情况统一返回空字典。


def _to_optional_float(value: Any) -> float | None:  # 定义安全浮点转换函数。
    if value is None:  # 如果值为空，
        return None  # 返回空。
    try:  # 尝试做浮点转换。
        return float(value)  # 转换成功直接返回。
    except (TypeError, ValueError):  # 如果无法转换，
        return None  # 返回空避免类型错误。


def _to_optional_datetime(value: Any) -> datetime | None:  # 定义安全时间转换函数。
    if isinstance(value, datetime):  # 如果已经是 datetime，
        return value  # 直接返回原值。
    if isinstance(value, str):  # 如果是字符串，
        return parse_datetime_input(value)  # 复用统一解析器转换。
    return None  # 其他类型统一返回空。


def _determine_trend_direction_and_rate(trend_payload: dict[str, Any]) -> tuple[str | None, float | None]:  # 定义趋势方向估算函数。
    series = trend_payload.get("series", [])  # 读取趋势序列列表。
    if not series:  # 如果没有序列数据，
        return None, None  # 返回空趋势信息。
    first_series = series[0] if isinstance(series[0], dict) else {}  # 取第一条序列作为估算基准。
    points = first_series.get("points", [])  # 读取该序列点位列表。
    if len(points) < 2:  # 如果点位不足两个，
        return None, None  # 无法计算变化率，返回空。
    first_value = float((points[0] or {}).get("value") or 0)  # 读取首点数值。
    last_value = float((points[-1] or {}).get("value") or 0)  # 读取末点数值。
    if first_value == 0:  # 如果首点为 0，
        return None, None  # 避免除零，返回空。
    change_rate = round((last_value - first_value) / abs(first_value), 4)  # 计算相对变化率。
    if change_rate > 0.03:  # 如果增长超过阈值，
        return "up", change_rate  # 判定为上升。
    if change_rate < -0.03:  # 如果下降超过阈值，
        return "down", change_rate  # 判定为下降。
    return "flat", change_rate  # 否则判定为持平。


def _build_ai_report_request(  # 定义构造 AI 报表请求函数。
    payload: GenerateReportRequest,  # 接收原始报表请求。
    ai_context_building_id: str,  # 接收用于 AI 总结的报表范围标识。
    meter: str,  # 接收标准化表计类型。
    report_time_range: TimeRange,  # 接收标准化时间范围。
    summary_payload: dict[str, Any],  # 接收摘要数据（python 模式，保留 datetime）。
    trend_payload: dict[str, Any],  # 接收趋势数据（json 模式）。
    anomaly_payload: dict[str, Any] | None,  # 接收异常分析数据（可选）。
    include_anomaly_insight: bool,  # 是否要求 AI 在总结时纳入异常洞察。
) -> AIReportSummaryRequest:  # 返回 AI 报表请求对象。
    trend_direction, trend_change_rate = _determine_trend_direction_and_rate(trend_payload)  # 先估算趋势方向和变化率。
    anomaly_snapshot = None  # 先初始化异常快照为空。
    if anomaly_payload:  # 如果有异常数据，
        anomaly_snapshot = AIReportSummaryAnomalySnapshotInput(  # 构造异常快照对象。
            summary=anomaly_payload.get("summary"),  # 写入异常摘要。
            analysis_mode=anomaly_payload.get("analysis_mode"),  # 写入分析模式。
            event_count=anomaly_payload.get("event_count"),  # 写入异常事件数量。
            detector_breakdown=anomaly_payload.get("detector_breakdown") or [],  # 写入检测器分布。
        )  # 完成异常快照构造。
    return AIReportSummaryRequest(  # 构造 AI 报表请求对象。
        report_type=AI_REPORT_TYPE_MAP.get(payload.report_type.value, "summary_card"),  # 传入映射后的 AI 报表类型。
        audience="manager",  # 固定受众为管理者视角。
        include_anomaly_insight=include_anomaly_insight,  # 按当前报表口径决定是否要求异常洞察。
        include_actions=False,  # 当前报表接口不返回动作建议按钮。
        context=AIReportSummaryContextInput(  # 构造 AI 上下文。
            building_id=ai_context_building_id,  # 写入报表范围标识。
            meter=meter,  # 写入表计类型。
            time_range=report_time_range,  # 写入时间范围。
            metrics_snapshot=AIReportSummaryMetricsSnapshotInput(  # 构造指标快照。
                total=_to_optional_float(summary_payload.get("total")),  # 写入总量。
                average=_to_optional_float(summary_payload.get("average")),  # 写入均值。
                peak=_to_optional_float(summary_payload.get("peak")),  # 写入峰值。
                peak_time=_to_optional_datetime(summary_payload.get("peak_time")),  # 写入峰值时间。
                unit=str(summary_payload.get("unit") or "") or None,  # 写入单位。
            ),  # 完成指标快照构造。
            trend_summary=AIReportSummaryTrendInput(  # 构造趋势快照。
                direction=trend_direction,  # 写入趋势方向。
                change_rate=trend_change_rate,  # 写入趋势变化率。
            ),  # 完成趋势快照构造。
            anomaly_summary=anomaly_snapshot,  # 写入异常快照（可空）。
        ),  # 完成 AI 上下文构造。
    )  # 完成 AI 报表请求对象构造。


def _build_rule_summary(  # 定义规则摘要函数，用于 AI 关闭或降级时兜底。
    report_type: str,  # 接收报表类型文本。
    summary_payload: dict[str, Any],  # 接收摘要数据。
    ranking_payload: list[dict[str, Any]],  # 接收排行条目列表。
    anomaly_payload: dict[str, Any] | None,  # 接收异常数据（可选）。
) -> str:  # 返回规则摘要文本。
    unit = summary_payload.get("unit") or ""  # 读取单位文本。
    total = summary_payload.get("total", 0)  # 读取总量值。
    average = summary_payload.get("average", 0)  # 读取均值。
    peak = summary_payload.get("peak", 0)  # 读取峰值。
    top_text = ""  # 先初始化排行摘要为空。
    if ranking_payload:  # 如果存在排行数据，
        top_item = ranking_payload[0]  # 取第一名作为摘要重点。
        top_text = f"，同口径排行首位建筑为 {top_item.get('building_id')}（{top_item.get('value')} {top_item.get('unit') or ''}）"  # 生成排行文本。
    anomaly_text = ""  # 先初始化异常摘要为空。
    if anomaly_payload:  # 如果存在异常分析结果，
        anomaly_text = f"，异常分析结论：{anomaly_payload.get('summary')}"  # 拼接异常摘要文本。
    return (  # 返回最终规则摘要。
        f"{report_type} 已生成：总量 {total}{unit}，均值 {average}{unit}，峰值 {peak}{unit}"  # 主摘要部分。
        f"{top_text}{anomaly_text}。"  # 附加排行与异常信息。
    )  # 完成规则摘要生成。


def _to_chart_number(value: Any) -> float | None:  # 定义图表数值安全转换函数。
    if value is None:  # 如果值为空，
        return None  # 返回空值。
    try:  # 尝试做浮点转换。
        return float(value)  # 转换成功则返回浮点值。
    except (TypeError, ValueError):  # 如果转换失败，
        return None  # 返回空值避免图表渲染报错。


def _format_chart_number(value: float) -> str:  # 定义图表数值格式化函数。
    text = f"{value:.4f}"  # 先按 4 位小数格式化。
    return text.rstrip("0").rstrip(".") or "0"  # 再去掉冗余尾零，保证可读性。


def _sanitize_mermaid_label(value: Any, max_length: int = 14) -> str:  # 定义 Mermaid 标签清洗函数。
    text = str(value or "").strip()  # 先把值转为文本并去空白。
    text = text.replace('"', "'").replace("\r", " ").replace("\n", " ")  # 清洗可能破坏语法的字符。
    if len(text) > max_length:  # 如果标签过长，
        text = f"{text[: max_length - 1]}…"  # 截断并追加省略号。
    return text or "N/A"  # 返回清洗后的标签（空值回退 N/A）。


def _calc_axis_bounds(values: list[float]) -> tuple[float, float]:  # 定义 y 轴范围计算函数。
    if not values:  # 如果没有有效数据，
        return 0.0, 1.0  # 返回默认范围，避免空图报错。
    min_value = min(values)  # 计算最小值。
    max_value = max(values)  # 计算最大值。
    lower = min(min_value, 0.0)  # 让下界至少覆盖 0（兼容负值）。
    upper = max(max_value, 0.0)  # 让上界至少覆盖 0。
    if lower == upper:  # 如果上下界相同，
        upper = lower + 1.0  # 适度扩展上界，保证坐标轴有效。
    return lower, upper  # 返回坐标轴范围。


def _build_xychart_block(  # 定义 Mermaid xychart 代码块构造函数。
    title: str,  # 接收图表标题。
    y_axis_label: str,  # 接收 y 轴标签。
    x_labels: list[str],  # 接收 x 轴标签列表。
    values: list[float],  # 接收图表数值列表。
    chart_kind: str = "bar",  # 接收图表类型（bar/line）。
) -> list[str]:  # 返回 Markdown 行列表。
    if not x_labels or not values or len(x_labels) != len(values):  # 如果标签和值无效，
        return []  # 返回空列表表示不生成图表。
    lower, upper = _calc_axis_bounds(values)  # 计算 y 轴范围。
    x_axis_text = ", ".join(f'"{_sanitize_mermaid_label(item)}"' for item in x_labels)  # 构造 x 轴标签文本。
    value_text = ", ".join(_format_chart_number(item) for item in values)  # 构造数值序列文本。
    return [  # 返回完整 Mermaid 图表代码块。
        "```mermaid",  # 代码块起始标记。
        "xychart-beta",  # 指定 Mermaid xychart 图类型。
        f'    title "{title}"',  # 写入图表标题。
        f"    x-axis [{x_axis_text}]",  # 写入 x 轴标签列表。
        f'    y-axis "{y_axis_label}" {_format_chart_number(lower)} --> {_format_chart_number(upper)}',  # 写入 y 轴范围。
        f"    {chart_kind} [{value_text}]",  # 写入图表数据序列。
        "```",  # 代码块结束标记。
        "",  # 图后追加空行。
    ]  # 结束图表代码块返回。


def _extract_section_map(report_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:  # 定义分节映射提取函数。
    section_map: dict[str, dict[str, Any]] = {}  # 初始化空分节映射。
    sections = report_payload.get("sections") or []  # 读取报表分节列表。
    for section in sections:  # 遍历每个分节。
        if not isinstance(section, dict):  # 如果当前分节不是字典，
            continue  # 跳过非法项。
        key = str(section.get("key") or "").strip()  # 读取并标准化分节键。
        data = section.get("data")  # 读取分节数据。
        if key and isinstance(data, dict):  # 如果键和值都合法，
            section_map[key] = data  # 写入映射字典。
    return section_map  # 返回分节映射。


def _build_markdown_export(report_payload: dict[str, Any]) -> str:  # 定义 Markdown 导出内容生成函数（人类可读版）。
    time_range = report_payload.get("time_range") or {}  # 读取报表时间范围。
    section_map = _extract_section_map(report_payload)  # 提取分节键到数据的映射关系。
    summary_data = section_map.get("energy_summary") or {}  # 读取能耗总览分节数据。
    trend_data = section_map.get("energy_trend") or {}  # 读取能耗趋势分节数据。
    ranking_data = section_map.get("energy_rankings") or {}  # 读取能耗排行分节数据。
    anomaly_data = section_map.get("anomaly_analysis") or {}  # 读取异常分析分节数据。
    weather_data = section_map.get("weather_correlation") or {}  # 读取天气相关性分节数据。
    lines = [  # 初始化 Markdown 文本行列表。
        f"# 报表 {report_payload.get('report_id')}",  # 写入报表标题。
        "",  # 空行分隔。
        f"- 类型: {report_payload.get('report_type')}",  # 写入报表类型。
        f"- 状态: {report_payload.get('status')}",  # 写入报表状态。
        f"- 建筑: {report_payload.get('building_id') or 'ALL'}",  # 写入建筑范围。
        f"- 表计: {report_payload.get('meter')}",  # 写入表计类型。
        f"- 时间范围: {time_range.get('start')} ~ {time_range.get('end')}",  # 写入时间范围。
        "",  # 空行分隔。
        "## 管理摘要",  # 写入摘要章节标题。
        report_payload.get("summary") or "本报表暂无摘要。",  # 写入摘要正文。
        "",  # 空行分隔。
    ]  # 完成头部内容构造。

    unit_text = str(summary_data.get("unit") or "")  # 读取单位文本。
    total_value = _to_chart_number(summary_data.get("total"))  # 读取总量并转换为数值。
    average_value = _to_chart_number(summary_data.get("average"))  # 读取均值并转换为数值。
    peak_value = _to_chart_number(summary_data.get("peak"))  # 读取峰值并转换为数值。
    peak_time = summary_data.get("peak_time")  # 读取峰值时间文本。
    lines.extend(  # 追加能耗总览的文字表格。
        [
            "## 能耗总览",  # 写入能耗总览标题。
            "| 指标 | 数值 |",  # 写入表头。
            "| --- | --- |",  # 写入表格分隔线。
            f"| 总量 | {summary_data.get('total', 'N/A')} {unit_text} |",  # 写入总量行。
            f"| 均值 | {summary_data.get('average', 'N/A')} {unit_text} |",  # 写入均值行。
            f"| 峰值 | {summary_data.get('peak', 'N/A')} {unit_text} |",  # 写入峰值行。
            f"| 峰值时间 | {peak_time or 'N/A'} |",  # 写入峰值时间行。
            "",  # 空行分隔。
        ]
    )  # 完成总览表格追加。
    summary_by_meter = summary_data.get("by_meter") or []  # 读取分表计摘要列表。
    summary_meter_rows = [item for item in summary_by_meter if isinstance(item, dict)]  # 过滤合法分表计摘要。
    if len(summary_meter_rows) > 1:  # 如果存在多表计摘要，
        lines.append("### 分表计摘要")  # 写入分表计摘要子标题。
        lines.append("| 表计 | 总量 | 均值 | 峰值 | 峰值时间 |")  # 写入分表计摘要表头。
        lines.append("| --- | --- | --- | --- | --- |")  # 写入分表计摘要分隔线。
        for item in summary_meter_rows:  # 遍历每个表计摘要。
            current_meter = item.get("meter") or "N/A"  # 读取表计名称。
            current_unit = str(item.get("unit") or "")  # 读取表计单位。
            lines.append(  # 写入分表计摘要行。
                f"| {current_meter} | {item.get('total', 'N/A')} {current_unit} | {item.get('average', 'N/A')} {current_unit} | "
                f"{item.get('peak', 'N/A')} {current_unit} | {item.get('peak_time') or 'N/A'} |"
            )
        lines.append("")  # 追加空行。
    metric_values = [item for item in [total_value, average_value, peak_value] if item is not None]  # 过滤出有效指标值。
    if len(metric_values) == 3:  # 如果三项指标都有效，
        lines.extend(  # 追加指标柱状图。
            _build_xychart_block(
                title="能耗指标对比",  # 图表标题。
                y_axis_label=f"数值({unit_text or 'unit'})",  # y 轴标签。
                x_labels=["总量", "均值", "峰值"],  # x 轴标签。
                values=[total_value or 0.0, average_value or 0.0, peak_value or 0.0],  # 图表数据。
                chart_kind="bar",  # 使用柱状图呈现。
            )
        )  # 完成指标图追加。

    lines.append("## 能耗趋势")  # 写入能耗趋势标题。
    trend_series = trend_data.get("series") or []  # 读取趋势序列列表。
    trend_rows = [item for item in trend_series if isinstance(item, dict)]  # 过滤合法趋势序列。
    trend_meter_values = _sort_report_meters([str(item.get("meter") or "").strip() for item in trend_rows if str(item.get("meter") or "").strip()])  # 提取并排序趋势覆盖表计。
    if trend_meter_values:  # 如果趋势包含表计信息，
        lines.append(f"- 覆盖表计: {', '.join(trend_meter_values)}")  # 输出覆盖表计提示。
        lines.append("")  # 追加空行。
    trend_points = []  # 初始化趋势点位列表。
    preferred_meter = str(report_payload.get("meter") or "").strip()  # 读取当前报表主表计。
    selected_series = None  # 初始化被选中的趋势序列为空。
    for item in trend_rows:  # 先尝试命中主表计序列。
        if (item.get("meter") or "").strip() == preferred_meter:  # 如果命中主表计，
            selected_series = item  # 记录主表计序列。
            break  # 结束查找。
    if selected_series is None and trend_rows:  # 如果未命中主表计但存在序列，
        selected_series = trend_rows[0]  # 回退到第一条序列。
    if selected_series is not None:  # 如果找到可用序列，
        trend_points = selected_series.get("points") or []  # 读取序列点位。
    valid_trend_points = [point for point in trend_points if isinstance(point, dict)]  # 过滤出合法点位对象。
    if len(valid_trend_points) > 16:  # 如果点位过多不利于阅读，
        step = max(len(valid_trend_points) // 16, 1)  # 计算抽样步长。
        valid_trend_points = valid_trend_points[::step]  # 按步长抽样减少点数。
        if valid_trend_points[-1] is not trend_points[-1]:  # 如果抽样后丢了最后一个点，
            valid_trend_points.append(trend_points[-1])  # 追加最后一个点保证趋势完整。
    trend_labels: list[str] = []  # 初始化趋势图 x 轴标签列表。
    trend_values: list[float] = []  # 初始化趋势图 y 轴值列表。
    for point in valid_trend_points:  # 遍历趋势点位。
        value = _to_chart_number(point.get("value"))  # 读取并转换点位值。
        if value is None:  # 如果当前值无效，
            continue  # 跳过该点位。
        raw_time = point.get("timestamp") or point.get("time")  # 读取时间标签字段。
        trend_labels.append(_sanitize_mermaid_label(str(raw_time)[:10], max_length=10))  # 追加格式化时间标签。
        trend_values.append(value)  # 追加趋势值。
    if trend_labels and trend_values:  # 如果存在可绘制趋势数据，
        lines.extend(  # 追加趋势折线图。
            _build_xychart_block(
                title="能耗趋势线",  # 图表标题。
                y_axis_label=f"数值({unit_text or 'unit'})",  # y 轴标签。
                x_labels=trend_labels,  # x 轴标签序列。
                values=trend_values,  # y 轴数值序列。
                chart_kind="line",  # 使用折线图表现趋势。
            )
        )  # 完成趋势图追加。
    else:  # 如果趋势数据不足，
        lines.extend(["趋势数据不足，无法绘图。", ""])  # 输出文字提示。

    lines.append("## 建筑能耗排行")  # 写入能耗排行标题。
    ranking_items = ranking_data.get("items") or []  # 读取排行条目列表。
    ranking_rows = [item for item in ranking_items if isinstance(item, dict)]  # 过滤合法排行条目。
    ranking_meter_values = _sort_report_meters([str(item.get("meter") or "").strip() for item in ranking_rows if str(item.get("meter") or "").strip()])  # 提取并排序排行覆盖表计。
    include_meter_column = len(ranking_meter_values) > 1  # 如果排行包含多个表计，则展示表计列。
    if ranking_rows:  # 如果排行数据存在，
        if include_meter_column:  # 如果需要展示表计列，
            lines.append("| 排名 | 表计 | 建筑 | 数值 |")  # 写入多表计排行表头。
            lines.append("| --- | --- | --- | --- |")  # 写入多表计排行分隔线。
        else:  # 如果只包含单表计，
            lines.append("| 排名 | 建筑 | 数值 |")  # 写入单表计排行表头。
            lines.append("| --- | --- | --- |")  # 写入单表计排行分隔线。
        for item in ranking_rows[:10]:  # 遍历前 10 条排行数据。
            if include_meter_column:  # 如果是多表计排行，
                lines.append(  # 写入多表计排行行。
                    f"| {item.get('rank', '-')} | {item.get('meter') or '-'} | {item.get('building_id', '-')} | "
                    f"{item.get('value', '-')} {item.get('unit') or ''} |"
                )
            else:  # 如果是单表计排行，
                lines.append(f"| {item.get('rank', '-')} | {item.get('building_id', '-')} | {item.get('value', '-')} {item.get('unit') or ''} |")  # 写入排行行。
        lines.append("")  # 追加空行分隔。
        chart_rows = ranking_rows  # 初始化用于绘图的排行行列表。
        if include_meter_column:  # 如果是多表计排行，
            chart_rows = [item for item in ranking_rows if (item.get("meter") or "").strip() == preferred_meter]  # 优先只绘制主表计排行。
            if not chart_rows:  # 如果主表计没有排行数据，
                chart_rows = ranking_rows  # 回退使用原始排行数据绘图。
        ranking_labels: list[str] = []  # 初始化排行图标签列表。
        ranking_values: list[float] = []  # 初始化排行图数值列表。
        for item in chart_rows[:10]:  # 再遍历前 10 条用于画图。
            value = _to_chart_number(item.get("value"))  # 读取并转换排行值。
            if value is None:  # 如果值无效，
                continue  # 跳过该条目。
            label_text = item.get("building_id")  # 读取建筑标签文本。
            if include_meter_column:  # 如果需要区分表计，
                label_text = f"{item.get('building_id')}({item.get('meter')})"  # 把表计拼到标签里。
            ranking_labels.append(_sanitize_mermaid_label(label_text, max_length=12))  # 追加建筑标签。
            ranking_values.append(value)  # 追加排行值。
        if ranking_labels and ranking_values:  # 如果存在可绘制排行数据，
            lines.extend(  # 追加排行柱状图。
                _build_xychart_block(
                    title="Top 建筑能耗排行",  # 图表标题。
                    y_axis_label=f"数值({unit_text or 'unit'})",  # y 轴标签。
                    x_labels=ranking_labels,  # x 轴建筑标签。
                    values=ranking_values,  # y 轴能耗值。
                    chart_kind="bar",  # 使用柱状图展示排行。
                )
            )  # 完成排行图追加。
    else:  # 如果没有排行数据，
        lines.extend(["当前条件下无排行数据。", ""])  # 输出提示文本。

    if anomaly_data:  # 如果存在异常分析数据，
        lines.append("## 异常分析")  # 写入异常分析标题。
        lines.append(f"- 异常结论: {anomaly_data.get('summary') or '暂无'}")  # 写入异常摘要。
        lines.append(f"- 异常事件数: {anomaly_data.get('event_count', 0)}")  # 写入异常事件数量。
        lines.append("")  # 追加空行。
        detector_items = anomaly_data.get("detector_breakdown") or []  # 读取检测器分布列表。
        detector_rows = [item for item in detector_items if isinstance(item, dict) and _to_chart_number(item.get("count")) is not None]  # 过滤合法检测器数据。
        if detector_rows:  # 如果检测器数据存在，
            lines.append("```mermaid")  # 写入 Mermaid 代码块开始。
            lines.append("pie showData")  # 指定饼图并显示数值。
            lines.append("    title 异常来源分布")  # 写入饼图标题。
            for item in detector_rows:  # 遍历检测器数据。
                label = _sanitize_mermaid_label(f"{item.get('detected_by')}:{item.get('event_type')}", max_length=20)  # 构造分布标签。
                count_value = _to_chart_number(item.get("count")) or 0.0  # 读取并转换计数值。
                lines.append(f'    "{label}" : {_format_chart_number(count_value)}')  # 写入饼图切片数据。
            lines.append("```")  # 写入 Mermaid 代码块结束。
            lines.append("")  # 追加空行。
        anomaly_by_meter = anomaly_data.get("by_meter") or []  # 读取分表计异常分析结果。
        anomaly_meter_rows = [item for item in anomaly_by_meter if isinstance(item, dict)]  # 过滤合法分表计异常结果。
        if len(anomaly_meter_rows) > 1:  # 如果异常分析覆盖多个表计，
            lines.append("### 分表计异常概览")  # 写入分表计异常子标题。
            lines.append("| 表计 | 异常事件数 | 异常结论 |")  # 写入分表计异常表头。
            lines.append("| --- | --- | --- |")  # 写入分表计异常分隔线。
            for item in anomaly_meter_rows:  # 遍历每个表计异常结果。
                lines.append(f"| {item.get('meter') or 'N/A'} | {item.get('event_count', 0)} | {item.get('summary') or '暂无'} |")  # 写入分表计异常行。
            lines.append("")  # 追加空行。

    if weather_data:  # 如果存在天气相关性数据，
        lines.append("## 天气相关性")  # 写入天气相关性标题。
        lines.append(f"- 相关系数: {weather_data.get('correlation_coefficient', 'N/A')}")  # 写入整体相关系数。
        factors = weather_data.get("factors") or []  # 读取因子列表。
        factor_rows = [item for item in factors if isinstance(item, dict) and _to_chart_number(item.get("coefficient")) is not None]  # 过滤合法因子项。
        if factor_rows:  # 如果天气因子存在，
            factor_labels = [_sanitize_mermaid_label(item.get("name"), max_length=12) for item in factor_rows]  # 生成因子标签列表。
            factor_values = [_to_chart_number(item.get("coefficient")) or 0.0 for item in factor_rows]  # 生成系数值列表。
            lines.append("")  # 追加空行。
            lines.extend(  # 追加天气相关性柱状图。
                _build_xychart_block(
                    title="天气因子相关性",  # 图表标题。
                    y_axis_label="相关系数",  # y 轴标签。
                    x_labels=factor_labels,  # x 轴因子标签。
                    values=factor_values,  # y 轴系数值。
                    chart_kind="bar",  # 使用柱状图展示因子系数。
                )
            )  # 完成天气图追加。
        weather_by_meter = weather_data.get("by_meter") or []  # 读取分表计天气相关性结果。
        weather_meter_rows = [item for item in weather_by_meter if isinstance(item, dict)]  # 过滤合法分表计天气结果。
        if len(weather_meter_rows) > 1:  # 如果天气相关性覆盖多个表计，
            lines.append("### 分表计天气相关性")  # 写入分表计天气相关性子标题。
            lines.append("| 表计 | 相关系数 |")  # 写入分表计天气相关性表头。
            lines.append("| --- | --- |")  # 写入分表计天气相关性分隔线。
            for item in weather_meter_rows:  # 遍历分表计天气结果。
                lines.append(f"| {item.get('meter') or 'N/A'} | {item.get('correlation_coefficient', 'N/A')} |")  # 写入分表计天气行。
            lines.append("")  # 追加空行。

    ai_insight = report_payload.get("ai_insight")  # 读取 AI 洞察数据。
    if isinstance(ai_insight, dict):  # 如果存在 AI 洞察，
        lines.append("## AI 分析总结")  # 写入 AI 总结标题。
        lines.append(ai_insight.get("summary") or "AI 未返回摘要。")  # 写入 AI 摘要正文。
        lines.append("")  # 追加空行。
        highlights = ai_insight.get("highlights") or []  # 读取亮点列表。
        if highlights:  # 如果存在亮点，
            lines.append("### 亮点")  # 写入亮点子标题。
            for item in highlights:  # 遍历亮点列表。
                lines.append(f"- {item}")  # 写入亮点条目。
            lines.append("")  # 追加空行。
        risks = ai_insight.get("risks") or []  # 读取风险列表。
        if risks:  # 如果存在风险提示，
            lines.append("### 风险提示")  # 写入风险子标题。
            for item in risks:  # 遍历风险列表。
                lines.append(f"- {item}")  # 写入风险条目。
            lines.append("")  # 追加空行。
        suggestions = ai_insight.get("suggestions") or []  # 读取建议列表。
        if suggestions:  # 如果存在建议，
            lines.append("### 建议动作")  # 写入建议子标题。
            for item in suggestions:  # 遍历建议列表。
                lines.append(f"- {item}")  # 写入建议条目。
            lines.append("")  # 追加空行。

    return "\n".join(lines).strip() + "\n"  # 返回最终 Markdown 文本。


def _build_section_payloads(  # 定义构造报表分节函数。
    report_time_range: TimeRange,  # 接收标准化时间范围。
    summary_payload: dict[str, Any],  # 接收摘要数据。
    trend_payload: dict[str, Any],  # 接收趋势数据。
    ranking_payload: dict[str, Any],  # 接收排行数据。
    anomaly_payload: dict[str, Any] | None,  # 接收异常数据（可选）。
    weather_payload: dict[str, Any] | None,  # 接收天气相关性数据（可选）。
) -> list[ReportSection]:  # 返回报表分节列表。
    sections: list[ReportSection] = [  # 初始化固定分节列表。
        ReportSection(  # 第 1 节：能耗总览。
            key="energy_summary",  # 分节键。
            title="能耗总览",  # 分节标题。
            data=summary_payload,  # 分节数据。
        ),  # 完成第 1 节创建。
        ReportSection(  # 第 2 节：能耗趋势。
            key="energy_trend",  # 分节键。
            title="能耗趋势",  # 分节标题。
            data={  # 分节数据对象。
                "time_range": report_time_range.model_dump(mode="json"),  # 写入时间范围。
                "series": trend_payload.get("series", []),  # 写入趋势序列。
            },  # 完成趋势节数据构造。
        ),  # 完成第 2 节创建。
        ReportSection(  # 第 3 节：能耗排行。
            key="energy_rankings",  # 分节键。
            title="建筑能耗排行",  # 分节标题。
            data=ranking_payload,  # 分节数据。
        ),  # 完成第 3 节创建。
    ]  # 结束固定分节初始化。
    if anomaly_payload:  # 如果存在异常分析数据，
        sections.append(  # 追加异常分析分节。
            ReportSection(  # 创建异常分节对象。
                key="anomaly_analysis",  # 分节键。
                title="异常分析",  # 分节标题。
                data=anomaly_payload,  # 分节数据。
            )  # 完成异常分节创建。
        )  # 完成异常分节追加。
    if weather_payload:  # 如果存在天气相关性数据，
        sections.append(  # 追加天气相关性分节。
            ReportSection(  # 创建天气分节对象。
                key="weather_correlation",  # 分节键。
                title="天气相关性",  # 分节标题。
                data=weather_payload,  # 分节数据。
            )  # 完成天气分节创建。
        )  # 完成天气分节追加。
    return sections  # 返回最终分节列表。


def _persist_report(  # 定义报表持久化函数。
    report_id: str,  # 接收报表 ID。
    payload: GenerateReportRequest,  # 接收创建报表请求。
    meter: str,  # 接收标准化表计类型。
    report_time_range: TimeRange,  # 接收时间范围。
    status: ReportStatus,  # 接收报表状态。
    summary_text: str | None,  # 接收摘要文本。
    report_payload: dict[str, Any],  # 接收完整报表 JSON。
    export_markdown: str | None,  # 接收导出的 Markdown 内容。
    error_message: str | None = None,  # 接收错误文本（可选）。
) -> None:  # 无返回值。
    execute_sql(  # 执行 UPSERT 持久化 SQL。
        """
        INSERT INTO reports (
            report_id,
            report_type,
            status,
            building_id,
            meter,
            time_start,
            time_end,
            include_ai_summary,
            summary,
            report_json,
            export_markdown,
            error_message,
            created_at,
            updated_at
        ) VALUES (
            :report_id,
            :report_type,
            :status,
            :building_id,
            :meter,
            :time_start,
            :time_end,
            :include_ai_summary,
            :summary,
            CAST(:report_json AS JSONB),
            :export_markdown,
            :error_message,
            NOW(),
            NOW()
        )
        ON CONFLICT (report_id) DO UPDATE
        SET
            report_type = EXCLUDED.report_type,
            status = EXCLUDED.status,
            building_id = EXCLUDED.building_id,
            meter = EXCLUDED.meter,
            time_start = EXCLUDED.time_start,
            time_end = EXCLUDED.time_end,
            include_ai_summary = EXCLUDED.include_ai_summary,
            summary = EXCLUDED.summary,
            report_json = EXCLUDED.report_json,
            export_markdown = EXCLUDED.export_markdown,
            error_message = EXCLUDED.error_message,
            updated_at = NOW()
        """,  # 结束 UPSERT SQL 文本。
        {
            "report_id": report_id,  # 传入报表 ID 参数。
            "report_type": payload.report_type.value,  # 传入报表类型参数。
            "status": status.value,  # 传入状态参数。
            "building_id": payload.building_id,  # 传入建筑编号参数。
            "meter": meter,  # 传入表计参数。
            "time_start": report_time_range.start,  # 传入开始时间参数。
            "time_end": report_time_range.end,  # 传入结束时间参数。
            "include_ai_summary": payload.include_ai_summary,  # 传入请求侧 AI 开关参数。
            "summary": summary_text,  # 传入摘要文本参数。
            "report_json": json.dumps(report_payload, ensure_ascii=False),  # 序列化报表 JSON 参数。
            "export_markdown": export_markdown,  # 传入 Markdown 导出内容参数。
            "error_message": error_message,  # 传入错误信息参数。
        },  # 结束参数字典。
    )  # 完成持久化写入。


def generate_report(  # 定义创建报表生成任务的入口函数。
    payload: GenerateReportRequest,  # 接收报表生成请求。
    base_url: str | None = None,  # 接收服务基础 URL，用于生成下载链接。
    background_tasks: Any | None = None,  # 接收 FastAPI BackgroundTasks；为空时退回线程执行。
) -> GenerateReportResponse:
    report_id = _build_report_id()  # 先生成本次报表 ID。
    fallback_meter = normalize_meter(DEFAULT_REPORT_METER)  # 准备占位记录使用的默认表计。
    queued_payload = {  # 先构造处理中状态的报表 JSON，保证列表接口可以立即查到。
        "report_id": report_id,
        "report_type": payload.report_type.value,
        "status": ReportStatus.processing.value,
        "time_range": payload.time_range.model_dump(mode="json"),
        "building_id": payload.building_id,
        "meter": fallback_meter,
        "analyzed_meters": [fallback_meter],
        "summary": "报表正在生成中，请稍后刷新查看。",
        "generated_at": require_api_datetime(datetime.now()).isoformat(),
        "include_ai_summary": payload.include_ai_summary,
        "ai_summary_applied": False,
        "ai_summary_skipped_reason": None if payload.include_ai_summary else "not_requested",
        "ai_insight": None,
        "sections": [],
        "exports": [],
        "download_url": None,
    }
    _persist_report(  # 先持久化 processing 状态，避免前端等待长任务且列表查不到。
        report_id=report_id,
        payload=payload,
        meter=fallback_meter,
        report_time_range=payload.time_range,
        status=ReportStatus.processing,
        summary_text="报表正在生成中，请稍后刷新查看。",
        report_payload=queued_payload,
        export_markdown=None,
    )
    if background_tasks is not None:  # FastAPI 正常请求路径使用后台任务。
        background_tasks.add_task(_generate_report_sync, report_id, payload, base_url)
    else:  # 非请求上下文调用时也不要阻塞调用方。
        Thread(target=_generate_report_sync, args=(report_id, payload, base_url), daemon=True).start()
    return GenerateReportResponse(
        report_id=report_id,
        status=ReportStatus.processing,
        include_ai_summary=payload.include_ai_summary,
        ai_summary_applied=False,
        ai_summary_skipped_reason=None if payload.include_ai_summary else "not_requested",
    )


def _generate_report_sync(report_id: str, payload: GenerateReportRequest, base_url: str | None = None) -> GenerateReportResponse:  # 定义同步执行报表生成的后台任务函数。
    fallback_meter = normalize_meter(DEFAULT_REPORT_METER)  # 先定义默认回退表计，避免异常分支丢失上下文。
    display_meter = fallback_meter  # 初始化对外展示表计字段。
    analyzed_meters: list[str] = [fallback_meter]  # 初始化参与分析的表计列表。
    ai_summary_applied = False  # 标记 AI 总结是否实际执行。
    ai_summary_skipped_reason: str | None = "not_requested" if not payload.include_ai_summary else None  # 记录 AI 总结未执行原因。
    try:  # 开始报表生成主流程。
        resolved_start, resolved_end = resolve_time_range(  # 按请求条件补齐时间范围。
            payload.time_range.start,  # 传入请求开始时间。
            payload.time_range.end,  # 传入请求结束时间。
            [payload.building_id] if payload.building_id else None,  # 传入建筑过滤（可选）。
            None,  # 当前报表不按 site 过滤。
            None if payload.building_id else fallback_meter,  # 指定建筑时按全表计补时间，否则维持默认电表口径。
        )  # 完成时间范围补齐。
        report_time_range = build_api_time_range(resolved_start, resolved_end)  # 转换为 API 标准时间范围对象。

        if payload.building_id:  # 如果请求指定了建筑编号，
            analyzed_meters = _list_building_meters(payload.building_id, resolved_start, resolved_end)  # 查询该建筑在当前时间范围内的可用表计。
        if not analyzed_meters:  # 如果没有查到可用表计，
            analyzed_meters = [fallback_meter]  # 回退到默认电表，保证流程可继续执行。
        analyzed_meters = _sort_report_meters(analyzed_meters)  # 对参与分析的表计做稳定排序。
        primary_meter = _select_primary_meter(analyzed_meters)  # 选择主展示表计（用于兼容旧结构与 AI 摘要）。
        display_meter = primary_meter if len(analyzed_meters) == 1 else REPORT_MULTI_METER_LABEL  # 多表计时改用统一标识。
        single_building_mode = bool(payload.building_id)  # 多建筑报表只保留聚合口径，不混入单楼诊断。
        if payload.include_ai_summary and not single_building_mode:
            ai_summary_skipped_reason = "multi_building_anomaly_insight_disabled"  # 多建筑报表禁用单楼异常洞察，但仍允许聚合 AI 总结。

        building_filters = [payload.building_id] if payload.building_id else None  # 预先构造建筑过滤条件。
        summary_by_meter_json: list[dict[str, Any]] = []  # 初始化分表计摘要列表。
        trend_series_combined: list[dict[str, Any]] = []  # 初始化组合趋势序列列表。
        ranking_items_combined: list[dict[str, Any]] = []  # 初始化组合排行列表。
        ranking_by_meter: list[dict[str, Any]] = []  # 初始化按表计分组排行列表。
        primary_summary_payload_python: dict[str, Any] = {}  # 初始化主表计 python 摘要。
        primary_summary_payload_json: dict[str, Any] = {}  # 初始化主表计 json 摘要。
        primary_trend_payload_json: dict[str, Any] = {}  # 初始化主表计趋势数据。

        for current_meter in analyzed_meters:  # 遍历每个需要分析的表计。
            summary_model = build_summary(  # 计算当前表计摘要。
                current_meter,  # 传入当前表计。
                resolved_start,  # 传入开始时间。
                resolved_end,  # 传入结束时间。
                building_filters,  # 传入建筑过滤条件。
                None,  # 当前不按站点过滤。
            )  # 完成当前表计摘要计算。
            current_summary_python = summary_model.model_dump(mode="python")  # 转成 python 模式摘要（供 AI 使用）。
            current_summary_json = summary_model.model_dump(mode="json")  # 转成 json 模式摘要（供报表展示）。
            summary_by_meter_json.append(current_summary_json)  # 追加到分表计摘要列表。
            if current_meter == primary_meter:  # 如果当前是主表计，
                primary_summary_payload_python = current_summary_python  # 记录主表计 python 摘要。
                primary_summary_payload_json = current_summary_json  # 记录主表计 json 摘要。

            trend_model = get_energy_trend(  # 查询当前表计趋势。
                building_filters,  # 传入建筑过滤。
                None,  # 当前不按站点过滤。
                current_meter,  # 传入当前表计。
                resolved_start,  # 传入开始时间。
                resolved_end,  # 传入结束时间。
                DEFAULT_REPORT_GRANULARITY,  # 使用内部固定粒度 day。
            )  # 完成当前表计趋势查询。
            current_trend_json = trend_model.model_dump(mode="json")  # 转成 json 字典。
            if current_meter == primary_meter:  # 如果当前是主表计，
                primary_trend_payload_json = current_trend_json  # 记录主表计趋势数据。
            for series_item in current_trend_json.get("series", []):  # 遍历当前表计趋势序列。
                if not isinstance(series_item, dict):  # 如果序列项结构不合法，
                    continue  # 跳过当前序列项。
                normalized_series = dict(series_item)  # 复制序列字典避免原地改动。
                normalized_series["meter"] = series_item.get("meter") or current_meter  # 补全序列表计字段。
                trend_series_combined.append(normalized_series)  # 追加到组合趋势序列。

            ranking_model = get_energy_rankings(  # 查询当前表计排行。
                current_meter,  # 传入当前表计。
                resolved_start,  # 传入开始时间。
                resolved_end,  # 传入结束时间。
                "sum",  # 固定按总量排行。
                "desc",  # 固定降序。
                DEFAULT_REPORT_RANKING_LIMIT,  # 使用内部固定排行条数上限。
            )  # 完成当前表计排行查询。
            current_ranking_json = ranking_model.model_dump(mode="json")  # 转成 json 字典。
            meter_ranking_items: list[dict[str, Any]] = []  # 初始化当前表计排行列表。
            for ranking_item in current_ranking_json.get("items", []):  # 遍历当前表计排行条目。
                if not isinstance(ranking_item, dict):  # 如果条目结构不合法，
                    continue  # 跳过当前条目。
                normalized_ranking_item = dict(ranking_item)  # 复制排行条目字典。
                normalized_ranking_item["meter"] = current_meter  # 补全条目表计字段。
                ranking_items_combined.append(normalized_ranking_item)  # 追加到组合排行列表。
                meter_ranking_items.append(normalized_ranking_item)  # 追加到当前表计排行列表。
            ranking_by_meter.append({"meter": current_meter, "items": meter_ranking_items})  # 写入按表计分组排行结果。

        effective_building_id = payload.building_id  # 只有单建筑报表才允许进入单楼口径的后续分析。

        anomaly_payload_json: dict[str, Any] | None = None  # 先初始化异常节为空。
        weather_payload_json: dict[str, Any] | None = None  # 先初始化天气节为空。
        primary_anomaly_payload_json: dict[str, Any] | None = None  # 初始化主表计异常结果为空。
        primary_weather_payload_json: dict[str, Any] | None = None  # 初始化主表计天气结果为空。
        anomaly_by_meter: list[dict[str, Any]] = []  # 初始化分表计异常结果列表。
        weather_by_meter: list[dict[str, Any]] = []  # 初始化分表计天气结果列表。
        if effective_building_id:  # 如果有可分析的建筑编号，
            detector_counter: defaultdict[tuple[str, str], int] = defaultdict(int)  # 初始化检测器事件计数字典。
            total_event_count = 0  # 初始化总异常事件数。
            has_anomaly = False  # 初始化是否存在异常标识。
            for current_meter in analyzed_meters:  # 遍历每个表计做异常与天气分析。
                anomaly_model = get_energy_anomaly_analysis(  # 查询当前表计异常分析结果。
                    EnergyAnomalyAnalysisRequest(  # 构造异常分析请求对象。
                        building_id=effective_building_id,  # 写入建筑编号。
                        meter=current_meter,  # 写入当前表计类型。
                        time_range=report_time_range,  # 写入时间范围。
                        granularity=DEFAULT_REPORT_GRANULARITY,  # 写入内部固定粒度 day。
                        analysis_mode="offline_event_review",  # 固定分析模式。
                        include_weather_context=True,  # 默认包含天气上下文。
                    )  # 完成异常分析请求构造。
                )  # 完成异常分析查询。
                anomaly_item = anomaly_model.model_dump(mode="json")  # 转为 json 字典供报表写入。
                anomaly_item["meter"] = current_meter  # 补全异常结果表计字段。
                anomaly_by_meter.append(anomaly_item)  # 追加当前表计异常结果。
                total_event_count += int(anomaly_item.get("event_count") or 0)  # 累加异常事件数。
                has_anomaly = has_anomaly or bool(anomaly_item.get("is_anomalous"))  # 更新是否存在异常标识。
                for detector_item in anomaly_item.get("detector_breakdown") or []:  # 遍历当前表计检测器分布。
                    if not isinstance(detector_item, dict):  # 如果检测器条目结构不合法，
                        continue  # 跳过当前条目。
                    key = (  # 构造检测器计数键。
                        str(detector_item.get("detected_by") or "offline_detector"),  # 检测器名称。
                        str(detector_item.get("event_type") or "offline_event"),  # 事件类型。
                    )  # 完成键构造。
                    detector_counter[key] += int(detector_item.get("count") or 0)  # 累加检测器计数。
                if current_meter == primary_meter:  # 如果当前是主表计，
                    primary_anomaly_payload_json = anomaly_item  # 记录主表计异常结果。

                weather_model = get_energy_weather_correlation(  # 查询当前表计天气相关性结果。
                    effective_building_id,  # 传入建筑编号。
                    current_meter,  # 传入当前表计类型。
                    resolved_start,  # 传入开始时间。
                    resolved_end,  # 传入结束时间。
                )  # 完成天气相关性查询。
                weather_item = weather_model.model_dump(mode="json")  # 转为 json 字典供报表写入。
                weather_item["meter"] = current_meter  # 补全天气结果表计字段。
                weather_by_meter.append(weather_item)  # 追加当前表计天气结果。
                if current_meter == primary_meter:  # 如果当前是主表计，
                    primary_weather_payload_json = weather_item  # 记录主表计天气结果。

            detector_breakdown = [  # 组装聚合后的检测器分布列表。
                {"detected_by": key[0], "event_type": key[1], "count": count}  # 构造检测器分布条目。
                for key, count in sorted(detector_counter.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))  # 按数量和名称排序输出。
            ]  # 完成检测器分布组装。
            if primary_anomaly_payload_json is None and anomaly_by_meter:  # 如果主表计异常为空但存在异常结果，
                primary_anomaly_payload_json = anomaly_by_meter[0]  # 回退取第一条异常结果作为主异常数据。
            if primary_weather_payload_json is None and weather_by_meter:  # 如果主表计天气为空但存在天气结果，
                primary_weather_payload_json = weather_by_meter[0]  # 回退取第一条天气结果作为主天气数据。
            if anomaly_by_meter:  # 如果存在异常结果，
                if len(anomaly_by_meter) == 1:  # 单表计时沿用原有异常结构，
                    anomaly_payload_json = primary_anomaly_payload_json  # 直接复用主表计异常数据。
                else:  # 多表计时输出聚合异常结构。
                    anomaly_payload_json = {  # 组装多表计异常分节数据。
                        "building_id": effective_building_id,  # 写入建筑编号。
                        "meter": primary_meter,  # 写入主表计。
                        "meters": analyzed_meters,  # 写入分析表计列表。
                        "is_anomalous": has_anomaly,  # 写入总体异常标识。
                        "summary": f"已完成 {len(anomaly_by_meter)} 种表计异常分析，累计异常事件 {total_event_count} 个。",  # 写入聚合摘要。
                        "analysis_mode": "offline_event_review",  # 写入分析模式。
                        "event_count": total_event_count,  # 写入总异常事件数。
                        "detector_breakdown": detector_breakdown,  # 写入聚合检测器分布。
                        "by_meter": anomaly_by_meter,  # 写入分表计异常结果。
                    }  # 完成多表计异常分节组装。
            if weather_by_meter:  # 如果存在天气相关性结果，
                if len(weather_by_meter) == 1:  # 单表计时沿用原有天气结构，
                    weather_payload_json = primary_weather_payload_json  # 直接复用主表计天气数据。
                else:  # 多表计时输出聚合天气结构。
                    weather_payload_json = {  # 组装多表计天气分节数据。
                        "building_id": effective_building_id,  # 写入建筑编号。
                        "meter": primary_meter,  # 写入主表计。
                        "meters": analyzed_meters,  # 写入分析表计列表。
                        "correlation_coefficient": (primary_weather_payload_json or {}).get("correlation_coefficient"),  # 兼容保留主相关系数字段。
                        "factors": (primary_weather_payload_json or {}).get("factors", []),  # 兼容保留主因子列表字段。
                        "by_meter": weather_by_meter,  # 写入分表计天气结果。
                    }  # 完成多表计天气分节组装。

        summary_payload_json = dict(primary_summary_payload_json)  # 以主表计摘要为兼容基底复制总览分节数据。
        summary_payload_json["meter"] = primary_meter  # 明确写入主表计字段。
        summary_payload_json["meters"] = analyzed_meters  # 写入本次分析覆盖的表计列表。
        summary_payload_json["by_meter"] = summary_by_meter_json  # 写入分表计摘要列表。

        trend_payload_json = {  # 组装趋势分节数据。
            "series": trend_series_combined,  # 写入组合趋势序列。
            "meters": analyzed_meters,  # 写入覆盖表计列表。
        }  # 完成趋势分节数据组装。

        ranking_payload_json = {  # 组装排行分节数据。
            "items": ranking_items_combined,  # 写入组合排行条目。
            "meters": analyzed_meters,  # 写入覆盖表计列表。
            "by_meter": ranking_by_meter,  # 写入按表计分组排行结果。
        }  # 完成排行分节数据组装。

        sections = _build_section_payloads(  # 构造报表分节列表。
            report_time_range,  # 传入标准化时间范围。
            summary_payload_json,  # 传入摘要节数据。
            trend_payload_json,  # 传入趋势节数据。
            ranking_payload_json,  # 传入排行节数据。
            anomaly_payload_json,  # 传入异常节数据（可空）。
            weather_payload_json,  # 传入天气节数据（可空）。
        )  # 完成分节构造。

        ai_insight: AIInsight | None = None  # 先初始化 AI 洞察为空。
        if payload.include_ai_summary:  # 只要请求了 AI，就尝试基于当前报表素材生成总结。
            ai_context_building_id = effective_building_id or "多建筑汇总"
            ai_request = _build_ai_report_request(  # 构造 AI 报表请求。
                payload=payload,  # 传入原始报表请求。
                ai_context_building_id=ai_context_building_id,  # 传入报表范围标识。
                meter=display_meter,  # 传入当前报表展示表计类型。
                report_time_range=report_time_range,  # 传入标准化时间范围。
                summary_payload=primary_summary_payload_python,  # 传入主表计摘要（python 模式）。
                trend_payload=primary_trend_payload_json,  # 传入主表计趋势数据。
                anomaly_payload=primary_anomaly_payload_json,  # 传入主表计异常数据。
                include_anomaly_insight=single_building_mode and primary_anomaly_payload_json is not None,  # 仅单建筑报表纳入异常洞察。
            )  # 完成 AI 请求构造。
            ai_response = get_report_summary(ai_request)  # 调用 AI 报表总结服务。
            ai_insight = AIInsight(  # 把 AI 响应映射为报表洞察对象。
                summary=ai_response.summary,  # 写入 AI 摘要。
                status=ai_response.status,  # 写入 AI 状态。
                highlights=[item.detail for item in ai_response.highlights],  # 提取亮点说明。
                risks=ai_response.risks,  # 写入风险列表。
                suggestions=[item.label for item in ai_response.suggestions],  # 提取建议文案。
            )  # 完成 AI 洞察对象构造。
            ai_summary_applied = True  # 记录本次报表已执行 AI 总结。
            ai_summary_skipped_reason = None  # AI 已执行，无需跳过原因。

        summary_text = ai_insight.summary if ai_insight and ai_insight.summary else _build_rule_summary(  # 生成最终摘要文本。
            payload.report_type.value,  # 传入报表类型。
            primary_summary_payload_python,  # 传入主表计摘要数据。
            ranking_items_combined,  # 传入组合排行条目。
            anomaly_payload_json,  # 传入异常摘要。
        )  # 完成摘要文本选择。

        exports = [  # 构造导出列表（仅 md）。
            ReportExport(  # 创建 md 导出描述对象。
                format="md",  # 导出格式固定 md。
                download_url=_build_download_url(report_id, base_url),  # 构造下载地址。
                content_type="text/markdown; charset=utf-8",  # 写入内容类型。
            )  # 完成导出对象创建。
        ]  # 完成导出列表构造。

        report_payload = {  # 组装最终报表 JSON 结构。
            "report_id": report_id,  # 写入报表 ID。
            "report_type": payload.report_type.value,  # 写入报表类型。
            "status": ReportStatus.ready.value,  # 写入报表状态。
            "time_range": report_time_range.model_dump(mode="json"),  # 写入时间范围。
            "building_id": payload.building_id,  # 写入建筑范围。
            "meter": display_meter,  # 写入对外展示表计（多表计场景使用统一标识）。
            "primary_meter": primary_meter,  # 写入主表计，便于前端兼容旧逻辑。
            "analyzed_meters": analyzed_meters,  # 写入参与分析的表计列表。
            "summary": summary_text,  # 写入摘要文本。
            "generated_at": require_api_datetime(datetime.now()).isoformat(),  # 写入生成时间。
            "include_ai_summary": payload.include_ai_summary,  # 写入请求侧 AI 开关。
            "ai_summary_applied": ai_summary_applied,  # 写入 AI 总结执行结果。
            "ai_summary_skipped_reason": ai_summary_skipped_reason,  # 写入 AI 总结跳过原因。
            "ai_insight": ai_insight.model_dump(mode="json") if ai_insight else None,  # 写入 AI 洞察（可空）。
            "sections": [section.model_dump(mode="json") for section in sections],  # 写入分节列表。
            "exports": [item.model_dump(mode="json") for item in exports],  # 写入导出描述。
            "download_url": _build_download_url(report_id, base_url),  # 写入默认下载链接。
        }  # 完成报表 JSON 组装。
        export_markdown = _build_markdown_export(report_payload)  # 生成 Markdown 导出内容。
        _persist_report(  # 持久化 ready 状态报表。
            report_id=report_id,  # 传入报表 ID。
            payload=payload,  # 传入原始请求。
            meter=display_meter,  # 传入对外展示表计。
            report_time_range=report_time_range,  # 传入时间范围。
            status=ReportStatus.ready,  # 传入 ready 状态。
            summary_text=summary_text,  # 传入摘要文本。
            report_payload=report_payload,  # 传入报表 JSON。
            export_markdown=export_markdown,  # 传入 md 导出内容。
        )  # 完成持久化。
        return GenerateReportResponse(
            report_id=report_id,
            status=ReportStatus.ready,
            include_ai_summary=payload.include_ai_summary,
            ai_summary_applied=ai_summary_applied,
            ai_summary_skipped_reason=ai_summary_skipped_reason,
        )  # 返回生成成功响应。
    except Exception as exc:  # noqa: BLE001  # 如果主流程异常，进入失败兜底。
        if payload.include_ai_summary and ai_summary_skipped_reason is None:
            ai_summary_skipped_reason = "report_generation_failed"  # 若整体失败，则补上失败原因。
        fallback_payload = {  # 组装失败态报表 JSON。
            "report_id": report_id,  # 写入报表 ID。
            "report_type": payload.report_type.value,  # 写入报表类型。
            "status": ReportStatus.failed.value,  # 写入失败状态。
            "time_range": payload.time_range.model_dump(mode="json"),  # 写入请求时间范围。
            "building_id": payload.building_id,  # 写入建筑范围。
            "meter": display_meter,  # 写入对外展示表计。
            "analyzed_meters": analyzed_meters,  # 写入分析表计列表（尽量保留上下文）。
            "summary": None,  # 失败态摘要为空。
            "include_ai_summary": payload.include_ai_summary,  # 保留请求侧 AI 开关。
            "ai_summary_applied": ai_summary_applied,  # 保留 AI 总结执行结果。
            "ai_summary_skipped_reason": ai_summary_skipped_reason,  # 保留 AI 总结跳过原因。
            "sections": [],  # 失败态分节为空。
            "download_url": _build_download_url(report_id, base_url),  # 仍保留下载地址字段。
        }  # 完成失败态 JSON 组装。
        _persist_report(  # 持久化 failed 状态报表。
            report_id=report_id,  # 传入报表 ID。
            payload=payload,  # 传入原始请求。
            meter=display_meter,  # 传入对外展示表计。
            report_time_range=payload.time_range,  # 使用请求时间范围写库。
            status=ReportStatus.failed,  # 写入 failed 状态。
            summary_text=None,  # 摘要为空。
            report_payload=fallback_payload,  # 写入失败态 JSON。
            export_markdown=None,  # 失败态没有导出内容。
            error_message=str(exc),  # 写入错误信息。
        )  # 完成失败态持久化。
        return GenerateReportResponse(
            report_id=report_id,
            status=ReportStatus.failed,
            include_ai_summary=payload.include_ai_summary,
            ai_summary_applied=ai_summary_applied,
            ai_summary_skipped_reason=ai_summary_skipped_reason,
        )  # 返回失败响应。


def get_report_detail(report_id: str, base_url: str | None = None) -> ReportDetailResponse:  # 定义查询报表详情函数。
    row = fetch_one(  # 查询报表主记录。
        """
        SELECT
            report_id,
            report_type,
            status,
            building_id,
            include_ai_summary,
            summary,
            report_json,
            error_message,
            created_at,
            time_start,
            time_end
        FROM reports
        WHERE report_id = :report_id
        """,  # 结束查询 SQL。
        {"report_id": report_id},  # 传入报表 ID 参数。
    )  # 执行查询。
    if row is None:  # 如果未查到报表，
        raise ResourceNotFoundError(f"未找到报表: {report_id}")  # 返回统一 404 异常。

    report_json = _coerce_report_json(row.get("report_json"))  # 解析报表 JSON 字段。
    ai_insight_raw = report_json.get("ai_insight")  # 读取原始 AI 洞察数据。
    ai_insight = AIInsight(**ai_insight_raw) if isinstance(ai_insight_raw, dict) else None  # 安全构造 AI 洞察对象。
    section_items = []  # 初始化分节模型列表。
    for item in report_json.get("sections", []):  # 遍历原始分节列表。
        if isinstance(item, dict):  # 如果当前分节是合法字典，
            section_items.append(ReportSection(**item))  # 转为模型对象后追加。

    export_items = [  # 构造导出列表（仅 md）。
        ReportExport(  # 创建 md 导出描述对象。
            format="md",  # 导出格式固定 md。
            download_url=_build_download_url(report_id, base_url),  # 构造下载地址。
            content_type="text/markdown; charset=utf-8",  # 写入内容类型。
        )  # 完成导出对象创建。
    ]  # 完成导出列表构造。

    start_time = to_api_datetime(row.get("time_start"))  # 优先取数据库开始时间并转时区。
    end_time = to_api_datetime(row.get("time_end"))  # 优先取数据库结束时间并转时区。
    if start_time is None:  # 如果数据库开始时间缺失，
        start_time = _to_optional_datetime((report_json.get("time_range") or {}).get("start"))  # 从 JSON 兜底恢复开始时间。
    if end_time is None:  # 如果数据库结束时间缺失，
        end_time = _to_optional_datetime((report_json.get("time_range") or {}).get("end"))  # 从 JSON 兜底恢复结束时间。
    if start_time is None or end_time is None:  # 如果时间范围仍无法恢复，
        raise ValueError("报表时间范围缺失，无法返回详情。")  # 抛出明确校验错误。

    return ReportDetailResponse(  # 构造并返回报表详情响应。
        report_id=str(row["report_id"]),  # 写入报表 ID。
        report_type=str(row["report_type"]),  # 写入报表类型。
        status=str(row["status"]),  # 写入报表状态。
        time_range=TimeRange(start=start_time, end=end_time),  # 写入时间范围对象。
        building_id=row.get("building_id"),  # 写入建筑编号。
        summary=row.get("summary") or report_json.get("summary"),  # 写入摘要文本。
        download_url=_build_download_url(report_id, base_url),  # 写入默认下载链接。
        generated_at=to_api_datetime(row.get("created_at")),  # 写入生成时间。
        include_ai_summary=bool(row.get("include_ai_summary")),  # 写入请求侧 AI 开关。
        ai_summary_applied=bool(report_json.get("ai_summary_applied")),  # 写入 AI 总结执行结果。
        ai_summary_skipped_reason=report_json.get("ai_summary_skipped_reason"),  # 写入 AI 总结跳过原因。
        ai_insight=ai_insight,  # 写入 AI 洞察对象。
        sections=section_items,  # 写入分节列表。
        exports=export_items,  # 写入导出描述列表。
        error_message=row.get("error_message"),  # 写入错误信息（可空）。
    )  # 完成报表详情响应构造。


def list_reports(
    *,
    base_url: str | None = None,
    report_type: str | None = None,
    status: str | None = None,
    building_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ReportListResponse:
    where_clauses = ["1=1"]
    params: dict[str, Any] = {
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }

    if report_type and str(report_type).strip():
        where_clauses.append("report_type = :report_type")
        params["report_type"] = str(report_type).strip()
    if status and str(status).strip():
        where_clauses.append("status = :status")
        params["status"] = str(status).strip()
    if building_id and str(building_id).strip():
        where_clauses.append("building_id = :building_id")
        params["building_id"] = str(building_id).strip()

    where_sql = " AND ".join(where_clauses)
    rows = fetch_all(
        f"""
        SELECT
            report_id,
            report_type,
            status,
            building_id,
            include_ai_summary,
            summary,
            report_json,
            error_message,
            created_at,
            time_start,
            time_end
        FROM reports
        WHERE {where_sql}
        ORDER BY created_at DESC, report_id DESC
        LIMIT :limit OFFSET :offset
        """,
        params,
    )
    count_row = fetch_one(
        f"""
        SELECT COUNT(*) AS total
        FROM reports
        WHERE {where_sql}
        """,
        {key: value for key, value in params.items() if key not in {"limit", "offset"}},
    ) or {"total": 0}
    total = int(count_row.get("total") or 0)

    items: list[ReportListItem] = []
    for row in rows:
        report_json = _coerce_report_json(row.get("report_json"))
        start_time = to_api_datetime(row.get("time_start"))
        end_time = to_api_datetime(row.get("time_end"))
        if start_time is None:
            start_time = _to_optional_datetime((report_json.get("time_range") or {}).get("start"))
        if end_time is None:
            end_time = _to_optional_datetime((report_json.get("time_range") or {}).get("end"))
        if start_time is None or end_time is None:
            continue
        items.append(
            ReportListItem(
                report_id=str(row["report_id"]),
                report_type=str(row["report_type"]),
                status=str(row["status"]),
                time_range=TimeRange(start=start_time, end=end_time),
                building_id=row.get("building_id"),
                summary=row.get("summary") or report_json.get("summary"),
                download_url=_build_download_url(str(row["report_id"]), base_url),
                generated_at=to_api_datetime(row.get("created_at")),
                include_ai_summary=bool(row.get("include_ai_summary")),
                ai_summary_applied=bool(report_json.get("ai_summary_applied")),
                ai_summary_skipped_reason=report_json.get("ai_summary_skipped_reason"),
                error_message=row.get("error_message"),
            )
        )

    return ReportListResponse(
        items=items,
        pagination=Pagination(page=page, page_size=page_size, total=total),
    )


def get_report_export(report_id: str, export_format: str) -> tuple[str, str, str]:  # 定义导出内容获取函数。
    normalized_format = export_format.lower().strip()  # 标准化导出格式文本。
    if normalized_format not in SUPPORTED_EXPORT_FORMATS:  # 如果格式不在支持列表内，
        raise ValueError(f"不支持的导出格式: {export_format}，允许值为 {', '.join(sorted(SUPPORTED_EXPORT_FORMATS))}")  # 返回校验错误。

    row = fetch_one(  # 查询导出所需字段。
        """
        SELECT report_id, report_json, export_markdown
        FROM reports
        WHERE report_id = :report_id
        """,  # 结束查询 SQL。
        {"report_id": report_id},  # 传入报表 ID 参数。
    )  # 执行查询。
    if row is None:  # 如果未查到报表，
        raise ResourceNotFoundError(f"未找到报表: {report_id}")  # 返回统一 404 异常。

    report_json = _coerce_report_json(row.get("report_json"))  # 解析报表 JSON 字段。
    content = row.get("export_markdown") or _build_markdown_export(report_json)  # 优先取缓存 md，缺失时现场生成。
    content_type = "text/markdown; charset=utf-8"  # 固定返回 Markdown 内容类型。
    filename = f"{report_id}.md"  # 固定返回 Markdown 文件名。
    return content, content_type, filename  # 返回导出内容、类型和文件名。


def delete_report(report_id: str) -> DeleteReportResponse:
    """删除一份已生成的报表记录。"""

    row = fetch_one(
        """
        SELECT report_id
        FROM reports
        WHERE report_id = :report_id
        """,
        {"report_id": report_id},
    )
    if row is None:
        raise ResourceNotFoundError(f"未找到报表 {report_id}")

    execute_sql(
        """
        DELETE FROM reports
        WHERE report_id = :report_id
        """,
        {"report_id": report_id},
    )
    return DeleteReportResponse(
        report_id=report_id,
        deleted=True,
        message="报表已删除。",
    )
