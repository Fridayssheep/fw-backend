from app.schemas import AIQAMeta
from app.schemas import AIQAReference
from app.schemas import AIQAReferenceChunk
from app.schemas import AIQAReferenceDocAgg
from app.schemas import AIQARequest
from app.schemas import AIQAResponse

from .config import get_ai_settings
from .ragflow_client import ragflow_client


def ask_ai_question(payload: AIQARequest) -> AIQAResponse:
    """执行知识库问答，并把 RAGFlow 返回结果规范化成统一响应。"""

    settings = get_ai_settings()
    result = ragflow_client.chat_completion(
        question=payload.question,
        session_id=payload.session_id,
    )

    references = result.get("references") or {}
    return AIQAResponse(
        answer=result.get("answer", "No answer generated."),
        session_id=result.get("session_id"),
        references=AIQAReference(
            chunks=[AIQAReferenceChunk(**item) for item in references.get("chunks", [])],
            doc_aggs=[AIQAReferenceDocAgg(**item) for item in references.get("doc_aggs", [])],
        ),
        meta=AIQAMeta(
            provider="ragflow",
            chat_id=settings.ragflow_default_chat_id,
            used_openai_compatible=True,
        ),
    )
