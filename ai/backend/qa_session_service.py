from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import text

from app.core.database import engine
from app.schemas import AIQAContext
from app.schemas import AIQAReferences
from app.schemas import AIQASessionDetailResponse
from app.schemas import AIQASessionDeleteResponse
from app.schemas import AIQASessionListResponse
from app.schemas import AIQASessionMessage
from app.schemas import AIQASessionSummary
from app.schemas import AIQAResponse
from app.schemas import AISuggestedAction
from app.schemas import AIUsedToolItem
from app.schemas import Pagination
from app.services.service_common import ResourceNotFoundError
from app.services.service_common import get_timezone_now
from app.services.service_common import normalize_pagination


MAX_QA_HISTORY_MESSAGES = 6
FOLLOW_UP_MARKERS = (
    "那",
    "那么",
    "这个",
    "这个呢",
    "它",
    "然后",
    "继续",
    "再说",
    "还有",
    "为什么",
    "那最近",
    "那这个",
)


@dataclass(slots=True)
class QAChatSession:
    session_id: str
    sticky_context: AIQAContext | None
    last_question_type: str | None


@dataclass(slots=True)
class QAMessageRecord:
    role: str
    question_type: str | None
    content: str
    context_json: dict
    references_json: dict
    used_tools_json: list
    suggested_actions_json: list


def _generate_session_id() -> str:
    return f"qa_{uuid4().hex[:16]}"


def _generate_message_id() -> str:
    return f"qa_msg_{uuid4().hex[:20]}"


def _context_to_dict(context: AIQAContext | None) -> dict:
    if not context:
        return {}
    return context.model_dump(mode="json", exclude_none=True)


def _dict_to_context(value: dict | None) -> AIQAContext | None:
    if not value:
        return None
    return AIQAContext.model_validate(value)


def _build_session_title(question: str) -> str:
    normalized = " ".join(question.strip().split())
    if not normalized:
        return "新会话"
    return normalized[:60]


def _strip_null_chars_from_text(value: str) -> str:
    return value.replace("\x00", "")


def _sanitize_json_payload(value: object) -> object:
    if isinstance(value, str):
        return _strip_null_chars_from_text(value)
    if isinstance(value, list):
        return [_sanitize_json_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_json_payload(item)
            for key, item in value.items()
        }
    return value


def _safe_json_dumps(value: object) -> str:
    return json.dumps(_sanitize_json_payload(value), ensure_ascii=False)


def _trim_preview(value: str | None, max_length: int = 120) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def _parse_references(value: dict | None) -> AIQAReferences:
    if not value:
        return AIQAReferences()
    return AIQAReferences.model_validate(value)


def _parse_used_tools(value: list | None) -> list[AIUsedToolItem]:
    if not value:
        return []
    return [AIUsedToolItem.model_validate(item) for item in value]


def _parse_suggested_actions(value: list | None) -> list[AISuggestedAction]:
    if not value:
        return []
    return [AISuggestedAction.model_validate(item) for item in value]


def _build_session_summary_from_row(row: dict) -> AIQASessionSummary:
    return AIQASessionSummary(
        session_id=row["session_id"],
        title=row["title"] or "新会话",
        last_question_type=row["last_question_type"],
        sticky_context=_dict_to_context(row.get("sticky_context_json") or {}),
        last_message=_trim_preview(row.get("last_message")),
        message_count=int(row.get("message_count") or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _get_latest_user_question(recent_messages: list[QAMessageRecord]) -> str | None:
    for item in reversed(recent_messages):
        if item.role == "user" and item.content.strip():
            return item.content.strip()
    return None


def _extract_context_from_recent_messages(recent_messages: list[QAMessageRecord]) -> AIQAContext | None:
    for item in reversed(recent_messages):
        context = _dict_to_context(item.context_json)
        if context:
            return context
    return None


def _merge_context(
    request_context: AIQAContext | None,
    sticky_context: AIQAContext | None,
    recent_messages: list[QAMessageRecord],
) -> AIQAContext | None:
    recent_context = _extract_context_from_recent_messages(recent_messages)
    merged: dict = {}
    for source in (recent_context, sticky_context, request_context):
        merged.update(_context_to_dict(source))
    return _dict_to_context(merged) if merged else None


def _build_context_prefix(context: AIQAContext | None) -> str:
    if not context:
        return ""
    parts: list[str] = []
    if context.building_id:
        parts.append(f"建筑={context.building_id}")
    if context.meter:
        parts.append(f"表计={context.meter}")
    if context.time_range:
        parts.append(
            "时间范围="
            f"{context.time_range.start.isoformat()} 至 {context.time_range.end.isoformat()}"
        )
    if not parts:
        return ""
    return "当前上下文：" + "；".join(parts)


def _is_follow_up_question(question: str, context: AIQAContext | None) -> bool:
    stripped = question.strip()
    if len(stripped) <= 8:
        return True
    if any(marker in stripped for marker in FOLLOW_UP_MARKERS):
        return True
    lowered = stripped.lower()
    if not context and not any(token in lowered for token in ("trend", "compare", "cop")):
        return True
    return False


def rewrite_followup_question(
    question: str,
    context: AIQAContext | None,
    recent_messages: list[QAMessageRecord],
) -> str:
    # 先做轻量追问补全，避免“那最近30天呢”这类问题在下游被当成无上下文短句。
    if not _is_follow_up_question(question, context):
        return question

    previous_question = _get_latest_user_question(recent_messages)
    context_prefix = _build_context_prefix(context)
    fragments = [part for part in (context_prefix, f"上一轮问题：{previous_question}" if previous_question else "", f"当前追问：{question}") if part]
    return "。".join(fragments) if fragments else question


def get_or_create_session(session_id: str | None, request_context: AIQAContext | None) -> QAChatSession:
    if session_id:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT session_id, sticky_context_json, last_question_type
                    FROM ai_qa_sessions
                    WHERE session_id = :session_id
                    """
                ),
                {"session_id": session_id},
            ).mappings().first()
        if not row:
            raise ValueError(f"qa session not found: {session_id}")
        return QAChatSession(
            session_id=row["session_id"],
            sticky_context=_dict_to_context(row["sticky_context_json"] or {}),
            last_question_type=row["last_question_type"],
        )

    new_session_id = _generate_session_id()
    sticky_context = _context_to_dict(request_context)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_qa_sessions (
                    session_id,
                    title,
                    sticky_context_json,
                    created_at,
                    updated_at
                ) VALUES (
                    :session_id,
                    :title,
                    CAST(:sticky_context_json AS jsonb),
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "session_id": new_session_id,
                "title": None,
                "sticky_context_json": json.dumps(sticky_context, ensure_ascii=False),
                "created_at": get_timezone_now(),
                "updated_at": get_timezone_now(),
            },
        )
    return QAChatSession(
        session_id=new_session_id,
        sticky_context=request_context,
        last_question_type=None,
    )


def load_recent_messages(session_id: str, limit: int = MAX_QA_HISTORY_MESSAGES) -> list[QAMessageRecord]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT role, question_type, content, context_json, references_json, used_tools_json, suggested_actions_json
                FROM ai_qa_messages
                WHERE session_id = :session_id
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"session_id": session_id, "limit": limit},
        ).mappings().all()
    records = [
        QAMessageRecord(
            role=row["role"],
            question_type=row["question_type"],
            content=row["content"],
            context_json=row["context_json"] or {},
            references_json=row["references_json"] or {},
            used_tools_json=row["used_tools_json"] or [],
            suggested_actions_json=row["suggested_actions_json"] or [],
        )
        for row in reversed(rows)
    ]
    return records


def build_effective_context(
    session: QAChatSession,
    request_context: AIQAContext | None,
    recent_messages: list[QAMessageRecord],
) -> AIQAContext | None:
    return _merge_context(request_context, session.sticky_context, recent_messages)


def list_sessions(page: int = 1, page_size: int = 20) -> AIQASessionListResponse:
    safe_page, safe_page_size, offset = normalize_pagination(page, page_size, 100)
    with engine.connect() as connection:
        total = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*) AS total
                    FROM ai_qa_sessions
                    """
                )
            ).scalar_one()
        )
        rows = connection.execute(
            text(
                """
                SELECT
                    s.session_id,
                    s.title,
                    s.sticky_context_json,
                    s.last_question_type,
                    s.created_at,
                    s.updated_at,
                    COALESCE(message_stats.message_count, 0) AS message_count,
                    last_message.content AS last_message
                FROM ai_qa_sessions AS s
                LEFT JOIN (
                    SELECT session_id, COUNT(*) AS message_count
                    FROM ai_qa_messages
                    GROUP BY session_id
                ) AS message_stats
                    ON message_stats.session_id = s.session_id
                LEFT JOIN LATERAL (
                    SELECT content
                    FROM ai_qa_messages
                    WHERE session_id = s.session_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS last_message ON TRUE
                ORDER BY s.updated_at DESC, s.created_at DESC
                LIMIT :limit
                OFFSET :offset
                """
            ),
            {"limit": safe_page_size, "offset": offset},
        ).mappings().all()

    return AIQASessionListResponse(
        items=[_build_session_summary_from_row(row) for row in rows],
        pagination=Pagination(page=safe_page, page_size=safe_page_size, total=total),
    )


def get_session_detail(session_id: str) -> AIQASessionDetailResponse:
    with engine.connect() as connection:
        session_row = connection.execute(
            text(
                """
                SELECT
                    s.session_id,
                    s.title,
                    s.sticky_context_json,
                    s.last_question_type,
                    s.created_at,
                    s.updated_at,
                    COUNT(m.message_id) AS message_count,
                    (
                        SELECT content
                        FROM ai_qa_messages
                        WHERE session_id = s.session_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) AS last_message
                FROM ai_qa_sessions AS s
                LEFT JOIN ai_qa_messages AS m
                    ON m.session_id = s.session_id
                WHERE s.session_id = :session_id
                GROUP BY
                    s.session_id,
                    s.title,
                    s.sticky_context_json,
                    s.last_question_type,
                    s.created_at,
                    s.updated_at
                """
            ),
            {"session_id": session_id},
        ).mappings().first()
        if not session_row:
            raise ResourceNotFoundError(f"未找到 AI 会话 {session_id}")

        message_rows = connection.execute(
            text(
                """
                SELECT
                    message_id,
                    role,
                    question_type,
                    content,
                    context_json,
                    references_json,
                    used_tools_json,
                    suggested_actions_json,
                    created_at
                FROM ai_qa_messages
                WHERE session_id = :session_id
                ORDER BY created_at ASC
                """
            ),
            {"session_id": session_id},
        ).mappings().all()

    return AIQASessionDetailResponse(
        session=_build_session_summary_from_row(session_row),
        messages=[
            AIQASessionMessage(
                message_id=row["message_id"],
                role=row["role"],
                question_type=row["question_type"],
                content=row["content"],
                context=_dict_to_context(row["context_json"] or {}),
                references=_parse_references(row["references_json"] or {}),
                used_tools=_parse_used_tools(row["used_tools_json"] or []),
                suggested_actions=_parse_suggested_actions(row["suggested_actions_json"] or []),
                created_at=row["created_at"],
            )
            for row in message_rows
        ],
    )


def save_user_message(session_id: str, question: str, context: AIQAContext | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_qa_messages (
                    message_id,
                    session_id,
                    role,
                    content,
                    context_json,
                    references_json,
                    used_tools_json,
                    suggested_actions_json,
                    created_at
                ) VALUES (
                    :message_id,
                    :session_id,
                    'user',
                    :content,
                    CAST(:context_json AS jsonb),
                    '{}'::jsonb,
                    '[]'::jsonb,
                    '[]'::jsonb,
                    :created_at
                )
                """
            ),
            {
                "message_id": _generate_message_id(),
                "session_id": session_id,
                "content": _strip_null_chars_from_text(question),
                "context_json": _safe_json_dumps(_context_to_dict(context)),
                "created_at": get_timezone_now(),
            },
        )


def save_assistant_message(session_id: str, response: AIQAResponse, context: AIQAContext | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_qa_messages (
                    message_id,
                    session_id,
                    role,
                    question_type,
                    content,
                    context_json,
                    references_json,
                    used_tools_json,
                    suggested_actions_json,
                    created_at
                ) VALUES (
                    :message_id,
                    :session_id,
                    'assistant',
                    :question_type,
                    :content,
                    CAST(:context_json AS jsonb),
                    CAST(:references_json AS jsonb),
                    CAST(:used_tools_json AS jsonb),
                    CAST(:suggested_actions_json AS jsonb),
                    :created_at
                )
                """
            ),
            {
                "message_id": _generate_message_id(),
                "session_id": session_id,
                "question_type": response.question_type,
                "content": _strip_null_chars_from_text(response.answer),
                "context_json": _safe_json_dumps(_context_to_dict(context)),
                "references_json": _safe_json_dumps(response.references.model_dump(mode="json")),
                "used_tools_json": _safe_json_dumps([item.model_dump(mode="json") for item in response.used_tools]),
                "suggested_actions_json": _safe_json_dumps([item.model_dump(mode="json") for item in response.suggested_actions]),
                "created_at": get_timezone_now(),
            },
        )


def update_session_state(
    session_id: str,
    latest_question: str,
    response: AIQAResponse,
    context: AIQAContext | None,
) -> None:
    # sticky_context 只保留当前对话后续最可能复用的业务上下文，避免每轮都要求前端重传。
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE ai_qa_sessions
                SET
                    title = COALESCE(title, :title),
                    sticky_context_json = CAST(:sticky_context_json AS jsonb),
                    last_question_type = :last_question_type,
                    updated_at = :updated_at
                WHERE session_id = :session_id
                """
            ),
            {
                "session_id": session_id,
                "title": _build_session_title(latest_question),
                "sticky_context_json": _safe_json_dumps(_context_to_dict(context)),
                "last_question_type": response.question_type,
                "updated_at": get_timezone_now(),
            },
        )


def save_error_message(session_id: str, error_message: str, context: AIQAContext | None) -> None:
    """保存失败态 assistant 消息，便于排查会话中断原因。"""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_qa_messages (
                    message_id,
                    session_id,
                    role,
                    question_type,
                    content,
                    context_json,
                    references_json,
                    used_tools_json,
                    suggested_actions_json,
                    created_at
                ) VALUES (
                    :message_id,
                    :session_id,
                    'assistant',
                    'error',
                    :content,
                    CAST(:context_json AS jsonb),
                    '{}'::jsonb,
                    '[]'::jsonb,
                    '[]'::jsonb,
                    :created_at
                )
                """
            ),
            {
                "message_id": _generate_message_id(),
                "session_id": session_id,
                "content": _strip_null_chars_from_text(error_message),
                "context_json": _safe_json_dumps(_context_to_dict(context)),
                "created_at": get_timezone_now(),
            },
        )


def update_session_failure_state(
    session_id: str,
    latest_question: str,
    error_message: str,
    context: AIQAContext | None,
) -> None:
    """在下游失败时仍更新会话标题与失败状态，避免留下半截 session。"""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE ai_qa_sessions
                SET
                    title = COALESCE(title, :title),
                    sticky_context_json = CAST(:sticky_context_json AS jsonb),
                    last_question_type = 'error',
                    updated_at = :updated_at
                WHERE session_id = :session_id
                """
            ),
            {
                "session_id": session_id,
                "title": _build_session_title(latest_question),
                "sticky_context_json": _safe_json_dumps(_context_to_dict(context)),
                "updated_at": get_timezone_now(),
            },
        )


def delete_session(session_id: str) -> AIQASessionDeleteResponse:
    """删除 AI 对话会话，并级联删除其历史消息。"""

    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT session_id
                FROM ai_qa_sessions
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_id},
        ).mappings().first()
        if not row:
            raise ResourceNotFoundError(f"未找到 AI 会话 {session_id}")
        connection.execute(
            text(
                """
                DELETE FROM ai_qa_sessions
                WHERE session_id = :session_id
                """
            ),
            {"session_id": session_id},
        )

    return AIQASessionDeleteResponse(
        session_id=session_id,
        deleted=True,
        message="AI 会话已删除。",
    )
