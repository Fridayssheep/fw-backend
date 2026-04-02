from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


# 这份脚本用于 /ai/qa 联调。
# 使用方式：
# 1. 先填写或导出下面这些环境变量
# 2. 确保后端服务已经启动，并且 /ai/qa 路由可访问
# 3. 运行本脚本，查看终端输出和生成的 JSON 报告


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"缺少环境变量: {name}")
    return value


def build_report_path() -> Path:
    return Path(__file__).resolve().parent / "ai_qa_integration_report.json"


def direct_ragflow_check() -> dict[str, Any]:
    """直接调用 RAGFlow retrieval，用于区分是后端问题还是上游问题。"""

    from ai.backend.ragflow_client import RagFlowClient

    ragflow_api_url = get_required_env("RAGFLOW_API_URL")
    ragflow_api_key = get_required_env("RAGFLOW_API_KEY")
    question = get_required_env("AI_QA_TEST_QUESTION")

    client = RagFlowClient(api_url=ragflow_api_url, api_key=ragflow_api_key)
    retrieval_result = client.retrieve_references(
        question=question,
        top_k=5,
    )
    return {
        "retrieval_reference_chunk_count": len((retrieval_result or {}).get("chunks", [])),
        "retrieval_reference_doc_count": len((retrieval_result or {}).get("doc_aggs", [])),
    }


def backend_http_check() -> dict[str, Any]:
    """通过后端 /ai/qa 接口做完整联调。"""

    backend_base_url = get_required_env("BACKEND_BASE_URL").rstrip("/")
    question = get_required_env("AI_QA_TEST_QUESTION")
    session_id = os.getenv("AI_QA_TEST_SESSION_ID", "").strip() or None

    payload: dict[str, Any] = {"question": question}
    if session_id:
        payload["session_id"] = session_id

    with httpx.Client(timeout=90.0, trust_env=False) as client:
        response = client.post(f"{backend_base_url}/ai/qa", json=payload)

    body: dict[str, Any]
    try:
        body = response.json()
    except ValueError:
        body = {"raw_text": response.text}

    result = {
        "status_code": response.status_code,
        "response": body,
    }

    if response.status_code == 200 and isinstance(body, dict):
        references = body.get("references") or {}
        knowledge_references = references.get("knowledge") or []
        data_references = references.get("data") or []
        history_references = references.get("history_cases") or []
        result["answer_preview"] = (body.get("answer") or "")[:200]
        result["question_type"] = body.get("question_type")
        result["knowledge_reference_count"] = len(knowledge_references)
        result["data_reference_count"] = len(data_references)
        result["history_reference_count"] = len(history_references)
        result["used_tools"] = [item.get("tool_name") for item in (body.get("used_tools") or []) if isinstance(item, dict)]
        result["suggested_actions"] = [item.get("target") for item in (body.get("suggested_actions") or []) if isinstance(item, dict)]
        result["provider"] = (body.get("meta") or {}).get("provider")
        result["model"] = (body.get("meta") or {}).get("model")
        result["has_references"] = (body.get("meta") or {}).get("has_references")

    return result


def main() -> None:
    # 允许开发时只测后端 HTTP；如果要先直连 RAGFlow 排查上游问题，可以设为 1。
    enable_direct_ragflow_check = os.getenv("AI_QA_DIRECT_RAGFLOW_CHECK", "1").strip() == "1"

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "env": {
            "BACKEND_BASE_URL": os.getenv("BACKEND_BASE_URL", ""),
            "RAGFLOW_API_URL": os.getenv("RAGFLOW_API_URL", ""),
            "RAGFLOW_DEFAULT_CHAT_ID": os.getenv("RAGFLOW_DEFAULT_CHAT_ID", ""),
            "RAGFLOW_DATASET_IDS": os.getenv("RAGFLOW_DATASET_IDS", ""),
            "AI_QA_TEST_QUESTION": os.getenv("AI_QA_TEST_QUESTION", ""),
            "AI_QA_TEST_SESSION_ID": os.getenv("AI_QA_TEST_SESSION_ID", ""),
            "AI_QA_DIRECT_RAGFLOW_CHECK": os.getenv("AI_QA_DIRECT_RAGFLOW_CHECK", "1"),
        },
    }

    errors: list[str] = []

    if enable_direct_ragflow_check:
        try:
            report["direct_ragflow_check"] = direct_ragflow_check()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"direct_ragflow_check 失败: {exc}")
            report["direct_ragflow_check_error"] = str(exc)

    try:
        report["backend_http_check"] = backend_http_check()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"backend_http_check 失败: {exc}")
        report["backend_http_check_error"] = str(exc)

    report["ok"] = not errors
    report["errors"] = errors

    out_path = build_report_path()
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
