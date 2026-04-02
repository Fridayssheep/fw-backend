from __future__ import annotations

from typing import Any

from .ragflow_client import ragflow_client


def _trim_text(value: str, max_length: int) -> str:
    """裁剪长文本，避免知识片段过长。"""

    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def search_domain_knowledge_references(
    query: str,
    *,
    top_k: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """执行通用知识库检索，返回结构化引用。

    这是共享能力：
    - MCP `search_domain_knowledge` 调它
    - `/ai/qa` 的知识问答分支也调它
    """

    normalized_query = query.strip()
    if not normalized_query:
        return {"chunks": [], "doc_aggs": []}
    return ragflow_client.retrieve_references(
        question=normalized_query,
        top_k=top_k,
    )


def answer_with_domain_knowledge(
    question: str,
    *,
    chat_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """执行基于 RAGFlow chats_openai 的知识问答。

    这是共享能力：
    - MCP `answer_with_domain_knowledge` 调它
    - 后续如果 `/ai/qa` 需要启用“知识问答直出答案”策略，也可以直接复用
    """

    normalized_question = question.strip()
    if not normalized_question:
        return {
            "answer": "",
            "session_id": session_id,
            "references": {"chunks": [], "doc_aggs": []},
            "raw": {},
        }
    return ragflow_client.chat_completion(
        question=normalized_question,
        chat_id=chat_id,
        session_id=session_id,
    )


def build_compact_knowledge_items(
    references: dict[str, list[dict[str, Any]]],
    *,
    max_items: int = 5,
    snippet_length: int = 320,
) -> list[dict[str, Any]]:
    """把结构化 retrieval 结果压缩成轻量知识引用。"""

    items: list[dict[str, Any]] = []
    for chunk in (references.get("chunks", []) or [])[:max_items]:
        items.append(
            {
                "document_id": chunk.get("document_id"),
                "document_name": chunk.get("document_name"),
                "chunk_id": chunk.get("chunk_id"),
                "snippet": _trim_text(str(chunk.get("content") or ""), snippet_length),
                "score": chunk.get("similarity"),
                "dataset_id": chunk.get("dataset_id"),
            }
        )
    return items


def retrieve_anomaly_knowledge(
    meter: str,
    anomaly_summary: str,
    question: str | None = None,
) -> list[dict[str, Any]]:
    """为异常分析提供轻量知识片段。"""

    search_query = f"关于表计 {meter} 产生异常的原因：{anomaly_summary}"
    if question:
        search_query += f"。用户关注：{question}"

    references = search_domain_knowledge_references(
        search_query,
        top_k=3,
    )
    compact_items = build_compact_knowledge_items(
        references,
        max_items=3,
        snippet_length=240,
    )
    return [
        {
            "content": item.get("snippet", ""),
            "document_name": item.get("document_name") or "Unknown Document",
        }
        for item in compact_items
    ]
