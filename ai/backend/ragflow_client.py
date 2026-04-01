import httpx
from typing import Any
import logging

from .config import get_ai_settings

logger = logging.getLogger(__name__)

class RagFlowClient:
    """RAGFlow HTTP 客户端封装。"""

    def __init__(self, api_url: str | None = None, api_key: str | None = None):
        settings = get_ai_settings()
        self.api_url = (api_url or settings.ragflow_api_url).rstrip('/')
        self.api_key = api_key or settings.ragflow_api_key

    def _get_headers(self) -> dict[str, str]:
        """构造统一请求头。"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def retrieve_chunks(self, question: str, dataset_ids: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        """按查询语句从知识库检索相关文档切片。"""
        if not self.api_key:
            logger.warning("RAGFlow API key not configured, returning empty chunks.")
            return []
            
        settings = get_ai_settings()
        datasets = dataset_ids or list(settings.ragflow_dataset_ids)
        
        if not datasets:
            logger.warning("No RAGFlow dataset IDs configured.")
            return []

        url = f"{self.api_url}/retrieval"
        payload = {
            "question": question,
            "dataset_ids": datasets,
            "top_k": top_k,
            "similarity_threshold": 0.2
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, headers=self._get_headers(), json=payload)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") == 0 and "data" in data and "chunks" in data["data"]:
                    return data["data"]["chunks"]
                
                logger.error(f"RAGFlow retrieval failed: {data.get('message', 'Unknown error')}")
                return []
                
        except Exception as e:
            logger.exception(f"Error communicating with RAGFlow: {e}")
            return []

    def chat_completion(self, question: str, chat_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        """调用 RAGFlow Chat 完成一次问答会话。"""
        if not self.api_key:
            return {"error": "RAGFlow API key not configured"}
            
        settings = get_ai_settings()
        chat = chat_id or settings.ragflow_default_chat_id
        
        if not chat:
            return {"error": "No RAGFlow Chat ID configured"}

        url = f"{self.api_url}/chats/{chat}/completions"
        payload = {
            "question": question,
            "stream": False
        }
        if session_id:
            payload["session_id"] = session_id

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, headers=self._get_headers(), json=payload)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") == 0 and "data" in data:
                    return data["data"]
                
                return {"error": data.get("message", "Unknown error")}
                
        except Exception as e:
            logger.exception(f"Error interacting with RAGFlow chat: {e}")
            return {"error": str(e)}

    def ask_ragflow_chat(self, question: str, chat_id: str | None = None) -> str:
        """简化封装：仅返回字符串答案。"""
        result = self.chat_completion(question, chat_id)
        if "error" in result:
            return f"Error connecting to knowledge base: {result['error']}"
        return result.get("answer", "No answer found in the knowledge base.")

ragflow_client = RagFlowClient()
