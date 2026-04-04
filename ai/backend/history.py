from typing import Any

from app.core.database import fetch_all


def retrieve_similar_feedback_cases(
    building_id: str,
    meter: str,
    start_time: str,
    end_time: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return similar historical feedback cases from persisted operator feedback.

    The first implementation keeps the similarity rule intentionally simple:
    same building + same meter first, then newest confirmed records first.
    If the feedback tables are not initialized yet, the retriever should fail soft
    so `/ai/analyze-anomaly` remains usable.
    """

    _ = start_time, end_time
    try:
        rows = fetch_all(
            """
            SELECT
                feedback_id::text AS feedback_id,
                analysis_id,
                building_id,
                meter,
                selected_cause_id,
                selected_score,
                resolution_status,
                comment,
                operator_name,
                created_at
            FROM ai_anomaly_feedback
            WHERE building_id = :building_id
              AND meter = :meter
            ORDER BY
                CASE resolution_status
                    WHEN 'confirmed' THEN 0
                    WHEN 'resolved' THEN 1
                    WHEN 'partially_confirmed' THEN 2
                    ELSE 3
                END,
                created_at DESC
            LIMIT :limit
            """,
            {
                'building_id': building_id,
                'meter': meter,
                'limit': limit,
            },
        )
    except Exception:
        return []
    return rows
