import json
import re
from typing import Any

import httpx

from .config import AISettings


class OpenAICompatibleClient:
    """OpenAI 兼容协议客户端。

    用途：
    1. 通过 Chat Completions 接口请求模型。
    2. 强制期望返回 JSON 对象，便于后续结构化解析。
    3. 兼容 Ollama 等提供 OpenAI 风格 API 的服务。
    """

    def __init__(self, settings: AISettings) -> None:
        self._settings = settings

    def _extract_json_text(self, content: str) -> str:
        """从模型回复中提取最可能的 JSON 文本。

        兼容三类常见输出：
        1. ```json ... ``` 代码块。
        2. 混杂说明文本 + JSON 对象。
        3. 纯 JSON 文本。
        """

        stripped = content.strip()
        if stripped.startswith('```'):
            match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", stripped, re.DOTALL)
            if match:
                return match.group(1).strip()
        first_object = stripped.find('{')
        last_object = stripped.rfind('}')
        if first_object != -1 and last_object != -1 and last_object > first_object:
            return stripped[first_object:last_object + 1]
        return stripped

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """调用 LLM 并返回反序列化后的 JSON 对象。"""
        payload = {
            'model': self._settings.llm_model,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': self._settings.llm_temperature,
            'top_p': self._settings.llm_top_p,
        }
        headers = {
            'Authorization': f'Bearer {self._settings.llm_api_key}',
            'Content-Type': 'application/json',
        }
        with httpx.Client(timeout=self._settings.llm_timeout_seconds, trust_env=False) as client:
            response = client.post(
                f"{self._settings.llm_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        body = response.json()
        content = body.get('choices', [{}])[0].get('message', {}).get('content')
        if not content:
            raise ValueError('LLM service returned an empty message content')
        json_text = self._extract_json_text(content)
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError('LLM service did not return valid JSON content') from exc

