from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from app.schemas import AnomalyDetectorBreakdownItem
from app.schemas import TimeRange


class OpsIncidentRef(BaseModel):
    incident_id: str | None = None
    message_id: str | None = None


class OpsOperatorContext(BaseModel):
    operator_id: str | None = None
    operator_name: str | None = None


class OpsPageContext(BaseModel):
    source: str | None = None
    page_type: str | None = None
    current_chart_range: str | None = None


class OpsAnomalySnapshot(BaseModel):
    summary: str = ""
    analysis_mode: str = "offline_event_review"
    event_count: int = 0
    detector_breakdown: list[AnomalyDetectorBreakdownItem] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)


class OpsDiagnosisSnapshot(BaseModel):
    summary: str = ""
    status: str = "low_confidence"
    candidate_cause_titles: list[str] = Field(default_factory=list)
    knowledge_hits: int = 0
    history_feedback_hits: int = 0


class OpsContext(BaseModel):
    question: str
    guide_mode: str
    building_id: str
    meter: str
    time_range: TimeRange
    incident_ref: OpsIncidentRef = Field(default_factory=OpsIncidentRef)
    operator_context: OpsOperatorContext = Field(default_factory=OpsOperatorContext)
    page_context: OpsPageContext = Field(default_factory=OpsPageContext)
    anomaly_snapshot: OpsAnomalySnapshot = Field(default_factory=OpsAnomalySnapshot)
    diagnosis_snapshot: OpsDiagnosisSnapshot = Field(default_factory=OpsDiagnosisSnapshot)
    generated_at: datetime
