CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ai_qa_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(128),
    title VARCHAR(255),
    sticky_context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_question_type VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_qa_sessions_updated_at
    ON ai_qa_sessions (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_qa_sessions_last_question_type
    ON ai_qa_sessions (last_question_type);


CREATE TABLE IF NOT EXISTS ai_qa_messages (
    message_id VARCHAR(64) PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    question_type VARCHAR(64),
    content TEXT NOT NULL,
    context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    references_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    used_tools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ai_qa_messages_session
        FOREIGN KEY (session_id) REFERENCES ai_qa_sessions (session_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_ai_qa_messages_role
        CHECK (role IN ('user', 'assistant'))
);

CREATE INDEX IF NOT EXISTS idx_ai_qa_messages_session_created_at
    ON ai_qa_messages (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_qa_messages_question_type
    ON ai_qa_messages (question_type);
