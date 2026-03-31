from typing import Any


def retrieve_anomaly_knowledge(
    meter: str,
    anomaly_summary: str,
    question: str | None = None,
) -> list[dict[str, Any]]:
    """Return knowledge snippets for anomaly analysis.

    This is intentionally a placeholder. The retrieval hook is kept separate so
    knowledge graph, RAPTOR, or RagFlow integration can be plugged in later
    without changing the HTTP route or orchestration service.
    """

    _ = meter, anomaly_summary, question
    return []
