from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from app.schemas import AnomalyDetectorBreakdownItem
from app.schemas import TimeRange


class ReportPageContext(BaseModel):
    source: str | None = None
    page_type: str | None = None
    current_chart_range: str | None = None


class ReportMetricsSnapshot(BaseModel):
    total: float | None = None
    average: float | None = None
    peak: float | None = None
    peak_time: datetime | None = None
    unit: str | None = None
    compare_total: float | None = None
    compare_change_rate: float | None = None


class ReportTrendSnapshot(BaseModel):
    direction: str | None = None
    change_rate: float | None = None
    peak_days: list[str] = Field(default_factory=list)
    low_days: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReportAnomalySnapshot(BaseModel):
    summary: str = ""
    analysis_mode: str = "offline_event_review"
    event_count: int = 0
    detector_breakdown: list[AnomalyDetectorBreakdownItem] = Field(default_factory=list)


class ReportDiagnosisSnapshot(BaseModel):
    summary: str = ""
    status: str = "low_confidence"
    candidate_cause_titles: list[str] = Field(default_factory=list)


class ReportContext(BaseModel):
    question: str
    report_type: str
    audience: str
    building_id: str
    meter: str | None = None
    time_range: TimeRange
    page_context: ReportPageContext = Field(default_factory=ReportPageContext)
    metrics_snapshot: ReportMetricsSnapshot = Field(default_factory=ReportMetricsSnapshot)
    trend_summary: ReportTrendSnapshot = Field(default_factory=ReportTrendSnapshot)
    anomaly_summary: ReportAnomalySnapshot = Field(default_factory=ReportAnomalySnapshot)
    diagnosis_snapshot: ReportDiagnosisSnapshot = Field(default_factory=ReportDiagnosisSnapshot)
    generated_at: datetime
