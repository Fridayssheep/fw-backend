from typing import Any
import httpx

from ai.mcp.config import BACKEND_BASE_URL, BACKEND_TIMEOUT
from ai.mcp.utils import _clean_none_values

def _extract_backend_error_message(response: httpx.Response) -> str:
    """从后端响应中提取可读错误信息。"""
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        if payload.get("message"):
            return str(payload["message"])
        if payload.get("detail"):
            return str(payload["detail"])
    return response.text.strip() or f"HTTP {response.status_code}"

def _request_backend(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一后端请求入口，包含参数清洗与异常转换。"""
    url = f"{BACKEND_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=BACKEND_TIMEOUT) as client:
            response = client.request(
                method=method,
                url=url,
                params=_clean_none_values(params or {}),
                json=json_body,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        message = _extract_backend_error_message(exc.response)
        raise ValueError(
            f"后端接口调用失败: {method} {path} -> HTTP {exc.response.status_code}，{message}"
        ) from exc
    except httpx.RequestError as exc:
        raise ValueError(
            f"后端服务不可达: {method} {path}。请确认后端已启动，当前地址为 {BACKEND_BASE_URL}。"
        ) from exc