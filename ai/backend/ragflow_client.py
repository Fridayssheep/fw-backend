import logging
from typing import Any
from urllib.parse import unquote

import httpx

from .config import get_ai_settings


logger = logging.getLogger(__name__)


class RagFlowError(Exception):
    """Base exception for RAGFlow integration."""


class RagFlowConfigurationError(RagFlowError):
    """Raised when required RAGFlow config is missing."""


class RagFlowAuthenticationError(RagFlowError):
    """Raised when upstream auth fails."""


class RagFlowNotFoundError(RagFlowError):
    """Raised when upstream resource is not found."""


class RagFlowTimeoutError(RagFlowError):
    """Raised when upstream request times out."""


class RagFlowUpstreamError(RagFlowError):
    """Raised when upstream request fails."""


class RagFlowInvalidResponseError(RagFlowError):
    """Raised when upstream response shape is invalid."""


class RagFlowClient:
    """Thin HTTP client for RAGFlow retrieval and chat APIs."""

    def __init__(self, api_url: str | None = None, api_key: str | None = None):
        self._api_url_override = api_url
        self._api_key_override = api_key

    def _settings(self):
        return get_ai_settings()

    def _api_url(self) -> str:
        return (self._api_url_override or self._settings().ragflow_api_url).rstrip("/")

    def _api_key(self) -> str:
        return self._api_key_override or self._settings().ragflow_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key()}",
        }

    def _ensure_basic_config(self) -> None:
        if not self._api_url():
            raise RagFlowConfigurationError("RAGFlow API URL 未配置。")
        if not self._api_key():
            raise RagFlowConfigurationError("RAGFlow API key 未配置。")

    def _handle_response_errors(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise RagFlowAuthenticationError("RAGFlow 鉴权失败，请检查 API key。")
        if response.status_code == 404:
            raise RagFlowNotFoundError("RAGFlow 上游资源不存在，请检查 Chat ID 或路径配置。")
        if 400 <= response.status_code < 500:
            raise RagFlowUpstreamError(f"RAGFlow 请求被拒绝: HTTP {response.status_code}。")
        if response.status_code >= 500:
            raise RagFlowUpstreamError(f"RAGFlow 上游服务异常: HTTP {response.status_code}。")

    def _request_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._settings().ragflow_timeout_seconds, trust_env=False) as client:
                response = client.post(url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise RagFlowTimeoutError("RAGFlow 请求超时。") from exc
        except httpx.RequestError as exc:
            raise RagFlowUpstreamError(f"无法连接到 RAGFlow 服务: {exc}") from exc

        self._handle_response_errors(response)

        try:
            return response.json()
        except ValueError as exc:
            raise RagFlowInvalidResponseError("RAGFlow 返回了无法解析的 JSON。") from exc

    def _request_get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._settings().ragflow_timeout_seconds, trust_env=False) as client:
                response = client.get(url, headers=self._headers(), params=params)
        except httpx.TimeoutException as exc:
            raise RagFlowTimeoutError("RAGFlow 请求超时。") from exc
        except httpx.RequestError as exc:
            raise RagFlowUpstreamError(f"无法连接到 RAGFlow 服务: {exc}") from exc

        self._handle_response_errors(response)
        try:
            return response.json()
        except ValueError as exc:
            raise RagFlowInvalidResponseError("RAGFlow 返回了无法解析的 JSON。") from exc

    def _request_get_bytes(self, url: str) -> tuple[bytes, httpx.Headers]:
        try:
            with httpx.Client(timeout=self._settings().ragflow_timeout_seconds, trust_env=False) as client:
                response = client.get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise RagFlowTimeoutError("RAGFlow 请求超时。") from exc
        except httpx.RequestError as exc:
            raise RagFlowUpstreamError(f"无法连接到 RAGFlow 服务: {exc}") from exc

        self._handle_response_errors(response)
        return response.content, response.headers

    def _normalize_reference(self, raw_reference: Any) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(raw_reference, dict):
            return {"chunks": [], "doc_aggs": []}

        raw_chunks = raw_reference.get("chunks", []) or []
        if isinstance(raw_chunks, dict):
            chunk_items = [item for item in raw_chunks.values() if isinstance(item, dict)]
        elif isinstance(raw_chunks, list):
            chunk_items = [item for item in raw_chunks if isinstance(item, dict)]
        else:
            chunk_items = []

        normalized_chunks: list[dict[str, Any]] = []
        for item in chunk_items:
            normalized_chunks.append(
                {
                    "chunk_id": item.get("chunk_id") or item.get("id"),
                    "document_id": item.get("document_id") or item.get("doc_id"),
                    "document_name": item.get("document_name") or item.get("document_keyword") or item.get("doc_name"),
                    "dataset_id": item.get("dataset_id"),
                    "content": item.get("content") or item.get("snippet") or item.get("text") or "",
                    "similarity": item.get("similarity") or item.get("vector_similarity") or item.get("term_similarity"),
                    "metadata": item,
                }
            )

        raw_doc_aggs = raw_reference.get("doc_aggs", []) or []
        if isinstance(raw_doc_aggs, dict):
            doc_agg_items = [item for item in raw_doc_aggs.values() if isinstance(item, dict)]
        elif isinstance(raw_doc_aggs, list):
            doc_agg_items = [item for item in raw_doc_aggs if isinstance(item, dict)]
        else:
            doc_agg_items = []

        normalized_doc_aggs: list[dict[str, Any]] = []
        for item in doc_agg_items:
            normalized_doc_aggs.append(
                {
                    "document_id": item.get("document_id") or item.get("doc_id"),
                    "document_name": item.get("document_name") or item.get("doc_name") or item.get("name"),
                    "count": item.get("count") or item.get("hit_count"),
                    "metadata": item,
                }
            )

        return {
            "chunks": normalized_chunks,
            "doc_aggs": normalized_doc_aggs,
        }

    def _normalize_retrieval_chunk(self, raw_chunk: dict[str, Any]) -> dict[str, Any]:
        similarity = (
            raw_chunk.get("similarity")
            or raw_chunk.get("vector_similarity")
            or raw_chunk.get("term_similarity")
            or raw_chunk.get("score")
        )
        try:
            similarity_value = float(similarity) if similarity is not None else None
        except (TypeError, ValueError):
            similarity_value = None

        return {
            "chunk_id": raw_chunk.get("chunk_id") or raw_chunk.get("id"),
            "document_id": raw_chunk.get("document_id") or raw_chunk.get("doc_id"),
            "document_name": raw_chunk.get("document_name") or raw_chunk.get("document_keyword") or raw_chunk.get("doc_name"),
            "dataset_id": raw_chunk.get("dataset_id") or raw_chunk.get("kb_id"),
            "content": raw_chunk.get("content") or raw_chunk.get("snippet") or raw_chunk.get("text") or "",
            "similarity": similarity_value,
            "metadata": raw_chunk,
        }

    def _normalize_retrieval_doc_aggs(self, raw_doc_aggs: Any) -> list[dict[str, Any]]:
        if isinstance(raw_doc_aggs, list):
            doc_agg_items = [item for item in raw_doc_aggs if isinstance(item, dict)]
        elif isinstance(raw_doc_aggs, dict):
            doc_agg_items = [item for item in raw_doc_aggs.values() if isinstance(item, dict)]
        else:
            doc_agg_items = []

        normalized_doc_aggs: list[dict[str, Any]] = []
        for item in doc_agg_items:
            count = item.get("count")
            try:
                normalized_count = int(count) if count is not None else None
            except (TypeError, ValueError):
                normalized_count = None

            normalized_doc_aggs.append(
                {
                    "document_id": item.get("document_id") or item.get("doc_id"),
                    "document_name": item.get("document_name") or item.get("doc_name") or item.get("name"),
                    "count": normalized_count,
                }
            )
        return normalized_doc_aggs

    def _build_doc_aggs_from_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        doc_stats: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        for chunk in chunks:
            document_id = chunk.get("document_id")
            document_name = chunk.get("document_name")
            doc_key = (document_id, document_name)
            if doc_key not in doc_stats:
                doc_stats[doc_key] = {
                    "document_id": document_id,
                    "document_name": document_name,
                    "count": 0,
                }
            doc_stats[doc_key]["count"] += 1

        return sorted(
            doc_stats.values(),
            key=lambda item: (
                -(item.get("count") or 0),
                item.get("document_name") or "",
                item.get("document_id") or "",
            ),
        )

    def _extract_data_list(self, body: dict[str, Any], *, list_key: str | None = None) -> list[dict[str, Any]]:
        data = body.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            if list_key and isinstance(data.get(list_key), list):
                return [item for item in data.get(list_key, []) if isinstance(item, dict)]
            if isinstance(data.get("items"), list):
                return [item for item in data.get("items", []) if isinstance(item, dict)]
            if isinstance(data.get("docs"), list):
                return [item for item in data.get("docs", []) if isinstance(item, dict)]
        raise RagFlowInvalidResponseError("RAGFlow 返回结构不符合预期。")

    def retrieve_references(
        self,
        question: str,
        dataset_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        settings = self._settings()
        if not self._api_key():
            logger.warning("RAGFlow API key 未配置，retrieve_references 直接返回空引用。")
            return {"chunks": [], "doc_aggs": []}

        datasets = dataset_ids or list(settings.ragflow_dataset_ids)
        if not datasets:
            logger.warning("RAGFlow dataset_ids 未配置，retrieve_references 直接返回空引用。")
            return {"chunks": [], "doc_aggs": []}

        url = f"{self._api_url()}/retrieval"
        payload = {
            "question": question,
            "dataset_ids": datasets,
            "top_k": top_k,
            "similarity_threshold": 0.2,
        }

        try:
            body = self._request_json(url, payload)
        except RagFlowError as exc:
            logger.exception("RAGFlow retrieval 调用失败: %s", exc)
            return {"chunks": [], "doc_aggs": []}

        if body.get("code") == 0 and isinstance(body.get("data"), dict):
            raw_chunks = body["data"].get("chunks", [])
            if not isinstance(raw_chunks, list):
                logger.error("RAGFlow retrieval chunks 字段不是 list: %s", body)
                return {"chunks": [], "doc_aggs": []}

            normalized_chunks = [
                self._normalize_retrieval_chunk(item)
                for item in raw_chunks
                if isinstance(item, dict)
            ]
            normalized_doc_aggs = self._normalize_retrieval_doc_aggs(body["data"].get("doc_aggs"))
            return {
                "chunks": normalized_chunks,
                "doc_aggs": normalized_doc_aggs or self._build_doc_aggs_from_chunks(normalized_chunks),
            }

        logger.error("RAGFlow retrieval 返回了非预期结构: %s", body)
        return {"chunks": [], "doc_aggs": []}

    def retrieve_chunks(
        self,
        question: str,
        dataset_ids: list[str] | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        references = self.retrieve_references(
            question=question,
            dataset_ids=dataset_ids,
            top_k=top_k,
        )
        return references.get("chunks", [])

    def chat_completion(
        self,
        question: str,
        chat_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_basic_config()
        settings = self._settings()

        chat = chat_id or settings.ragflow_default_chat_id
        if not chat:
            raise RagFlowConfigurationError("RAGFlow 默认 Chat ID 未配置。")

        url = f"{self._api_url()}/chats_openai/{chat}/chat/completions"
        payload: dict[str, Any] = {
            "model": settings.ragflow_chat_model,
            "messages": [
                {
                    "role": "user",
                    "content": question,
                }
            ],
            "stream": False,
        }
        if session_id:
            logger.warning("RAGFlow chats_openai 当前未使用 session_id 请求参数，已忽略传入值。")

        body = self._request_json(url, payload)

        if isinstance(body.get("choices"), list) and body["choices"]:
            message = body["choices"][0].get("message", {}) or {}
            answer = message.get("content")
            if not answer:
                raise RagFlowInvalidResponseError("RAGFlow 聊天返回缺少 answer 内容。")
            return {
                "answer": answer,
                "session_id": body.get("session_id") or body.get("conversation_id"),
                "references": self._normalize_reference(message.get("reference") or body.get("reference")),
                "raw": body,
            }

        if body.get("code") == 0 and isinstance(body.get("data"), dict):
            data = body["data"]
            answer = data.get("answer") or data.get("content")
            if not answer:
                raise RagFlowInvalidResponseError("RAGFlow 旧风格返回缺少 answer 内容。")
            return {
                "answer": answer,
                "session_id": data.get("session_id") or session_id,
                "references": self._normalize_reference(data.get("reference")),
                "raw": body,
            }

        raise RagFlowInvalidResponseError("RAGFlow 聊天返回结构不符合预期。")

    def list_datasets(self, page: int = 1, page_size: int = 100) -> list[dict[str, Any]]:
        self._ensure_basic_config()
        url = f"{self._api_url()}/datasets"
        body = self._request_get_json(
            url,
            params={
                "page": page,
                "page_size": page_size,
            },
        )
        datasets = self._extract_data_list(body)
        return [
            {
                "id": item.get("id") or item.get("dataset_id"),
                "name": item.get("name") or item.get("title"),
            }
            for item in datasets
            if item.get("id") or item.get("dataset_id")
        ]

    def list_dataset_documents(
        self,
        dataset_id: str,
        *,
        keywords: str | None = None,
        page: int = 1,
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        self._ensure_basic_config()
        url = f"{self._api_url()}/datasets/{dataset_id}/documents"
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
        }
        if keywords:
            params["keywords"] = keywords
        body = self._request_get_json(url, params=params)
        return self._extract_data_list(body, list_key="docs")

    def download_document(self, dataset_id: str, document_id: str) -> dict[str, Any]:
        self._ensure_basic_config()
        url = f"{self._api_url()}/datasets/{dataset_id}/documents/{document_id}"
        content, headers = self._request_get_bytes(url)
        content_disposition = str(headers.get("content-disposition") or "")
        filename = document_id
        if "filename*=" in content_disposition:
            filename = unquote(
                content_disposition.split("filename*=", 1)[1].split("''", 1)[-1].strip().strip('"')
            ) or filename
        elif "filename=" in content_disposition:
            filename = content_disposition.split("filename=", 1)[1].strip().strip('"') or filename
        return {
            "content": content,
            "content_type": headers.get("content-type") or "application/octet-stream",
            "filename": filename,
        }


ragflow_client = RagFlowClient()
