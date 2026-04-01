import httpx
from typing import Any
import logging

from .config import get_ai_settings

logger = logging.getLogger(__name__)

# ============================================================================
# RAGFlow 客户端封装模块
# 主要功能：
#   1. 与 RAGFlow 服务进行 HTTP 通信
#   2. 从知识库检索相关文档切片（RAG 检索）
#   3. 执行会话级别的 Chat 问答（支持多轮对话）
#   4. 处理 API 错误和日志记录
# ============================================================================


class RagFlowClient:
    """RAGFlow HTTP 客户端封装。"""

    def __init__(self, api_url: str | None = None, api_key: str | None = None):
        settings = get_ai_settings()
        self.api_url = (api_url or settings.ragflow_api_url).rstrip('/')
        self.api_key = api_key or settings.ragflow_api_key

    def _get_headers(self) -> dict[str, str]:
        """构造统一请求头。

        包括 Content-Type 和 Authorization Bearer Token，用于与 RAGFlow API 通信。
        """
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def retrieve_chunks(self, question: str, dataset_ids: list[str] | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        """从知识库检索相关文档切片（RAG检索）。

        根据提供的问题查询文本，从指定数据集（知识库）中检索最相关的文档片段，
        返回排序后的切片数据。用于问答系统的上下文增强和知识补充。

        Args:
            question: 查询问题文本
            dataset_ids: 目标知识库 ID 列表；如不指定则使用配置的默认数据集
            top_k: 返回的最相关切片数量（默认 3 个）

        Returns:
            相关切片列表，每个切片包含文本内容和元数据
        """
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
        """执行 RAGFlow Chat 会话问答。

        基于 RAGFlow 知识库进行一次问答对话，支持会话级别的上下文维持。
        与 retrieve_chunks 的区别在于：retrieve_chunks 只返回文档片段，
        而 chat_completion 返回 LLM 生成的自然语言答案。

        Args:
            question: 用户提问
            chat_id: 使用的 Chat ID；如不指定则使用配置的默认 Chat ID
            session_id: 会话 ID，用于维持多轮对话上下文；如为 None 则开启新会话

        Returns:
            包含 answer、session_id 等字段的字典；如出错则返回 {"error": "错误信息"}
        """
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
        """简化封装：仅返回字符串答案。

        对 chat_completion 的便利包装，直接返回答案字符串（不含 session_id 等元数据）。
        如调用失败则返回错误信息字符串。

        Args:
            question: 用户提问
            chat_id: Chat ID（可选）

        Returns:
            答案字符串，如出错则返回错误提示信息
        """
        result = self.chat_completion(question, chat_id)
        if "error" in result:
            return f"Error connecting to knowledge base: {result['error']}"
        return result.get("answer", "No answer found in the knowledge base.")

ragflow_client = RagFlowClient()
