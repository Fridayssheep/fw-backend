import json
import re
from typing import Any

import httpx

from .config import AISettings


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible JSON generation client.

    This client targets any service exposing the OpenAI Chat Completions API,
    including Ollama's `/v1/chat/completions` compatibility layer.
    """

    def __init__(self, settings: AISettings) -> None:
        self._settings = settings

    def _extract_json_text(self, content: str) -> str:
        """Extract the most likely JSON payload from model output."""

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

