import logging
from typing import Any

import httpx

from .config import get_ai_settings


logger = logging.getLogger(__name__)


class RagFlowError(Exception):
    """RAGFlow 调用基础异常。"""


class RagFlowConfigurationError(RagFlowError):
    """RAGFlow 配置缺失或不合法。"""


class RagFlowAuthenticationError(RagFlowError):
    """RAGFlow 鉴权失败。"""


class RagFlowNotFoundError(RagFlowError):
    """RAGFlow 上游资源不存在。"""


class RagFlowTimeoutError(RagFlowError):
    """RAGFlow 请求超时。"""


class RagFlowUpstreamError(RagFlowError):
    """RAGFlow 上游服务错误。"""


class RagFlowInvalidResponseError(RagFlowError):
    """RAGFlow 返回结构不符合预期。"""


class RagFlowClient:
    """RAGFlow HTTP 客户端封装。

    当前保留两类能力：
    1. retrieval：用于异常分析和 MCP 的知识检索
    2. chats_openai：用于 /ai/qa 的 OpenAI-compatible 问答
    """

    def __init__(self, api_url: str | None = None, api_key: str | None = None):
        settings = get_ai_settings()
        self._settings = settings
        self.api_url = (api_url or settings.ragflow_api_url).rstrip("/")
        self.api_key = api_key or settings.ragflow_api_key

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _ensure_basic_config(self) -> None:
        if not self.api_key:
            raise RagFlowConfigurationError("RAGFlow API key 未配置。")

    def _request_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """统一发送请求并按 HTTP 状态码映射为明确的上游异常。"""

        try:
            with httpx.Client(timeout=self._settings.ragflow_timeout_seconds, trust_env=False) as client:
                response = client.post(url, headers=self._get_headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise RagFlowTimeoutError("RAGFlow 请求超时。") from exc
        except httpx.RequestError as exc:
            raise RagFlowUpstreamError(f"无法连接到 RAGFlow 服务: {exc}") from exc

        if response.status_code in {401, 403}:
            raise RagFlowAuthenticationError("RAGFlow 鉴权失败，请检查 API key。")
        if response.status_code == 404:
            raise RagFlowNotFoundError("RAGFlow 上游资源不存在，请检查 Chat ID 或路径配置。")
        if 400 <= response.status_code < 500:
            raise RagFlowUpstreamError(f"RAGFlow 请求被拒绝: HTTP {response.status_code}。")
        if response.status_code >= 500:
            raise RagFlowUpstreamError(f"RAGFlow 上游服务异常: HTTP {response.status_code}。")

        try:
            return response.json()
        except ValueError as exc:
            raise RagFlowInvalidResponseError("RAGFlow 返回了无法解析的 JSON。") from exc

    def _normalize_reference(self, raw_reference: Any) -> dict[str, list[dict[str, Any]]]:
        """把 RAGFlow 的引用信息整理成统一结构。

        RAGFlow 在不同接口/版本下，reference.chunks 和 reference.doc_aggs
        可能返回 dict，也可能返回 list。这里统一兼容，避免明明命中了知识库，
        但因为结构差异被我们吃掉。
        """

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

    def retrieve_chunks(
        self,
        question: str,
        dataset_ids: list[str] | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """从 RAGFlow 知识库检索相关片段。

        这条链路用于异常分析和 MCP，当前保持软失败：
        只要知识库暂时不可用，就返回空列表，不阻断主分析流程。
        """

        if not self.api_key:
            logger.warning("RAGFlow API key 未配置，retrieve_chunks 直接返回空列表。")
            return []

        datasets = dataset_ids or list(self._settings.ragflow_dataset_ids)
        if not datasets:
            logger.warning("RAGFlow dataset_ids 未配置，retrieve_chunks 直接返回空列表。")
            return []

        url = f"{self.api_url}/retrieval"
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
            return []

        if body.get("code") == 0 and isinstance(body.get("data"), dict):
            chunks = body["data"].get("chunks", [])
            return chunks if isinstance(chunks, list) else []

        logger.error("RAGFlow retrieval 返回了非预期结构: %s", body)
        return []

    def chat_completion(
        self,
        question: str,
        chat_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """通过 RAGFlow OpenAI-compatible 聊天接口执行知识问答。"""

        self._ensure_basic_config()

        chat = chat_id or self._settings.ragflow_default_chat_id
        if not chat:
            raise RagFlowConfigurationError("RAGFlow 默认 Chat ID 未配置。")

        url = f"{self.api_url}/chats_openai/{chat}/chat/completions"
        payload: dict[str, Any] = {
            "model": self._settings.ragflow_chat_model,
            "messages": [
                {
                    "role": "user",
                    "content": question,
                }
            ],
            "stream": False,
            # RAGFlow 的 chats_openai 接口要求把引用开关放进 extra_body。
            # 如果直接放顶层，聊天能回答，但大概率拿不到 reference。
            "extra_body": {
                "reference": True,
            },
        }
        if session_id:
            # 文档没有强调 session_id 的固定位置，但当前继续透传，
            # 便于兼容服务端已有的会话能力。
            payload["session_id"] = session_id

        body = self._request_json(url, payload)

        if isinstance(body.get("choices"), list) and body["choices"]:
            message = body["choices"][0].get("message", {}) or {}
            answer = message.get("content")
            if not answer:
                raise RagFlowInvalidResponseError("RAGFlow 聊天返回缺少 answer 内容。")
            return {
                "answer": answer,
                "session_id": body.get("session_id") or body.get("conversation_id") or body.get("id") or session_id,
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


ragflow_client = RagFlowClient()
