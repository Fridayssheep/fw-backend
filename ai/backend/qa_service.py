from app.schemas import AIQAMeta
from app.schemas import AIQAReference
from app.schemas import AIQAReferenceChunk
from app.schemas import AIQAReferenceDocAgg
from app.schemas import AIQARequest
from app.schemas import AIQAResponse

from .config import get_ai_settings
from .ragflow_client import ragflow_client


MAX_QA_REFERENCE_CHUNKS = 5
MAX_QA_REFERENCE_DOC_AGGS = 5
MAX_QA_REFERENCE_CONTENT_LENGTH = 600


def _trim_text(value: str, max_length: int) -> str:
    """裁剪长文本，避免引用内容过大。"""

    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _build_compact_chunk(item: dict) -> AIQAReferenceChunk:
    """构造给前端展示的轻量引用片段。

    /ai/qa 的 references 只用于前端证据展示，不给 MCP 拼接大上下文，
    所以这里主动裁剪 content 和 metadata，避免响应体过大。
    """

    raw_metadata = item.get("metadata") or {}
    compact_metadata = {}
    if isinstance(raw_metadata, dict):
        for key in ("doc_type_kwd", "image_id", "positions"):
            if key in raw_metadata:
                compact_metadata[key] = raw_metadata[key]

    return AIQAReferenceChunk(
        chunk_id=item.get("chunk_id"),
        document_id=item.get("document_id"),
        document_name=item.get("document_name"),
        dataset_id=item.get("dataset_id"),
        content=_trim_text(str(item.get("content") or ""), MAX_QA_REFERENCE_CONTENT_LENGTH),
        similarity=item.get("similarity"),
        metadata=compact_metadata,
    )


def _build_compact_references(references: dict) -> AIQAReference:
    """把 retrieval 结果压缩成适合前端展示的轻量结构。"""

    chunks = references.get("chunks", [])[:MAX_QA_REFERENCE_CHUNKS]
    doc_aggs = references.get("doc_aggs", [])[:MAX_QA_REFERENCE_DOC_AGGS]
    return AIQAReference(
        chunks=[_build_compact_chunk(item) for item in chunks],
        doc_aggs=[AIQAReferenceDocAgg(**item) for item in doc_aggs],
    )


def ask_ai_question(payload: AIQARequest) -> AIQAResponse:
    """执行知识库问答，并把 RAGFlow 返回结果规范化成统一响应。

    当前采用双阶段：
    1. 先走 retrieval 拿稳定的结构化引用
    2. 再走 chats_openai 拿自然语言答案和会话 ID

    这样即使 chats_openai 不稳定返回 reference，/ai/qa 仍然能把文档引用返回给前端。
    """

    settings = get_ai_settings()
    retrieval_references = ragflow_client.retrieve_references(
        question=payload.question,
        top_k=5,
    )
    chat_result = ragflow_client.chat_completion(
        question=payload.question,
        session_id=payload.session_id,
    )

    # 优先使用 retrieval 阶段拿到的结构化引用；如果 retrieval 因配置或上游问题为空，
    # 再退回 chats_openai 自带的 reference，避免把已有信息丢掉。
    references = retrieval_references
    if not references.get("chunks"):
        references = chat_result.get("references") or {"chunks": [], "doc_aggs": []}

    return AIQAResponse(
        answer=chat_result.get("answer", "No answer generated."),
        session_id=chat_result.get("session_id"),
        references=_build_compact_references(references),
        meta=AIQAMeta(
            provider="ragflow",
            chat_id=settings.ragflow_default_chat_id,
            used_openai_compatible=True,
        ),
    )
