from datetime import datetime  # 导入 datetime，用于声明时间字段类型。
from enum import Enum  # 导入 Enum，用于定义枚举类型。
from typing import Any  # 导入 Any，用于声明灵活 JSON 字段类型。

from pydantic import BaseModel  # 导入 BaseModel，用于声明 Pydantic 数据模型。
from pydantic import ConfigDict  # 导入 ConfigDict，用于配置模型额外字段策略。
from pydantic import Field  # 导入 Field，用于声明字段默认值与校验约束。

from .schemas_common import TimeRange  # 导入统一时间范围模型。


class ReportType(str, Enum):  # 定义报表类型枚举。
    daily_summary = "daily_summary"  # 每日报表类型。
    weekly_summary = "weekly_summary"  # 周报表类型。
    monthly_summary = "monthly_summary"  # 月报表类型。
    anomaly_report = "anomaly_report"  # 异常报表类型。


class ReportStatus(str, Enum):  # 定义报表状态枚举。
    queued = "queued"  # 排队中状态。
    processing = "processing"  # 处理中状态。
    ready = "ready"  # 已完成状态。
    failed = "failed"  # 失败状态。


class GenerateReportRequest(BaseModel):  # 定义生成报表请求模型。
    model_config = ConfigDict(extra="forbid")  # 禁止请求体传入未定义字段，确保与 API 文档严格一致。
    report_type: ReportType  # 报表类型（必填）。
    building_id: str | None = None  # 建筑编号（可选，不传表示多建筑聚合）。
    time_range: TimeRange  # 时间范围（必填）。
    include_ai_summary: bool = True  # 是否包含 AI 分析总结（默认开启）。


class GenerateReportResponse(BaseModel):  # 定义生成报表响应模型。
    report_id: str  # 报表 ID。
    status: ReportStatus  # 报表状态。
    include_ai_summary: bool = False  # 是否请求 AI 参与报表生成。
    ai_summary_applied: bool = False  # AI 总结是否实际执行。
    ai_summary_skipped_reason: str | None = None  # AI 总结未执行时的跳过原因。


class AIInsight(BaseModel):  # 定义报表中的 AI 洞察模型。
    summary: str | None = None  # AI 摘要文本。
    status: str | None = None  # AI 结果状态。
    highlights: list[str] = Field(default_factory=list)  # AI 亮点列表。
    risks: list[str] = Field(default_factory=list)  # AI 风险提示列表。
    suggestions: list[str] = Field(default_factory=list)  # AI 建议列表。


class ReportSection(BaseModel):  # 定义报表分节模型。
    key: str  # 分节唯一键。
    title: str  # 分节标题。
    data: dict[str, Any] = Field(default_factory=dict)  # 分节数据内容。


class ReportExport(BaseModel):  # 定义报表导出描述模型。
    format: str  # 导出格式（当前仅 md）。
    download_url: str  # 导出下载地址。
    content_type: str  # 导出内容类型。


class ReportDetailResponse(BaseModel):  # 定义报表详情响应模型。
    report_id: str  # 报表 ID。
    report_type: str  # 报表类型。
    status: str  # 报表状态。
    time_range: TimeRange  # 报表时间范围。
    building_id: str | None = None  # 建筑编号（可空）。
    summary: str | None = None  # 报表摘要文本。
    download_url: str | None = None  # 默认下载链接。
    generated_at: datetime | None = None  # 报表生成时间。
    include_ai_summary: bool = False  # 是否请求 AI 参与报表生成。
    ai_summary_applied: bool = False  # AI 总结是否实际执行。
    ai_summary_skipped_reason: str | None = None  # AI 总结未执行时的跳过原因。
    ai_insight: AIInsight | None = None  # AI 洞察结构（可空）。
    sections: list[ReportSection] = Field(default_factory=list)  # 报表分节列表。
    exports: list[ReportExport] = Field(default_factory=list)  # 可用导出格式列表。
    error_message: str | None = None  # 失败时错误信息。

class DeleteReportResponse(BaseModel):
    report_id: str = Field(..., description="被删除的报表 ID")
    deleted: bool = Field(default=True, description="是否删除成功")
    message: str = Field(..., description="删除结果说明")