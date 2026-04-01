from typing import Any

from .ragflow_client import ragflow_client


def retrieve_anomaly_knowledge(
    meter: str,
    anomaly_summary: str,
    question: str | None = None,
) -> list[dict[str, Any]]:
    """Return knowledge snippets for anomaly analysis from RAGFlow."""
    
    search_query = f"关于表计 {meter} 产生异常的原因：{anomaly_summary}"
    if question:
        search_query += f"。用户关注：{question}"
        
    chunks = ragflow_client.retrieve_chunks(question=search_query, top_k=3)
    
    # Format chunks into a consistent structure for prompting
    formatted_chunks = []
    for chunk in chunks:
        formatted_chunks.append({
            "content": chunk.get("content", ""),
            "document_name": chunk.get("document_keyword") or chunk.get("document_name", "Unknown Document")
        })
        
    return formatted_chunks
