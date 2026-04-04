from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.core.database import engine
from app.schemas import AnomalyFeedbackMeta
from app.schemas import AnomalyFeedbackRequest
from app.schemas import AnomalyFeedbackResponse
from app.schemas import CandidateFeedbackItem
from app.schemas import SelectedCauseSummary
from app.services.service_common import get_taipei_now


VALID_RESOLUTION_STATUS = {
    'confirmed',
    'partially_confirmed',
    'rejected',
    'resolved',
}


def _validate_score(score: int, field_name: str) -> None:
    """校验评分范围，统一要求 1-5 分。"""
    if score < 1 or score > 5:
        raise ValueError(f'{field_name} must be between 1 and 5')


def _normalize_candidate_feedbacks(payload: AnomalyFeedbackRequest) -> list[CandidateFeedbackItem]:
    """标准化候选原因反馈，并补齐 selected_cause 的评分记录。"""
    seen: set[str] = set()
    normalized: list[CandidateFeedbackItem] = []
    for item in payload.candidate_feedbacks:
        if item.cause_id in seen:
            raise ValueError(f'duplicate candidate feedback cause_id: {item.cause_id}')
        _validate_score(item.score, f'candidate_feedbacks[{item.cause_id}].score')
        seen.add(item.cause_id)
        normalized.append(item)

    if payload.selected_cause_id not in seen:
        normalized.append(
            CandidateFeedbackItem(
                cause_id=payload.selected_cause_id,
                score=payload.selected_score,
                title=payload.selected_cause_title,
            )
        )
    return normalized


def submit_anomaly_feedback(payload: AnomalyFeedbackRequest) -> AnomalyFeedbackResponse:
    """写入异常反馈主表与候选评分子表。

    该接口用于后续历史检索和候选原因重排，是异常分析闭环的数据入口。
    """

    _validate_score(payload.selected_score, 'selected_score')
    if payload.resolution_status not in VALID_RESOLUTION_STATUS:
        raise ValueError('resolution_status is invalid')
    if payload.time_range.end < payload.time_range.start:
        raise ValueError('time_range.end must be greater than or equal to time_range.start')

    candidate_feedbacks = _normalize_candidate_feedbacks(payload)
    feedback_id = str(uuid4())
    created_at = get_taipei_now()

    insert_feedback_sql = text(
        """
        INSERT INTO ai_anomaly_feedback (
            feedback_id,
            analysis_id,
            building_id,
            meter,
            time_start,
            time_end,
            selected_cause_id,
            selected_score,
            resolution_status,
            comment,
            operator_id,
            operator_name,
            model_name,
            baseline_mode
        ) VALUES (
            :feedback_id,
            :analysis_id,
            :building_id,
            :meter,
            :time_start,
            :time_end,
            :selected_cause_id,
            :selected_score,
            :resolution_status,
            :comment,
            :operator_id,
            :operator_name,
            :model_name,
            :baseline_mode
        )
        """
    )
    insert_candidate_sql = text(
        """
        INSERT INTO ai_anomaly_feedback_candidate_scores (
            feedback_id,
            cause_id,
            score
        ) VALUES (
            :feedback_id,
            :cause_id,
            :score
        )
        ON CONFLICT (feedback_id, cause_id) DO UPDATE SET
            score = EXCLUDED.score,
            created_at = NOW()
        """
    )

    try:
        with engine.begin() as connection:
            connection.execute(
                insert_feedback_sql,
                {
                    'feedback_id': feedback_id,
                    'analysis_id': payload.analysis_id,
                    'building_id': payload.building_id,
                    'meter': payload.meter,
                    'time_start': payload.time_range.start,
                    'time_end': payload.time_range.end,
                    'selected_cause_id': payload.selected_cause_id,
                    'selected_score': payload.selected_score,
                    'resolution_status': payload.resolution_status,
                    'comment': payload.comment,
                    'operator_id': payload.operator_id,
                    'operator_name': payload.operator_name,
                    'model_name': payload.model_name,
                    'baseline_mode': payload.analysis_mode,
                },
            )
            for item in candidate_feedbacks:
                connection.execute(
                    insert_candidate_sql,
                    {
                        'feedback_id': feedback_id,
                        'cause_id': item.cause_id,
                        'score': item.score,
                    },
                )
    except Exception as exc:
        raise ValueError('failed to persist anomaly feedback; please ensure feedback tables are initialized') from exc

    return AnomalyFeedbackResponse(
        feedback_id=feedback_id,
        analysis_id=payload.analysis_id,
        stored=True,
        message='Anomaly feedback stored successfully and is available for future retrieval.',
        selected_cause=SelectedCauseSummary(
            cause_id=payload.selected_cause_id,
            title=payload.selected_cause_title or payload.selected_cause_id,
            score=payload.selected_score,
        ),
        meta=AnomalyFeedbackMeta(
            building_id=payload.building_id,
            meter=payload.meter,
            resolution_status=payload.resolution_status,
            created_at=created_at,
        ),
    )
