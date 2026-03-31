CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ai_anomaly_feedback (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id VARCHAR(64) NOT NULL,
    building_id VARCHAR(128) NOT NULL,
    meter VARCHAR(64) NOT NULL,
    time_start TIMESTAMPTZ NOT NULL,
    time_end TIMESTAMPTZ NOT NULL,
    selected_cause_id VARCHAR(128) NOT NULL,
    selected_score SMALLINT NOT NULL,
    resolution_status VARCHAR(32) NOT NULL,
    comment TEXT,
    operator_id VARCHAR(128),
    operator_name VARCHAR(128),
    model_name VARCHAR(128),
    baseline_mode VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ai_anomaly_feedback_analysis UNIQUE (analysis_id),
    CONSTRAINT chk_ai_anomaly_feedback_selected_score CHECK (selected_score BETWEEN 1 AND 5),
    CONSTRAINT chk_ai_anomaly_feedback_resolution_status CHECK (
        resolution_status IN ('confirmed', 'partially_confirmed', 'rejected', 'resolved')
    ),
    CONSTRAINT chk_ai_anomaly_feedback_time_range CHECK (time_end >= time_start)
);

CREATE INDEX IF NOT EXISTS idx_ai_anomaly_feedback_building_meter
    ON ai_anomaly_feedback (building_id, meter);

CREATE INDEX IF NOT EXISTS idx_ai_anomaly_feedback_selected_cause
    ON ai_anomaly_feedback (selected_cause_id);

CREATE INDEX IF NOT EXISTS idx_ai_anomaly_feedback_created_at
    ON ai_anomaly_feedback (created_at DESC);


CREATE TABLE IF NOT EXISTS ai_anomaly_feedback_candidate_scores (
    id BIGSERIAL PRIMARY KEY,
    feedback_id UUID NOT NULL,
    cause_id VARCHAR(128) NOT NULL,
    score SMALLINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_anomaly_feedback_candidate_scores_feedback
        FOREIGN KEY (feedback_id) REFERENCES ai_anomaly_feedback (feedback_id)
        ON DELETE CASCADE,
    CONSTRAINT uq_ai_anomaly_feedback_candidate_scores UNIQUE (feedback_id, cause_id),
    CONSTRAINT chk_ai_anomaly_feedback_candidate_scores_score CHECK (score BETWEEN 1 AND 5)
);

CREATE INDEX IF NOT EXISTS idx_ai_anomaly_feedback_candidate_scores_cause
    ON ai_anomaly_feedback_candidate_scores (cause_id);

