from fastapi import APIRouter

from ai.backend.anomaly_service import analyze_anomaly_with_ai
from ai.backend.feedback_service import submit_anomaly_feedback
from ai.backend.query_assistant_service import build_query_intent

from .schemas import AIAnalyzeAnomalyRequest
from .schemas import AIAnalyzeAnomalyResponse
from .schemas import AIQueryAssistantRequest
from .schemas import AIQueryAssistantResponse
from .schemas import AnomalyFeedbackRequest
from .schemas import AnomalyFeedbackResponse


router = APIRouter(tags=["AI"])


@router.post("/ai/analyze-anomaly", response_model=AIAnalyzeAnomalyResponse, summary="AI anomaly analysis")
def analyze_anomaly_api(payload: AIAnalyzeAnomalyRequest) -> AIAnalyzeAnomalyResponse:
    """Run anomaly analysis orchestration and return a structured AI response."""

    return analyze_anomaly_with_ai(payload)


@router.post("/ai/query-assistant", response_model=AIQueryAssistantResponse, summary="Parse query intent")
def query_assistant_api(payload: AIQueryAssistantRequest) -> AIQueryAssistantResponse:
    """Parse natural-language energy questions into query intent and endpoint recommendations."""

    return build_query_intent(payload)


@router.post("/ai/anomaly-feedback", response_model=AnomalyFeedbackResponse, summary="Submit anomaly feedback")
def submit_anomaly_feedback_api(payload: AnomalyFeedbackRequest) -> AnomalyFeedbackResponse:
    """Store operator feedback for anomaly analysis and future retrieval."""

    return submit_anomaly_feedback(payload)
