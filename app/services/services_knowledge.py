from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from ai.backend.config import get_ai_settings
from ai.backend.ragflow_client import ragflow_client

from app.schemas.schemas_common import Pagination
from app.schemas.schemas_knowledge import KnowledgeDocument
from app.schemas.schemas_knowledge import KnowledgeDocumentListResponse
from app.services.service_common import ResourceNotFoundError


MAX_UPSTREAM_DOCUMENT_PAGE_SIZE = 200


@dataclass(slots=True)
class KnowledgeDownloadResult:
    content: bytes
    media_type: str
    filename: str
    content_disposition: str


def _extract_source_type(filename: str) -> str | None:
    if "." not in filename:
        return None
    suffix = filename.rsplit(".", 1)[-1].strip().lower()
    return suffix or None


def _normalize_updated_at(raw_value: object) -> tuple[str | None, float]:
    if raw_value is None or raw_value == "":
        return None, 0.0
    if isinstance(raw_value, (int, float)):
        timestamp = float(raw_value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        try:
            iso_value = datetime.fromtimestamp(timestamp).astimezone().isoformat()
        except (OSError, OverflowError, ValueError):
            return None, 0.0
        return iso_value, timestamp
    text_value = str(raw_value).strip()
    if not text_value:
        return None, 0.0
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        return parsed.isoformat(), parsed.timestamp()
    except ValueError:
        return text_value, 0.0


def _get_accessible_datasets() -> list[dict]:
    settings = get_ai_settings()
    configured_dataset_ids = set(settings.ragflow_dataset_ids)
    datasets = ragflow_client.list_datasets(page_size=100)
    if configured_dataset_ids:
        datasets = [item for item in datasets if str(item.get("id") or "") in configured_dataset_ids]
    return datasets


def list_knowledge_documents(
    *,
    keyword: str | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> KnowledgeDocumentListResponse:
    datasets = _get_accessible_datasets()
    categories_available = sorted(
        {
            str(item.get("name") or "").strip()
            for item in datasets
            if str(item.get("name") or "").strip()
        },
        key=lambda item: item.lower(),
    )
    if category:
        datasets = [item for item in datasets if str(item.get("name") or "").strip() == category]

    merged_documents: list[tuple[float, KnowledgeDocument]] = []
    for dataset in datasets:
        dataset_id = str(dataset.get("id") or "").strip()
        dataset_name = str(dataset.get("name") or "").strip() or dataset_id
        if not dataset_id:
            continue
        documents = ragflow_client.list_dataset_documents(
            dataset_id,
            keywords=keyword,
            page=1,
            page_size=MAX_UPSTREAM_DOCUMENT_PAGE_SIZE,
        )
        for document in documents:
            title = str(document.get("name") or document.get("title") or document.get("id") or "").strip()
            updated_at, updated_sort_value = _normalize_updated_at(
                document.get("update_time") or document.get("updated_at") or document.get("create_time") or document.get("created_at")
            )
            size_value = document.get("size")
            try:
                size = int(size_value) if size_value is not None else None
            except (TypeError, ValueError):
                size = None
            merged_documents.append(
                (
                    updated_sort_value,
                    KnowledgeDocument(
                        document_id=str(document.get("id") or "").strip(),
                        dataset_id=dataset_id,
                        title=title,
                        category=dataset_name,
                        source_type=_extract_source_type(title),
                        updated_at=updated_at,
                        size=size,
                    ),
                )
            )

    merged_documents.sort(
        key=lambda item: (
            -item[0],
            item[1].title.lower(),
            item[1].document_id,
        )
    )
    items = [item for _, item in merged_documents]
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    paginated_items = items[start_index:end_index]
    return KnowledgeDocumentListResponse(
        items=paginated_items,
        pagination=Pagination(page=page, page_size=page_size, total=len(items)),
        categories_available=categories_available,
    )


def download_knowledge_document(dataset_id: str, document_id: str) -> KnowledgeDownloadResult:
    dataset_id = dataset_id.strip()
    document_id = document_id.strip()
    if not dataset_id or not document_id:
        raise ValueError("dataset_id 和 document_id 不能为空。")

    accessible_datasets = _get_accessible_datasets()
    allowed_dataset_ids = {str(item.get("id") or "").strip() for item in accessible_datasets}
    if dataset_id not in allowed_dataset_ids:
        raise ResourceNotFoundError(f"未找到可访问的数据集 {dataset_id}")

    upstream_result = ragflow_client.download_document(dataset_id, document_id)
    filename = upstream_result.get("filename") or document_id
    filename = str(filename).strip() or document_id
    encoded_filename = quote(filename)
    return KnowledgeDownloadResult(
        content=upstream_result["content"],
        media_type=str(upstream_result.get("content_type") or "application/octet-stream"),
        filename=filename,
        content_disposition=f"attachment; filename*=UTF-8''{encoded_filename}",
    )
