from datetime import datetime

from app.schemas import AnomalyFeedbackRequest, CandidateFeedbackItem, TimeRange
from ai.backend.feedback_service import submit_anomaly_feedback
from ai.backend.history import retrieve_similar_feedback_cases

payload = AnomalyFeedbackRequest(
    analysis_id='ana_test_feedback_001',
    building_id='Bear_assembly_Angel',
    meter='electricity',
    time_range=TimeRange(
        start=datetime.fromisoformat('2017-01-01T00:00:00+00:00'),
        end=datetime.fromisoformat('2017-01-03T00:00:00+00:00'),
    ),
    selected_cause_id='load_shift',
    selected_cause_title='Load pattern shift',
    selected_score=4,
    candidate_feedbacks=[
        CandidateFeedbackItem(cause_id='load_shift', score=4, title='Load pattern shift'),
        CandidateFeedbackItem(cause_id='efficiency_drop', score=2, title='Equipment efficiency drop'),
    ],
    comment='Operator confirmed load shift was the most likely explanation.',
    operator_id='tester_001',
    operator_name='Codex Test',
    resolution_status='confirmed',
    model_name='qwen3.5:35b',
    baseline_mode='overall_mean',
)
response = submit_anomaly_feedback(payload)
print(response.feedback_id)
print(response.stored)
print(response.selected_cause.title)
rows = retrieve_similar_feedback_cases('Bear_assembly_Angel', 'electricity', '2017-01-01T00:00:00+00:00', '2017-01-03T00:00:00+00:00')
print(len(rows))
print(rows[0]['selected_cause_id'] if rows else 'none')
